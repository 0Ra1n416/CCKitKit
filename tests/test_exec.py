"""exec:node 分支的 NODE_PATH 注入、env 缺失报受检错误。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from cckit import config, exec as exec_mod, registry


def _install_node_skill(name: str = "hi", env_ok: bool = True):
    """装一个 node skill,返回 env 目录路径。"""
    kit = "nodekit"
    store = config.store_dir() / kit
    skill_dir = store / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "run.js").write_text("console.log('hi')\n", encoding="utf-8")
    (store / "cckit.yaml").write_text(
        "cckit: 1\nkit: nodekit\nversion: 1.0.0\ndescription: d\n"
        f"skills:\n  - name: {name}\n    needs: [node]\n    scripts: [run.js]\n",
        encoding="utf-8")
    env_dir = config.envs_dir() / f"{kit}__{name}"
    if env_ok:
        (env_dir / "node_modules").mkdir(parents=True)
    registry.add_kit(kit, {
        "source": {"url": "https://x", "ref": None, "sha": None},
        "version": "1.0.0",
        "store": str(store),
        "skills": [{"name": name, "env": str(env_dir), "runtime": "node",
                    "needs": ["node"]}],
        "known_scopes": ["global"]})
    return env_dir


def test_exec_node_sets_node_path(tmp_path, monkeypatch):
    env_dir = _install_node_skill()
    captured: dict = {}
    monkeypatch.setattr(
        exec_mod.subprocess, "run",
        lambda cmd, env=None: captured.update(env=env) or SimpleNamespace(returncode=0))
    rc = exec_mod.run("hi", "run.js", [])
    assert rc == 0
    assert captured["env"]["NODE_PATH"] == str(env_dir / "node_modules")


def test_exec_node_missing_env_raises(tmp_path, monkeypatch):
    _install_node_skill(env_ok=False)
    with pytest.raises(exec_mod.ExecError) as exc:
        exec_mod.run("hi", "run.js", [])
    assert "doctor" in str(exc.value)
