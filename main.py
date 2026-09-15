"""羽画插件入口：命令与自然语言双入口，异步描摹编排。

模块分工（域分组，一次说清）：
- 配置层：config.py（默认值与读取原语）
- 防护层：hardening.py（图片体积/像素炸弹/多帧检查）
- 限流层：limiter.py（全局并发 + 每用户冷却）
- 转换层：service.py（静态编排与预算阶梯）+ service_animation.py（动图编排）
  + feather_art/（算法包）
- 交付层：deliver.py（文案与文件链）
本文件只负责「进门」：认出用户想描图、把图抓下来、把任务派出去、把结果端回去。
"""
import asyncio
import logging
import os
import secrets
import shutil
import tempfile
import time
from pathlib import Path

from astrbot.api.all import *
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Image, Plain

try:
    from .config import DEFAULTS, load_settings
    from .deliver import build_chain
    from .feather_art import __version__
    from .feather_art.presets import resolve
    from .hardening import (
        animation_length_hint,
        check_file_size,
        inspect_animation,
        user_fault,
    )
    from .inbox import SessionInbox
    from .limiter import ConversionLimiter
    from .options import SAMPLE_MAX, SAMPLE_MIN, parse_options
    from .service import TraceConfig, TraceError, trace_image
    from .service_animation import trace_animation
    _DEPS_OK = True
    _DEP_ERROR = ""
except Exception as _dep_exc:  # 依赖缺失（cv2 等）也不让插件挂掉
    _DEPS_OK = False
    _DEP_ERROR = str(_dep_exc)

logger = logging.getLogger(__name__)

VERSION = __version__ if _DEPS_OK else "0.1.0"

HELP_TEXT = (
    "羽画用法：\n"
    "[羽画 + 发一张图] 描摹成纯 HTML+CSS 插画（默认写意档）\n"
    "档位词随写随认：/羽画 工笔、/羽画 速写 图片，顺序无所谓，图以附件为准\n"
    "工笔最细最慢，速写最快最轻，写意是日常均衡之选。\n"
    "发 GIF / 动图自动描成 CSS 动画（动画档），浏览器直接播放。\n"
    "配置里可把渲染后端切成内联 SVG 方言（体积约省一半）。"
)


class _Delivery:
    """两种入口的交付差异，集中在这一处。

    命令入口 yield chain_result，框架会把它落进会话；工具入口的返回值是给上层
    LLM 的收尾提示，成品得自己 send 出去。差别就这一处——集中之后
    _paint_common 里不再到处 if via_tool，将来多一个入口（比如 WebUI 单图
    预览）也只需在这里加一支。
    """

    def __init__(self, event: AstrMessageEvent, via_tool: bool):
        self._event = event
        self._via_tool = via_tool

    def text(self, note: str):
        """一句人话：命令入口落会话，工具入口交给上层 LLM 收尾。"""
        if self._via_tool:
            return note
        return self._event.chain_result([Plain(note)])

    async def artifact(self, chain):
        """成品：工具入口先推给用户，再回一句收尾提示给上层 LLM。"""
        if self._via_tool:
            await self._event.send(MessageChain(chain=list(chain)))
            return "已为用户完成描摹并发送 HTML 文件。请自然收尾一句（如询问是否满意）。"
        return self._event.chain_result(chain)


