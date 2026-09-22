"""fsutil.rmtree:删目录树必须能处理只读文件和只读目录。

只读文件不是假想:git 在 Windows 上把 `.git/objects/**` 标成只读,普通
`shutil.rmtree(ignore_errors=True)` 会静默跳过它们 —— 症状是"remove 报告成功,
store 里却留着 .git 骨架",之后 add 永远报"store 已存在"。
"""
from __future__ import annotations

import os

import pytest

from cckit import fsutil


def test_removes_readonly_file(tmp_path):
    """复现条件:目录里有一个只读文件(等效 .git/objects/ab/cdef)。"""
    obj = tmp_path / "git" / "objects" / "ab" / "cdef"
    obj.parent.mkdir(parents=True)
    obj.write_bytes(b"x")
    os.chmod(obj, 0o400)  # 只读

    fsutil.rmtree(tmp_path / "git")

    assert not (tmp_path / "git").exists()


def test_removes_readonly_dir(tmp_path):
    """只读目录:不先恢复写权限,里面的条目根本删不掉。"""
    inner = tmp_path / "ro" / "inner"
    inner.mkdir(parents=True)
    (inner / "f.txt").write_text("x", encoding="utf-8")
    os.chmod(tmp_path / "ro", 0o500)  # 只读

    fsutil.rmtree(tmp_path / "ro")

    assert not (tmp_path / "ro").exists()


def test_missing_path_raises_by_default(tmp_path):
    """默认严格:调用方必须知道目录真的没了,不能"报告成功却留下残留"。"""
    with pytest.raises(FileNotFoundError):
        fsutil.rmtree(tmp_path / "nope")


def test_missing_path_ignored_with_ignore_errors(tmp_path):
    fsutil.rmtree(tmp_path / "nope", ignore_errors=True)  # 不抛


def test_ignore_errors_still_clears_readonly(tmp_path):
    """ignore_errors 只该压掉"最终失败",不该跳过只读处理(否则形同虚设)。"""
    obj = tmp_path / "git" / "objects" / "ab"
    obj.mkdir(parents=True)
    f = obj / "cdef"
    f.write_bytes(b"x")
    os.chmod(f, 0o400)

    fsutil.rmtree(tmp_path / "git", ignore_errors=True)

    assert not (tmp_path / "git").exists()
