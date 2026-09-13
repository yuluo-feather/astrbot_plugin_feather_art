"""文档构建：把结构化中间表示写成纯 HTML + CSS 单文件。

方言（羽画版）：
- 一个 main.illustration，里面住着一群 div.shape；
- 可见图形只来自 CSS clip-path 多边形与 linear-gradient；
- 纯色走共享类 .p0/.p1/...（按色值去重），渐变直接内联 background；
- 底板层是 inset:0 的整幅容器，按降采样网格的盒子归一化多边形；
- 精度按形状包围盒定：两位小数起步，越大的形状越配多留一位；
  底板是大而整的剪影，固定给足四位。

几何与涂色不在这里——regions.build_illustration 已经算完；本模块只管
「写成 CSS」这一件事：怎么摆、去哪些重、给几位精度。

预算纪律：拼接过程只记账不抛——超预算不打断提取与拼接，由末尾终检抛出
BudgetExceeded（携带真实完整字节数），给上层的 fit 跳档精确的体积信号。
注意：不能中途抛——所有失败档的计数都会趋同（停在 target+ε），
跳档预测失去依据，等于白算。
"""

import html
import math

from .geometry import bridge_rings, hex_color, number, polygon_css
from .paint import Gradient
from .regions import Region, build_illustration
from .score import Rasterizer

# 老内核兜底提示文案（静态/动画渲染共用，改这里一处即可）
FALLSAFE_MESSAGE = "此浏览器内核较旧，不支持 CSS 多边形（clip-path）渲染——画面会错乱成色块。推荐改用 Chrome / Edge / Firefox 等现代浏览器打开，或转至电脑浏览器查看。"
# 底板多边形的小数位（前景按包围盒尺寸算，见 CssShapeWriter.shape）
FOUNDATION_DIGITS = 4


class BudgetExceeded(ValueError):
    """渲染中途发现文档将超出体积预算。"""

    def __init__(self, byte_count: int):
        super().__init__("HTML exceeds the byte budget")
        self.byte_count = byte_count


class CssShapeWriter:
    """把区域写成 div.shape 序列，边写边记账。"""

    def __init__(self, illustration):
        self.width = illustration.width
        self.height = illustration.height
        self.byte_count = 0
        self.paint_classes: dict[str, str] = {}
        self.stats = {"shapes": 0, "gradient_fills": 0, "polygon_vertices": 0,
                      "underpainting_shapes": 0}

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

    def shape(self, region: Region) -> str:
        """前景区域 → 一个 div.shape（按包围盒定位 + 多边形裁形）。"""
        origin, size = region.box
        points = bridge_rings(region.rings)
        # 两位小数已把误差压到 尺寸/10000 px，只有极大的形状才配第三位
        digits = max(2, math.ceil(math.log10(max(size) / 10)))
        clip = polygon_css(points, origin, size, digits)
        css = region.paint.to_css()
        cls = "shape"
        background = ""
        if isinstance(region.paint, Gradient):
            background = f"background:{css};"
        else:
            cls = f"shape {self.solid_class(css)}"
        style = (
            f"left:{number(origin[0] / self.width * 100, 3)}%;"
            f"top:{number(origin[1] / self.height * 100, 3)}%;"
            f"width:{number(size[0] / self.width * 100, 3)}%;"
            f"height:{number(size[1] / self.height * 100, 3)}%;"
            f"{background}clip-path:{clip}"
        )
        self.stats["shapes"] += 1
        self.stats["polygon_vertices"] += len(points)
        self.stats["gradient_fills"] += int(isinstance(region.paint, Gradient))
        return self.account(f'<div class="{cls}" style="{style}"></div>')

    def _board_polygon(self, holder) -> str:
        """剪影/底板层 → polygon 串（按网格盒子归一化）；空环集返回空串。"""
        points = bridge_rings(holder.rings)
        if not len(points):
            return ""
        self.stats["polygon_vertices"] += len(points)
        return polygon_css(points, holder.box[0], holder.box[1], FOUNDATION_DIGITS)

    def foundation(self, foundation) -> str:
        """底板：inset:0 的整幅容器（剪影裁形）+ 里面若干分色层。

        分色层按降采样网格的盒子归一化；同一串百分比铺到整幅画布上，
        等于把粗网格拉开——所以这里不需要额外的缩放系数。
        """
        clip = self._board_polygon(foundation.clip)
        if not clip:
            return ""
        parts = []
        for region in foundation.regions:
            polygon = self._board_polygon(region)
            if not polygon:
                continue
            parts.append(self.account(
                f'<div class="shape" style="top:0;left:0;right:0;bottom:0;'
                f'background:{region.paint.to_css()};clip-path:{polygon}"></div>'))
            self.stats["shapes"] += 1
            self.stats["underpainting_shapes"] += 1
        return self.account(
            '<div class="underpainting" aria-hidden="true" style="clip-path:' + clip + '">') + "\n" + "\n".join(parts) + "\n</div>"


def render_document(reference, labels, palette, original_size, *, background, title,
                    epsilon, gradients, underpainting, max_bytes, progress, score=False):
    """全量渲染；返回 (HTML 文档字符串, 统计 dict)。"""
    raster = Rasterizer((reference.shape[1], reference.shape[0]), background) if score else None
    illustration = build_illustration(
        reference, labels, palette, background=background, epsilon=epsilon,
        gradients=gradients, underpainting=underpainting, progress=progress, raster=raster)
    writer = CssShapeWriter(illustration)
    foundation = writer.foundation(illustration.foundation) if illustration.foundation else ""
    shapes = "\n".join(writer.shape(region) for region in illustration.foreground)
    width, height = original_size
    matte = hex_color(background)
    label = html.escape(title, quote=True)
    # ::before 撑高代替 aspect-ratio：后者在 Chromium 88 之前的 WebView 里
    # 不生效（容器高度塌陷），padding-top 百分比却是老内核都认的。
    sizer = number(height / width * 100.0, 5)
    paints = "".join(f".{name}{{background:{paint}}}" for paint, name in writer.paint_classes.items())
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
.illustration{{position:relative;isolation:isolate;overflow:hidden;width:100%;max-width:{illustration.width}px;margin:0 auto;background:{matte};contain:layout paint}}
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
    stats = {**illustration.stats, **writer.stats}
    if raster is not None:
        detail, thumbnail = raster.errors(reference)
        stats["similarity"] = {"mae": detail, "mae_thumbnail": thumbnail}
    return document, stats
