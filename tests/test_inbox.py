"""收件箱测试：取图顺序（含引用下钻）、按人隔离、TTL、失效路径。

这段逻辑存在的理由是同一个真实 bug 换过两次脸：

第一次，群里 A 发图、B 说「帮我画」，工具取到了 B 自己的旧图 → 用户看到的
是「两次都画了同一张」。当时把缓存键从发送者改成会话，救活了这一路。

第二次，同一个群里 A 发图、C 发图、A 再说「帮我画」，会话键把 C 的图喂给了
A → 换了个人，还是画错。所以键必须是（会话, 发送者），且绝不跨人回退。

而「B 引用 A 的图说帮我画」那张一开始就丢过，靠 iter_images 下钻
Reply.chain 补回来；归属者还得跟着图走，否则那张图会记到 B 名下。
"""

import re
import time
from pathlib import Path

from astrbot.api.message_components import Image, Reply
from data.plugins.astrbot_plugin_feather_art.inbox import SessionInbox, iter_images


def _touch(tmp_path: Path, name: str) -> Path:
    target = tmp_path / name
    target.write_bytes(b"png")
    return target


# ---------- 取图顺序 ----------

def test_message_image_wins_over_quoted():
    """自己发的图优先于引用的图——引用只是「借来说事」，附件才是本意。"""
    own = Image(file="own.png")
    quoted = Reply(id="9", chain=[Image(file="quoted.png")], sender_id=1001)
    got = list(iter_images([own, quoted], "2002"))
    assert len(got) == 2
    assert got[0][0] is own
    assert got[0][1] == "2002"


def test_quoted_image_is_reached():
    """引用消息里的图必须取得出来——不下钻就等于没看见。"""
    quoted = Reply(id="9", chain=[Image(file="quoted.png")], sender_id=1001)
    got = list(iter_images([quoted], "2002"))
    assert len(got) == 1
    assert got[0][0].file == "quoted.png"


def test_quoted_image_belongs_to_its_author():
    """归属者跟着图走：那张图是 A 的，不能记到 B 名下。

    记错名下的后果是「B 此后只说一句帮我画，就画出 A 的图」——还是串。
    """
    quoted = Reply(id="9", chain=[Image(file="quoted.png")], sender_id=1001)
    assert list(iter_images([quoted], "2002"))[0][1] == "1001"


def test_broken_reply_chain_is_safe():
    """chain 为 None 或空时不能炸——框架给的就是空链（webchat 的选择文本引用）。"""
    assert list(iter_images(None, "1")) == []
    assert list(iter_images([], "1")) == []
    assert list(iter_images([Reply(id="9", chain=None, sender_id=5)], "1")) == []


def test_reply_without_author_falls_back_to_requester():
    """取不到被引用者 ID 时退回请求者，不能变成字符串 "0" 这种虚构的人。"""
    quoted = Reply(id="9", chain=[Image(file="q.png")])
    assert list(iter_images([quoted], "2002"))[0][1] == "2002"


# ---------- 按人隔离 ----------

def test_latest_does_not_leak_between_senders(tmp_path):
    """A 发的图不能喂给 B 的请求——这就是「多人发图就串」那一条。"""
    inbox = SessionInbox()
    inbox.remember("g1", "A", _touch(tmp_path, "a.png"), now=100.0)
    assert inbox.latest("g1", "B", now=101.0) is None


def test_each_sender_keeps_their_own_latest(tmp_path):
    """同一会话里两个人各记各的，后来者不覆盖先到者。"""
    inbox = SessionInbox()
    first = _touch(tmp_path, "a.png")
    second = _touch(tmp_path, "b.png")
    inbox.remember("g1", "A", first, now=100.0)
    inbox.remember("g1", "B", second, now=101.0)
    assert inbox.latest("g1", "A", now=102.0) == first
    assert inbox.latest("g1", "B", now=102.0) == second


def test_same_sender_keeps_only_the_newest(tmp_path):
    """同一个人连发两张，后一张顶上。"""
    inbox = SessionInbox()
    first = _touch(tmp_path, "a.png")
    second = _touch(tmp_path, "b.png")
    inbox.remember("g1", "A", first, now=100.0)
    inbox.remember("g1", "A", second, now=101.0)
    assert inbox.latest("g1", "A", now=102.0) == second


def test_sessions_do_not_leak(tmp_path):
    """会话之间互不干扰；没记过的会话返回 None。"""
    inbox = SessionInbox()
    inbox.remember("g1", "A", _touch(tmp_path, "a.png"), now=100.0)
    inbox.remember("g2", "A", _touch(tmp_path, "b.png"), now=100.0)
    assert inbox.latest("g9", "A", now=100.0) is None


def test_ttl_expiry_returns_none(tmp_path):
    """过期就给 None——宁可回一句「先发图」，也不拿半小时前的旧图顶。"""
    inbox = SessionInbox()
    inbox.remember("s", "A", _touch(tmp_path, "a.png"), now=0.0)
    assert inbox.latest("s", "A", now=SessionInbox.TTL - 1) is not None
    assert inbox.latest("s", "A", now=SessionInbox.TTL) is None


def test_missing_file_returns_none(tmp_path):
    """文件被清掉（启动时清超 6 小时那批）时不能返回死路径。"""
    inbox = SessionInbox()
    path = _touch(tmp_path, "a.png")
    inbox.remember("s", "A", path, now=time.time())
    path.unlink()
    assert inbox.latest("s", "A") is None


def test_unknown_returns_none():
    assert SessionInbox().latest("nobody", "A") is None


# ---------- 调用点 ----------

def test_main_hands_over_both_keys():
    """main.py 必须同时把会话与发送者交给收件箱。

    上面几条测的是收件箱自己，测不到「调用方传了什么」，而这里正是两次 bug
    都复发过的地方：漏掉发送者就退回「后来者的图盖掉先到者的」，漏掉会话就
    串到别的群。所以直接钉住调用点的实参。

    读的是**运行目录**那份 main.py——与其余测试的导入口径一致（它们是
    from data.plugins.astrbot_plugin_feather_art 导入的）。读 dev 那份会
    让这条断言测不到变异。
    """
    import data.plugins.astrbot_plugin_feather_art as package

    source = (Path(package.__path__[0]) / "main.py").read_text(encoding="utf-8")
    assert re.search(r"inbox\.remember\(event\.unified_msg_origin, owner", source)
    assert re.search(
        r"inbox\.latest\(\s*event\.unified_msg_origin,\s*str\(event\.get_sender_id\(\)\)\)",
        source,
    )
    assert re.search(r"iter_images\(event\.get_messages\(\), sender\)", source)


def test_main_never_hands_over_session_alone():
    """收件箱的取图调用不许只给会话——那就是「串」的写法本身。"""
    import data.plugins.astrbot_plugin_feather_art as package

    source = (Path(package.__path__[0]) / "main.py").read_text(encoding="utf-8")
    assert not re.search(r"inbox\.latest\(event\.unified_msg_origin\)", source)
    assert not re.search(r"inbox\.remember\([^)]*origin,\s*dest", source)
