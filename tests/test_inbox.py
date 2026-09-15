"""收件箱测试：会话级最近图、跨发送者、TTL、失效路径。

这段逻辑存在的理由是真实 bug：群里 A 发图、B 说「帮我画」时，工具取到了
B 自己的旧图，于是「两次都画了同一张」。缓存按会话（而不是按发送者）就是
那条红线的正面。
"""

import re
import time
from pathlib import Path

from data.plugins.astrbot_plugin_feather_art.inbox import SessionInbox


def _touch(tmp_path: Path, name: str) -> Path:
    target = tmp_path / name
    target.write_bytes(b"png")
    return target


def test_latest_is_shared_across_senders_in_one_session(tmp_path):
    """同一会话里后来者的图覆盖先到者的——跨发送者取最新，正是 bug 的正面。"""
    inbox = SessionInbox()
    first = _touch(tmp_path, "a.png")
    second = _touch(tmp_path, "b.png")
    inbox.remember("qq:GroupMessage:1", first, now=100.0)
    inbox.remember("qq:GroupMessage:1", second, now=101.0)
    assert inbox.latest("qq:GroupMessage:1", now=102.0) == second


def test_sessions_do_not_leak(tmp_path):
    """会话之间互不干扰；没记过的会话返回 None。"""
    inbox = SessionInbox()
    inbox.remember("qq:GroupMessage:1", _touch(tmp_path, "a.png"), now=100.0)
    inbox.remember("qq:GroupMessage:2", _touch(tmp_path, "b.png"), now=100.0)
    assert inbox.latest("qq:GroupMessage:9", now=100.0) is None


def test_ttl_expiry_returns_none(tmp_path):
    """过期就给 None——宁可回一句「先发图」，也不拿半小时前的旧图顶。"""
    inbox = SessionInbox()
    inbox.remember("s", _touch(tmp_path, "a.png"), now=0.0)
    assert inbox.latest("s", now=SessionInbox.TTL - 1) is not None
    assert inbox.latest("s", now=SessionInbox.TTL) is None


def test_missing_file_returns_none(tmp_path):
    """文件被清掉（启动时清超 6 小时那批）时不能返回死路径。"""
    inbox = SessionInbox()
    path = _touch(tmp_path, "a.png")
    inbox.remember("s", path, now=time.time())
    path.unlink()
    assert inbox.latest("s") is None


def test_unknown_session_returns_none():
    assert SessionInbox().latest("nobody") is None


def test_main_hands_over_the_session_not_the_sender():
    """main.py 必须把会话标识交给收件箱。

    上面几条测的是收件箱自己，测不到「调用方传了什么」。而这条恰恰是 bug
    复发的地方：只要有人把 event.get_sender_id() 传进来，缓存就又按发送者
    分了，症状与修复前一模一样。所以这里直接钉住调用点的实参。

    读的是**运行目录**那份 main.py——与其余测试的导入口径一致（它们是
    from data.plugins.astrbot_plugin_feather_art 导入的）。读 dev 那份会
    让这条断言测不到变异。
    """
    import data.plugins.astrbot_plugin_feather_art as package

    source = (Path(package.__path__[0]) / "main.py").read_text(encoding="utf-8")
    assert re.search(r"inbox\.remember\(event\.unified_msg_origin", source)
    assert re.search(r"inbox\.latest\(event\.unified_msg_origin\)", source)
    assert not re.search(r"inbox\.(remember|latest)\([^)]*get_sender_id", source)
