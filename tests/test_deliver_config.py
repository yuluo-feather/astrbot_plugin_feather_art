"""交付与配置测试：文案组装、文件链、配置读取语义。"""

from data.plugins.astrbot_plugin_feather_art import config, deliver


def _report() -> dict:
    return {
        "version": "0.1.0",
        "preset": {"key": "freehand", "name": "写意"},
        "seconds": 0.8,
        "original_size": [600, 760],
        "trace_size": [600, 760],
        "shapes": 267,
        "interior_holes": 81,
        "gradient_fills": 69,
        "underpainting_shapes": 48,
        "polygon_vertices": 24120,
        "bytes": 359893,
        "similarity": {"mae": 1.37, "mae_thumbnail": 3.04},
        "audit": {"valid": True, "errors": []},
    }


def test_report_text_key_facts():
    text = deliver.report_to_text(_report())
    assert "羽画" in text
    assert "写意" in text
    assert "267" in text
    assert "MAE 1.37" in text


def test_report_text_no_paths():
    text = deliver.report_to_text(_report())
    assert ".work" not in text
    assert "\\" not in text


def test_report_text_downscaled_note():
    rep = _report()
    rep["trace_size"] = [300, 380]
    text = deliver.report_to_text(rep)
    assert "描摹尺度 300×380" in text


def test_build_chain_types(tmp_path):
    html = tmp_path / "feather_abc.html"
    html.write_text("<html></html>", encoding="utf-8")
    chain = deliver.build_chain(_report(), html)
    assert len(chain) == 2
    names = [type(c).__name__ for c in chain]
    assert names == ["Plain", "File"]
    assert chain[1].name.endswith(".html")


# ---------- config ----------

def test_defaults_when_no_config():
    assert config.load_settings(None) == config.DEFAULTS


def test_defaults_when_empty_object():
    assert config.load_settings({}) == config.DEFAULTS


def test_overrides():
    settings = config.load_settings({"preset": "sketch", "fit_mb": 5})
    assert settings["preset"] == "sketch"
    assert settings["fit_mb"] == 5


def test_string_number_tolerant():
    settings = config.load_settings({"fit_mb": "10", "cooldown": "30"})
    assert settings["fit_mb"] == 10.0
    assert settings["cooldown"] == 30


def test_unknown_key_not_injected():
    settings = config.load_settings({"not_a_real_key": 1})
    assert "not_a_real_key" not in settings


def test_none_value_uses_default():
    settings = config.load_settings({"preset": None, "score": None})
    assert settings["preset"] == config.DEFAULTS["preset"]
    assert settings["score"] == config.DEFAULTS["score"]

def test_grouped_schema_reads(monkeypatch):
    """安全修复：框架按 _conf_schema.json 落盘的是分组结构，
    conversion/gate/input/tool 分组内的键必须能读到。"""
    fake = {
        "conversion": {"preset": "finebrush", "fit_mb": "24", "max_mb": 64.0, "score": True},
        "gate": {"concurrent": 2, "cooldown": 10},
        "input": {"max_image_mb": 5.0, "max_pixels": 1000},
        "tool": {"llm_tool": False},
    }
    settings = config.load_settings(fake)
    assert settings["preset"] == "finebrush"  # 用户设工笔就读工笔
    assert settings["fit_mb"] == 24.0         # 分组内字符串数字也宽容
    assert settings["concurrent"] == 2
    assert settings["cooldown"] == 10
    assert settings["max_image_mb"] == 5.0
    assert settings["max_pixels"] == 1000
    assert settings["llm_tool"] is False


def test_flat_takes_priority_over_grouped():
    """扁平键优先（兼容旧结构，也避免双写时打架）。"""
    fake = {"preset": "sketch", "conversion": {"preset": "finebrush"}}
    assert config.load_settings(fake)["preset"] == "sketch"


def test_defaults_match_conf_schema():
    """DEFAULTS 与 _conf_schema.json 的 default 必须一致（双处必过时防线）。

    改默认值时两处要同步；此测试把「忘了改另一边」变成红灯。
    """
    import json
    from pathlib import Path
    schema_path = Path(__file__).resolve().parents[1] / "_conf_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    seen = {}
    for group in schema.values():
        for key, item in group.get("items", {}).items():
            if "default" in item:
                seen[key] = item["default"]
    assert set(seen) == set(config.DEFAULTS), (
        f"schema 与 DEFAULTS 键不一致：只看 schema={sorted(set(seen) - set(config.DEFAULTS))} "
        f"只在 DEFAULTS={sorted(set(config.DEFAULTS) - set(seen))}")
    for key, expected in config.DEFAULTS.items():
        actual = seen[key]
        if isinstance(expected, bool):
            assert actual == expected, f"{key}: {actual!r} != {expected!r}"
        elif isinstance(expected, float):
            assert float(actual) == expected, f"{key}: {actual!r} != {expected!r}"
        else:
            assert actual == expected, f"{key}: {actual!r} != {expected!r}"
