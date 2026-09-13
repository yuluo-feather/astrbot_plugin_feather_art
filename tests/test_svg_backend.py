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
import util

from data.plugins.astrbot_plugin_feather_art import service
from data.plugins.astrbot_plugin_feather_art.feather_art import audit, backends, render, svg_backend
from data.plugins.astrbot_plugin_feather_art.feather_art.contract import DocumentConfig
from data.plugins.astrbot_plugin_feather_art.feather_art.geometry import bridge_rings, number
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
    assert data.count("m") + data.count("M") == data.count("Z") == 2
    # 两个环各 8 个数，一个桥点都不多（桥会塞进一段往返线）
    assert len(re.findall(r"-?\d+(?:\.\d+)?", data)) == 16




def test_foundation_rings_are_stretched_to_the_canvas():
    """底板住在降采样网格里，落位盒是整幅画布——按比例铺开而不是原样画。"""
    grid = ((0.0, 0.0), (4.0, 4.0))
    layer = Region([_ring(2, 0, 0)], Solid(np.array([9, 9, 9], np.float64)), grid, BOX)
    clip = Clip([_ring(16, 0, 0)], BOX)
    document, _ = _render_svg(_illustration([], Foundation(clip, [layer])))
    clip_data = re.search(r'<clipPath id="c0"><path d="([^"]+)"', document).group(1)
    layer_data = re.search(r'<path class="f0" d="([^"]+)"', document).group(1)
    assert np.allclose(np.asarray(_decode(clip_data)[0]),
                       [[0, 0], [16, 0], [16, 16], [0, 16]])
    assert np.allclose(np.asarray(_decode(layer_data)[0]),
                       [[0, 0], [8, 0], [8, 8], [0, 8]])          # 4 倍：粗网格铺满画布



# ---- d 属性写法：相对增量（只换写法，不动几何） ----

_NUMBER = re.compile(r"[MmZz]|-?(?:\d+\.?\d*|\.\d+)")


def _decode(data, digits=svg_backend.COORD_DIGITS):
    """独立解码器：按 SVG 规则把 d 解回每个子路径的绝对顶点（画布像素）。

    刻意不复用后端的格式化代码——这条红线的价值就在两边独立。增量累积写错、
    首点参照写错、正则漏了 ".5" 这种省前导零的写法（会当成 5），都会在这里对不上。
    """
    scale = 10 ** digits
    tokens = _NUMBER.findall(data)
    rings, ring, cursor, start, mode, index = [], None, (0.0, 0.0), None, "M", 0
    while index < len(tokens):
        token = tokens[index]
        if token == "Z":
            cursor, index = start, index + 1
            continue
        if token in "Mm":
            mode, start, index = token, None, index + 1
            continue
        step = (round(float(token) * scale), round(float(tokens[index + 1]) * scale))
        index += 2
        if start is None:
            point = (cursor[0] + step[0], cursor[1] + step[1]) if mode == "m" else step
            ring = [point]
            rings.append(ring)
            start = point
        else:
            tail = ring[-1]
            ring.append((tail[0] + step[0], tail[1] + step[1]) if mode == "m" else step)
        cursor = ring[-1]
    return [[(x / scale, y / scale) for x, y in points] for points in rings]


def _canvas_rings(illustration):
    """文档顺序上的全部环，坐标已落到画布：剪影、底板各层、前景。"""
    def mapped(rings, box, target):
        origin, size = (np.asarray(part, np.float64) for part in box)
        target_origin, target_size = (np.asarray(part, np.float64) for part in target)
        return [target_origin + (np.asarray(ring, np.float64) - origin) * (target_size / size)
                for ring in rings]
    rings = []
    if illustration.foundation is not None:
        clip = illustration.foundation.clip
        rings += mapped(clip.rings, clip.box, clip.box)
        for region in illustration.foundation.regions:
            rings += mapped(region.rings, region.box, region.target)
    for region in illustration.foreground:
        rings += mapped(region.rings, region.box, region.target)
    return rings


