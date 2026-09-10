"""exec:按脚本扩展名选 runtime(.py→python,.js/.mjs→node)、NODE_PATH 注入、env 缺失报受检错误。"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from cckit import config, env as env_mod, exec as exec_mod, registry, state


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


# ---- 环境变量注入(kit_env + skill 的 env) ----

KIT_DECL = {"name": "KIT_VAR", "required": False, "description": "kit 级"}
SKILL_DECL = {"name": "SKILL_VAR", "required": False, "description": "skill 级"}


def _install_env_skill(kit_env=None, skill_env=None, name="hi", kit="envkit"):
    """装一个带环境变量声明的 skill(registry 快照与 installer 写的一致)。"""
    store = config.store_dir() / kit
    skill_dir = store / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "run.py").write_text("print('hi')\n", encoding="utf-8")
    (store / "cckit.yaml").write_text(
        "cckit: 1\n" f"kit: {kit}\n" "version: 1.0.0\ndescription: d\n"
        f"skills:\n  - name: {name}\n    needs: [python]\n    scripts: [run.py]\n",
        encoding="utf-8")
    py_dir = config.envs_dir() / f"{kit}__{name}__python"
    interp = env_mod.python_interpreter(py_dir)
    interp.parent.mkdir(parents=True, exist_ok=True)
    interp.write_bytes(b"")
    os.chmod(interp, 0o755)
    registry.add_kit(kit, {
        "source": {"url": "https://x", "ref": None, "sha": None},
        "version": "1.0.0",
        "store": str(store),
        "kit_env": list(kit_env or []),
        "skills": [{"name": name, "envs": {"python": str(py_dir)},
                    "needs": ["python"], "env": list(skill_env or []),
                    "conf_files": []}],
        "known_scopes": ["global"]})
    return store


def _capture_subprocess_env(monkeypatch) -> dict:
    captured: dict = {}
    monkeypatch.setattr(
        exec_mod.subprocess, "run",
        lambda cmd, env=None: captured.update(cmd=cmd, env=env)
        or SimpleNamespace(returncode=0))
    return captured


def test_exec_injects_kit_and_skill_env(tmp_path, monkeypatch):
    """kit_env 与 skill 的 env 都注入,值取自用户填写的 cckit 存储。"""
    _install_env_skill(kit_env=[KIT_DECL], skill_env=[SKILL_DECL])
    state.set_user_env("KIT_VAR", "kv", kit="envkit")
    state.set_user_env("SKILL_VAR", "sv", kit="envkit", skill="hi")

    captured = _capture_subprocess_env(monkeypatch)
    assert exec_mod.run("hi", "run.py", []) == 0
    assert captured["env"]["KIT_VAR"] == "kv"
    assert captured["env"]["SKILL_VAR"] == "sv"


def test_exec_skill_env_overrides_kit_env(tmp_path, monkeypatch):
    """同名变量同时出现在 kit_env 与 skill 的 env → 以 skill 级为准。"""
    decl = {"name": "SHARED", "required": False, "description": "两处都声明"}
    _install_env_skill(kit_env=[decl], skill_env=[decl])
    state.set_user_env("SHARED", "from-kit", kit="envkit")
    state.set_user_env("SHARED", "from-skill", kit="envkit", skill="hi")

    captured = _capture_subprocess_env(monkeypatch)
    exec_mod.run("hi", "run.py", [])
    assert captured["env"]["SHARED"] == "from-skill"


def test_exec_stored_value_beats_os_environ(tmp_path, monkeypatch):
    """cckit 存储优先:用户在 CLI/Web 填的值是权威值。"""
    _install_env_skill(skill_env=[SKILL_DECL])
    monkeypatch.setenv("SKILL_VAR", "from-shell")
    state.set_user_env("SKILL_VAR", "from-store", kit="envkit", skill="hi")

    captured = _capture_subprocess_env(monkeypatch)
    exec_mod.run("hi", "run.py", [])
    assert captured["env"]["SKILL_VAR"] == "from-store"


def test_exec_falls_back_to_os_environ(tmp_path, monkeypatch):
    """存储里没有 → 回落调用方的进程环境(保持与旧行为一致)。"""
    _install_env_skill(skill_env=[SKILL_DECL])
    monkeypatch.setenv("SKILL_VAR", "from-shell")

    captured = _capture_subprocess_env(monkeypatch)
    exec_mod.run("hi", "run.py", [])
    assert captured["env"]["SKILL_VAR"] == "from-shell"


def test_exec_required_missing_raises(tmp_path, monkeypatch):
    """required 且两处都没有 → 报错中止,并给出设置办法。"""
    decl = {"name": "NEEDED", "required": True, "description": "必须填"}
    _install_env_skill(skill_env=[decl])
    monkeypatch.delenv("NEEDED", raising=False)

    with pytest.raises(exec_mod.ExecError) as exc:
        exec_mod.run("hi", "run.py", [])
    assert "NEEDED" in str(exc.value)
    assert "cckit env" in str(exc.value)


def test_exec_optional_missing_is_silent(tmp_path, monkeypatch):
    """required=false 且没值 → 既不注入也不报错,由 skill 自己决定跳过哪一步。"""
    _install_env_skill(skill_env=[SKILL_DECL])
    monkeypatch.delenv("SKILL_VAR", raising=False)

    captured = _capture_subprocess_env(monkeypatch)
    assert exec_mod.run("hi", "run.py", []) == 0
    assert "SKILL_VAR" not in captured["env"]


def test_exec_scope_isolates_env_values(tmp_path, monkeypatch):
    """作用域隔离:项目作用域填的值不该出现在全局作用域的注入里。"""
    _install_env_skill(skill_env=[SKILL_DECL])
    root = tmp_path / "proj"
    (root / ".claude").mkdir(parents=True)
    state.set_user_env("SKILL_VAR", "proj-only", kit="envkit", skill="hi",
                       scope="project", root=root)
    monkeypatch.delenv("SKILL_VAR", raising=False)

    captured = _capture_subprocess_env(monkeypatch)
    exec_mod.run("hi", "run.py", [], scope="global")
    assert "SKILL_VAR" not in captured["env"]