@register("feather_art", "羽落", "羽画：把图片离线描摹成单文件插画，默认纯 HTML+CSS、可选内联 SVG 方言，无图片无脚本无外链", VERSION)
class FeatherArtPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.settings = load_settings(config) if _DEPS_OK else {}
        self.limiter = ConversionLimiter(
            concurrent=self.settings.get("concurrent", 1),
            cooldown=self.settings.get("cooldown", 60),
        )
        # 工作目录：系统临时目录下专属文件夹，只容纳本插件前缀的文件
        self.work_dir = Path(tempfile.gettempdir()) / "feather_art"
        self.work_dir.mkdir(parents=True, exist_ok=True)
        # 会话级收件箱：按会话记最近一张图（实现见 inbox.py，那里能单测）。
        # 不按发送者——群里 A 发图、B 说「帮我画」时，事件归属可能落在 B 身上，
        # 按发送者取会静默回退成 B 自己的旧图（即「两次都画第一张」）。
        self.inbox = SessionInbox()
        # 后台落盘任务：存引用防被 GC 回收
        self._cache_tasks: set[asyncio.Task] = set()
        self._cleanup_stale()

    def _cleanup_stale(self) -> None:
        """启动时清掉超过 6 小时的本插件文件（仅限我们的前缀，绝不越界）。"""
        now = time.time()
        try:
            for name in os.listdir(self.work_dir):
                if not (name.startswith("feather_") or name.startswith("inbox_")):
                    continue
                path = self.work_dir / name
                try:
                    if now - path.stat().st_mtime > 6 * 3600:
                        path.unlink(missing_ok=True)
                except OSError:
                    pass
        except OSError:
            pass

    async def initialize(self):
        logger.info("羽画 v%s · 描摹就位，图来了就开工。", VERSION)

    # ---------- 图片获取 ----------

    async def _cache_image(self, event: AstrMessageEvent, comp: Image) -> Path | None:
        """把一张图落到工作目录、记进本会话缓存，返回路径。

        框架是懒下载：图片要 convert_to_file_path() 才落盘，所以没被取过的图
        在任何地方都不存在——别人发的图必须由 _remember_image 主动记一份。
        """
        try:
            path = await comp.convert_to_file_path()
            if not path:
                return None
            src = Path(path)
            if not src.exists():
                return None
            dest = self.work_dir / f"inbox_{int(time.time())}_{secrets.token_hex(4)}{src.suffix.lower()}"
            shutil.copyfile(src, dest)
            self.inbox.remember(event.unified_msg_origin, dest)
            return dest
        except Exception as exc:
            logger.warning("图片获取失败: %s", exc)
            return None

    @filter.event_message_type(
        filter.EventMessageType.GROUP_MESSAGE | filter.EventMessageType.PRIVATE_MESSAGE
    )
    async def _remember_image(self, event: AstrMessageEvent):
        """带图消息一律记一份：群里别人发的图也得描得到。

        不 yield 任何东西，所以不参与响应、不影响事件后续传播；落盘丢给后台
        任务，不挡消息流水线。优先级用默认的 0，高于 AngelHeart 的 -10，能在
        它的防抖把事件拦停之前拿到图。
        """
        for comp in event.get_messages():
            if isinstance(comp, Image):
                task = asyncio.create_task(self._cache_image(event, comp))
                self._cache_tasks.add(task)
                task.add_done_callback(self._cache_tasks.discard)
                return

    async def _grab_image(self, event: AstrMessageEvent) -> Path | None:
        """从当前消息里取第一张图（框架下载到本地），缓存并返回路径。"""
        try:
            for comp in event.get_messages():
                if isinstance(comp, Image):
                    dest = await self._cache_image(event, comp)
                    if dest:
                        return dest
        except Exception as exc:
            logger.warning("图片获取失败: %s", exc)
        return None

    def _recent_image(self, event: AstrMessageEvent) -> Path | None:
        """回退：取本会话最近的图（LLM 工具场景与「继续」场景用）。"""
        return self.inbox.latest(event.unified_msg_origin)

    # ---------- 入口 ----------

    @command("羽画", desc="把图片描摹成纯 HTML+CSS 插画（三档：速写/写意/工笔）")
    async def paint(self, event: AstrMessageEvent, text: str = ""):
        """命令入口：/羽画 图片 [档位] [--fit N]。"""
        async for result in self._paint_common(event, text, via_tool=False):
            yield result

    @filter.llm_tool(name="feather_art_trace")
    async def paint_tool(self, event: AstrMessageEvent):
        """羽画描摹：把用户发来的图片转成纯 HTML+CSS 单文件插画。

        当用户发送了图片并明确希望「做成纯 CSS 插画 / 转成 HTML 画 / CSS 艺术」
        时调用；输出为单文件 HTML（无 img/SVG/JS/外链）。档位由文本中的
        速写/写意/工笔 决定；文本未提档位时用插件设置的默认档位（默认写意）。
        """
        text = (getattr(event, "message_str", "") or "").strip()
        async for result in self._paint_common(event, text, via_tool=True):
            yield result

    # ---------- 公共流程 ----------

    async def _paint_common(self, event: AstrMessageEvent, text: str, *, via_tool: bool):
        """命令与工具共用的描摹编排；交付差异交给 _Delivery。"""
        delivery = _Delivery(event, via_tool)
        if not _DEPS_OK:
            yield delivery.text(
                f"羽画启动时缺依赖（{_DEP_ERROR}），请先执行 pip install -r requirements.txt。")
            return

        preset_key, fit_mb, sample = parse_options(
            text, str(self.settings.get("preset", "freehand")),
            float(self.settings.get("fit_mb", DEFAULTS["fit_mb"])))

        img_path = await self._grab_image(event) or self._recent_image(event)
        if img_path is None:
            yield delivery.text("没收到图呀。先发一张图，再：/羽画 工笔（档位顺序随写随认）")
            return

        uid = str(event.get_sender_id())
        ok, wait = await self.limiter.acquire(uid)
        if not ok:
            yield delivery.text(f"我刚画完一幅，手速慢点～ 再等 {wait:.0f} 秒就能下单。")
            return

        try:
            data = img_path.read_bytes()
            check_file_size(data, int(self.settings.get("max_image_mb", DEFAULTS["max_image_mb"]) * 1024 * 1024))
            fmt, (w, h), frames = inspect_animation(data, int(self.settings.get("max_pixels", DEFAULTS["max_pixels"])))
            if frames > 1:
                hint = animation_length_hint(data, frames, text)
                if hint:
                    yield delivery.text(hint)
                    return
            out = self.work_dir / f"feather_{int(time.time())}_{secrets.token_hex(4)}.html"
            report_path = self.work_dir / f"feather_{int(time.time())}_{secrets.token_hex(4)}.json"
            if frames > 1:
                motion_name = resolve("motion").name
                await event.send(MessageChain([Plain(
                    f"收到 {fmt} 动图 {frames} 帧，开始描摹动画（{motion_name}档）……")]))
                # 动画线的参数表照静态线的形状发，但两个字段在这条线上不算数：
                # render_backend 只为过 TraceConfig 的注册校验（动画不走静态
                # 后端），score 也没有相似度计算可喂——别把它们当动画开关。
                traced = TraceConfig(
                    max_mb=float(self.settings.get("max_mb", DEFAULTS["max_mb"])),
                    fit_mb=0.0,
                    score=False,
                )
                # 采样帧数：--sample 指令 > 配置默认 > 0=按时长自适应
                sample_frames = sample
                if sample_frames <= 0:
                    sample_frames = int(self.settings.get("motion_sample", 0) or 0)
                    if sample_frames > 0:
                        sample_frames = min(SAMPLE_MAX, max(SAMPLE_MIN, sample_frames))
                report = await asyncio.to_thread(
                    trace_animation, data, "motion", out,
                    config=traced, force=True, report_path=report_path,
                    sample_frames=sample_frames,
                    style=str(self.settings.get("animation_style", "scanline")))
            else:
                preset_name = resolve(preset_key).name
                await event.send(MessageChain([Plain(f"收到 {fmt} {w}×{h}，开始描摹（{preset_name}档）……")]))
                traced = TraceConfig(
                    max_mb=float(self.settings.get("max_mb", DEFAULTS["max_mb"])),
                    fit_mb=fit_mb,
                    score=bool(self.settings.get("score", True)),
                    render_backend=str(self.settings.get("render_backend", "css") or "css"),
                )
                report = await asyncio.to_thread(
                    trace_image, data, preset_key, out,
                    config=traced, force=True, report_path=report_path)
            chain = build_chain(report, out)
            yield await delivery.artifact(chain)
        except (TraceError, ValueError) as exc:
            detail = user_fault(exc)
            if detail is None:
                # 安全修复：内部异常（cv2/PIL 原始消息）只进日志，不外泄
                note = "描摹断了。机器今天手抖，换个时候再试。"
                logger.warning("[羽画][%s] 内部异常不外露: %s", uid, exc)
            else:
                note = f"这稿画得不太顺：{detail}"
                logger.warning("[羽画][%s] 用户可见失败: %s", uid, detail)
            yield delivery.text(note)
        except Exception as exc:
            logger.error("描摹失败: %s", exc, exc_info=True)
            yield delivery.text("描摹断了。机器今天手抖，换个时候再试。")
        finally:
            self.limiter.release()
