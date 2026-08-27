"""registry:读写与原子性。"""
from __future__ import annotations

import pytest

from cckit import config, registry
from cckit.errors import CckitError


def test_roundtrip():
    registry.add_kit("k", {"version": "1.0.0"})
    assert registry.get_kit("k")["version"] == "1.0.0"
    registry.remove_kit("k")
    assert registry.get_kit("k") is None


def test_no_tmp_left():
    registry.add_kit("k", {})
    assert list(config.registry_path().parent.glob(".registry-*.tmp")) == []


def test_load_missing_returns_default():
    assert registry.load() == {"version": 1, "kits": {}}


def test_find_skill():
    registry.add_kit("k", {
        "skills": [{"name": "foo", "envs": {}, "needs": []}]})
    kit, sk = registry.find_skill("foo")
    assert kit == "k"
    assert sk["name"] == "foo"


def test_find_skill_missing_raises():
    with pytest.raises(CckitError):
        registry.find_skill("nope")


def test_find_skill_scope_disambiguates(tmp_path):
    """同名 skill 全局与项目各装一份时,靠 scope 唯一定位。"""
    (tmp_path / ".claude").mkdir()  # 让 project_root 找到项目根
    root = config.project_root()
    registry.add_kit("g-kit", {
        "skills": [{"name": "hello", "envs": {}, "needs": []}],
        "known_scopes": ["global"]})
    registry.add_kit("p-kit", {
        "skills": [{"name": "hello", "envs": {}, "needs": []}],
        "known_scopes": [str(root)]})

    assert registry.find_skill("hello", "global")[0] == "g-kit"
    assert registry.find_skill("hello", "project")[0] == "p-kit"
    # 不给 scope 时仍是歧义错误
    with pytest.raises(CckitError):
        registry.find_skill("hello")


def test_corrupt_registry_raises():
    path = config.registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(Exception):
        registry.load()
