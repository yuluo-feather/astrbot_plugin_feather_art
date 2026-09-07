"""渲染与审计测试：产物结构、契约审计、预算熔断、离线评分。"""

import numpy as np
import pytest

from data.plugins.astrbot_plugin_feather_art.feather_art import audit, render
from data.plugins.astrbot_plugin_feather_art.feather_art.render import (
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
