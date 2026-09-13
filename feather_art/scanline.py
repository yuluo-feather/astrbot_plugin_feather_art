"""扫描线动画渲染：每行 = 一条横向色带渐变（linear-gradient 硬色带）。

动画从「实例矢量轨迹」换成「行渐变扫描线」：逐像素还原、100% 覆盖、
任意缩放无缝隙、帧间稳定不闪。代价：动图的 dithering 颗粒被中值滤波
抹平、颜色 16 步收敛——纹理保真让位于稳定（2026-09-08 实测拍板）。

结构：
- 静止行 → div.shape（矩形 inline clip-path + 行渐变背景；audit 要求
  shape 的 clip-path 必须在 inline style 里，类里不算）；
- 动态行 → div.layer（@keyframes 逐帧 background 切换 + 100% 回环首帧）；
- 行高 = 行距% + OVERLAP_PCT：亚像素重叠，根治「非整数设备缩放下的
  取整缝隙」（Windows 125%/文本缩放场景实测 0 白线）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import cv2
import numpy as np

from .contract import FALLSAFE_MESSAGE
from .geometry import hex_color

DENOISE_KERNEL = 3   # 去抖动中值滤波核
QUANT_STEP = 16      # 颜色量化步长（跨帧收敛，帧间色不漂移）
SEG_TOL = 20         # 行分段色差阈值（单通道）
ROW_PX = 2           # 行合并：原图纵向 ROW_PX 像素并为一行
OVERLAP_PCT = 0.17   # 行高超出行距的百分比（防取整缝隙）
RECT_POLY = "polygon(0 0,100% 0,100% 100%,0 100%)"


@dataclass
class ScanlineConfig:
    """渲染配置（由 service_animation 组装）。"""

    title: str = "羽画 · 纯 CSS 动画"
    background: "str | tuple" = "#ffffff"   # "#hex" 或 (r, g, b) 三元组
    duration: float = 1.0      # 单轮循环总时长（秒）
    loop: bool = True
    progress: Callable | None = None


def _bg_color(value) -> str:
    """背景色转 CSS：#开头的字符串原样透传，数值三元组走 hex_color。"""
    if isinstance(value, str) and value.startswith("#"):
        return value
    return hex_color(value)


