"""文件系统小工具:删目录树。

单独成模块,是因为 Windows 上"删不干净"是个静默故障:git 把 `.git/objects` 里的
对象文件标成只读,`shutil.rmtree(ignore_errors=True)` 会把这些 PermissionError
吞掉 —— 表现为"命令报告成功,目录却还在"。installer / alt / web 都要删目录,
不能各写一处 `shutil.rmtree`。
"""
from __future__ import annotations

import os
import shutil
import stat


def _force(func, path: str, _exc: BaseException) -> None:
    """rmtree 单步失败时的兜底:清掉只读位再试一次,仍失败则让异常抛出去。

    Windows 上 git 把 `.git/objects/**` 标为只读,`os.unlink` 抛
    PermissionError;不重试就会留下整个 `.git` 骨架(见 Docs/06)。
    """
    os.chmod(path, stat.S_IRWXU)  # Windows 只反转只读位;POSIX 保留属主 rwx
    func(path)


def rmtree(path, *, ignore_errors: bool = False) -> None:
    """shutil.rmtree,但给只读文件一次机会。

    与 shutil 的差别:即使 ignore_errors=True 也会先清只读位重试(否则本函数就没
    有存在意义);ignore_errors 只决定"重试仍失败时是否抛出"。

    默认(ignore_errors=False)失败即抛出:调用方要么确认目录真的没了,要么把错误
    报给用户。**不允许"报告成功却留下残留"** —— 残留的 store 会让后续 add 永远卡在
    "store 已存在",而 remove 又说"未安装",用户无路可走。
    """
    try:
        shutil.rmtree(path, onexc=_force)
    except OSError:
        if not ignore_errors:
            raise
