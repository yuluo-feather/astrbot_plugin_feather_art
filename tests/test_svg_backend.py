"""SVG 后端测试：结构、方言审计、与 CSS 后端吃同一份中间表示。

判据分两层：
- 结构层：出来的文档必须过 svg 方言审计（元素/属性/锚点/CSP 全在合同内），
  且不许留 CSS 方言的痕迹；
- 数据层：两个后端吃的是同一份 Illustration，必须一块区域都不少、一个环点
  都不漏——合并同色区域最容易犯的错就是「悄悄丢掉一块」，所以拿中间表示
  当账本逐项对账，而不是看两边各自报的数。

本地跑法：这份测试 import 的是 data.plugins.astrbot_plugin_feather_art（框架
实际加载的那份），所以改完 dev 要同步到运行目录再跑，否则测的是旧代码。
"""

import re

import numpy as np
import pytest

from data.plugins.astrbot_plugin_feather_art import service
from data.plugins.astrbot_plugin_feather_art.feather_art import audit, backends, render, svg_backend
from data.plugins.astrbot_plugin_feather_art.feather_art.contract import DocumentConfig
from data.plugins.astrbot_plugin_feather_art.feather_art.geometry import bridge_rings
from data.plugins.astrbot_plugin_feather_art.feather_art.paint import Gradient, Solid
from data.plugins.astrbot_plugin_feather_art.feather_art.regions import (
    Clip, Foundation, Illustration, Region,
)

BOX = ((0.0, 0.0), (16.0, 16.0))


def _small_art():
    """16x16 三色块参考图 + 标签 + 调色板。"""
    reference = np.zeros((16, 16, 3), np.uint8)
    reference[:8, :8] = (255, 0, 0)
    reference[:8, 8:] = (0, 255, 0)
    reference[8:, :] = (0, 0, 255)
    labels = np.zeros((16, 16), np.uint8)
    labels[:8, :8] = 0
    labels[:8, 8:] = 1
    labels[8:, :] = 2
    palette = np.array([[255, 0, 0], [0, 255, 0], [0, 0, 255]], np.uint8)
    return reference, labels, palette


def _render(backend, **overrides):
    reference, labels, palette = _small_art()
    kwargs = {"background": (255, 255, 255), "title": "测试稿", "epsilon": 0.5,
              "gradients": False, "underpainting": False, "max_bytes": 10 ** 7,
              "progress": lambda _: None, "score": True}
    kwargs.update(overrides)
    return render.render_document(reference, labels, palette, (16, 16),
                                  backend=backend, **kwargs)


def _render_svg(illustration):
    return svg_backend.SvgBackend().render_static(
        illustration, DocumentConfig(title="测试稿", original_size=(16, 16),
                                     max_bytes=10 ** 7))


def _ring(n, x, y):
    """一个方形环。"""
    return np.array([[x, y], [x + n, y], [x + n, y + n], [x, y + n]], np.float64)


def _illustration(regions, foundation=None, size=(16, 16)):
    return Illustration(width=size[0], height=size[1],
                        background=np.array([255, 255, 255]), foreground=list(regions),
                        foundation=foundation, stats={"interior_holes": 0})


def _solid(rgb, rings, box=BOX):
    return Region(rings, Solid(np.array(rgb, np.float64)), box, box)


def _gradient(angle=45.0, box=((0.0, 0.0), (10.0, 10.0))):
    paint = Gradient(angle, np.array([0, 0, 0], np.float64), np.array([255, 255, 255], np.float64))
    return Region([_ring(10, 0, 0)], paint, box, box)


def _gradient_doc():
    """一份带渐变的 SVG 稿：审计拒收面测试的底稿（要它里面有 url(#g…)）。"""
    return _render_svg(_illustration([_gradient()]))[0]


def _path_data(document):
    """取第一条 path 的 d 属性。"""
    return document.split('<path class="')[1].split('d="')[1].split('"')[0]


# ---- 结构层 ----

def test_svg_document_passes_dialect_audit():
    document, stats = _render("svg")
    report = audit.audit_html(document, "svg")
    assert report["valid"], report["errors"]
    assert stats["backend"] == "svg"
    assert "<svg viewBox=" in document
    assert report["shapes"] == stats["paths"]  # 每条 path 一次（无底板，无剪影 path）


def test_svg_document_has_no_css_dialect_traces():
    document, _ = _render("svg")
    assert "<div" not in document
    assert "clip-path:polygon(" not in document
    assert "fallsafe" not in document
    assert "@supports" not in document


def test_svg_paints_only_via_class():
    """样式归样式：涂色写在 style 块的类里，几何只留在 d 里。"""
    document, _ = _render("svg")
    assert "fill:#" in document and 'fill="' not in document
    assert "stroke" not in document


def test_svg_keeps_underpainting_clip():
    document, stats = _render("svg", underpainting=True)
    assert stats["underpainting_shapes"] > 0
    assert '<clipPath id="c0">' in document and 'clip-path="url(#c0)"' in document
    report = audit.audit_html(document, "svg")
    assert report["valid"], report["errors"]


def test_hole_is_two_subpaths_without_bridge():
    """带洞的区域：一条 d 里两个子路径、靠 nonzero 挖孔，没有零面积桥。"""
    rings = [_ring(10, 0, 0), np.array([[3, 3], [3, 6], [6, 6], [6, 3]], np.float64)]
    document, stats = _render_svg(_illustration([_solid((10, 20, 30), rings)]))
    assert stats["paths"] == 1
    data = _path_data(document)
    assert data.count("M") == data.count("Z") == 2
    # 两个环各 8 个数，一个桥点都不多（桥会塞进一段往返线）
    assert len(re.findall(r"-?\d+(?:\.\d+)?", data)) == 16


