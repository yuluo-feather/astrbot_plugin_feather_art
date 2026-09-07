"""文档构建：把标签图变成纯 HTML + CSS 单文件。

方言（羽画版）：
- 一个 main.illustration，里面住着一群 div.shape；
- 可见图形只来自 CSS clip-path 多边形与 linear-gradient；
- 纯色走共享类 .p0/.p1/...（按色值去重），渐变直接内联 background；
- 小碎块按 160px 网格分组、整组用该色渲染，省 div 也省心眼；
- 底板（underpainting）是一张 48 色剪影，专治缩小观看时的浅色接缝。

预算纪律：拼接过程只记账不抛——超预算不打断提取与拼接，由末尾终检抛出
BudgetExceeded（携带真实完整字节数），让上层的 fit 跳档拿到精确体积信号，
而不是「target+ε」的失真计数（2026-09-07 端到端实测：中途抛会让所有失败
档的 byte_count 趋同、跳档预测失去依据）。
"""

import html
import math

import cv2
import numpy as np

from .geometry import (
    bridge_rings,
    component_rings,
    hex_color,
    mask_polygon,
    number,
    polygon_css,
)
from .merge import label_components
from .paint import paint_for_region
from .quantize import quantize
from .score import Rasterizer

# 小碎块分组网格（逻辑像素）
SMALL_GROUP_GRID = 160
# 老内核兜底提示文案（静态/动画渲染共用，改这里一处即可）
FALLSAFE_MESSAGE = "此浏览器内核较旧，不支持 CSS 多边形（clip-path）渲染——画面会错乱成色块。推荐改用 Chrome / Edge / Firefox 等现代浏览器打开，或转至电脑浏览器查看。"
# 底板剪影的调色板规模
UNDERPAINT_COLORS = 48
# 与底色差不超过该值的颜色被跳过（避免画看不见的层）
MATTE_TOLERANCE = 3


class BudgetExceeded(ValueError):
    """渲染中途发现文档将超出体积预算。"""

    def __init__(self, byte_count: int):
        super().__init__("HTML exceeds the byte budget")
        self.byte_count = byte_count


def color_order(labels: np.ndarray, palette: np.ndarray) -> list[int]:
    """颜色绘制顺序：亮度高者先垫底，亮度相同按编号升序（确定性）。"""
    return sorted(np.unique(labels),
                  key=lambda i: (-float(palette[i] @ np.array([.2126, .7152, .0722])), int(i)))


def same_as_matte(rgb, background) -> bool:
    """与底色几乎同色（单通道差 <= MATTE_TOLERANCE）则不必画。"""
    return int(np.abs(rgb.astype(np.int16) - background).max()) <= MATTE_TOLERANCE


