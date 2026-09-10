"""Web 的配置端点:环境变量值的读写、conf_files 的读写与路径校验。

与 test_web_alt 一样直接调用端点函数,不经过 ASGI 测试客户端。
重点覆盖**服务端校验** —— UI 禁用了不等于服务端可以不拦。
"""
from __future__ import annotations

import importlib

import pytest

from cckit import config, link, registry, state
from cckit.errors import CckitError

web = importlib.import_module("cckit.web.app")

KIT_DECL = {"name": "KIT_VAR", "required": False, "description": "kit 级"}
SKILL_DECL = {"name": "SKILL_VAR", "required": True, "description": "skill 级"}


def _install(kit: str = "cfg-kit", skill: str = "cfg-skill", *, link_it: bool = True,
             conf_files=("config.json",), kit_env=None, skill_env=None,
             store_conf: bool = True, managed: bool = True):
    """装一个带 kit_env / skill env / conf_files 的 kit,返回 skill 的 store 目录。"""
    store = config.store_dir() / kit
    skill_dir = store / skill
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\ndescription: x\n---\n", encoding="utf-8")
    if store_conf:
        (skill_dir / "config.json").write_text('{"a": 1}', encoding="utf-8")

    if managed:
        registry.add_kit(kit, {
            "source": {"url": "https://x", "ref": None, "sha": None},
            "version": "1.0.0",
            "store": str(store),
            "kit_env": list(kit_env or []),
            "skills": [{"name": skill, "envs": {}, "needs": [],
                        "env": list(skill_env or []),
                        "conf_files": list(conf_files)}],
            "known_scopes": ["global"]})
    if link_it:
        skills_dir = config.claude_config_dir() / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        link.create(skill_dir, skills_dir / skill)
    return skill_dir


# ---- 列出配置需求 ----

def test_get_config_skill_returns_envs_and_conf_files():
    _install(kit_env=[KIT_DECL], skill_env=[SKILL_DECL])
    got = web.get_config(kit="cfg-kit", skill="cfg-skill")
    assert [e["name"] for e in got["envs"]] == ["KIT_VAR", "SKILL_VAR"]
    assert [e["level"] for e in got["envs"]] == ["kit", "skill"]
    assert got["conf_files"] == ["config.json"]


def test_get_config_kit_only_has_no_conf_files():
    """kit 级下拉只展示 kit_env,不带 conf_files。"""
    _install(kit_env=[KIT_DECL], skill_env=[SKILL_DECL])
    got = web.get_config(kit="cfg-kit", skill=None)
    assert [e["name"] for e in got["envs"]] == ["KIT_VAR"]
    assert got["conf_files"] == []


def test_get_config_reports_unset_value():
    _install(skill_env=[SKILL_DECL])
    got = web.get_config(kit="cfg-kit", skill="cfg-skill")
    assert got["envs"][0]["value"] is None


# ---- 写环境变量值 ----

def test_set_config_env_roundtrip():
    _install(kit_env=[KIT_DECL], skill_env=[SKILL_DECL])
    web.set_config_env(web.EnvSetBody(kit="cfg-kit", skill="cfg-skill",
                                      name="SKILL_VAR", value="v1"))
    assert state.stored_env("global", "cfg-kit", "cfg-skill")["SKILL_VAR"] == "v1"
    got = web.get_config(kit="cfg-kit", skill="cfg-skill")
    assert got["envs"][1]["value"] == "v1"


def test_set_config_env_kit_level_writes_kit_bucket():
    """kit_env 声明的变量写 kit 桶 —— 即便请求里带了 skill。"""
    _install(kit_env=[KIT_DECL])
    web.set_config_env(web.EnvSetBody(kit="cfg-kit", skill="cfg-skill",
                                      name="KIT_VAR", value="kv"))
    data = state.read_user_envs()
    assert data["kit_env"]["global|cfg-kit"] == {"KIT_VAR": "kv"}
    assert "skill_env" not in data          # 没有误写进 skill 桶
    # 但 kit 桶的值对所有 skill 生效
    assert state.stored_env("global", "cfg-kit", "cfg-skill")["KIT_VAR"] == "kv"


