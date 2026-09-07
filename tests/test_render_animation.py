"""render_animation：图层 → @keyframes HTML；审计对动画的校验。"""
import numpy as np
import pytest

from data.plugins.astrbot_plugin_feather_art.feather_art.animate import ShapeKey, Track  # noqa: E402
from data.plugins.astrbot_plugin_feather_art.feather_art.audit import audit_html  # noqa: E402
from data.plugins.astrbot_plugin_feather_art.feather_art.render import (  # noqa: E402
    BudgetExceeded, FALLSAFE_MESSAGE,
)
from data.plugins.astrbot_plugin_feather_art.feather_art.render_animation import (  # noqa: E402
    AnimationConfig, _pad_poly, render_animation,
)


def _key(frame, x=10, y=10, w=20, h=20, color=(100, 100, 100)):
    return ShapeKey(
        frame=frame, label=1,
        poly=np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], np.float32),
        bbox=(x, y, w, h), centroid=(x + w / 2, y + h / 2), area=w * h, color=color)


def _tracks():
    a = Track(keys=[_key(0, x=10), _key(1, x=12), _key(2, x=14)])
    b = Track(keys=[_key(0, x=60, y=40, w=30, h=30, color=(200, 0, 0)),
                    _key(1, x=62, y=42, w=30, h=30, color=(200, 0, 0)),
                    _key(2, x=64, y=44, w=30, h=30, color=(200, 0, 0))])
    return [a, b]


def test_render_structure_and_audit():
    doc, stats = render_animation(_tracks(), (100, 100), 3,
                                  AnimationConfig(max_bytes=10_000_000))
    assert "@keyframes k0" in doc and "@keyframes k1" in doc
    assert 'class="layer l0"' in doc and 'class="layer l1"' in doc
    assert "step-end" in doc
    assert stats["layers"] == 2 and stats["frames"] == 3
    assert stats["keyframe_total"] == 8  # 每层 3 帧关键帧 + 100% 回环
    assert stats["duration"] == pytest.approx(3 / 8.0, abs=0.01)
    report = audit_html(doc)
    assert report["valid"], report["errors"]
    assert report["layers"] == 2
    assert report["keyframes"] == 2


def test_track_color_is_stable_across_frames():
    """长动画防闪色：同一轨迹所有关键帧 background 恒定（均值色）。"""
    import re as _re
    a = Track(keys=[_key(0, x=10, color=(120, 40, 200)),
                    _key(1, x=12, color=(130, 50, 210)),
                    _key(2, x=14, color=(110, 30, 190))])
    doc, _ = render_animation([a], (100, 100), 3,
                              AnimationConfig(max_bytes=10_000_000))
    start = doc.index("@keyframes k0{")
    end = doc.find("</style>", start)
    colors = set(_re.findall(r"background:(#[0-9a-f]{6})", doc[start:end]))
    assert len(colors) == 1


def test_render_tween_aligns_vertices():
    """补间模式：关键帧顶点数对齐到轨迹最大值，且为 linear。"""
    track = Track(keys=[_key(0, x=10), _key(1, x=12), _key(2, x=14)])
    doc, _ = render_animation([track], (100, 100), 3,
                              AnimationConfig(tween=True, max_bytes=10_000_000))
    assert "linear" in doc
    assert "step-end" not in doc
    # 每个关键帧多边形顶点数一致（4 点方块 + 100% 回环帧）
    polys = doc.split("clip-path:polygon(")[1:]
    counts = {len(p.split(")")[0].split(",")) for p in polys}
    assert counts == {4}


def test_render_budget_exceeded():
    with pytest.raises(BudgetExceeded):
        render_animation(_tracks(), (100, 100), 3,
                         AnimationConfig(max_bytes=200))


def test_render_loop_off():
    doc, _ = render_animation(_tracks(), (100, 100), 3,
                              AnimationConfig(loop=False, max_bytes=10_000_000))
    assert "animation-iteration-count:1" in doc
    assert "infinite" not in doc


def test_pad_poly_repeats_first_point():
    pts = np.array([[0, 0], [5, 0], [5, 5], [0, 5]], np.float32)
    padded = _pad_poly(pts, 6)
    assert padded.shape == (6, 2)
    assert list(padded[4]) == [0, 0] and list(padded[5]) == [0, 0]


def test_audit_rejects_dangling_animation():
    """layer 引用了不存在的 @keyframes → 审计报错。"""
    doc = (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
        "<meta http-equiv=\"Content-Security-Policy\" "
        "content=\"default-src 'none'; script-src 'none'; img-src 'none\">"
        "<title>t</title><style>.l0{animation-name:k9}</style></head><body>"
        "<main class=\"illustration\" role=\"img\" aria-label=\"t\">"
        "<div class=\"layer l0\"></div></main></body></html>")
    report = audit_html(doc)
    assert not report["valid"]
    assert any("missing keyframes" in e for e in report["errors"])


def test_template_old_webview_compatible_animation():
    """动画页同样不用 aspect-ratio/min()/inset，且带 viewport 与 color-scheme。"""
    doc, _ = render_animation(_tracks(), (100, 100), 3,
                              AnimationConfig(max_bytes=10_000_000))
    assert "aspect-ratio" not in doc
    assert "min(100%" not in doc
    assert "inset:0" not in doc
    assert "evenodd" not in doc
    assert ".illustration::before" in doc
    assert 'name="viewport"' in doc
    assert 'name="color-scheme"' in doc
    assert "max-width" in doc
    assert '<div class="fallsafe"></div>' in doc
    assert FALLSAFE_MESSAGE in doc
    assert '@supports (clip-path: polygon(0 0))' in doc
    report = audit_html(doc)
    assert report["valid"], report["errors"]
