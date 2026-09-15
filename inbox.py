"""收件箱：取图的优先级，以及「这个人最近发的那张图」缓存。

两个判据都放在这里，因为它们回答的是同一个问题——「哪张图算数」：

一、取图顺序。当前消息自己带的图优先；没有就下钻被引用的消息链。群里
「B 引用 A 的图说帮我画」时图在 `Reply.chain` 里，不下钻就等于没看见，
会静默回退成一张旧图（用户看到的是「两次都画了第一张」）。

二、缓存键必须带发送者。只按会话记会让后来者的图盖掉先到者的：A 发图、
C 发图、A 说帮我画，画出来是 C 的。按（会话, 发送者）记，B 没自己发过图
时就取不到、直说「先发图」——画错比画不出更糟。

为什么不塞在 main.py 里：main.py 的装饰器依赖框架上下文，测试约定不导入它
（见 tests/conftest.py），逻辑留在这儿才能有红线。
"""

import time
from collections.abc import Iterable, Iterator
from pathlib import Path

from astrbot.api.message_components import Image, Reply


def iter_images(
    components: Iterable | None,
    owner: str | int | None,
) -> Iterator[tuple[Image, str]]:
    """按优先级吐 (图, 归属者)：本消息的图在前、归属 owner；被引用消息里的图
    在后、归属原作者的 sender_id（拿不到就退回 owner）。

    只下钻一层。被引用消息里再套引用时，框架自己会把内层压平——aiocqhttp
    取引用消息时带 `get_reply=False`，防的正是无限嵌套。

    归属者得跟着图走：B 引用 A 的图说「帮我画」，那张图是 A 的。若记在 B
    名下，此后 B 只发一句「帮我画」就会画出 A 的图——换了种方式还是串。
    """
    for comp in components or []:
        if isinstance(comp, Image):
            yield comp, str(owner)
        elif isinstance(comp, Reply):
            author = getattr(comp, "sender_id", None)
            yield from iter_images(
                getattr(comp, "chain", None),
                author if author else owner,
            )


class SessionInbox:
    """按（会话, 发送者）记最近一张图。

    跨用户共享同一张表、但键里带发送者，因为「A 发的图」和「B 发的图」必须
    分得开；表本身共用只是为了少一层会话到用户的嵌套。
    """

    TTL = 1800.0
    """有效期（秒）。超过就当作没有——宁可回一句「先发图」，也别拿半小时前
    的旧图顶上。"""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], tuple[Path, float]] = {}

    def remember(
        self,
        session: str,
        sender: str,
        path: Path,
        now: float | None = None,
    ) -> None:
        """记下这个人在这个会话里最新的一张图。"""
        self._records[(session, str(sender))] = (
            path,
            time.time() if now is None else now,
        )

    def latest(
        self,
        session: str,
        sender: str,
        now: float | None = None,
    ) -> Path | None:
        """取这个人自己 TTL 内最近的一张图；没发过、过期、文件没了都给 None。

        绝不跨发送者回退：A 的图不会喂给 B 的请求。
        """
        record = self._records.get((session, str(sender)))
        if record is None:
            return None
        path, stamp = record
        current = time.time() if now is None else now
        if current - stamp >= self.TTL:
            return None
        if not path.exists():
            return None
        return path
