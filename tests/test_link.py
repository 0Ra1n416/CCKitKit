"""link 层复用:上层只通过 link.py 碰链接(create/is_link/remove/is_dangling)。"""
from __future__ import annotations

import os
import shutil

import pytest

from cckit import link


def test_create_islink_remove(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    lp = tmp_path / "link"
    link.create(target, lp)
    assert link.is_link(lp)
    (lp / "marker").write_text("x", encoding="utf-8")
    assert (target / "marker").is_file()  # 跟随到 target
    link.remove(lp)
    assert not os.path.lexists(lp)
    assert target.is_dir()  # 源文件存活


def test_create_rejects_existing(tmp_path):
    target = tmp_path / "t"
    target.mkdir()
    lp = tmp_path / "l"
    link.create(target, lp)
    with pytest.raises(Exception):
        link.create(target, lp)


def test_remove_real_dir_refused(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    with pytest.raises(IsADirectoryError):
        link.remove(real)


def test_dangling_detect_and_clean(tmp_path):
    target = tmp_path / "t"
    target.mkdir()
    lp = tmp_path / "l"
    link.create(target, lp)
    shutil.rmtree(target)
    assert link.is_dangling(lp)
    link.remove(lp)
    assert not os.path.lexists(lp)
