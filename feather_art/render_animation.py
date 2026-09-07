"""动画渲染：图层轨迹 → 单文件 HTML（@keyframes 时间线）。

跟静态渲染同一套脾气：
- 图层 = <div class="layer lN">，样式全在 <style> 里；
- 每层一条 @keyframes，step-end 硬切（稳、省），或顶点对齐后 linear 补间（顺）；
- 坐标归一化成画布百分比，颜色一律 #rrggbb，数字压缩走 geometry.number；
- 预算记账：边写边数，超限抛 BudgetExceeded（跟静态渲染共用一个异常）。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .animate import Track, ShapeKey, anchor_track
from .geometry import hex_color, number
from .render import BudgetExceeded, FALLSAFE_MESSAGE

_CSP_META = '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; img-src \'none\'; script-src \'none\'; connect-src \'none\'; font-src \'none\'; object-src \'none\'; base-uri \'none\'; form-action \'none\'">'



@dataclass
class AnimationConfig:
    title: str = "羽画 · 纯 CSS 动画"
    background: tuple[int, int, int] = (255, 255, 255)
    fps: float = 8.0
    loop: bool = True
    tween: bool = False         # False=硬切跳帧；True=顶点对齐线性补间
    max_bytes: int = 32 * 1024 * 1024
    progress: object = None     # Callable[[str], None]


def _poly_text(points: np.ndarray, size: tuple[int, int], digits: int = 2) -> str:
    w, h = size
    return ",".join(
        f"{number(px / w * 100.0, digits)}% {number(py / h * 100.0, digits)}%"
        for px, py in points)


def _pad_poly(points: np.ndarray, length: int) -> np.ndarray:
    """顶点对齐：不足的用首点补成 0 面积折线，供 clip-path 插值。"""
    if len(points) >= length:
        return points
    padding = np.repeat(points[:1], length - len(points), axis=0)
    return np.vstack([points, padding])


@dataclass
class _CssWriter:
    """边写边记账的样式块收集器。"""

    max_bytes: int
    parts: list = None
    budget: int = 0

    def __post_init__(self):
        if self.parts is None:
            self.parts = []

    def push(self, text: str) -> None:
        self.budget += len(text.encode("utf-8"))
        if self.budget > self.max_bytes:
            raise BudgetExceeded(self.budget)
        self.parts.append(text)

    @property
    def text(self) -> str:
        return "".join(self.parts)


def render_animation(tracks: list[Track], size: tuple[int, int],
                     frame_count: int, config: AnimationConfig) -> tuple[str, dict]:
    """图层轨迹 → (HTML 文档, stats)。

    stats：{layers, keyframe_total, frames, duration}；字节数由审计方统计。
    """
    progress = config.progress or (lambda _: None)
    writer = _CssWriter(max_bytes=config.max_bytes)
    duration = frame_count / config.fps if config.fps > 0 else 1.0
    # ::before 撑高代替 aspect-ratio（老 WebView 兼容，理由同静态渲染）
    sizer = number(size[1] / size[0] * 100.0, 5)
    timing = "step-end" if not config.tween else "linear"

    # z 排序：面积大的沉底（背景分量自然最底）
    ordered = sorted(tracks, key=lambda t: max(k.area for k in t.keys), reverse=True)

    keyframe_blocks: list[str] = []
    keyframe_total = 0
    for index, track in enumerate(ordered):
        # 轨迹级固定色：每帧独立量化会让同一物体跨帧色板漂移、颜色乱跳，
        # 这是长动画「闪色」的主源——统一到轨迹平均色，颜色恒定不闪。
        _colors = np.asarray([k.color for k in track.keys], dtype=float)
        track_color = tuple(np.round(_colors.mean(axis=0)).astype(int))
        # 逐帧展开 + 锚定：None → 最近前一个有值的特征
        filled: list[ShapeKey] = []
        last: ShapeKey | None = None
        for key in anchor_track(track, frame_count):
            if key is not None:
                last = key
            filled.append(last)
        if filled[0] is None:
            # 轨迹首个有值帧之前可能有多个空槽，全部锚定到首特征，不能只补第 0 个
            first_key = track.first
            filled = [first_key if k is None else k for k in filled]

        max_len = max(len(k.poly) for k in filled if k is not None)
        keyframes: list[str] = []
        for frame_idx, key in enumerate(filled):
            pct = number(frame_idx / frame_count * 100.0, 2)
            poly = _pad_poly(key.poly, max_len) if config.tween else key.poly
            clip = "polygon(" + _poly_text(poly, size) + ")"
            keyframes.append(
                f"{pct}%{{clip-path:{clip};background:{hex_color(track_color)}}}")
        # 末帧补回首帧（循环首尾衔接）
        poly0 = _pad_poly(filled[0].poly, max_len) if config.tween else filled[0].poly
        keyframes.append(
            f"100%{{clip-path:polygon({_poly_text(poly0, size)});"
            f"background:{hex_color(track_color)}}}")
        keyframe_total += len(keyframes)
        keyframe_blocks.append(f"@keyframes k{index}{{{''.join(keyframes)}}}")
        progress(f"Layer {index + 1}/{len(ordered)}")

    css = (
        f"html{{color-scheme:light}}\n"
        f".illustration{{position:relative;isolation:isolate;overflow:hidden;"
        f"width:100%;max-width:{size[0]}px;margin:0 auto;"
        f"background:{hex_color(config.background)};contain:layout paint}}\n"
        f".illustration::before{{content:\"\";display:block;padding-top:{sizer}%}}\n"
        f".fallsafe{{display:block;position:fixed;top:0;left:0;right:0;bottom:0;z-index:2147483647;background:{hex_color(config.background)};color:#333;padding:24px;font:15px/1.8 sans-serif;box-sizing:border-box}}\n"
        f".fallsafe::after{{content:\"{FALLSAFE_MESSAGE}\"}}\n"
        f"@supports (clip-path: polygon(0 0)){{.fallsafe{{display:none}}}}\n"
        f".layer{{position:absolute;left:0;top:0;width:100%;height:100%;"
        f"animation-duration:{duration:.2f}s;"
        f"animation-timing-function:{timing};"
        f"animation-iteration-count:{'infinite' if config.loop else '1'}}}\n"
        + "\n".join(f".l{i}{{animation-name:k{i}}}" for i in range(len(ordered)))
        + "\n" + "\n".join(keyframe_blocks) + "\n"
    )
    writer.push(css)
    document = (
        "<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<meta name=\"color-scheme\" content=\"light\">"
        f"{_CSP_META}"
        f"<title>{config.title}</title><style>{writer.text}</style></head><body>"
        "<div class=\"fallsafe\"></div>"
        "<main class=\"illustration\" role=\"img\" aria-label=\"羽画 · 纯 CSS 动画\">"
        + "".join(f'<div class="layer l{i}"></div>' for i in range(len(ordered)))
        + "</main></body></html>"
    )
    stats = {"layers": len(ordered), "keyframe_total": keyframe_total,
             "frames": frame_count, "duration": round(duration, 2)}
    return document, stats
