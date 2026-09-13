"""渲染后端：把中间表示写成某一种单文件文档。

一个后端就是一件本事：illustration + config → 文档。几何、涂色、绘制顺序
全在 Illustration 里，后端不许动——它只决定「写成什么字」：摆位、精度、
去重、模板，以及超出体积预算时抛 BudgetExceeded。

当前只挂 CSS 一个后端（那是产品身份，不是技术限制）。接口按协议写，是为了
让第二种方言接上来时不必回头改上游——但也别指望接口能替你做决定：
成品一律走 .html 外壳（独立 .svg 在聊天里是文件不是预览，且没有 meta CSP），
所以这里没有「文件后缀」这种成员。
"""

import html
import math
from dataclasses import dataclass
from typing import Protocol

from .contract import FALLSAFE_MESSAGE, BudgetExceeded
from .geometry import bridge_rings, hex_color, number, polygon_css
from .paint import Gradient

# 底板多边形的小数位（前景按包围盒尺寸算，见 CssShapeWriter.shape）
FOUNDATION_DIGITS = 4


@dataclass(frozen=True)
class DocumentConfig:
    """出文档所需的这点参数（几何不在这里，在 Illustration 里）。

    original_size: 原图尺寸——只用来算容器长宽比（描摹尺寸可能被压过）；
    max_bytes: 体积上限，超了抛 BudgetExceeded。
    """

    title: str
    original_size: tuple
    max_bytes: int


class RenderBackend(Protocol):
    """静态渲染后端：结构化中间表示 → 单文件文档。

    render_static 必须逐字节确定：同一份 illustration 与 config，任何时候
    都得产出同一串字符（产品承诺的一部分，基线红线盯着）。
    """

    name: str

    def render_static(self, illustration, config: DocumentConfig) -> tuple:
        """返回 (文档字符串, 统计 dict)。超预算抛 BudgetExceeded。"""
        ...


class CssShapeWriter:
    """把区域写成 div.shape 序列，边写边记账。

    预算纪律：只累计不抛——超预算不打断拼接，由 CssBackend.render_static
    末尾终检统一抛，携带真实完整字节数。中途抛会让所有失败档的计数趋同
    （停在 target+ε），fit 跳档的预测就失去依据，等于白算。
    """

    def __init__(self, illustration):
        self.width = illustration.width
        self.height = illustration.height
        self.byte_count = 0
        self.paint_classes: dict[str, str] = {}
        self.stats = {"shapes": 0, "gradient_fills": 0, "polygon_vertices": 0,
                      "underpainting_shapes": 0}

    def account(self, text: str) -> str:
        self.byte_count += len(text.encode("utf-8"))
        return text

    def solid_class(self, paint: str) -> str:
        """每种纯色一个共享 class，只在头部 <style> 里声明一次。"""
        if paint not in self.paint_classes:
            self.paint_classes[paint] = f"p{len(self.paint_classes)}"
        return self.paint_classes[paint]

    def shape(self, region) -> str:
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


class CssBackend:
    """纯 HTML + CSS 单文件后端：纯色共享类、渐变内联、clip-path 裁形。"""

    name = "css"

    def render_static(self, illustration, config: DocumentConfig) -> tuple:
        writer = CssShapeWriter(illustration)
        foundation = (writer.foundation(illustration.foundation)
                      if illustration.foundation else "")
        shapes = "\n".join(writer.shape(region) for region in illustration.foreground)
        width, height = config.original_size
        matte = hex_color(illustration.background)
        label = html.escape(config.title, quote=True)
        # ::before 撑高代替 aspect-ratio：后者在 Chromium 88 之前的 WebView 里
        # 不生效（容器高度塌陷），padding-top 百分比却是老内核都认的。
        sizer = number(height / width * 100.0, 5)
        paints = "".join(f".{name}{{background:{paint}}}"
                         for paint, name in writer.paint_classes.items())
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
        if len(document.encode("utf-8")) > config.max_bytes:
            raise BudgetExceeded(len(document.encode("utf-8")))
        return document, writer.stats


BACKENDS: dict[str, RenderBackend] = {"css": CssBackend()}


def get_backend(name: str) -> RenderBackend:
    """按名取后端；名字不认识就直接报出来，别悄悄退回默认。"""
    try:
        return BACKENDS[name]
    except KeyError:
        raise ValueError(
            f"未知的渲染后端：{name}（可用的有 {'、'.join(sorted(BACKENDS))}）") from None