def _dense_rings():
    """稠密轮廓：相邻顶点只差几个像素（ε 简化后的真实成品就长这样）。"""
    def noisy(x0, y0, step_x, step_y, count, wobble):
        index = np.arange(count, dtype=np.float64)
        return np.stack([x0 + step_x * index + wobble * np.sin(index * 1.7),
                         y0 + step_y * index + wobble * np.cos(index * 2.3)], axis=1)

    return [noisy(30.0, 30.0, 4.7, 1.1, 90, 2.0), noisy(450.0, 330.0, -6.1, -1.7, 60, 1.5)]


def _sparse_rings():
    """稀疏大环：顶点少、跨度大——增量跟绝对坐标一样长，相对写法就亏。"""
    return [np.array([[5, 5], [475, 5], [475, 355], [5, 355]], np.float64),
            np.array([[470, 350], [10, 344], [6, 10], [474, 8]], np.float64)]


def _spread_art(rings=None):
    """画布 480x360 + 底板 + 剪影；每个环一块区域（同色，会被合并成一条 path）。"""
    if rings is None:
        rings = _dense_rings() + _sparse_rings()
    grid = ((0.0, 0.0), (4.0, 4.0))
    layer = Region([_ring(2, 1, 1)], Solid(np.array([9, 9, 9], np.float64)), grid,
                   ((0.0, 0.0), (480.0, 360.0)))
    clip = Clip([np.array([[0, 0], [480, 0], [480, 360], [0, 360]], np.float64)],
                ((0.0, 0.0), (480.0, 360.0)))
    return _illustration([_solid((10, 20, 30), [ring]) for ring in rings],
                         Foundation(clip, [layer]), size=(480, 360))


def _single_path_art(rings):
    """只留前景、同色：会合成一条 path，跟测试侧拼的纯策略写法能一比一。"""
    return _illustration([_solid((10, 20, 30), [ring]) for ring in rings], None, size=(480, 360))


def _pure_d_data(illustration, relative):
    """测试侧自己拼的「纯策略」写法（全相对 / 全绝对），用来当上界。

    跟后端各写各的：这条红线量的是「有没有比两种纯策略都短」，不是「哪种写法好看」。
    两边若有一边算错，逐点解回绝对坐标那条红线会先红。
    """
    digits = svg_backend.COORD_DIGITS
    scale = 10 ** digits
    parts, previous = [], (0, 0)
    for ring in _canvas_rings(illustration):
        units = [(int(round(x * scale)), int(round(y * scale))) for x, y in ring]
        point = lambda value: number(value / scale, digits)      # noqa: E731
        if not relative:
            parts.append("M" + " ".join(f"{point(x)} {point(y)}" for x, y in units) + "Z")
        else:
            tokens = ["m", point(units[0][0] - previous[0]), point(units[0][1] - previous[1])]
            cursor = units[0]
            for step in units[1:]:
                tokens += [point(step[0] - cursor[0]), point(step[1] - cursor[1])]
                cursor = step
            parts.append(" ".join(tokens) + "Z")
        previous = units[0]
    return "".join(parts)




def test_path_data_decodes_back_to_the_same_geometry():
    """红线：拿独立解码器逐环逐点解回绝对坐标，必须与中间表示一致。

    写的是增量、读的是绝对——只要有一个环的首点参照或累积方向写错，这里必红。
    """
    document, _ = _render_svg(_spread_art())
    decoded = [ring for chunk in re.findall(r' d="([^"]+)"', document) for ring in _decode(chunk)]
    expected = _canvas_rings(_spread_art())          # 契约是「写到 COORD_DIGITS 位」，期望值取同一位
    assert len(decoded) == len(expected)
    for got, want in zip(decoded, expected):
        assert len(got) == len(want)
        assert np.allclose(np.asarray(got), np.round(want, svg_backend.COORD_DIGITS),
                           atol=1e-9), (got, want)


