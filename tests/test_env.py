"""env:依赖环境创建(只测命令构造,不真跑 uv/npm)。"""
from __future__ import annotations

from cckit import env as env_mod


def test_create_node_env_windows_uses_cmd(monkeypatch, tmp_path):
    # Windows 上 npm 是 npm.cmd,subprocess 无法直接执行,须经 cmd /c 转发(回归 WinError 2)。
    monkeypatch.setattr(env_mod.os, "name", "nt")
    calls: list[list[str]] = []
    monkeypatch.setattr(env_mod.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    pkg = tmp_path / "package.json"
    pkg.write_text("{}\n", encoding="utf-8")
    env_mod.create_node_env(tmp_path / "env", pkg)
    assert calls == [["cmd", "/c", "npm", "install", "--prefix", str(tmp_path / "env")]]


def test_create_node_env_posix_direct(monkeypatch, tmp_path):
    monkeypatch.setattr(env_mod.os, "name", "posix")
    calls: list[list[str]] = []
    monkeypatch.setattr(env_mod.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    pkg = tmp_path / "package.json"
    pkg.write_text("{}\n", encoding="utf-8")
    env_mod.create_node_env(tmp_path / "env", pkg)
    assert calls == [["npm", "install", "--prefix", str(tmp_path / "env")]]


def test_create_node_env_no_package_json(monkeypatch, tmp_path):
    # 无 package.json 时不应执行 npm(纯 prompt/无 node 依赖的 skill 不会装东西)
    calls: list[list[str]] = []
    monkeypatch.setattr(env_mod.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    env_mod.create_node_env(tmp_path / "env", None)
    assert calls == []
