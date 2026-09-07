"""指令文本解析：档位词与 --fit 位置无关，占位词「图片」透明忽略。

纯字符串逻辑，不依赖 astrbot / PIL，方便单测。
"""

PRESET_WORDS = ("速写", "写意", "工笔", "sketch", "freehand", "finebrush")

# 出现在指令里的这些词只是占位/语气词，不参与解析，也不报错
_IGNORED_WORDS = ("图片", "图", "pic", "picture", "img", "image")


def parse_options(text: str, default_preset: str, default_fit: float):
    """从指令文本里抠档位与 --fit；抠不到就用默认。

    顺序随意：/羽画 工笔 图片 和 /羽画 图片 工笔 是一回事——
    档位词按关键词扫，图认附件，压根不需要在文本里写「图片」。
    """
    preset = default_preset
    fit = default_fit
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
    return preset, fit
