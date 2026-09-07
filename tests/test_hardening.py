"""防护层测试：体积上限、像素炸弹、多帧检查、损坏文件。"""

import pytest

from data.plugins.astrbot_plugin_feather_art import hardening
import util


def test_size_limit_exceeded():
    data = b"x" * (5 * 1024 * 1024)
    with pytest.raises(ValueError):
        hardening.check_file_size(data, 1 * 1024 * 1024)


def test_size_limit_ok():
    hardening.check_file_size(b"small", 1024 * 1024)


def test_pixel_bomb_rejected():
    data = util.png_big_pixels(6400, 6400)  # 40.96M > 40M
    with pytest.raises(ValueError) as exc:
        hardening.inspect_animation(data, 40_000_000)
    assert "像素" in str(exc.value)


def test_pixel_bomb_allowed_with_higher_limit():
    data = util.png_big_pixels(6400, 6400)
    fmt, size, frames = hardening.inspect_animation(data, 100_000_000)
    assert fmt == "PNG" and size == (6400, 6400) and frames == 1


def test_animation_length_hint_short_is_none():
    """短动图不提示（2 帧 / 0.2 秒）。"""
    assert hardening.animation_length_hint(util.gif_two_frames(), 2, "") is None


def test_animation_length_hint_long_returns_note():
    """40 秒长动图：返回提示文案，不闷头描。"""
    note = hardening.animation_length_hint(util.gif_n_frames(400), 400, "")
    assert note is not None and "继续" in note and "40" in note


def test_animation_length_hint_continue_bypasses():
    """用户明确说「继续」→ 放行描摹。"""
    assert hardening.animation_length_hint(
        util.gif_n_frames(400), 400, "继续描吧") is None


def test_estimate_duration_from_metadata():
    """时长估算取首帧元数据：2 帧 × 100ms ≈ 0.2 秒。"""
    assert hardening.estimate_duration(util.gif_two_frames(), 2) == pytest.approx(0.2, abs=0.02)


def test_long_animation_allowed_by_default():
    """默认帧数上限 6000：201 帧动图不再被拒（采样 ≤16 帧描摹，成本可控）。"""
    fmt, size, frames = hardening.inspect_animation(util.gif_n_frames(201))
    assert frames == 201 and fmt == "GIF"


def test_frame_limit_respected_when_lowered():
    """显式收紧 max_frames 时仍拒绝——防线可调，不因放宽而失效。"""
    with pytest.raises(ValueError) as exc:
        hardening.inspect_animation(util.gif_n_frames(201), max_frames=200)
    assert "帧" in str(exc.value)


def test_animation_inspected_not_rejected():
    """动图入口不再拒绝：inspect_animation 放行，帧数交给调用方分发。"""
    fmt, size, frames = hardening.inspect_animation(util.gif_two_frames())
    assert frames >= 2 and fmt == "GIF"


def test_corrupt_rejected():
    with pytest.raises(ValueError):
        hardening.inspect_animation(b"definitely not an image")


def test_ok_png():
    fmt, size, frames = hardening.inspect_animation(util.png_bytes((64, 64)))
    assert fmt == "PNG" and size == (64, 64) and frames == 1


def test_user_fault_internal_not_leaked():
    """安全修复：内部异常（ASCII 开头/空消息）不得外露给用户。"""
    assert hardening.user_fault(ValueError("cv2.error: /srv/img/out.bin")) is None
    assert hardening.user_fault(ValueError("")) is None
    assert hardening.user_fault(ValueError("cannot identify image file")) is None


def test_user_fault_chinese_passes():
    """自家中文文案（首字符非 ASCII）正常放行给用户。"""
    msg = "图片太大了（12.3 MiB），换个小的罢。"
    assert hardening.user_fault(ValueError(msg)) == msg
    assert hardening.user_fault(ValueError("不支持动图/多帧输入，请先导出单帧。")) == (
        "不支持动图/多帧输入，请先导出单帧。")
    assert hardening.user_fault(ValueError("输出体积超预算，减小图片或换低一档精度再来。")) == (
        "输出体积超预算，减小图片或换低一档精度再来。")