def prepare_frame(frame: np.ndarray) -> np.ndarray:
    """单帧预处理：中值去抖动 → 16 步量化（uint8）。"""
    blurred = cv2.medianBlur(frame, DENOISE_KERNEL)
    quant = ((blurred.astype(np.int16) + QUANT_STEP // 2)
             // QUANT_STEP * QUANT_STEP)
    return quant.clip(0, 255).astype(np.uint8)


def row_segments(row: np.ndarray, tol: int = SEG_TOL) -> list:
    """一行像素 → 同色段 [(x0, rgb), ...]；段间单通道色差 > tol 才分段。"""
    segs = [(0, tuple(int(v) for v in row[0]))]
    for x in range(1, row.shape[0]):
        c = tuple(int(v) for v in row[x])
        if max(abs(c[i] - segs[-1][1][i]) for i in range(3)) > tol:
            segs.append((x, c))
    return segs


def seg_gradient(segs: list, width: int) -> str:
    """同色段 → CSS 横向渐变串（双位置 stop，Chromium 71+）。"""
    parts = []
    for i, (x0, c) in enumerate(segs):
        x1 = segs[i + 1][0] if i + 1 < len(segs) else width
        parts.append("#%02x%02x%02x %dpx %dpx" % (c[0], c[1], c[2], x0, x1))
    return "linear-gradient(90deg," + ",".join(parts) + ")"


def merge_rows(frame: np.ndarray, row_h: int) -> np.ndarray:
    """纵向 ROW_PX 像素均值合成一行（行数 = h // ROW_PX）。"""
    hh = frame.shape[0] // row_h
    out = np.zeros((hh, frame.shape[1], 3), np.uint8)
    for i in range(hh):
        out[i] = frame[i * row_h:(i + 1) * row_h].astype(np.int16) \
            .mean(axis=0).astype(np.uint8)
    return out


def render_scanline(frames: list, config: ScanlineConfig) -> tuple:
    """帧列表 → (HTML 文档, stats)。

    帧尺寸须一致（采样管线保证）；stats 字段与 render_animation 对齐：
    layers（动态行数）、static_rows、frames、duration、keyframe_total、
    rows、bytes。
    """
    h, w = frames[0].shape[:2]
    frame_count = len(frames)
    progress = config.progress or (lambda _: None)

    prepared = [prepare_frame(f) for f in frames]
    hh = max(1, h // ROW_PX)
    merged = [merge_rows(f, ROW_PX) for f in prepared]

    grads: list = []
    for t, m in enumerate(merged):
        row_g = []
        for y in range(hh):
            row_g.append(seg_gradient(row_segments(m[y]), w))
        grads.append(row_g)
        progress("预分段 帧 %d/%d" % (t + 1, frame_count))

    changed = [y for y in range(hh)
               if any(grads[t][y] != grads[0][y] for t in range(1, frame_count))]
    row_h_pct = 100.0 / hh + OVERLAP_PCT

    css = [
        ".illustration{position:relative;isolation:isolate;overflow:hidden;"
        "width:100%;max-width:" + str(w) + "px;margin:0 auto;background:"
        + _bg_color(config.background) + ";contain:layout paint}",
        ".illustration::before{content:\"\";display:block;padding-top:"
        + ("%.5f%%" % (h / w * 100)) + "}",
        ".shape{position:absolute;left:0;right:0;height:"
        + ("%.4f%%" % row_h_pct) + ";pointer-events:none}",
        ".layer{position:absolute;left:0;top:0;right:0;height:"
        + ("%.4f%%" % row_h_pct) + ";animation-duration:"
        + ("%.2f" % config.duration) + "s;animation-timing-function:step-end;"
        "animation-iteration-count:" + ("infinite" if config.loop else "1")
        + "}",
        ".fallsafe{display:block;position:fixed;top:0;left:0;right:0;bottom:0;"
        "z-index:2147483647;background:" + _bg_color(config.background)
        + ";color:#333;padding:24px;font:15px/1.8 sans-serif;box-sizing:border-box}",
        ".fallsafe::after{content:\"" + FALLSAFE_MESSAGE + "\"}",
        "@supports (clip-path: polygon(0 0)){.fallsafe{display:none}}",
    ]

    body = []
    for y in range(hh):
        top = y / hh * 100
        if y not in changed:
            body.append('<div class="shape" style="top:%.4f%%;background:%s;'
                        'clip-path:%s"></div>' % (top, grads[0][y], RECT_POLY))
    keyframe_total = 0
    for idx, y in enumerate(changed):
        top = y / hh * 100
        steps = "".join("%.2f%%{background:%s}"
                        % (t / frame_count * 100, grads[t][y])
                        for t in range(frame_count))
        steps += "100%%{background:%s}" % grads[0][y]
        css.append(".l%d{animation-name:k%d}" % (idx, idx))
        css.append("@keyframes k%d{%s}" % (idx, steps))
        body.append('<div class="layer l%d" style="top:%.4f%%"></div>'
                    % (idx, top))
        keyframe_total += frame_count + 1
        if idx and idx % 10 == 0:
            progress("行 %d/%d（动态 %d）" % (idx, hh, len(changed)))

    document = (
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="color-scheme" content="light">'
        '<meta http-equiv="Content-Security-Policy" content="default-src '
        "'none'; style-src 'unsafe-inline'; img-src 'none'; script-src 'none'; "
        "connect-src 'none'; font-src 'none'; object-src 'none'; base-uri "
        "'none'; form-action 'none'\">"
        '<title>' + config.title + '</title><style>'
        + chr(10).join(css) + "</style></head><body>"
        '<main class="illustration" role="img" aria-label="'
        + config.title + '"><div class="fallsafe"></div>'
        + chr(10).join(body) + "</main></body></html>"
    )
    stats = {
        "style": "scanline",
        "rows": hh,
        "static_rows": hh - len(changed),
        "layers": len(changed),
        "frames": frame_count,
        "duration": round(config.duration, 2),
        "keyframe_total": keyframe_total,
        "bytes": len(document.encode("utf-8")),
    }
    return document, stats