def test_writing_beats_both_pure_strategies():
    """红线：每个环自己挑写法——输出必须比「全写绝对」「全写相对」两种纯策略都短。

    拿两种纯策略当上界，就不必断言某个环具体写成哪种形式（那种断言会被「刚好差一
    两个字符」的几何左右）。变异：强制任一种纯策略，这条立刻红。
    """
    illustration = _single_path_art(_dense_rings() + _sparse_rings())
    document, _ = _render_svg(illustration)
    written = "".join(re.findall(r' d="([^"]+)"', document))
    absolute, relative = _pure_d_data(illustration, False), _pure_d_data(illustration, True)
    assert len(relative) < len(absolute)                     # 两种纯策略确实分得出高下
    assert len(written) < len(absolute), (len(written), len(absolute), len(relative))
    assert len(written) < len(relative), (len(written), len(absolute), len(relative))









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


def test_gradient_defs_are_not_rounded_into_shared_keys():
    """红线：角度/端点色只按精确值共享——不量化凑合并。

    曾经把角度量化到 5°、端点色量化到通道步长 8 来换合并，两张真实图上省不到
    0.1% 字节却白搭偏差，已去掉。这条钉住它别回头：差 1.5° 就该是两条 def，
    端点色差 3/255 也是两条。
    """
    base = _gradient()
    near_angle = Region([_ring(10, 0, 0)],
                        Gradient(46.5, base.paint.start, base.paint.end),
                        ((0.0, 0.0), (10.0, 10.0)), ((0.0, 0.0), (10.0, 10.0)))
    shifted = np.clip(base.paint.start + 3, 0, 255)
    near_color = Region([_ring(10, 0, 0)],
                        Gradient(45.0, shifted, base.paint.end),
                        ((0.0, 0.0), (10.0, 10.0)), ((0.0, 0.0), (10.0, 10.0)))
    document, stats = _render_svg(_illustration([base, near_angle, near_color]))
    assert stats["gradient_defs"] == 3
    assert document.count("<linearGradient ") == 3



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
    (lambda doc: re.sub(r' d="', ' x="', doc, count=1), "lacks a d attribute"),
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


def test_service_delivers_the_configured_backend(tmp_path):
    """配置值要真的走到产物：同一个入口换成 svg，交付的 HTML 就是 svg 方言。

    防的是「配置项存进去了、但没人读」这类哑配置——报告字段与文档方言必须一起变；
    反向对照保证这条红线不是对谁都绿。
    """
    svg_out = tmp_path / "svg.html"
    svg_report = service.trace_image(
        util.png_gradient((48, 48)), "sketch", svg_out,
        config=service.TraceConfig(render_backend="svg", progress=lambda _: None),
        force=True)
    assert svg_report["backend"] == "svg"
    assert svg_report["audit"]["valid"], svg_report["audit"]["errors"]
    assert "<svg" in svg_out.read_text(encoding="utf-8")

    css_out = tmp_path / "css.html"
    css_report = service.trace_image(
        util.png_gradient((48, 48)), "sketch", css_out,
        config=service.TraceConfig(progress=lambda _: None), force=True)
    assert css_report["backend"] == "css"
    assert "<svg" not in css_out.read_text(encoding="utf-8")


def test_audit_counts_gradient_paths_regardless_of_class_order():
    """一个 path 挂多个 class 时，渐变涂色要逐个 token 查到。

    只取最后一个 token 的实现会把 class="f0 extra" 这类路径漏掉——它不报错，
    只是统计悄悄偏低。判据取「顺序无关」：两种顺序都必须数得出来。
    """
    policy = "default-src 'none'; script-src 'none'; img-src 'none'"
    template = (
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta http-equiv="Content-Security-Policy" content="' + policy + '">'
        '<title>t</title><style>.f0{fill:url(#g0)}</style></head><body>'
        '<main class="illustration" role="img" aria-label="t">'
        '<svg viewBox="0 0 10 10"><defs>'
        '<linearGradient id="g0" gradientUnits="userSpaceOnUse" '
        'x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#000"/><stop offset="1" stop-color="#fff"/>'
        '</linearGradient></defs>'
        '<path class="__CLS__" d="M0 0L1 1Z"/></svg></main></body></html>')
    for cls in ("f0", "f0 extra", "extra f0"):
        result = audit.audit_html(template.replace("__CLS__", cls), "svg")
        assert result["valid"], result["errors"]
        assert result["gradient_fills"] == 1, cls
