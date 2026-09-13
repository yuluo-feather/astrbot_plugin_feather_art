"""输出契约：跨渲染器共用的约定——体积预算异常与老内核兜底文案。

为什么单独放一层：这两样东西被不止一个渲染器用到（静态 CSS 描摹、矢量动画、
扫描线动画，将来还有别的方言）。留在某个渲染器里，别的渲染器就得反向依赖它，
接口方向会拧成麻花——而它们本身与「怎么写图」无关，一个是预算信号，
一个是给旧内核看的说明文字。
"""


class BudgetExceeded(ValueError):
    """渲染中途发现文档将超出体积预算。

    byte_count 是真实完整字节数（不是估算），fit 跳档靠它算降档幅度。
    """

    def __init__(self, byte_count: int):
        super().__init__("HTML exceeds the byte budget")
        self.byte_count = byte_count


# 老内核兜底提示文案（静态 / 矢量动画 / 扫描线动画共用，改这里一处即可）
FALLSAFE_MESSAGE = "此浏览器内核较旧，不支持 CSS 多边形（clip-path）渲染——画面会错乱成色块。推荐改用 Chrome / Edge / Firefox 等现代浏览器打开，或转至电脑浏览器查看。"
