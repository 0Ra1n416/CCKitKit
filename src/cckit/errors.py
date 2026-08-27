"""cckit 的受检错误。

所有面向用户的错误都应是 CckitError(或其子类),cli.main 捕获它打印
"错误: ..." 并返回非零退出码,而不是把堆栈甩给用户。
"""
from __future__ import annotations


class CckitError(Exception):
    """cckit 的受检错误:可安全展示给用户,无需堆栈。"""
