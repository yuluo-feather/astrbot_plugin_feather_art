"""转换编排测试：端到端描摹、覆盖保护、fit 阶梯、确定性。"""

import pytest

from data.plugins.astrbot_plugin_feather_art import service
import util


def _trace(tmp_path, preset="sketch", fit=10.0, **kwargs):
    return service.trace_image(
        util.png_gradient((64, 64)), preset, tmp_path / "out.html",
        config=service.TraceConfig(fit_mb=fit, score=True, progress=lambda _: None),
        force=True, report_path=tmp_path / "r.json", **kwargs)


def test_trace_end_to_end(tmp_path):
    rep = _trace(tmp_path)
    assert (tmp_path / "out.html").exists()
    assert (tmp_path / "r.json").exists()
    assert rep["audit"]["valid"]
    assert rep["shapes"] > 0
    assert rep["bytes"] > 0
    assert rep["similarity"] is not None
    assert rep["preset"]["key"] == "sketch"


def test_trace_rejects_overwrite(tmp_path):
    _trace(tmp_path)
    with pytest.raises(service.TraceError):
        service.trace_image(
            util.png_gradient((64, 64)), "sketch", tmp_path / "out.html",
            config=service.TraceConfig(), force=False)


def test_trace_rejects_non_html(tmp_path):
    with pytest.raises(service.TraceError):
        service.trace_image(
            util.png_gradient((64, 64)), "sketch", tmp_path / "out.txt",
            config=service.TraceConfig(), force=True)


def test_trace_fit_too_small(tmp_path):
    with pytest.raises(service.TraceError) as exc:
        _trace(tmp_path, fit=0.001)  # 1 KiB 预算连模板都装不下，必触发阶梯熔断
    assert "降" in str(exc.value)


def test_trace_deterministic(tmp_path):
    rep1 = _trace(tmp_path, fit=10.0)
    rep2 = _trace(tmp_path / "sub", fit=10.0)
    assert rep1["sha256"] == rep2["sha256"]


def test_trace_rejects_animated(tmp_path):
    with pytest.raises(service.TraceError):
        service.trace_image(
            util.gif_two_frames(), "sketch", tmp_path / "g.gif.html",
            config=service.TraceConfig(), force=True)


def test_trace_reports_fit_attempts(tmp_path):
    # 0.35 MiB 下 64x64 图大概率一次装下；大图才走阶梯，这里验证字段存在
    rep = _trace(tmp_path, fit=10.0)
    assert rep["fit"]["target_mb"] == 10.0


# ---------- fit 跳档（_next_attempt）纯函数锁定 ----------


def _base_ladder():
    return service._fit_ladder(
        {"max_width": 1600, "colors": 256, "epsilon": 0.24, "passes": 4})


def test_next_attempt_colors_axis_judge():
    """颜色轴判定：颜色降到地板够 → 在颜色轴上跳（宽度不变）。"""
    ladder = _base_ladder()
    hist = [{"max_width": 1600, "colors": 128, "bytes": 7 * 2**20, "axis": "colors"}]
    nxt = service._next_attempt(hist, 6 * 2**20, ladder)
    assert (nxt["max_width"], nxt["colors"]) == (1600, 64)


def test_next_attempt_switches_to_width_axis():
    """颜色降到底也不够 → 切宽度轴，预测段半程跳。"""
    ladder = _base_ladder()
    hist = [{"max_width": 1600, "colors": 256, "bytes": 20 * 2**20, "axis": "width"}]
    nxt = service._next_attempt(hist, 8 * 2**20, ladder)
    assert (nxt["max_width"], nxt["colors"]) == (1200, 64)


def test_next_attempt_loglog_converges():
    """宽度轴两个同轴真实点 → log-log 插值精确命中。"""
    ladder = _base_ladder()
    hist = [
        {"max_width": 1600, "colors": 64, "bytes": 12 * 2**20, "axis": "width"},
        {"max_width": 1200, "colors": 64, "bytes": 9 * 2**20, "axis": "width"},
    ]
    nxt = service._next_attempt(hist, 8 * 2**20, ladder)
    assert (nxt["max_width"], nxt["colors"]) == (900, 64)


