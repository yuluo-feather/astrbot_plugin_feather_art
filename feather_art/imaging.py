"""图片装载：EXIF 转正、透明合成、限宽缩放与双边滤波。

进料统一是字节流（插件场景：消息里抓下来的图），文件路径也认。
出来的就是「描摹参考位图」——底色调好、最长边限住、噪点滤掉，
RGB uint8 数组，量化与轮廓直接拿去用。
"""

from io import BytesIO
from pathlib import Path
from typing import Union

import cv2
import numpy as np
from PIL import Image, ImageOps

# 输入就是普通图片字节的来源类型
SourceLike = Union[bytes, bytearray, Path, str]


def _to_reference(image: Image.Image, matte: tuple[int, int, int],
                  max_width: int) -> tuple[np.ndarray, tuple[int, int]]:
    """EXIF 转正 → 透明合成 → 限宽缩放 → (参考数组, 原始尺寸)。不滤波。"""
    image = ImageOps.exif_transpose(image)
    original_size = image.size
    rgba = image.convert("RGBA")
    mat = Image.new("RGBA", rgba.size, (*matte, 255))
    reference_image = Image.alpha_composite(mat, rgba).convert("RGB")
    # 长边死限：防超高/超宽图绕开单轴限制
    scale = min(1.0, max_width / reference_image.width,
                2 * max_width / max(reference_image.size))
    size = (max(1, round(reference_image.width * scale)),
            max(1, round(reference_image.height * scale)))
    if reference_image.size != size:
        reference_image = reference_image.resize(size, Image.Resampling.LANCZOS)
    return np.asarray(reference_image), original_size


def _denoise(reference: np.ndarray) -> np.ndarray:
    """两轮轻量双边滤波，压掉扫描噪声与 JPEG 蚊噪。"""
    if min(reference.shape[:2]) >= 3:
        reference = cv2.bilateralFilter(reference, 7, 22, 4)
        reference = cv2.bilateralFilter(reference, 9, 24, 5)
    return reference


def load_image(source: SourceLike, max_width: int, matte: tuple[int, int, int]) -> tuple[np.ndarray, tuple[int, int]]:
    """一张图的进厂流程（单帧）：解码、转正、合成、限宽、去噪，完事。

    返回 (参考数组 HxWx3 uint8, 原始尺寸 (w, h))。
    - 动图/多帧直接赶走，要画动画走 decode_frames；
    - EXIF 方向先转正，透明像素按 matte 合成（合成前保持 RGBA）再说话；
    - 最长边受 max_width 与 2*max_width 双重约束，缩放用 LANCZOS；
    - 尺寸不小于 3 的图做两轮轻量双边滤波，把扫描噪声和 JPEG 蚊噪压下去。
    """
    handle = Image.open(BytesIO(source)) if isinstance(source, (bytes, bytearray)) else Image.open(Path(source))
    with handle:
        frames = getattr(handle, "n_frames", 1)
        if frames > 1:
            raise ValueError("不支持动图/多帧输入，请先导出单帧。")
        reference, original_size = _to_reference(handle, matte, max_width)
    return _denoise(reference), original_size


def decode_frames(source: SourceLike, max_width: int, matte: tuple[int, int, int],
                  sample_limit: int = 48) -> tuple[list[np.ndarray], tuple[int, int], float, int]:
    """多帧动图 → (采样后的帧数组列表, 原始尺寸, 平均帧时长秒)。

    - 只伺候多帧（GIF / WebP 动图）；单帧去 load_image；
    - 采样密度按时长自适应：目标约 4 帧/秒，下限 8 帧，硬上限 sample_limit
      （短动画近全帧还原节奏，长动画按上限兜底——固定 16 帧抽 2000+ 帧
      会隔 5 秒多才跳一帧，成品自然"诡异"）；
    - 每帧都走与 load_image 相同的合成/缩放/去噪，待遇一样；
    - 平均帧时长取自帧元数据（GIF/WebP 的 duration），查不到按 0.125s 记。
    """
    handle = Image.open(BytesIO(source)) if isinstance(source, (bytes, bytearray)) else Image.open(Path(source))
    with handle:
        total = int(getattr(handle, "n_frames", 1))
        if total <= 1:
            raise ValueError("这不是多帧动图（只有 1 帧）。")
        # 首帧时长估算全局节奏（GIF/WebP 帧间隔通常均匀），按秒定采样数
        handle.seek(0)
        est_duration = _frame_duration(handle) * total
        if est_duration > 0:
            sample = int(min(sample_limit, max(8, est_duration * 4)))
        else:
            sample = min(sample_limit, total)
        chosen = sorted(set(round(x) for x in np.linspace(0, total - 1, min(sample, total))))
        durations: list[float] = []
        original_size: tuple[int, int] = handle.size
        frames: list[np.ndarray] = []
        for index in chosen:
            handle.seek(index)
            durations.append(_frame_duration(handle))
            arr, _ = _to_reference(handle, matte, max_width)
            frames.append(_denoise(arr))
    avg = sum(durations) / len(durations) if durations else 0.125
    if avg <= 0:
        avg = 0.125
    return frames, original_size, avg, total


def _frame_duration(handle: Image.Image) -> float:
    """当前帧时长（秒）：优先帧内 info，缺失用全局平均。"""
    info = getattr(handle, "info", {}) or {}
    frame_ms = getattr(handle, "duration", None)
    if frame_ms:
        return frame_ms / 1000.0
    if "duration" in info:
        return info["duration"] / 1000.0
    return 0.125
