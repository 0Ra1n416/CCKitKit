"""exec:按脚本扩展名选 runtime(.py→python,.js/.mjs→node)、NODE_PATH 注入、env 缺失报受检错误。"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from cckit import config, env as env_mod, exec as exec_mod, registry


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
    env_dir = config.envs_dir() / f"{kit}__{name}__node"
    if env_ok:
        (env_dir / "node_modules").mkdir(parents=True)
    registry.add_kit(kit, {
        "source": {"url": "https://x", "ref": None, "sha": None},
        "version": "1.0.0",
        "store": str(store),
        "skills": [{"name": name, "envs": {"node": str(env_dir)},
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


def _install_dual_skill(name: str = "hi"):
    """装一个同时 needs python 与 node 的 skill,返回 (py_dir, node_dir)。"""
    kit = "dualkit"
    store = config.store_dir() / kit
    skill_dir = store / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "run.py").write_text("print('py')\n", encoding="utf-8")
    (skill_dir / "run.js").write_text("console.log('js')\n", encoding="utf-8")
    (store / "cckit.yaml").write_text(
        "cckit: 1\nkit: dualkit\nversion: 1.0.0\ndescription: d\n"
        f"skills:\n  - name: {name}\n    needs: [python, node]\n"
        "    scripts: [run.py, run.js]\n",
        encoding="utf-8")

    py_dir = config.envs_dir() / f"{kit}__{name}__python"
    interp = env_mod.python_interpreter(py_dir)
    interp.parent.mkdir(parents=True, exist_ok=True)
    interp.write_bytes(b"")
    os.chmod(interp, 0o755)
    node_dir = config.envs_dir() / f"{kit}__{name}__node"
    (node_dir / "node_modules").mkdir(parents=True)

    registry.add_kit(kit, {
        "source": {"url": "https://x", "ref": None, "sha": None},
        "version": "1.0.0",
        "store": str(store),
        "skills": [{"name": name,
                    "envs": {"python": str(py_dir), "node": str(node_dir)},
                    "needs": ["python", "node"]}],
        "known_scopes": ["global"]})
    return py_dir, node_dir


def test_exec_dual_py_uses_python(tmp_path, monkeypatch):
    """同一 skill 同时有 python 与 node 时,.py 脚本走 python 解释器。"""
    py_dir, _ = _install_dual_skill()
    captured: dict = {}
    monkeypatch.setattr(
        exec_mod.subprocess, "run",
        lambda cmd, env=None: captured.update(cmd=cmd, env=env)
        or SimpleNamespace(returncode=0))
    rc = exec_mod.run("hi", "run.py", [])
    assert rc == 0
    assert captured["cmd"][0] == str(env_mod.python_interpreter(py_dir))


def test_exec_dual_js_uses_node(tmp_path, monkeypatch):
    """同一 skill 同时有 python 与 node 时,.js 脚本走 node 并注入 NODE_PATH。"""
    _, node_dir = _install_dual_skill()
    captured: dict = {}
    monkeypatch.setattr(
        exec_mod.subprocess, "run",
        lambda cmd, env=None: captured.update(cmd=cmd, env=env)
        or SimpleNamespace(returncode=0))
    rc = exec_mod.run("hi", "run.js", [])
    assert rc == 0
    assert captured["cmd"][0] == "node"
    assert captured["env"]["NODE_PATH"] == str(node_dir / "node_modules")
