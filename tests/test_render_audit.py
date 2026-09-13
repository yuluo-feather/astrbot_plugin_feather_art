"""渲染与审计测试：产物结构、契约审计、预算熔断、离线评分。"""

import numpy as np
import pytest

from data.plugins.astrbot_plugin_feather_art.feather_art import audit, backends, render
from data.plugins.astrbot_plugin_feather_art.feather_art.contract import (
    BudgetExceeded, FALLSAFE_MESSAGE,
)


def _small_art():
    """8x8 三色块参考图 + 标签 + 调色板。"""
    reference = np.zeros((8, 8, 3), np.uint8)
    reference[:4, :4] = (255, 0, 0)
    reference[:4, 4:] = (0, 255, 0)
    reference[4:, :] = (0, 0, 255)
    labels = np.zeros((8, 8), np.uint8)
    labels[:4, :4] = 0
    labels[:4, 4:] = 1
    labels[4:, :] = 2
    palette = np.array([[255, 0, 0], [0, 255, 0], [0, 0, 255]], np.uint8)
    return reference, labels, palette


def test_render_document_structure():
    reference, labels, palette = _small_art()
    doc, stats = render.render_document(
        reference, labels, palette, (8, 8), background=(255, 255, 255),
        title="测试稿", epsilon=0.5, gradients=False, underpainting=False,
        max_bytes=10_000_000, progress=lambda _: None)
    assert doc.startswith("<!DOCTYPE html>")
    assert '<main class="illustration"' in doc
    assert stats["shapes"] >= 3
    assert stats["polygon_vertices"] > 0
    result = audit.audit_html(doc)
    assert result["valid"], result["errors"]


def test_render_document_scored():
    reference, labels, palette = _small_art()
    doc, stats = render.render_document(
        reference, labels, palette, (8, 8), background=(255, 255, 255),
        title="测试稿", epsilon=0.5, gradients=False, underpainting=False,
        max_bytes=10_000_000, progress=lambda _: None, score=True)
    assert "similarity" in stats
    assert 0 <= stats["similarity"]["mae"] <= 255


def test_render_budget_exceeded():
    reference, labels, palette = _small_art()
    with pytest.raises(BudgetExceeded):
        render.render_document(
            reference, labels, palette, (8, 8), background=(255, 255, 255),
            title="测试稿", epsilon=0.5, gradients=False, underpainting=False,
            max_bytes=200, progress=lambda _: None)


def test_backend_registry_wired():
    """默认路径 = 按名取到的 css 后端；名字不认识就直接报错，不悄悄退回默认。

    可插拔的验收不是接口写得漂亮，是两条路都真被走到、且落在同一处。
    """
    reference, labels, palette = _small_art()
    args = (reference, labels, palette, (8, 8))
    kwargs = {"background": (255, 255, 255), "title": "测试稿", "epsilon": 0.5,
              "gradients": False, "underpainting": False,
              "max_bytes": 10 ** 7, "progress": lambda _: None}
    default_doc, _ = render.render_document(*args, **kwargs)
    named_doc, _ = render.render_document(*args, backend="css", **kwargs)
    assert default_doc == named_doc
    assert backends.get_backend("css").name == "css"
    assert sorted(backends.BACKENDS) == ["css", "svg"]      # 两门方言都在册：css 产品身份 / svg 可选方言
    with pytest.raises(ValueError):
        backends.get_backend("webgl")


def _valid_doc() -> str:
    reference, labels, palette = _small_art()
    doc, _ = render.render_document(
        reference, labels, palette, (8, 8), background=(255, 255, 255),
        title="测试稿", epsilon=0.5, gradients=False, underpainting=False,
        max_bytes=10_000_000, progress=lambda _: None)
    return doc


def test_audit_ok():
    result = audit.audit_html(_valid_doc())
    assert result["valid"]


def test_audit_rejects_script_element():
    doc = _valid_doc().replace("<body>", "<body><script>alert(1)</script>")
    result = audit.audit_html(doc)
    assert not result["valid"]
    assert any("script" in e for e in result["errors"])


def test_audit_rejects_url_in_css():
    doc = _valid_doc().replace("</style>", "url(https://evil.example/x.png)</style>")
    result = audit.audit_html(doc)
    assert not result["valid"]
    assert any("url" in e for e in result["errors"])


def test_audit_rejects_base64():
    doc = _valid_doc().replace("</style>", "base64,AAAA</style>")
    result = audit.audit_html(doc)
    assert not result["valid"]


def test_audit_requires_csp():
    import re
    doc = re.sub(r'<meta http-equiv="Content-Security-Policy"[^>]*>', "", _valid_doc())
    result = audit.audit_html(doc)
    assert not result["valid"]
    assert any("Content-Security-Policy" in e for e in result["errors"])