def test_foundation_rings_are_stretched_to_the_canvas():
    """底板住在降采样网格里，落位盒是整幅画布——按比例铺开而不是原样画。"""
    grid = ((0.0, 0.0), (4.0, 4.0))
    layer = Region([_ring(2, 0, 0)], Solid(np.array([9, 9, 9], np.float64)), grid, BOX)
    clip = Clip([_ring(16, 0, 0)], BOX)
    document, _ = _render_svg(_illustration([], Foundation(clip, [layer])))
    assert '<clipPath id="c0"><path d="M0 0 16 0 16 16 0 16Z"/></clipPath>' in document
    assert '<path class="f0" d="M0 0 8 0 8 8 0 8Z"/>' in document   # 4 倍：粗网格铺满画布


# ---- 数据层：两个后端吃同一份中间表示 ----

def test_both_backends_account_for_every_region():
    """拿中间表示当账本：形状数、环点数三方对账。"""
    reference, labels, palette = _small_art()
    illustration = render.build_illustration(
        reference, labels, palette, background=(255, 255, 255), epsilon=0.5,
        gradients=False, underpainting=True, progress=lambda _: None)
    raw = sum(len(ring) for region in illustration.foreground for ring in region.rings)
    bridged = sum(len(bridge_rings(region.rings)) for region in illustration.foreground)
    base = sum(len(ring) for region in illustration.foundation.regions for ring in region.rings)
    clip = sum(len(ring) for ring in illustration.foundation.clip.rings)
    config = DocumentConfig("测试稿", (16, 16), 10 ** 7)
    _, css_stats = backends.get_backend("css").render_static(illustration, config)
    _, svg_stats = backends.get_backend("svg").render_static(illustration, config)
    expected_shapes = len(illustration.foreground) + len(illustration.foundation.regions)
    assert css_stats["shapes"] == svg_stats["shapes"] == expected_shapes
    assert css_stats["gradient_fills"] == svg_stats["gradient_fills"] == 0
    # 两边口径一致：前景 + 底板各层 + 剪影；差别只在洞要不要桥（这张图恰好没有洞）
    assert css_stats["polygon_vertices"] == bridged + base + clip
    assert svg_stats["polygon_vertices"] == raw + base + clip
    assert bridged == raw


def test_bridge_points_are_the_only_vertex_difference():
    """有洞时：CSS 的顶点数 = SVG 的 + 桥（这正是 SVG 挖孔不用付的那笔）。"""
    rings = [_ring(10, 0, 0), np.array([[3, 3], [3, 6], [6, 6], [6, 3]], np.float64)]
    illustration = _illustration([_solid((10, 20, 30), rings)])
    config = DocumentConfig("测试稿", (16, 16), 10 ** 7)
    _, css_stats = backends.get_backend("css").render_static(illustration, config)
    _, svg_stats = backends.get_backend("svg").render_static(illustration, config)
    assert svg_stats["polygon_vertices"] == 8                 # 两个环各 4 点，一点不多
    assert css_stats["polygon_vertices"] == len(bridge_rings(rings))
    assert css_stats["polygon_vertices"] > svg_stats["polygon_vertices"]


def test_gradient_defs_are_shared_when_geometry_matches():
    """同角度同色同盒子的渐变只写一条 def；角度差一格就另写一条。"""
    same = [_gradient(), Region([_ring(6, 2, 2)], _gradient().paint,
                                ((0.0, 0.0), (10.0, 10.0)), ((0.0, 0.0), (10.0, 10.0)))]
    document, stats = _render_svg(_illustration(same))
    assert document.count("<linearGradient ") == stats["gradient_defs"] == 1
    document, stats = _render_svg(_illustration(same + [_gradient(angle=90.0)]))
    assert document.count("<linearGradient ") == stats["gradient_defs"] == 2


# ---- 方言审计的拒收面 ----

@pytest.mark.parametrize("mutate,needle", [
    (lambda doc: doc.replace("</svg>", "<script>alert(1)</script></svg>"), "script"),
    (lambda doc: doc.replace("</svg>", '<image href="https://e.example/x.png"/></svg>'), "image"),
    (lambda doc: doc.replace("</svg>", '<use xlink:href="#g0"/></svg>'), "use"),
    (lambda doc: doc.replace("</svg>", '<foreignObject width="1" height="1"/></svg>'),
     "foreignobject"),
    (lambda doc: doc.replace("</style>", ".fx{fill:url(https://e.example/x.svg)}</style>"),
     "same-document"),
    (lambda doc: re.sub(r"url\(#g\d+\)", "url(#nope)", doc, count=1), "Dangling"),
    (lambda doc: doc.replace('d="M', 'x="M', 1), "lacks a d attribute"),
])
def test_svg_audit_rejects(mutate, needle):
    report = audit.audit_html(mutate(_gradient_doc()), "svg")
    assert not report["valid"]
    assert any(needle in error for error in report["errors"]), report["errors"]


def test_unknown_backend_is_reported_not_silently_defaulted():
    with pytest.raises(ValueError):
        backends.get_backend("webgl")
    with pytest.raises(service.TraceError):
        service.TraceConfig(render_backend="webgl")
