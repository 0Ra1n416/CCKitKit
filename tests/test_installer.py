"""installer:计划计算与渲染(不触发网络/uv 的部分)。"""
from __future__ import annotations

from types import SimpleNamespace

from cckit import config, installer, manifest


def test_compute_plan(tmp_path):
    kit = tmp_path / "k"
    kit.mkdir()
    (kit / "cckit.yaml").write_text(
        "cckit: 1\n"
        "kit: k\n"
        "version: 1.0.0\n"
        "description: d\n"
        "requires:\n"
        "  system:\n"
        "    - bin: definitely-not-a-real-bin-xyz\n"
        "      hint:\n"
        "        windows: winget install x\n"
        "        linux: apt install x\n"
        "        macos: brew install x\n"
        "  python:\n"
        "    file: requirements.txt\n"
        "skills:\n"
        "  - name: s\n"
        "    needs: [python]\n",
        encoding="utf-8")
    (kit / "requirements.txt").write_text("requests\nnumpy\n", encoding="utf-8")

    data = manifest.load(kit / "cckit.yaml")
    plan = installer.compute_plan("https://example.com/k", "v1", "sha123", data, kit)

    assert plan.sha == "sha123"
    assert plan.ref == "v1"
    assert plan.python_packages == ["requests", "numpy"]
    assert any(d["bin"] == "definitely-not-a-real-bin-xyz" for d in plan.system_missing)


def test_render_plan_mentions_source_sha_and_postinstall():
    from cckit.installer import Plan, render_plan
    p = Plan(source="https://x", ref="v1", sha="abc", kit="k", version="1.0.0",
             description="d", postinstall=[{"run": "scripts/setup.py", "when": "python"}])
    text = render_plan(p)
    assert "https://x" in text
    assert "abc" in text
    assert "scripts/setup.py" in text
    assert "代码" in text  # 安全警示


def test_build_envs_dual_runtime(tmp_path, monkeypatch):
    """needs 同时含 python 与 node 时,各建一个独立 env,不再互相吞掉。"""
    data = {
        "kit": "k",
        "skills": [
            {"name": "s", "needs": ["python", "node"]},
            {"name": "prompt", "needs": []},
        ],
    }

    calls: list[tuple] = []
    monkeypatch.setattr(
        installer.env_mod, "create_python_env",
        lambda env_dir, c=None, r=None: calls.append(("python", env_dir)))
    monkeypatch.setattr(
        installer.env_mod, "create_node_env",
        lambda env_dir, p=None: calls.append(("node", env_dir)))

    envs = installer.build_envs(data, tmp_path)

    assert set(envs["s"]) == {"python", "node"}
    assert envs["s"]["python"] == config.envs_dir() / "k__s__python"
    assert envs["s"]["node"] == config.envs_dir() / "k__s__node"
    assert envs["prompt"] == {}
    assert sorted(rt for rt, _ in calls) == ["node", "python"]


# ---- 系统依赖版本约束 ----

def test_version_satisfies_operators():
    sat = installer._version_satisfies
    assert sat("6.0.0", ">=6.0")
    assert not sat("5.1.0", ">=6.0")
    assert sat("6.0", ">=6.0")
    assert sat("6.0.0", "==6.0")     # PEP 440 归一化:6.0.0 == 6.0
    assert not sat("6.1", "==6.0")
    assert sat("5.0", "<6.0")
    assert sat("6.0", "!=5.0")
    assert sat("7.1.1", ">=6.0,<8.0")
    assert not sat("9.0.0", ">=6.0,<8.0")
    assert sat("1.4.9", "~=1.4.5")   # 兼容版本
    assert not sat("1.5.0", "~=1.4.5")


def test_check_system_version_skips_without_constraint():
    level, msg = installer._check_system_version({"bin": "ffmpeg"})
    assert level is None and msg == ""


def test_check_system_version_satisfied(monkeypatch):
    monkeypatch.setattr(
        installer.subprocess, "run",
        lambda argv, **kw: SimpleNamespace(
            returncode=0, stdout="ffmpeg version 7.1.1 Copyright\n", stderr=""))
    level, msg = installer._check_system_version(
        {"bin": "ffmpeg", "version": ">=6.0", "version_cmd": "ffmpeg -version"})
    assert level is None


