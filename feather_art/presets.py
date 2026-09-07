"""描摹档位：速写 / 写意 / 工笔（外加 motion 动画档）。

档位是「宽度上限、调色板规模、轮廓简化度、合并轮数」的组合拳：
- 速写 sketch：轻快，小图、表情包、印章的命；
- 写意 freehand：均衡，日常插画的默认选择；
- 工笔 finebrush：细描，细节与保真优先，输出也更大更慢；
- 动画 motion：动图专用，多帧描摹，快而稳。
"""

from typing import NamedTuple


class Preset(NamedTuple):
    """一档描摹参数。"""

    key: str
    name: str
    max_width: int
    colors: int
    epsilon: float
    passes: int
    brief: str


PRESETS: dict[str, Preset] = {
    "sketch": Preset("sketch", "速写", 768, 96, 0.38, 2, "快而轻：小图、表情包、印章"),
    "freehand": Preset("freehand", "写意", 1200, 160, 0.30, 3, "均衡之选：日常插画"),
    "finebrush": Preset("finebrush", "工笔", 1600, 256, 0.24, 4, "精细复刻：细节优先"),
    "motion": Preset("motion", "动画", 512, 96, 0.36, 2, "动图档：多帧描摹，快而稳"),
}

DEFAULT_KEY = "freehand"

# 宽度与颜色数的合法上下界
WIDTH_LIMITS = (1, 2400)
COLORS_LIMITS = (2, 256)

# 输出体积预算（MiB）；超过预算时若开启 fit 则按阶梯降档重试
DEFAULT_MAX_MB = 64.0


def resolve(key: str) -> Preset:
    """按 key（速写/写意/工笔或英文）取档；未知档回退默认写意。"""
    aliases = {
        "速写": "sketch", "素描": "sketch", "快速": "sketch",
        "写意": "freehand", "均衡": "freehand", "默认": "freehand",
        "工笔": "finebrush", "精细": "finebrush", "细描": "finebrush",
        "动画": "motion", "动图": "motion", "motion": "motion",
    }
    norm = aliases.get(key.strip().lower().replace(" ", ""), key.strip().lower())
    return PRESETS.get(norm, PRESETS[DEFAULT_KEY])
