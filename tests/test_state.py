"""state 模块:四态模型、锁、原子写、只改 skillOverrides、非托管 skill 列表。"""
from __future__ import annotations

import json
import os
import time

import pytest

from cckit import config, link, registry, state
from cckit.errors import CckitError
from helpers import install_kit_skill


def test_four_states():
    install_kit_skill("foo")
    skills_dir = config.claude_config_dir() / "skills"
    assert state.get_state("foo", "global") == "installed"

    state.set_state("foo", "enabled", "global")
    assert state.get_state("foo", "global") == "enabled"
    assert link.is_link(skills_dir / "foo")

    state.set_state("foo", "name-only", "global")
    assert state.get_state("foo", "global") == "name-only"

    state.set_state("foo", "off", "global")
    assert state.get_state("foo", "global") == "off"

    state.set_state("foo", "installed", "global")
    assert state.get_state("foo", "global") == "installed"
    assert not link.is_link(skills_dir / "foo")


def test_set_state_preserves_other_keys():
    install_kit_skill("foo")
    settings_dir = config.claude_config_dir()
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "settings.json").write_text(
        json.dumps({"model": "opus", "env": {"A": "1"}}), encoding="utf-8")

    state.set_state("foo", "off", "global")

    data = json.loads((settings_dir / "settings.json").read_text(encoding="utf-8"))
    assert data["model"] == "opus"
    assert data["env"] == {"A": "1"}
    assert data["skillOverrides"]["foo"] == "off"


def test_atomic_write_no_tmp_left():
    install_kit_skill("foo")
    state.set_state("foo", "name-only", "global")
    settings_dir = config.claude_config_dir()
    assert list(settings_dir.glob("*.tmp")) == []
    data = json.loads((settings_dir / "settings.json").read_text(encoding="utf-8"))
    assert data["skillOverrides"]["foo"] == "name-only"


def test_stale_lock_cleaned():
    install_kit_skill("foo")
    settings_dir = config.claude_config_dir()
    settings_dir.mkdir(parents=True, exist_ok=True)
    lock_path = settings_dir / "settings.json.cckit.lock"
    lock_path.write_text("stale", encoding="utf-8")
    old = time.time() - 100
    os.utime(lock_path, (old, old))

    state.set_state("foo", "off", "global")  # 应清理陈旧锁后成功

    assert not lock_path.exists()
    data = json.loads((settings_dir / "settings.json").read_text(encoding="utf-8"))
    assert data["skillOverrides"]["foo"] == "off"


def test_list_includes_nonmanaged():
    skills_dir = config.claude_config_dir() / "skills"
    (skills_dir / "user-skill").mkdir(parents=True)
    (skills_dir / "user-skill" / "SKILL.md").write_text(
        "---\ndescription: user thing\n---\n", encoding="utf-8")
    skills = state.list_skills("global")
    assert any(s.name == "user-skill" and s.managed is False for s in skills)


def test_list_env_and_desc():
    install_kit_skill("foo", runtime="python", needs=["python"], desc="test skill")
    state.set_state("foo", "enabled", "global")
    s = next(x for x in state.list_skills("global") if x.name == "foo")
    assert s.managed is True
    assert s.state == "enabled"
    assert s.env_ok is True
    assert s.desc_chars == len("test skill")


def test_prompt_only_env_none():
    install_kit_skill("bar", runtime=None, needs=[], desc="pure")
    state.set_state("bar", "enabled", "global")
    s = next(x for x in state.list_skills("global") if x.name == "bar")
    assert s.env_ok is None


def test_installed_appears_in_list():
    install_kit_skill("foo", runtime=None, needs=[])
    skills = state.list_skills("global")
    assert any(s.name == "foo" and s.state == "installed" for s in skills)


def test_set_state_unknown_raises():
    install_kit_skill("foo")
    with pytest.raises(CckitError):
        state.set_state("foo", "bogus", "global")


def test_set_state_nonmanaged_raises():
    with pytest.raises(CckitError):
        state.set_state("not-installed", "enabled", "global")


def test_list_all_same_name_different_scopes(tmp_path):
    """同名 skill 全局(--no-enable,无 link)与项目(link)各装一份,
    list --all 两者都在、作用域各自正确(回归 M1)。"""
    (tmp_path / ".claude").mkdir()
    root = config.project_root()
    store = config.store_dir()

    def _add_kit(kit: str, scope_value: str) -> None:
        kstore = store / kit
        (kstore / "hello").mkdir(parents=True)
        (kstore / "hello" / "SKILL.md").write_text(
            f"---\ndescription: {kit} hello\n---\n", encoding="utf-8")
        registry.add_kit(kit, {
            "source": {"url": f"https://x/{kit}", "ref": None, "sha": None},
            "version": "1.0.0",
            "store": str(kstore),
            "skills": [{"name": "hello", "env": None, "runtime": None, "needs": []}],
            "known_scopes": [scope_value]})

    _add_kit("globkit", "global")     # --no-enable:无 link
    _add_kit("projkit", str(root))    # 项目装

    proj_skills = root / ".claude" / "skills"
    proj_skills.mkdir(parents=True)
    link.create(store / "projkit" / "hello", proj_skills / "hello")

    skills = state.list_skills(None)
    by = {(s.kit, s.name): s for s in skills}
    assert ("globkit", "hello") in by
    assert by[("globkit", "hello")].scope == "global"
    assert by[("globkit", "hello")].state == "installed"
    assert ("projkit", "hello") in by
    assert by[("projkit", "hello")].scope == "project"
    assert by[("projkit", "hello")].state == "enabled"
