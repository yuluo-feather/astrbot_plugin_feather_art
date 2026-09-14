"""options.parse_options：指令解析顺序无关 + 占位词透明。"""
from data.plugins.astrbot_plugin_feather_art.options import (  # noqa: E402
    PRESET_WORDS,
    SAMPLE_MAX,
    SAMPLE_MIN,
    parse_options,
)


def test_preset_position_does_not_matter():
    """档位在图片词前后都能认。"""
    assert parse_options("图片 工笔", "freehand", 20.0) == ("工笔", 20.0, 0)
    assert parse_options("工笔 图片", "freehand", 20.0) == ("工笔", 20.0, 0)
    assert parse_options("速写 图片 写意", "freehand", 20.0) == ("写意", 20.0, 0)


def test_placeholder_words_are_transparent():
    """「图片」等占位词不参与解析，也绝不报错。"""
    for word in ("图片", "图", "pic", "image"):
        preset, fit, sample = parse_options(f"/羽画 {word} 工笔", "freehand", 20.0)
        assert preset == "工笔"
        assert fit == 20.0
        assert sample == 0


def test_english_presets():
    for word in ("sketch", "freehand", "finebrush"):
        preset, _, _ = parse_options(f"图片 {word}", "freehand", 20.0)
        assert preset == word


def test_fit_position_does_not_matter():
    assert parse_options("图片 工笔 --fit 10", "freehand", 20.0) == ("工笔", 10.0, 0)
    assert parse_options("--fit 10 工笔 图片", "freehand", 20.0) == ("工笔", 10.0, 0)
    assert parse_options("图片 --fit=10 工笔", "freehand", 20.0) == ("工笔", 10.0, 0)


def test_bad_fit_falls_back():
    assert parse_options("工笔 --fit abc", "freehand", 20.0) == ("工笔", 20.0, 0)
    assert parse_options("工笔 --fit", "freehand", 20.0) == ("工笔", 20.0, 0)


def test_sample_variants():
    """--sample 三种写法都认；位置随意；与档位互不干扰。"""
    assert parse_options("图片 --sample 24", "freehand", 20.0) == ("freehand", 20.0, 24)
    assert parse_options("--sample=24 图片", "freehand", 20.0) == ("freehand", 20.0, 24)
    assert parse_options("图片 --sample 24 工笔", "freehand", 20.0) == ("工笔", 20.0, 24)
    assert parse_options("图片 --sample 24 --fit 10", "freehand", 20.0) == ("freehand", 10.0, 24)


def test_sample_clamped():
    """越界钳制到 [8, 96]；非法/非正数视为 0（不指定）。"""
    assert parse_options("--sample 200", "freehand", 20.0) == ("freehand", 20.0, SAMPLE_MAX)
    assert parse_options("--sample 3", "freehand", 20.0) == ("freehand", 20.0, SAMPLE_MIN)
    assert parse_options("--sample abc", "freehand", 20.0) == ("freehand", 20.0, 0)
    assert parse_options("--sample 0", "freehand", 20.0) == ("freehand", 20.0, 0)
    assert parse_options("--sample", "freehand", 20.0) == ("freehand", 20.0, 0)


def test_empty_text_uses_defaults():
    assert parse_options("", "freehand", 20.0) == ("freehand", 20.0, 0)
    assert parse_options("   ", "finebrush", 30.0) == ("finebrush", 30.0, 0)


def test_preset_words_are_not_empty():
    assert PRESET_WORDS
    assert len(set(PRESET_WORDS)) == len(PRESET_WORDS)
