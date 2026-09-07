"""限流层测试：全局并发串行、每用户冷却、过期清理。"""

import asyncio
import sys
import time

from data.plugins.astrbot_plugin_feather_art import limiter


def test_serial_gate_blocks_second():
    async def scenario():
        gate = limiter.ConversionLimiter(concurrent=1, cooldown=0)
        ok1, _ = await gate.acquire("u")
        assert ok1
        acquired = []

        async def second():
            ok, _ = await gate.acquire("v")
            acquired.append(ok)

        task = asyncio.create_task(second())
        await asyncio.sleep(0.05)
        assert acquired == []  # 并发位被占，第二人必须等
        gate.release()
        await asyncio.sleep(0.05)
        assert acquired == [True]
        gate.release()

    asyncio.run(scenario())


def test_cooldown_blocks_then_allows():
    async def scenario():
        gate = limiter.ConversionLimiter(concurrent=2, cooldown=0.2)
        ok, _ = await gate.acquire("u")
        assert ok
        gate.release()
        ok2, wait = await gate.acquire("u")
        assert not ok2 and wait > 0
        await asyncio.sleep(0.25)
        ok3, _ = await gate.acquire("u")
        assert ok3
        gate.release()

    asyncio.run(scenario())


def test_different_users_not_blocked_by_cooldown():
    async def scenario():
        gate = limiter.ConversionLimiter(concurrent=2, cooldown=60)
        ok, _ = await gate.acquire("a")
        assert ok
        gate.release()
        ok2, wait = await gate.acquire("b")
        assert ok2 and wait == 0
        gate.release()

    asyncio.run(scenario())


def test_reset_clears_cooldown():
    async def scenario():
        gate = limiter.ConversionLimiter(concurrent=1, cooldown=60)
        ok, _ = await gate.acquire("u")
        assert ok
        gate.release()
        gate.reset("u")
        ok2, _ = await gate.acquire("u")
        assert ok2
        gate.release()

    asyncio.run(scenario())


def test_prune_removes_expired_entries():
    """条目超阈值时，冷却早已过期的记录被惰性清掉（无界字典增长防线）。"""
    async def scenario():
        gate = limiter.ConversionLimiter(cooldown=60.0, max_entries=16)
        now = time.monotonic()
        for i in range(10):
            gate._last[f"old_{i}"] = now - 3600 * 2  # 早已过期
        for i in range(10):
            gate._last[f"new_{i}"] = now
        assert len(gate._last) == 20
        ok, _ = await gate.acquire("fresh_uid")
        assert ok
        # 旧的被清掉，新的保留（10 条 + fresh 写入）
        assert len(gate._last) <= 11
        assert not any(k.startswith("old_") for k in gate._last)

    asyncio.run(scenario())


def test_prune_not_triggered_under_threshold():
    """未超阈值不清理（不误删还在冷却内的记录）。"""
    async def scenario():
        gate = limiter.ConversionLimiter(cooldown=60.0, max_entries=32)
        gate._last["alice"] = time.monotonic() - 5  # 5 秒前，冷却中
        ok, wait = await gate.acquire("bob")
        assert ok and wait == 0.0
        assert "alice" in gate._last  # 未到阈值，不清理

    asyncio.run(scenario())
