"""输出契约：跨渲染器共用的约定——体积预算异常、老内核兜底文案、后端入参。

为什么单独放一层：这些被不止一个渲染器用到（静态 CSS 描摹、矢量动画、扫描线
动画、SVG 方言）。留在某个渲染器里，别的渲染器就得反向依赖它，接口方向会拧成
麻花——而它们本身与「怎么写图」无关：一个是预算信号，一个是给旧内核看的说明，
一个是「出文档要带的那点参数」。

DocumentConfig 放这里而不是放进后端模块，是为了让后端能标注自己的入参类型：
后端若从调度器 import，而调度器又要 import 后端来注册，就成了循环。
"""

from dataclasses import dataclass


class BudgetExceeded(ValueError):
    """渲染中途发现文档将超出体积预算。

    byte_count 是真实完整字节数（不是估算），fit 跳档靠它算降档幅度。
    """

    def __init__(self, byte_count: int):
        super().__init__("HTML exceeds the byte budget")
        self.byte_count = byte_count


@dataclass(frozen=True)
class DocumentConfig:
    """出文档所需的这点参数（几何不在这里，在 Illustration 里）。

    title: 文档标题（同时充当 aria-label 与页面标题）——**进文档前必须 html.escape**：
        它落在元素文本与属性值两处，四个出文档的地方（CSS/SVG 后端、矢量动画、
        扫描线动画）口径必须一致，只转一处等于没转；
    original_size: 原图尺寸——只用来算容器长宽比（描摹尺寸可能被压过）；
    max_bytes: 体积上限，超了抛 BudgetExceeded；每个渲染器都要在末尾终检，
        只在静态线上挂着，另一条线就变成「配置里承诺、实际不生效」。
    """

    title: str
    original_size: tuple
    max_bytes: int


# 老内核兜底提示文案（静态 / 矢量动画 / 扫描线动画共用，改这里一处即可）
FALLSAFE_MESSAGE = "此浏览器内核较旧，不支持 CSS 多边形（clip-path）渲染——画面会错乱成色块。推荐改用 Chrome / Edge / Firefox 等现代浏览器打开，或转至电脑浏览器查看。"