def test_set_config_env_null_clears():
    _install(skill_env=[SKILL_DECL])
    web.set_config_env(web.EnvSetBody(kit="cfg-kit", skill="cfg-skill",
                                      name="SKILL_VAR", value="v1"))
    web.set_config_env(web.EnvSetBody(kit="cfg-kit", skill="cfg-skill",
                                      name="SKILL_VAR", value=None))
    assert state.stored_env("global", "cfg-kit", "cfg-skill") == {}


def test_set_config_env_rejects_undeclared_name():
    """变量名必须来自声明 —— 不能让面板往环境里塞任意变量。"""
    _install(skill_env=[SKILL_DECL])
    with pytest.raises(CckitError):
        web.set_config_env(web.EnvSetBody(kit="cfg-kit", skill="cfg-skill",
                                          name="EVIL", value="x"))


def test_set_config_env_rejects_installed_skill():
    """installed 态(无 link)不允许改配置。"""
    _install(skill_env=[SKILL_DECL], link_it=False)
    with pytest.raises(CckitError) as exc:
        web.set_config_env(web.EnvSetBody(kit="cfg-kit", skill="cfg-skill",
                                          name="SKILL_VAR", value="x"))
    assert "installed" in str(exc.value)


def test_set_config_env_rejects_unaddressable_skill():
    """非 cckit 管理的 skill 在 state 里 `kit` 恒为 None,按 (kit, skill) 定位
    永远匹配不到 —— 服务端因此天然拦住了它们,不需要额外的 managed 分支。"""
    skills_dir = config.claude_config_dir() / "skills"
    (skills_dir / "hand-written").mkdir(parents=True)
    with pytest.raises(CckitError) as exc:
        web.set_config_env(web.EnvSetBody(kit="cfg-kit", skill="hand-written",
                                          name="X", value="1"))
    assert "不在 kit" in str(exc.value)


# ---- 读写配置文件 ----

def test_conf_file_read_write_roundtrip():
    _install()
    got = web.read_config_conf(kit="cfg-kit", skill="cfg-skill", path="config.json")
    assert got["content"] == '{"a": 1}'
    web.write_config_conf(web.ConfWriteBody(kit="cfg-kit", skill="cfg-skill",
                                            path="config.json",
                                            content='{"a": 2}'))
    got = web.read_config_conf(kit="cfg-kit", skill="cfg-skill", path="config.json")
    assert got["content"] == '{"a": 2}'


def test_conf_file_rejects_undeclared_path():
    """没在 conf_files 里声明过的路径一律拒绝(客户端传来的一律不可信)。"""
    _install()
    for bad in ("../outside.json", "other.json", "/etc/passwd", "C:\\Windows\\win.ini"):
        with pytest.raises(CckitError) as exc:
            web.read_config_conf(kit="cfg-kit", skill="cfg-skill", path=bad)
        assert "conf_files" in str(exc.value)


def test_conf_file_rejects_escape_even_if_declared():
    """纵深防御:哪怕 registry 快照里被塞进了 `..`,解析后仍必须落在 skill 目录内。"""
    skill_dir = _install(conf_files=("../outside.json",))
    (skill_dir.parent / "outside.json").write_text("secret", encoding="utf-8")
    with pytest.raises(CckitError) as exc:
        web.read_config_conf(kit="cfg-kit", skill="cfg-skill", path="../outside.json")
    assert "越出" in str(exc.value)


def test_conf_file_rejects_installed_skill():
    _install(link_it=False)
    with pytest.raises(CckitError):
        web.read_config_conf(kit="cfg-kit", skill="cfg-skill", path="config.json")


def test_conf_file_missing_on_disk():
    _install(store_conf=False)
    with pytest.raises(CckitError) as exc:
        web.read_config_conf(kit="cfg-kit", skill="cfg-skill", path="config.json")
    assert "不存在" in str(exc.value)


# ---- 列表接口带上 kit_env ----

def test_get_skills_exposes_kit_env():
    _install(kit_env=[KIT_DECL])
    got = web.get_skills()
    assert got["kit_env"]["cfg-kit"] == [KIT_DECL]
    item = next(s for s in got["skills"] if s["name"] == "cfg-skill")
    assert item["conf_files"] == ["config.json"]