class ContourRenderer:
    """把标签图与调色板逐色转成 shape div 序列。"""

    def __init__(self, reference, background, epsilon, gradients, max_bytes, score=False):
        self.reference = reference
        self.height, self.width = reference.shape[:2]
        self.background = np.asarray(background)
        self.epsilon = epsilon
        self.gradients = gradients
        self.max_bytes = max_bytes
        self.byte_count = 0
        self.paint_classes: dict[str, str] = {}
        self.raster = Rasterizer((self.width, self.height), background) if score else None
        self.stats = {"shapes": 0, "gradient_fills": 0, "polygon_vertices": 0,
                      "interior_holes": 0, "underpainting_shapes": 0}

    def account(self, text: str) -> str:
        # 只做累计统计：不在这里抛 BudgetExceeded（见模块 docstring「预算纪律」），
        # 超预算由 render_document 末尾终检统一抛出，携带真实完整字节数。
        self.byte_count += len(text.encode("utf-8"))
        return text

    def solid_class(self, paint: str) -> str:
        """每种纯色一个共享 class，只在头部 <style> 里声明一次。"""
        if paint not in self.paint_classes:
            self.paint_classes[paint] = f"p{len(self.paint_classes)}"
        return self.paint_classes[paint]

    def shape(self, rings, paint):
        """一组环 → 一个 div.shape 字符串；退化（零尺寸）返回 None。"""
        all_points = np.concatenate(rings)
        origin = all_points.min(axis=0)
        size = all_points.max(axis=0) - origin
        if np.any(size <= 0):
            return None
        points = bridge_rings(rings)
        # 两位小数已把误差压到 尺寸/10000 px，只有极大的形状才配第三位
        digits = max(2, math.ceil(math.log10(max(size) / 10)))
        clip = polygon_css(points, origin, size, digits)
        cls = "shape"
        background = ""
        if paint.startswith("#"):
            cls = f"shape {self.solid_class(paint)}"
        else:
            background = f"background:{paint};"
        style = (
            f"left:{number(origin[0] / self.width * 100, 3)}%;"
            f"top:{number(origin[1] / self.height * 100, 3)}%;"
            f"width:{number(size[0] / self.width * 100, 3)}%;"
            f"height:{number(size[1] / self.height * 100, 3)}%;"
            f"{background}clip-path:{clip}"
        )
        self.stats["shapes"] += 1
        self.stats["polygon_vertices"] += len(points)
        if self.raster is not None:
            self.raster.fill_rings(points, origin, size, paint)
        return self.account(f'<div class="{cls}" style="{style}"></div>')

    def foreground(self, labels, palette, progress):
        """逐色输出前景形状；先大块后碎块，碎块按网格聚组。"""
        parts = []
        ids, colors_by_component, areas, boxes, centers = label_components(labels)
        components_of = {}
        for component in range(1, len(colors_by_component)):
            components_of.setdefault(int(colors_by_component[component]), []).append(component)
        order = color_order(labels, palette)
        for position, color in enumerate(order):
            rgb = palette[color]
            if same_as_matte(rgb, self.background):
                continue
            small_groups = {}
            for component in components_of.get(int(color), ()):
                x, y, width, height = map(int, boxes[component])
                area = int(areas[component])
                mask = (ids[y:y + height, x:x + width] == component).astype(np.uint8)
                if area >= 24:
                    paint, gradient = paint_for_region(
                        self.reference, mask, x, y, width, height, self.gradients)
                else:
                    paint, gradient = hex_color(rgb), False
                for rings in component_rings(mask, x, y, area, self.epsilon):
                    self.stats["interior_holes"] += len(rings) - 1
                    if area < 24:
                        key = tuple((centers[component] // SMALL_GROUP_GRID).astype(int))
                        small_groups.setdefault(key, []).extend(rings)
                    else:
                        shape = self.shape(rings, paint)
                        if shape:
                            parts.append(shape)
                            self.stats["gradient_fills"] += int(gradient)
            for rings in small_groups.values():
                shape = self.shape(rings, hex_color(rgb))
                if shape:
                    parts.append(shape)
            if position % 32 == 0:
                progress(f"Trace {position + 1}/{len(order)} colors: {self.stats['shapes']} shapes")
        return "\n".join(parts)

    def underpainting(self) -> str:
        """48 色低分辨率底板：剪影 clip 包住整组分色层，压住缩小观看的接缝。"""
        if min(self.width, self.height) < 8:
            return ""
        difference = np.abs(self.reference.astype(np.int16) - self.background).max(axis=2)
        silhouette = cv2.medianBlur((difference > 9).astype(np.uint8), 3)
        silhouette = cv2.erode(silhouette, np.ones((5, 5), np.uint8))
        clip, vertices = mask_polygon(silhouette, .5, 8)
        if not clip:
            return ""
        self.stats["polygon_vertices"] += vertices
        scale = min(1, 516 / self.width, 1 / 3)
        small = cv2.resize(self.reference,
                           (max(2, round(self.width * scale)), max(2, round(self.height * scale))),
                           interpolation=cv2.INTER_AREA)
        small = cv2.medianBlur(small, 3)
        labels, palette = quantize(small, UNDERPAINT_COLORS)
        parts = []
        for color in color_order(labels, palette):
            rgb = palette[color]
            if same_as_matte(rgb, self.background):
                continue
            mask = cv2.dilate((labels == color).astype(np.uint8),
                              cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
            polygon, vertices = mask_polygon(mask, .26, 1)
            if polygon:
                parts.append(self.account(
                    f'<div class="shape" style="top:0;left:0;right:0;bottom:0;background:{hex_color(rgb)};clip-path:{polygon}"></div>'))
                if self.raster is not None:
                    full = cv2.resize(mask, (self.width, self.height), interpolation=cv2.INTER_NEAREST)
                    self.raster.fill_mask(full > 0, 0, 0, hex_color(rgb))
                self.stats["polygon_vertices"] += vertices
                self.stats["shapes"] += 1
                self.stats["underpainting_shapes"] += 1
        return self.account(
            '<div class="underpainting" aria-hidden="true" style="clip-path:' + clip + '">') + "\n" + "\n".join(parts) + "\n</div>"


def render_document(reference, labels, palette, original_size, *, background, title,
                    epsilon, gradients, underpainting, max_bytes, progress, score=False):
    """全量渲染；返回 (HTML 文档字符串, 统计 dict)。"""
    renderer = ContourRenderer(reference, background, epsilon, gradients, max_bytes, score)
    foundation = renderer.underpainting() if underpainting else ""
    shapes = renderer.foreground(labels, palette, progress)
    width, height = original_size
    matte = hex_color(background)
    label = html.escape(title, quote=True)
    # ::before 撑高代替 aspect-ratio：后者在 Chromium 88 之前的 WebView 里
    # 不生效（容器高度塌陷），padding-top 百分比却是老内核都认的。
    sizer = number(height / width * 100.0, 5)
    paints = "".join(f".{name}{{background:{paint}}}" for paint, name in renderer.paint_classes.items())
    document = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; script-src 'none'; connect-src 'none'; font-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">
<title>{label}</title>
<style>
*{{box-sizing:border-box}}
html,body{{margin:0;min-height:100%;background:{matte};color-scheme:light}}
.illustration{{position:relative;isolation:isolate;overflow:hidden;width:100%;max-width:{renderer.width}px;margin:0 auto;background:{matte};contain:layout paint}}
.illustration::before{{content:"";display:block;padding-top:{sizer}%}}
.shape{{position:absolute;pointer-events:none}}
.underpainting{{position:absolute;top:0;left:0;right:0;bottom:0;pointer-events:none}}
.fallsafe{{display:block;position:fixed;top:0;left:0;right:0;bottom:0;z-index:2147483647;background:{matte};color:#333;padding:24px;font:15px/1.8 sans-serif;box-sizing:border-box}}
.fallsafe::after{{content:"{FALLSAFE_MESSAGE}"}}
@supports (clip-path: polygon(0 0)){{.fallsafe{{display:none}}}}
{paints}
@media print{{@page{{margin:0}}.illustration{{width:100%;print-color-adjust:exact;-webkit-print-color-adjust:exact}}}}
</style>
</head>
<body>
<div class="fallsafe"></div>
<!-- 羽画 · 纯 CSS 描摹：每个可见图形都是 div + CSS 多边形 -->
<main class="illustration" role="img" aria-label="{label}">
{foundation}
{shapes}
</main>
</body>
</html>
"""
    if len(document.encode("utf-8")) > max_bytes:
        raise BudgetExceeded(len(document.encode("utf-8")))
    if renderer.raster is not None:
        detail, thumbnail = renderer.raster.errors(reference)
        renderer.stats["similarity"] = {"mae": detail, "mae_thumbnail": thumbnail}
    return document, renderer.stats
