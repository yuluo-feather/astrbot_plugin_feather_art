"""SVG 后端（实验分支）：同一份中间表示，写成内联 SVG 的单文件 HTML。

跟 CSS 方言的三处实质差别：
- 一个 path 装同色：相邻同涂色的区域合并成一条 d（多个子路径），元素壳从
  每形状一百来字节掉到二十来字节；
- 洞不靠零面积桥：nonzero 绕数填充吃方向，而环的方向归一化本来就在中间
  表示里做好了，SVG 这边把环原样写出去就行（fill-rule 一个字都不用写）；
- 渐变走 defs：CSS 内联一条渐变才四十来字节，SVG 一条要一百多，所以渐变色
  按量化键去重共享（角度 5°、端点色通道步长 8）。

坐标用画布像素，viewBox 就是画布，省掉百分比那一串字符；环到画布的映射统一
按中间表示的盒子算：先按基准盒归一化，再按落位盒铺开——前景两盒相同于是
原样，底板基准盒是降采样网格、落位盒是整幅画布，于是被拉伸铺满。

成品仍是 .html 外壳（P-1 选型）：独立 .svg 在聊天里是文件不是预览，而且拿不到
meta CSP；内联进 HTML 一样都不丢。老内核不用兜底提示——svg 它本来就认。
"""

import math
from itertools import groupby

import numpy as np

from .contract import BudgetExceeded
from .geometry import hex_color, number
from .paint import Gradient

ANGLE_STEP = 5.0     # 渐变角度量化步长（度）：最坏偏差 2.5°，看不出来
COLOR_STEP = 8       # 渐变端点色量化步长（通道）：最坏偏差 4/255
COORD_DIGITS = 1     # 坐标小数位（单位：画布像素）
CSP = ("default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; script-src 'none'; "
       "connect-src 'none'; font-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'")


def _quantized_color(rgb) -> str:
    """端点色量化到通道步长 COLOR_STEP（就近取整），返回 #rrggbb。"""
    code = hex_color(rgb)
    channels = (min(255, round(int(code[index:index + 2], 16) / COLOR_STEP) * COLOR_STEP)
                for index in (1, 3, 5))
    return "#" + "".join(f"{value:02x}" for value in channels)


def _canvas_point(ring: np.ndarray, box, target) -> np.ndarray:
    """环点（基准盒坐标）→ 画布坐标：先归一化，再按落位盒铺开。"""
    origin, size = (np.asarray(part, np.float64) for part in box)
    t_origin, t_size = (np.asarray(part, np.float64) for part in target)
    return t_origin + (ring - origin) * (t_size / size)


def _path_data(regions) -> str:
    """若干区域 → 一条 d：每个环一个子路径，坐标即画布像素。"""
    parts = []
    for region in regions:
        for ring in region.rings:
            points = _canvas_point(np.asarray(ring, np.float64), region.box, region.target)
            parts.append("M" + " ".join(f"{number(px, COORD_DIGITS)} {number(py, COORD_DIGITS)}"
                                        for px, py in points) + "Z")
    return "".join(parts)


class _GradientTable:
    """渐变去重表：键 = 量化角度 + 量化端点色 + 落位盒。

    落位盒进键是没办法的事：CSS 的渐变线长度 = |dx|W + |dy|H，取决于盒子尺寸，
    而 SVG 的 userSpaceOnUse 还要知道盒子在哪。于是「同角度同色」并不足以共享，
    能撞上的只有位置尺寸也一致的那些——去重率实测不高，如实记着。
    """

    def __init__(self):
        self.names: dict = {}
        self.entries: list = []

    def reference(self, gradient: Gradient, target) -> str:
        origin, size = target
        key = (round(gradient.angle / ANGLE_STEP),
               _quantized_color(gradient.start), _quantized_color(gradient.end),
               round(float(origin[0]), COORD_DIGITS), round(float(origin[1]), COORD_DIGITS),
               round(float(size[0]), COORD_DIGITS), round(float(size[1]), COORD_DIGITS))
        if key not in self.names:
            self.names[key] = f"g{len(self.names)}"
            self.entries.append((self.names[key], key))
        return self.names[key]

    def defs(self) -> str:
        parts = []
        for name, (step, start, end, origin_x, origin_y, width, height) in self.entries:
            radians = math.radians(step * ANGLE_STEP)
            dx, dy = math.sin(radians), -math.cos(radians)
            length = abs(dx) * width + abs(dy) * height
            center_x, center_y = origin_x + width / 2, origin_y + height / 2
            line = (number(center_x - dx * length / 2, COORD_DIGITS),
                    number(center_y - dy * length / 2, COORD_DIGITS),
                    number(center_x + dx * length / 2, COORD_DIGITS),
                    number(center_y + dy * length / 2, COORD_DIGITS))
            parts.append(f'<linearGradient id="{name}" gradientUnits="userSpaceOnUse" '
                         f'x1="{line[0]}" y1="{line[1]}" x2="{line[2]}" y2="{line[3]}">'
                         f'<stop offset="0" stop-color="{start}"/>'
                         f'<stop offset="1" stop-color="{end}"/></linearGradient>')
        return "".join(parts)


