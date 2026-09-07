"""动画管线端到端：帧解码/采样 → trace_animation → 审计。"""
from io import BytesIO

import pytest
from PIL import Image

from data.plugins.astrbot_plugin_feather_art import service_animation as service  # noqa: E402
from data.plugins.astrbot_plugin_feather_art.feather_art.imaging import decode_frames  # noqa: E402

import util  # noqa: E402


def _gif(n=4, size=(16, 16)) -> bytes:
    frames = [Image.new("RGB", size, (i * 60 % 255, 30, 200)) for i in range(n)]
    buf = BytesIO()
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], duration=120)
    return buf.getvalue()


def test_decode_frames_two():
    frames, size, avg, total = decode_frames(util.gif_two_frames(), 512, (255, 255, 255))
    assert total == 2 and len(frames) == 2
    assert size == (8, 8)
    assert frames[0].shape == (8, 8, 3)
    assert avg == pytest.approx(0.1, abs=0.02)


def test_decode_frames_uniform_sampling():
    frames, _, _, total = decode_frames(_gif(n=6), 512, (255, 255, 255), sample_limit=3)
    assert total == 6 and len(frames) == 3  # 首尾 + 中间均匀


def test_decode_frames_rejects_single():
    with pytest.raises(ValueError):
        decode_frames(util.png_bytes(), 512, (255, 255, 255))


def test_decode_frames_adaptive_sample():
    """采样按时长自适应：6 秒 60 帧 → 约 4 帧/秒 ≈ 24 帧，不再死采 16 帧。"""
    frames, size, avg, total = decode_frames(util.gif_n_frames(60), 512,
                                             (255, 255, 255))
    assert total == 60 and len(frames) == 24
    assert avg == pytest.approx(0.1, abs=0.02)


def test_decode_frames_long_caps_at_limit():
    """超长动图按上限兜底：60 秒 300 帧 → 48 帧（上限），不无限膨胀。"""
    frames, _, _, total = decode_frames(util.gif_n_frames(300), 512,
                                        (255, 255, 255))
    assert total == 300 and len(frames) == 48


def test_trace_animation_e2e(tmp_path):
    rep = service.trace_animation(
        _gif(n=4), "motion", tmp_path / "anim.html",
        config=service.TraceConfig(progress=lambda _: None),
        force=True, report_path=tmp_path / "anim.json")
    assert rep["audit"]["valid"], rep["audit"]["errors"]
    an = rep["animation"]
    assert an["frames"] == 4 and an["original_frames"] == 4
    assert an["layers"] >= 1
    assert an["keyframe_total"] >= an["layers"] * 4
    assert rep["bytes"] > 0
    assert (tmp_path / "anim.html").read_text(encoding="utf-8").startswith("<!DOCTYPE html>")


def test_trace_animation_tween_and_report(tmp_path):
    rep = service.trace_animation(
        _gif(n=3), "motion", tmp_path / "t.html",
        config=service.TraceConfig(), tween=True, force=True)
    doc = (tmp_path / "t.html").read_text(encoding="utf-8")
    assert "linear" in doc and rep["animation"]["tween"] is True
    assert rep["audit"]["valid"]
