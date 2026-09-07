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
    from .config import load_settings
    from .deliver import build_chain
    from .hardening import (animation_length_hint, check_file_size,
                          inspect_animation, user_fault)
    from .limiter import ConversionLimiter
    from .options import parse_options
    from .feather_art.presets import resolve
    from .feather_art import __version__
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
    "发 GIF / 动图自动描成 CSS 动画（动画档），浏览器直接播放。"
)


@register("feather_art", "羽落", "羽画：把图片离线描摹成纯 HTML+CSS 单文件插画，无图片无脚本无外链", VERSION)
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
        # 最近一次带图消息缓存：uid -> (本地路径, 时间戳)
        self._last_image: dict[str, tuple[Path, float]] = {}
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
        logger.info("羽画 v%s · 纯 CSS 描摹就位，图来了就开工。", VERSION)

    # ---------- 图片获取 ----------

    async def _grab_image(self, event: AstrMessageEvent) -> Path | None:
        """从消息里取第一张图（框架下载到本地），缓存并返回路径。"""
        try:
            for comp in event.get_messages():
                if isinstance(comp, Image):
                    path = await comp.convert_to_file_path()
                    if not path:
                        continue
                    src = Path(path)
                    if not src.exists():
                        continue
                    dest = self.work_dir / f"inbox_{int(time.time())}_{secrets.token_hex(4)}{src.suffix.lower()}"
                    shutil.copyfile(src, dest)
                    self._last_image[str(event.get_sender_id())] = (dest, time.time())
                    return dest
        except Exception as exc:
            logger.warning("图片获取失败: %s", exc)
        return None

    def _recent_image(self, event: AstrMessageEvent) -> Path | None:
        """回退：取该用户 5 分钟内的最近缓存图（LLM 工具场景用）。"""
        uid = str(event.get_sender_id())
        record = self._last_image.get(uid)
        if record and time.time() - record[1] < 300 and record[0].exists():
            return record[0]
        return None

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
        """命令与工具共用的描摹编排；产出 chain/MessageChain 或字符串。"""
        if not _DEPS_OK:
            note = f"羽画启动时缺依赖（{_DEP_ERROR}），请先执行 pip install -r requirements.txt。"
            if via_tool:
                yield note
                return
            yield event.chain_result([Plain(note)])
            return

        preset_key, fit_mb = parse_options(
            text, str(self.settings.get("preset", "freehand")),
            float(self.settings.get("fit_mb", 40.0)))

        img_path = await self._grab_image(event) or self._recent_image(event)
        if img_path is None:
            note = "没收到图呀。先发一张图，再：/羽画 工笔（档位顺序随写随认）"
            if via_tool:
                yield note
                return
            yield event.chain_result([Plain(note)])
            return

        uid = str(event.get_sender_id())
        ok, wait = await self.limiter.acquire(uid)
        if not ok:
            note = f"我刚画完一幅，手速慢点～ 再等 {wait:.0f} 秒就能下单。"
            if via_tool:
                yield note
                return
            yield event.chain_result([Plain(note)])
            return

        try:
            data = img_path.read_bytes()
            check_file_size(data, int(self.settings.get("max_image_mb", 20.0) * 1024 * 1024))
            fmt, (w, h), frames = inspect_animation(data, int(self.settings.get("max_pixels", 40_000_000)))
            if frames > 1:
                hint = animation_length_hint(data, frames, text)
                if hint:
                    if via_tool:
                        yield hint
                    else:
                        yield event.chain_result([Plain(hint)])
                    return
            out = self.work_dir / f"feather_{int(time.time())}_{secrets.token_hex(4)}.html"
            report_path = self.work_dir / f"feather_{int(time.time())}_{secrets.token_hex(4)}.json"
            if frames > 1:
                motion_name = resolve("motion").name
                await event.send(MessageChain([Plain(
                    f"收到 {fmt} 动图 {frames} 帧，开始描摹动画（{motion_name}档）……")]))
                traced = TraceConfig(
                    max_mb=float(self.settings.get("max_mb", 64.0)),
                    fit_mb=0.0,
                    score=False,
                )
                report = await asyncio.to_thread(
                    trace_animation, data, "motion", out,
                    config=traced, force=True, report_path=report_path)
            else:
                preset_name = resolve(preset_key).name
                await event.send(MessageChain([Plain(f"收到 {fmt} {w}×{h}，开始描摹（{preset_name}档）……")]))
                traced = TraceConfig(
                    max_mb=float(self.settings.get("max_mb", 64.0)),
                    fit_mb=fit_mb,
                    score=bool(self.settings.get("score", True)),
                )
                report = await asyncio.to_thread(
                    trace_image, data, preset_key, out,
                    config=traced, force=True, report_path=report_path)
            chain = build_chain(report, out)
            if via_tool:
                await event.send(MessageChain(chain=list(chain)))
                yield "已为用户完成描摹并发送 HTML 文件。请自然收尾一句（如询问是否满意）。"
            else:
                yield event.chain_result(chain)
        except (TraceError, ValueError) as exc:
            detail = user_fault(exc)
            if detail is None:
                # 安全修复：内部异常（cv2/PIL 原始消息）只进日志，不外泄
                note = "描摹断了。机器今天手抖，换个时候再试。"
                logger.warning("[羽画][%s] 内部异常不外露: %s", uid, exc)
            else:
                note = f"这稿画得不太顺：{detail}"
                logger.warning("[羽画][%s] 用户可见失败: %s", uid, detail)
            if via_tool:
                yield note
                return
            yield event.chain_result([Plain(note)])
        except Exception as exc:
            logger.error("描摹失败: %s", exc, exc_info=True)
            note = "描摹断了。机器今天手抖，换个时候再试。"
            if via_tool:
                yield note
                return
            yield event.chain_result([Plain(note)])
        finally:
            self.limiter.release()