class _Fills:
    """涂色 → class 名（纯色按色值去重、渐变按去重表取引用）。"""

    def __init__(self, gradients: _GradientTable):
        self.gradients = gradients
        self.names: dict = {}
        self.declared: list = []

    def class_of(self, region) -> str:
        if isinstance(region.paint, Gradient):
            fill = f"url(#{self.gradients.reference(region.paint, region.target)})"
        else:
            fill = region.paint.to_css()
        if fill not in self.names:
            self.names[fill] = f"f{len(self.names)}"
            self.declared.append((fill, self.names[fill]))
        return self.names[fill]

    def style(self) -> str:
        return "".join(f".{name}{{fill:{fill}}}" for fill, name in self.declared)


class SvgBackend:
    """内联 SVG 后端：绝对坐标、nonzero 挖孔、渐变走 defs。"""

    name = "svg"

    def render_static(self, illustration, config) -> tuple:
        gradients = _GradientTable()
        fills = _Fills(gradients)
        stats = {"shapes": 0, "gradient_fills": 0, "polygon_vertices": 0,
                 "underpainting_shapes": 0, "gradient_defs": 0, "paths": 0}
        clip_attributes, foundation = self._foundation(illustration, fills, stats)
        body = []
        for token, group in groupby(illustration.foreground,
                                    key=lambda region: fills.class_of(region)):
            regions = list(group)
            data = _path_data(regions)
            body.append(f'<path class="{token}" d="{data}"/>')
            used = len(regions)
            stats["shapes"] += used
            stats["paths"] += 1
            stats["polygon_vertices"] += sum(len(ring) for region in regions for ring in region.rings)
            stats["gradient_fills"] += sum(1 for region in regions
                                           if isinstance(region.paint, Gradient))
        stats["gradient_defs"] = len(gradients.entries)
        defs = gradients.defs() + clip_attributes
        width, height = config.original_size
        sizer = number(height / width * 100.0, 5)
        document = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<meta http-equiv="Content-Security-Policy" content="{CSP}">
<title>{config.title}</title>
<style>
*{{box-sizing:border-box}}
html,body{{margin:0;min-height:100%;background:{hex_color(illustration.background)};color-scheme:light}}
.illustration{{position:relative;width:100%;max-width:{illustration.width}px;margin:0 auto;background:{hex_color(illustration.background)}}}
.illustration::before{{content:"";display:block;padding-top:{sizer}%}}
.illustration svg{{position:absolute;top:0;left:0;width:100%;height:100%}}
{fills.style()}
@media print{{@page{{margin:0}}.illustration{{width:100%;print-color-adjust:exact;-webkit-print-color-adjust:exact}}}}
</style>
</head>
<body>
<main class="illustration" role="img" aria-label="{config.title}">
<svg viewBox="0 0 {illustration.width} {illustration.height}">
<defs>{defs}</defs>
{foundation}
{chr(10).join(body)}
</svg>
</main>
</body>
</html>
"""
        if len(document.encode("utf-8")) > config.max_bytes:
            raise BudgetExceeded(len(document.encode("utf-8")))
        return document, stats

    def _foundation(self, illustration, fills, stats) -> tuple:
        """底板 → (clipPath 定义, g 分组)；没有底板时返回空串。"""
        foundation = illustration.foundation
        if foundation is None:
            return "", ""
        clip = ("<clipPath id=\"c0\"><path d=\"" +
                _path_data([_ClipRegion(foundation.clip)]) + "\"/></clipPath>")
        stats["polygon_vertices"] += sum(len(ring) for ring in foundation.clip.rings)
        layers = []
        for region in foundation.regions:
            token = fills.class_of(region)
            layers.append(f'<path class="{token}" d="{_path_data([region])}"/>')
            stats["shapes"] += 1
            stats["underpainting_shapes"] += 1
            stats["polygon_vertices"] += sum(len(ring) for ring in region.rings)
        return clip, '<g clip-path="url(#c0)">' + "".join(layers) + "</g>"


class _ClipRegion:
    """把 Clip 当成区域用：它只有环、基准盒与落位盒，没有涂色。"""

    __slots__ = ("rings", "box", "target")

    def __init__(self, clip):
        self.rings = clip.rings
        self.box = clip.box
        self.target = clip.box          # 剪影本来就住在画布坐标里，落位即基准盒