def test_audit_unbalanced_tag():
    doc = _valid_doc().replace("</html>", "")
    result = audit.audit_html(doc)
    assert not result["valid"]


def test_template_old_webview_compatible():
    """模板不用 Chromium 88+ 特性：无 aspect-ratio/min(100%/inset:0，
    有 ::before padding-top 撑高与 color-scheme:light（防自动深色反转）。"""
    reference, labels, palette = _small_art()
    doc, stats = render.render_document(
        reference, labels, palette, (8, 8), background=(255, 255, 255),
        title="测试稿", epsilon=0.5, gradients=False, underpainting=False,
        max_bytes=10_000_000, progress=lambda _: None)
    assert "aspect-ratio" not in doc
    assert "min(100%" not in doc
    assert "inset:0" not in doc
    assert "evenodd" not in doc
    assert ".illustration::before" in doc
    assert 'name="color-scheme"' in doc
    assert "max-width" in doc
    # 不带 clip-path 的内核要有提示层兜底（默认显示、支持时隐藏）
    assert '<div class="fallsafe"></div>' in doc
    assert FALLSAFE_MESSAGE in doc
    assert '@supports (clip-path: polygon(0 0))' in doc
    # 兼容改动不能破坏审计（元素/属性/CSP 全在合同内）
    result = audit.audit_html(doc)
    assert result["valid"], result["errors"]


def test_title_escaped_in_both_static_backends():
    """标题进 <title> 与 aria-label 两处，两个后端口径一致地转义。

    挡的是「一个后端转了、另一个没转」那种静默分家：默认标题里没有特殊字符，
    分家不会报错，只会在哪天标题接上外部输入时变成一个注入点。
    """
    reference, labels, palette = _small_art()
    for backend in ("css", "svg"):
        doc, _ = render.render_document(
            reference, labels, palette, (8, 8), background=(255, 255, 255),
            title='a<b>&"c', epsilon=0.5, gradients=False, underpainting=False,
            max_bytes=10_000_000, progress=lambda _: None, backend=backend)
        assert 'a&lt;b&gt;&amp;&quot;c' in doc, backend
        assert "<title>a<b>" not in doc, backend
        assert 'aria-label="a<b' not in doc, backend
        assert doc.count("&lt;b&gt;") == 2, backend      # title 与 aria-label 各一处
        result = audit.audit_html(doc, backend)
        assert result["valid"], result["errors"]


def test_every_backend_owns_a_label():
    """前提断言：注册表里每个后端都得有一句方言自称，缺了先红在这里。

    没有这条，将来接第三门方言时忘了写 label，报错的会是 backend_title 里的
    AttributeError——比「忘了自称」本身难读得多。
    """
    for name, backend in backends.BACKENDS.items():
        assert getattr(backend, "label", ""), name
        assert backend.label not in ("css", "svg"), name      # 自称是人话，不是注册键


def test_default_title_claims_its_own_dialect():
    """默认标题跟后端自称走：产物说的是什么方言，页签与朗读标签上就写什么。

    挡的是 2026-09-13 下午那次的实况：配置切到 svg，产出的文档在页签上还写着
    「羽画 · 纯 CSS 描摹」——描的是 SVG，自称是 CSS，用户第一眼看到的就是错的。
    """
    reference, labels, palette = _small_art()
    for backend, claim, taboo in (("css", "纯 CSS", "SVG"), ("svg", "SVG", "纯 CSS")):
        title = backends.backend_title(backend)
        assert claim in title and taboo not in title, backend
        doc, _ = render.render_document(
            reference, labels, palette, (8, 8), background=(255, 255, 255),
            title=title, epsilon=0.5, gradients=False, underpainting=False,
            max_bytes=10_000_000, progress=lambda _: None, backend=backend)
        assert f"<title>{title}</title>" in doc, backend
        assert f'aria-label="{title}"' in doc, backend      # 两处都要跟着走
        assert taboo not in doc, backend                    # 也不许顺手写另一门方言
        result = audit.audit_html(doc, backend)
        assert result["valid"], result["errors"]


def test_css_default_document_unchanged_by_title_rework():
    """等价性对照：静态默认路径（css + 不给标题）出稿与写死标题时逐字节相同。

    这条是给上面那条兜底的——标题改成「跟后端走」的过程中，最容易顺手把 css
    这条产品身份路径的字面量也动了；动没动不看代码看产物。
    """
    reference, labels, palette = _small_art()
    kwargs = {"background": (255, 255, 255), "epsilon": 0.5, "gradients": False,
              "underpainting": False, "max_bytes": 10 ** 7, "progress": lambda _: None}
    auto, _ = render.render_document(reference, labels, palette, (8, 8),
                                     title=backends.backend_title("css"), **kwargs)
    frozen, _ = render.render_document(reference, labels, palette, (8, 8),
                                       title="羽画 · 纯 CSS 描摹", **kwargs)
    assert auto == frozen
