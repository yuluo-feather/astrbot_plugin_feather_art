"""异常口径：能不能讲给用户听由类型决定，不由文案决定。

放在顶层而不是 service.py：算法层（feather_art 包）也要抛这两类错，
反向 import service 会成环。
"""


class TraceError(ValueError):
    """转换失败。用户侧看到的是固定友好文案，原文只进日志。"""


class UserFaultError(TraceError):
    """转换失败，且文案本来就是写给用户看的——只有这一类会原样透出。

    以前这个区分靠 user_fault 猜「消息首字符是不是 ASCII」：写一句
    "[羽画] 图片太大" 会被当内部异常吞掉，而「文件已存在：x.html」
    反倒会漏给用户。改成类型判定后，这条约定从「大家都记得」变成代码里查得到的。
    """
