"""收件箱：会话级的「最近一张图」缓存。

为什么按会话而不是按发送者：群里 A 发图、B 接着说「帮我画」时，触发工具的
事件可能归属 B，按发送者取就会静默回退成 B 自己的旧图——用户看到的是
「两次都画了同一张」。

为什么不塞在 main.py 里：main.py 的装饰器依赖框架上下文，测试约定不导入它
（见 tests/conftest.py），逻辑留在这儿才能有红线。
"""

import time
from pathlib import Path


class SessionInbox:
    """按会话记最近一张图；跨用户共享，因为「群里别人发的图」正是常态。"""

    TTL = 1800.0
    """有效期（秒）。超过就当作没有——宁可回一句「先发图」，也别拿半小时前
    的旧图顶上。"""

    def __init__(self) -> None:
        self._records: dict[str, tuple[Path, float]] = {}

    def remember(self, session: str, path: Path, now: float | None = None) -> None:
        """记下这个会话最新的一张图。"""
        self._records[session] = (path, time.time() if now is None else now)

    def latest(self, session: str, now: float | None = None) -> Path | None:
        """取这个会话 TTL 内的最近一张图；过期或文件已不在则返回 None。"""
        record = self._records.get(session)
        if record is None:
            return None
        path, stamp = record
        current = time.time() if now is None else now
        if current - stamp >= self.TTL:
            return None
        if not path.exists():
            return None
        return path
