"""限流闸门：全局并发 + 每用户冷却。

描摹是重 CPU 任务（OpenCV 轮廓提取），绝不能并发堆叠——同时跑两张
大图能把机器拖死，还会互相抢内存。这里两道闸：
- 全局并发：Semaphore，默认同时只允许一个任务；
- 每用户冷却：同一个人刚点过描摹，至少隔 cooldown 秒（默认 60）
  才能下单——既防手滑重复点，也防被刷。
"""

import time

import asyncio


class ConversionLimiter:
    """异步限流器：acquire 返回 (是否放行, 剩余冷却秒)。"""

    def __init__(self, concurrent: int = 1, cooldown: float = 60.0,
                 max_entries: int = 1024):
        self.semaphore = asyncio.Semaphore(max(1, int(concurrent)))
        self.cooldown = max(0.0, float(cooldown))
        self.max_entries = max(16, int(max_entries))
        self._last: dict[str, float] = {}

    def _prune_stale(self) -> None:
        """惰性过期清理：条目超阈值时，丢掉冷却早已过期的记录。

        记录只在冷却判定里有用，冷却过期 10 倍时长后不可能再命中；
        惰性触发（无后台任务），且只删本字典内的键，不碰别处。
        """
        if len(self._last) < self.max_entries:
            return
        cutoff = time.monotonic() - self.cooldown * 10
        expired = [uid for uid, ts in self._last.items() if ts < cutoff]
        for uid in expired:
            self._last.pop(uid, None)

    async def acquire(self, uid: str) -> tuple[bool, float]:
        """尝试放行：先过冷却闸，再占并发位。"""
        self._prune_stale()
        now = time.monotonic()
        last = self._last.get(uid)
        if last is not None and now - last < self.cooldown:
            remain = self.cooldown - (now - last)
            return False, round(remain, 1)
        await self.semaphore.acquire()
        self._last[uid] = now
        return True, 0.0

    def release(self) -> None:
        """占位完成，归还并发位。冷却记录保留（防连点）。"""
        self.semaphore.release()

    def reset(self, uid: str) -> None:
        """清除某用户的冷却记录（测试/管理用）。"""
        self._last.pop(uid, None)