def test_next_attempt_clamps_to_ultimate_floor():
    """预测低于阶梯实际地板 → 钳位到终极替补档。"""
    ladder = _base_ladder()
    hist = [{"max_width": 512, "colors": 4, "bytes": 5 * 2**20, "axis": "width"}]
    nxt = service._next_attempt(hist, 1 * 2**20, ladder)
    assert (nxt["max_width"], nxt["colors"]) == (256, 4)


def test_next_attempt_interpolation_needs_same_color():
    """插值只用同颜色宽度点：base（256 色）与当前（64 色）非同函数 → 走预测段。"""
    ladder = _base_ladder()
    hist = [
        {"max_width": 1600, "colors": 256, "bytes": 15 * 2**20, "axis": "width"},
        {"max_width": 900, "colors": 64, "bytes": 10 * 2**20, "axis": "width"},
    ]
    nxt = service._next_attempt(hist, 1 * 2**20, ladder)
    # 同色点只有 1 个 → 预测段半程跳（不混入 256 色点外推）
    assert (nxt["max_width"], nxt["colors"]) == (512, 64)


def test_next_attempt_never_regresses():
    """最粗档仍超支：返回末档本身（不 None 不回退），由外层解算熔断。"""
    ladder = _base_ladder()
    hist = [{"max_width": 256, "colors": 4, "bytes": 10 * 2**20, "axis": "width"}]
    nxt = service._next_attempt(hist, 1 * 2**20, ladder)
    assert (nxt["max_width"], nxt["colors"]) == (256, 4)
    assert service._next_attempt(hist, 1 * 2**20, ladder) is not None


def test_next_attempt_deterministic():
    """同一失败史必得同一档（确定性承诺）。"""
    ladder = _base_ladder()
    hist = [{"max_width": 1600, "colors": 256, "bytes": 20 * 2**20, "axis": "width"}]
    a = service._next_attempt(hist, 8 * 2**20, ladder)
    b = service._next_attempt(hist, 8 * 2**20, ladder)
    assert a == b


def test_fit_ladder_colors_first():
    """降档阶梯：颜色优先，宽度兜底；且整条阶梯单调收紧。"""
    base = {"max_width": 1600, "colors": 256, "epsilon": 0.24, "passes": 4}
    ladder = service._fit_ladder(base)
    assert ladder[0] == base
    # 前两级都是「保宽度、先降颜色」
    assert ladder[1]["max_width"] == 1600 and ladder[1]["colors"] == 128
    assert ladder[2]["max_width"] == 1600 and ladder[2]["colors"] == 64
    # 单调收紧：宽度不增、颜色不增、且每级至少有一样变小
    for a, b in zip(ladder, ladder[1:]):
        assert b["max_width"] <= a["max_width"]
        assert b["colors"] <= a["colors"]
        assert (b["max_width"], b["colors"]) != (a["max_width"], a["colors"])
    # 覆盖到底：最窄一档 <= 512 宽
    assert min(c["max_width"] for c in ladder) <= 512


def test_fit_ladder_dedups_small_palette():
    """96 色档（速写）：÷2 与 ÷4 取整后相同，不得出现重复级。"""
    base = {"max_width": 768, "colors": 96, "epsilon": 0.38, "passes": 2}
    ladder = service._fit_ladder(base)
    keys = [(c["max_width"], c["colors"]) for c in ladder]
    assert len(keys) == len(set(keys))


def test_traceconfig_guards_bad_values(tmp_path):
    """渗透发现：畸形 fit/max 值不得穿透到算数层（TypeError → 中文熔断）。"""
    cfg = service.TraceConfig(fit_mb="abc", max_mb=-1.0)
    assert cfg.fit_mb == 40.0   # 转 float 失败回默认
    assert cfg.max_mb == 0.0    # 负数钳回 0
    with pytest.raises(service.TraceError):
        service.trace_image(
            util.png_gradient((16, 16)), "sketch", tmp_path / "x.html",
            config=cfg, force=True)


def test_fit_target_tolerance():
    """fit 预算含 2% 容差；0 = 不设目标，且不超 max_mb 硬上限。"""
    t = service._fit_target(20.0, 64.0)
    assert t == int(20 * 1024 * 1024 * service.FIT_TOLERANCE)
    assert t > 20 * 1024 * 1024  # 容差确实放宽了
    assert service._fit_target(0.0, 64.0) == 64 * 1024 * 1024
    assert service._fit_target(100.0, 64.0) == 64 * 1024 * 1024
    assert service._fit_target(40.0, 64.0) < 64 * 1024 * 1024
