"""配置层：默认值与读取原语。

配置键说明（既有默认值就是羽画开箱即用的气质）：
- preset: 默认描摹档位（速写/写意/工笔）
- fit_mb: 输出体积目标（MiB），0 表示不启用自动降档
- max_mb: 输出体积硬上限（MiB），超过即失败
- score: 是否离线计算 MAE 相似度
- concurrent: 同时进行的描摹任务数（重 CPU 任务，默认 1）
- cooldown: 同一用户的相邻描摹冷却秒数
- llm_tool: 自然语言入口开关
- max_image_mb: 输入图片体积宽容（防御异常大文件）
- max_pixels: 输入图片总像素上限（像素炸弹防线）
"""

# 分组 schema（_conf_schema.json）中的键 → 所在分组
_GROUPED_KEYS = {
    "preset": "conversion",
    "fit_mb": "conversion",
    "max_mb": "conversion",
    "score": "conversion",
    "concurrent": "gate",
    "cooldown": "gate",
    "llm_tool": "tool",
    "max_image_mb": "input",
    "max_pixels": "input",
}

DEFAULTS = {
    "preset": "freehand",
    "fit_mb": 40.0,
    "max_mb": 64.0,
    "score": True,
    "concurrent": 1,
    "cooldown": 60,
    "llm_tool": True,
    "max_image_mb": 20.0,
    "max_pixels": 40_000_000,
}


def load_settings(astrbot_config=None) -> dict:
    """从 AstrBot 配置对象读取；对象缺失或键缺失一律回默认值。

    兼容两种结构（2026-09-06 修复设置项断链）：
    - 分组结构（框架按 _conf_schema.json 生成的实际落盘结构）：
      {"conversion": {"preset": "finebrush", ...}, "gate": {...}, ...}
    - 扁平结构（单测与旧版本）：
      {"preset": "finebrush", ...}
    优先级：扁平键 > 分组键 > 默认值。
    """
    settings = dict(DEFAULTS)
    if astrbot_config is None:
        return settings
    for key, default in DEFAULTS.items():
        group = _GROUPED_KEYS.get(key)
        try:
            value = astrbot_config.get(key)
            if value is None and group:
                nested = astrbot_config.get(group)
                if isinstance(nested, dict):
                    value = nested.get(key)
            if value is None:
                value = default
            # 类型宽容：WebUI 可能回传字符串数字
            if isinstance(default, (int, float)) and not isinstance(value, (int, float)):
                value = type(default)(float(value))
            settings[key] = value
        except Exception:
            settings[key] = default
    return settings
