"""跨平台目录链接层。

Windows 用 junction,POSIX 用 symlink。选择理由:
  - Windows 上 symlink 需要管理员权限或开发者模式(实测 FAIL:需要管理员权限),
    junction 不需要。junction 只支持目录+本地绝对路径,而 skill 恰好都满足。
  - POSIX 上 symlink 本来就免权限,没必要绕。

三个平台差异都是实测结论,不是推断:
  创建  Windows: _winapi.CreateJunction   Linux: os.symlink
  删除  os.unlink 两边都行;os.rmdir 只在 Windows 行,Linux 报 NotADirectoryError
  检测  Windows: islink=False isjunction=True   Linux: islink=True isjunction=False
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

IS_WIN = sys.platform == "win32"


def create(target: Path, link: Path) -> None:
    """在 link 处建一个指向 target 的链接。target 必须是已存在的目录。

    若 link 已存在(哪怕是用户手写的真实目录),两个平台都会拒绝并抛错,
    不会静默覆盖 —— 实测 Windows winerror 183 / Linux FileExistsError。
    调用方负责先判断 exists 再决定报错还是提示用户。
    """
    target, link = target.resolve(), Path(link)
    if not target.is_dir():
        raise NotADirectoryError(f"链接目标不是目录: {target}")
    link.parent.mkdir(parents=True, exist_ok=True)

    if not IS_WIN:
        os.symlink(target, link, target_is_directory=True)
        return
    try:
        import _winapi  # CPython 私有但稳定;自测套件在用
        _winapi.CreateJunction(str(target), str(link))
    except (ImportError, AttributeError):
        # 兜底:老版本 / 非 CPython 实现
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                       check=True, capture_output=True)


def is_link(path: Path) -> bool:
    """path 是否是我们建的链接。

    必须两个都查:junction 上 islink() 返回 False,symlink 上 isjunction()
    返回 False。只查一个会在另一个平台上把链接误判成普通目录 —— 那会让
    cckit 把自己装的 skill 当成用户手写的,从而拒绝管理它,且不报错。
    """
    return os.path.islink(path) or (
        IS_WIN and hasattr(os.path, "isjunction") and os.path.isjunction(path)
    )


def remove(link: Path) -> None:
    """删掉链接本身,绝不动目标目录里的内容。

    os.unlink 两个平台都可用。不要用 os.rmdir(Linux 上对 symlink 抛
    NotADirectoryError),更不要用 shutil.rmtree(语义是递归删内容,
    一旦哪天在某平台上跟随了链接就会删穿到 store 里的源码)。
    """
    if not os.path.lexists(link):
        return  # 已经没了,幂等
    if not is_link(link):
        raise IsADirectoryError(f"拒绝删除:{link} 是真实目录而非链接")
    os.unlink(link)


def is_dangling(link: Path) -> bool:
    """链接存在但目标已消失。doctor 用它找残留。

    lexists 看链接自身,exists 会跟随到目标 —— 目标没了就返回 False。
    """
    return os.path.lexists(link) and not os.path.exists(link)
