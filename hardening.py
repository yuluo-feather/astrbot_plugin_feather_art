"""输入防护：图片文件的体积与像素炸弹检查。

图片由框架下载（Image.convert_to_file_path），我们不自己拉 URL，
所以只守最后一道门：文件本身能不能安全解码。

防线：
1. 文件体积上限（默认 20 MiB）——防异常大的附件；
2. 解码前先读头部拿尺寸与帧数——总像素超限（默认 4000 万）立即拒绝，
   不进入真实解码（防解压炸弹撑爆内存）；
3. 动图有单独通道：帧数超限 / 总像素超限也拒绝，但不再一见「动图」就赶人。
"""

from io import BytesIO
import re

from PIL import Image

MAX_PIXELS_DEFAULT = 40_000_000

# 扩展名到格式提示（仅用于错误文案更贴心，不做强校验）
_EXT_HINT = {".jpg": "JPEG 图片", ".jpeg": "JPEG 图片", ".png": "PNG 图片",
             ".webp": "WebP 图片", ".gif": "GIF 图片", ".bmp": "BMP 图片"}


def user_fault(exc: Exception) -> str | None:
    """异常 → 可给用户看的中文文案；内部异常返回 None（只进日志）。

    安全修复：cv2 / PIL / 框架的原始异常消息多为 ASCII 开头，
    可能带服务器路径与内部结构——一律不外露，用户侧走固定友好文案。
    判定规则是确定性的（首字符是否 ASCII）：我们自己的用户可见文案
    首字符都是中文，不会误伤。
    """
    text = str(exc)
    if not text or text[0].isascii():
        return None
    return text


def check_file_size(data: bytes, max_bytes: int) -> None:
    """文件太大就直接扔个能看的异常回去。"""
    if len(data) > max_bytes:
        raise ValueError(f"图片太大了（{len(data) / 1024 / 1024:.1f} MiB），换个小的罢。")


def inspect_animation(data: bytes, max_pixels: int = MAX_PIXELS_DEFAULT,
                      max_frames: int = 6000) -> tuple[str, tuple[int, int], int]:
    """读图片头部（动图也在内），返回 (格式名, (宽, 高), 帧数)。

    只看头，不解码全身像素：
    - 未知/损坏格式抛 ValueError（中文文案，不吓人）；
    - 单帧像素超限、动图总像素超限都拒绝（防解压炸弹）；
    - 帧数超过 max_frames 拒绝：上限按成本语义收紧到 6000——头解析很便宜，
      管线只均匀采样 ≤16 帧描摹，帧数本身不贵；真正的成本炸弹是「帧数 ×
      单帧像素」，由总像素预算（max_pixels * 4）兜底。2000+ 帧的普通动图
      因此不再被误拒，无限帧/超大动图照样拦。
    """
    try:
        with Image.open(BytesIO(data)) as handle:
            fmt = (handle.format or "未知格式").upper()
            width, height = handle.size
            frames = int(getattr(handle, "n_frames", 1))
    except ValueError as exc:
        raise ValueError("这不是一张能读的图片，换个格式试试（PNG / JPG / WebP / GIF）。") from exc
    except Exception as exc:
        raise ValueError("图片解析失败，可能文件损坏。") from exc
    if frames > max_frames:
        raise ValueError(f"动图太长了（{frames} 帧，上限 {max_frames}），剪一剪再描。")
    if width * height > max_pixels:
        raise ValueError(f"图片太精细了（{width}×{height}），超出 {max_pixels:,} 像素上限，压一压再描。")
    if frames > 1 and width * height * frames > max_pixels * 4:
        raise ValueError(f"动图总像素超限（{width}×{height}×{frames} 帧），压一压再描。")
    return fmt, (width, height), frames


LONG_ANIM_SECONDS = 30.0        # 超过即提示：CSS 动画保留的关键帧会明显稀疏
LONG_ANIM_FRAMES = 2500         # 帧数兜底（时长元数据缺失时也不能放行超长片）


def estimate_duration(data: bytes, frames: int,
                      default_per_frame: float = 0.125) -> float:
    """动图总时长估算（秒）：首帧时长 × 帧数（GIF/WebP 帧间隔通常均匀）。

    拿不到时长元数据时按 default_per_frame 兜底；这是给用户提示用的估算，
    不承担防线职责。
    """
    try:
        handle = Image.open(BytesIO(data))
        with handle:
            handle.seek(0)
            frame_ms = getattr(handle, "duration", None)
            if not frame_ms:
                frame_ms = (getattr(handle, "info", {}) or {}).get("duration")
            if frame_ms:
                return frame_ms / 1000.0 * frames
    except Exception:
        pass
    return default_per_frame * frames


def animation_length_hint(data: bytes, frames: int, text: str) -> str | None:
    """超长动图的人话提示：返回 None 表示可以描；否则返回提示文案。

    - 文本含「继续」视为用户明确要描（先给话、再放行，绝不闷头产出
      一个会被认为「诡异」的删帧成品）；
    - 阈值：估算时长 > LONG_ANIM_SECONDS 或帧数 > LONG_ANIM_FRAMES；
    - 提示文案单一来源，main.py 直接转发即可。
    """
    if "继续" in text:
        return None
    total_seconds = estimate_duration(data, frames)
    if total_seconds <= LONG_ANIM_SECONDS and frames <= LONG_ANIM_FRAMES:
        return None
    return (
        f"这张动图有点长（约 {round(total_seconds)} 秒 / {frames} 帧），"
        f"CSS 动画只能保留少量关键帧，还原度会大打折扣。\n"
        f"要不直接用原 GIF 播放，或剪 10~15 秒的片段再来描；"
        f"实在要描，回复「继续」就行——图我留着，不用重发。"
    )


def guess_kind(path) -> str:
    """按扩展名给个中文提示，纯文案用。"""
    name = str(path).lower()
    for ext, hint in _EXT_HINT.items():
        if name.endswith(ext):
            return hint
    return "图片"