def test_check_system_version_mismatch(monkeypatch):
    monkeypatch.setattr(
        installer.subprocess, "run",
        lambda argv, **kw: SimpleNamespace(
            returncode=0, stdout="ffmpeg version 5.1.0 Copyright\n", stderr=""))
    level, msg = installer._check_system_version(
        {"bin": "ffmpeg", "version": ">=6.0", "version_cmd": "ffmpeg -version"})
    assert level == "error"
    assert "5.1.0" in msg and ">=6.0" in msg


def test_check_system_version_unparseable_warns(monkeypatch):
    monkeypatch.setattr(
        installer.subprocess, "run",
        lambda argv, **kw: SimpleNamespace(returncode=0, stdout="", stderr=""))
    level, msg = installer._check_system_version(
        {"bin": "ffmpeg", "version": ">=6.0"})  # 无 version_cmd → 默认 `<bin> --version`
    assert level == "warn"


def test_check_system_version_default_cmd(monkeypatch):
    captured = {}

    def fake_run(argv, **kw):
        captured["argv"] = argv
        return SimpleNamespace(returncode=0, stdout="git version 2.47.0\n", stderr="")

    monkeypatch.setattr(installer.subprocess, "run", fake_run)
    level, msg = installer._check_system_version({"bin": "git", "version": ">=2.0"})
    assert level is None
    assert captured["argv"][0] == "git" and "--version" in captured["argv"]


def test_check_system_version_rejects_non_whitelist_flag(monkeypatch):
    ran = []
    monkeypatch.setattr(
        installer.subprocess, "run",
        lambda argv, **kw: ran.append(argv) or SimpleNamespace(returncode=0, stdout="", stderr=""))
    level, msg = installer._check_system_version(
        {"bin": "git", "version": ">=2.0", "version_cmd": "git log"})
    assert level == "warn"
    assert ran == []  # 白名单拦下,压根没执行


def test_check_system_version_rejects_other_binary(monkeypatch):
    ran = []
    monkeypatch.setattr(
        installer.subprocess, "run",
        lambda argv, **kw: ran.append(argv) or SimpleNamespace(returncode=0, stdout="", stderr=""))
    level, msg = installer._check_system_version(
        {"bin": "ffmpeg", "version": ">=6.0", "version_cmd": "curl --version"})
    assert level == "warn"
    assert ran == []


def test_check_system_version_rejects_extra_args(monkeypatch):
    ran = []
    monkeypatch.setattr(
        installer.subprocess, "run",
        lambda argv, **kw: ran.append(argv) or SimpleNamespace(returncode=0, stdout="", stderr=""))
    level, msg = installer._check_system_version(
        {"bin": "git", "version": ">=2.0", "version_cmd": "git --version --short"})
    assert level == "warn"
    assert ran == []


def test_check_system_version_rejects_code_exec(monkeypatch):
    """想借 python -c 执行任意代码 → 白名单直接拦下,不运行。"""
    ran = []
    monkeypatch.setattr(
        installer.subprocess, "run",
        lambda argv, **kw: ran.append(argv) or SimpleNamespace(returncode=0, stdout="", stderr=""))
    level, msg = installer._check_system_version(
        {"bin": "python", "version": ">=3.10", "version_cmd": "python -c 'import os'"})
    assert level == "warn"
    assert ran == []


def test_compute_plan_records_version_error(monkeypatch, tmp_path):
    kit = tmp_path / "k"
    kit.mkdir()
    (kit / "cckit.yaml").write_text(
        "cckit: 1\nkit: k\nversion: 1.0.0\ndescription: d\n"
        "requires:\n  system:\n"
        "    - bin: ffmpeg\n"
        "      hint:\n        windows: winget install ffmpeg\n"
        "      version: \">=6.0\"\n"
        "      version_cmd: ffmpeg -version\n"
        "skills:\n  - name: s\n    needs: []\n",
        encoding="utf-8")
    monkeypatch.setattr(installer.shutil, "which", lambda b: "/usr/bin/ffmpeg")
    monkeypatch.setattr(
        installer.subprocess, "run",
        lambda argv, **kw: SimpleNamespace(
            returncode=0, stdout="ffmpeg version 5.1.0\n", stderr=""))

    data = manifest.load(kit / "cckit.yaml")
    plan = installer.compute_plan("https://x", None, "sha", data, kit)

    assert [d["bin"] for d in plan.system_version_error] == ["ffmpeg"]
    assert plan.system_missing == []
