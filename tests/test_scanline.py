"""扫描线渲染：结构约定与审计红线。

被测对象是运行目录副本（conftest 把 AstrBot 根加进 sys.path，import 走
data.plugins.astrbot_plugin_feather_art），dev 改动须先同步再跑测试。
"""

import re
from io import BytesIO

import numpy as np
import pytest
from PIL import Image

from data.plugins.astrbot_plugin_feather_art import service_animation as service  # noqa: E402
from data.plugins.astrbot_plugin_feather_art.feather_art.audit import audit_html  # noqa: E402
from data.plugins.astrbot_plugin_feather_art.feather_art.scanline import (  # noqa: E402
    OVERLAP_PCT, ScanlineConfig, render_scanline)


def _gif(n=4, size=(16, 16), duration=120):
    frames = [Image.new("RGB", size, (i * 40 % 255, 30, 200)) for i in range(n)]
    buf = BytesIO()
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:],
                   duration=duration)
    return buf.getvalue()


def _frames(n=3, size=(16, 8)):
    return [np.asarray(Image.new("RGB", size, (i * 60 % 255, 90, 120)), np.uint8)
            for i in range(n)]


def test_scanline_structure_and_audit():
    doc, stats = render_scanline(_frames(3), ScanlineConfig(duration=0.9))
    assert stats["style"] == "scanline" and stats["rows"] == 4  # 8 // ROW_PX
    assert stats["frames"] == 3 and stats["duration"] == 0.9
    assert '@keyframes k0' in doc
    assert 'class="illustration"' in doc
    # padding-top 必须带 %（裸数字 = 画布塌陷，2026-09-08 坑的回归红线）
    m = re.search(r"padding-top:([0-9.]+)%", doc)
    assert m and float(m.group(1)) > 0
    rep = audit_html(doc)
    assert rep["valid"], rep["errors"]


def test_scanline_static_row_and_dynamic():
    """前两帧相同 → 静止行 shape（inline clip-path）；第三帧变化 → 动态层。"""
    same = [np.asarray(Image.new("RGB", (8, 8), (10, 20, 30)), np.uint8)
            for _ in range(2)]
    diff = np.asarray(Image.new("RGB", (8, 8), (200, 100, 50)), np.uint8)
    doc, stats = render_scanline(same + [diff], ScanlineConfig(duration=0.3))
    assert stats["layers"] > 0
    assert stats["static_rows"] + stats["layers"] == stats["rows"]
    # 静止行 shape 必须 inline clip-path（audit 契约）
    m = doc.count("clip-path:polygon(0 0,100% 0,100% 100%,0 100%)")
    assert m == stats["static_rows"]


def test_scanline_loop_steps_and_100pct():
    doc, _ = render_scanline(_frames(4), ScanlineConfig(duration=1.0))
    assert "100%{background:" in doc
    assert "0.00%{background:" in doc and "75.00%{background:" in doc


def test_scanline_row_height_overlap():
    """行高 = 行距% + 重叠（防缩放缝隙的回归红线）。"""
    doc, stats = render_scanline(_frames(2), ScanlineConfig(duration=0.2))
    expect = 100.0 / stats["rows"] + OVERLAP_PCT
    assert ("height:%.4f%%" % expect) in doc


def test_trace_animation_scanline_e2e(tmp_path):
    rep = service.trace_animation(
        _gif(n=4), "motion", tmp_path / "a.html",
        config=service.TraceConfig(progress=lambda _: None),
        force=True, report_path=tmp_path / "a.json")
    assert rep["audit"]["valid"], rep["audit"]["errors"]
    assert rep["animation"]["style"] == "scanline"
    assert rep["animation"]["rows"] > 0
    # 4 帧 × 120ms 动图：循环时长应约等于原时长
    assert abs(rep["animation"]["duration"] - 0.48) < 0.05


def test_trace_animation_vector_style(tmp_path):
    rep = service.trace_animation(
        _gif(n=4), "motion", tmp_path / "v.html",
        config=service.TraceConfig(progress=lambda _: None),
        style="vector", force=True)
    assert rep["audit"]["valid"], rep["audit"]["errors"]
    assert rep["animation"]["style"] == "vector"
