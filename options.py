"""指令文本解析：档位词、--fit 与 --sample 位置无关，占位词「图片」透明忽略。

纯字符串逻辑，不依赖 astrbot / PIL，方便单测。
"""

PRESET_WORDS = ("速写", "写意", "工笔", "sketch", "freehand", "finebrush")

# 动画采样帧数边界：越界钳制——拉太大会拖死渲染时延，太小会变幻灯片
SAMPLE_MIN = 8
SAMPLE_MAX = 96

# 出现在指令里的这些词只是占位/语气词，不参与解析，也不报错
_IGNORED_WORDS = ("图片", "图", "pic", "picture", "img", "image")


def parse_options(text: str, default_preset: str, default_fit: float):
    """从指令文本里抠档位、--fit 与 --sample；抠不到就用默认。

    顺序随意：/羽画 工笔 图片 和 /羽画 图片 工笔 是一回事——
    档位词按关键词扫，图认附件，压根不需要在文本里写「图片」。

    --fit N：目标体积；--sample N：动画采样帧数（8~96 越界钳制，
    非法/非正数视为 0=不指定）。返回 (preset, fit, sample)。
    """
    preset = default_preset
    fit = default_fit
    sample = 0
    tokens = text.split()
    for index, token in enumerate(tokens):
        if token in PRESET_WORDS:
            preset = token
        if token.startswith("--fit"):
            raw = token[len("--fit"):].lstrip("=")
            if not raw and index + 1 < len(tokens):
                raw = tokens[index + 1]
            try:
                fit = float(raw)
            except ValueError:
                pass
        if token.startswith("--sample"):
            raw = token[len("--sample"):].lstrip("=")
            if not raw and index + 1 < len(tokens):
                raw = tokens[index + 1]
            try:
                sample = int(float(raw))
            except ValueError:
                sample = 0
            if sample > 0:
                sample = min(SAMPLE_MAX, max(SAMPLE_MIN, sample))
    return preset, fit, sample
