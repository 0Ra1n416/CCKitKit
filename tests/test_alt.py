"""alt 流程:前置条件、物化、确定性校验、审计结论解析、转换编排。"""
from __future__ import annotations

import subprocess

import pytest

from cckit import alt, config, installer, manifest, registry, state
from cckit.alt import AltError, AgentCancelled, AgentResult, KitBuilderStatus


# ---- 工具 ----

def _write(path, text: str) -> None:
    """以 LF 写入(Windows 上 write_text 会转成 CRLF,触发 lint 噪声)。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def _write_skill(skill_dir, name: str, desc: str = "a test skill") -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    _write(skill_dir / "SKILL.md", f"---\nname: {name}\ndescription: {desc}\n---\n")


def _minimal_cckit_yaml(kit: str = "my-kit", skill: str = "my-skill") -> str:
    return (
        "cckit: 1\n"
        f"kit: {kit}\n"
        "version: 0.1.0\n"
        "description: test kit\n"
        "skills:\n"
        f"  - name: {skill}\n"
        "    needs: []\n"
    )


def _install_kit_builder(monkeypatch) -> None:
    """把真实源码树的 kit-builder 装到隔离环境的全局作用域(等价 cckit add --local)。"""
    src = alt.kit_builder_source_dir()
    staged = installer.stage_install(str(src), is_local_path=True, project=False)
    for _ev in installer.execute_install(staged):
        pass


# ---- 审计结论解析 ----

def test_parse_audit_verdict_pass():
    assert alt.parse_audit_verdict("一些说明\nAUDIT RESULT: PASS") is True


def test_parse_audit_verdict_fail():
    assert alt.parse_audit_verdict("AUDIT RESULT: FAIL") is False


def test_parse_audit_verdict_unclear():
    assert alt.parse_audit_verdict("没有结论标记") is None
    assert alt.parse_audit_verdict("") is None
    assert alt.parse_audit_verdict(None) is None


def test_parse_audit_verdict_last_marker_wins():
    # 模型可能先说 PASS 又改口 FAIL,取最后一个
    text = "AUDIT RESULT: PASS\n但后来发现问题\nAUDIT RESULT: FAIL"
    assert alt.parse_audit_verdict(text) is False


# ---- 物化 ----

def test_materialize_local_strips_git(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "README.md").write_text("hi", encoding="utf-8")
    (src / ".git").mkdir()  # 本地 git 仓库
    (src / ".git" / "HEAD").write_text("ref", encoding="utf-8")

    repo = alt.materialize(str(src), None, True, tmp_path / "out")

    assert (repo / "README.md").is_file()
    assert not (repo / ".git").exists()  # 必须剥离 .git,否则 stage_install 会 re-clone 丢改造


def test_materialize_remote_clone_and_strip(monkeypatch, tmp_path):
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        if argv[0] == "git" and argv[1] == "clone":
            out = tmp_path / "out" / "repo"
            out.mkdir(parents=True)
            (out / "f.txt").write_text("x", encoding="utf-8")
            (out / ".git").mkdir()
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(alt.subprocess, "run", fake_run)
    monkeypatch.setattr(alt.shutil, "rmtree", lambda p, **kw: None)

    repo = alt.materialize("https://x/y.git", "v1", False, tmp_path / "out")
    assert (repo / "f.txt").is_file()
    assert any("checkout" in c and "v1" in c for c in calls)


# ---- 前置条件 ----

def test_kit_builder_status_missing(tmp_path):
    st = alt.kit_builder_status()
    assert st.status == "missing"
    assert st.auto_fix == "install"


def test_kit_builder_status_ready(monkeypatch):
    _install_kit_builder(monkeypatch)
    st = alt.kit_builder_status()
    assert st.status == "ready", st.reason


def test_kit_builder_status_not_enabled(monkeypatch):
    _install_kit_builder(monkeypatch)
    state.set_state("kit-builder", "off", "global", kit="kit-builder")
    st = alt.kit_builder_status()
    assert st.status == "not_enabled"
    assert st.auto_fix == "enable"


def test_kit_builder_status_installed(monkeypatch):
    _install_kit_builder(monkeypatch)
    state.set_state("kit-builder", "installed", "global", kit="kit-builder")
    st = alt.kit_builder_status()
    assert st.status == "not_enabled"
    assert st.auto_fix == "enable"


def test_kit_builder_status_conflict_other_kit(monkeypatch):
    # 其他 kit 也提供一个叫 kit-builder 的 skill → 冲突
    registry.add_kit("other-kit", {
        "source": {"url": "https://x/other", "ref": None, "sha": "abc"},
        "version": "1.0.0", "installed_at": "2026-01-01T00:00:00Z",
        "store": str(config.store_dir() / "other-kit"),
        "skills": [{"name": "kit-builder", "envs": {}, "needs": []}],
        "known_scopes": ["global"],
    })
    st = alt.kit_builder_status()
    assert st.status == "conflict"


def test_kit_builder_status_conflict_non_managed(monkeypatch):
    # 全局存在非 cckit 管理的同名 skill(真实目录)→ 冲突
    skills_dir = config.claude_config_dir() / "skills"
    _write_skill(skills_dir / "kit-builder", "kit-builder")
    st = alt.kit_builder_status()
    assert st.status == "conflict"


def test_kit_builder_status_source_conflict(monkeypatch):
    # registry 有 kit-builder 但来源不是当前源码树 → source_conflict
    registry.add_kit("kit-builder", {
        "source": {"url": "/some/other/path", "ref": None, "sha": "abc"},
        "version": "0.1.0", "installed_at": "2026-01-01T00:00:00Z",
        "store": str(config.store_dir() / "kit-builder"),
        "skills": [{"name": "kit-builder", "envs": {}, "needs": []}],
        "known_scopes": ["global"],
    })
    st = alt.kit_builder_status()
    assert st.status == "source_conflict"


def test_fix_kit_builder_conflict_raises(monkeypatch):
    registry.add_kit("other-kit", {
        "source": {"url": "https://x/other", "ref": None, "sha": "abc"},
        "version": "1.0.0", "installed_at": "2026-01-01T00:00:00Z",
        "store": str(config.store_dir() / "other-kit"),
        "skills": [{"name": "kit-builder", "envs": {}, "needs": []}],
        "known_scopes": ["global"],
    })
    with pytest.raises(AltError):
        alt.fix_kit_builder(KitBuilderStatus("conflict", "x"), assume_yes=True)


def test_fix_kit_builder_install(monkeypatch):
    st = alt.kit_builder_status()  # missing, auto_fix=install
    assert st.status == "missing"
    alt.fix_kit_builder(st, assume_yes=True)
    assert alt.kit_builder_status().status == "ready"


def test_fix_kit_builder_enable(monkeypatch):
    _install_kit_builder(monkeypatch)
    state.set_state("kit-builder", "off", "global", kit="kit-builder")
    st = alt.kit_builder_status()
    assert st.status == "not_enabled"
    alt.fix_kit_builder(st, assume_yes=True)
    assert alt.kit_builder_status().status == "ready"


def test_apply_kit_builder_fix_rejects_conflict(monkeypatch):
    # Web 端点在冲突/来源不可信时不得静默安装或切换(见 TODO 2.2)。
    registry.add_kit("other-kit", {
        "source": {"url": "https://x/other", "ref": None, "sha": "abc"},
        "version": "1.0.0", "installed_at": "2026-01-01T00:00:00Z",
        "store": str(config.store_dir() / "other-kit"),
        "skills": [{"name": "kit-builder", "envs": {}, "needs": []}],
        "known_scopes": ["global"],
    })
    with pytest.raises(AltError):
        alt.apply_kit_builder_fix("enable")


def test_apply_kit_builder_fix_wrong_action(monkeypatch):
    with pytest.raises(AltError):
        alt.apply_kit_builder_fix("bogus")


def test_agent_options_security_boundary(tmp_path):
    """锁定安全边界:auto、不设 can_use_tool、隔离仓库自带 settings/MCP。"""
    sdk = pytest.importorskip("claude_agent_sdk")
    opts = alt._build_agent_options(tmp_path, "builder", lambda ev: None)
    assert opts.permission_mode == "auto"
    assert opts.can_use_tool is None          # 不设回调,auto 的自动判断才生效
    assert opts.setting_sources == ["user"]   # 隔离仓库自带 .claude/settings*.json
    assert opts.strict_mcp_config is True     # 隔离仓库自带 .mcp.json
    assert opts.cwd == str(tmp_path)


# ---- 确定性校验 ----

def test_deterministic_check_ok(tmp_path):
    repo = tmp_path / "repo"
    _write_skill(repo / "my-skill", "my-skill")
    _write(repo / "cckit.yaml", _minimal_cckit_yaml())
    events = []
    alt._deterministic_check(repo, events.append)
    assert events == []  # 无 lint 消息


def test_deterministic_check_lint_error(tmp_path):
    repo = tmp_path / "repo"
    _write_skill(repo / "my-skill", "my-skill", desc="")  # 空 description → error
    _write(repo / "cckit.yaml", _minimal_cckit_yaml())
    with pytest.raises(AltError):
        alt._deterministic_check(repo, lambda ev: None)


def test_deterministic_check_missing_manifest(tmp_path):
    with pytest.raises(Exception):  # MissingManifestError(ManifestError)
        alt._deterministic_check(tmp_path / "nope", lambda ev: None)


# ---- 转换编排 ----

def _fake_run_agent(builder_writes_cckit: bool = True, verdict: str | None = "PASS"):
    def fake(prompt, cwd, stage, emit=None, is_cancelled=None, client_holder=None):
        from pathlib import Path
        if "审计员" in prompt:
            text = f"...\nAUDIT RESULT: {verdict}\n" if verdict is not None else "no verdict"
            return AgentResult(ok=True, text=text)
        # builder:写入一份合法 cckit.yaml 模拟改造
        if builder_writes_cckit:
            _write(Path(cwd) / "cckit.yaml", _minimal_cckit_yaml())
        return AgentResult(ok=True, text="done")
    return fake


def test_convert_repo_success(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    _write_skill(repo / "my-skill", "my-skill")
    monkeypatch.setattr(alt, "run_agent", _fake_run_agent())
    events = []
    alt.convert_repo(repo, events.append)
    assert any(e.kind == "done" and e.stage == "audit" for e in events)


def test_convert_repo_audit_fail(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    _write_skill(repo / "my-skill", "my-skill")
    monkeypatch.setattr(alt, "run_agent", _fake_run_agent(verdict="FAIL"))
    with pytest.raises(AltError):
        alt.convert_repo(repo, lambda ev: None)


def test_convert_repo_audit_unclear(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    _write_skill(repo / "my-skill", "my-skill")
    monkeypatch.setattr(alt, "run_agent", _fake_run_agent(verdict=None))
    with pytest.raises(AltError):
        alt.convert_repo(repo, lambda ev: None)


def test_convert_repo_cancel(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    _write_skill(repo / "my-skill", "my-skill")
    monkeypatch.setattr(alt, "run_agent", _fake_run_agent())
    cancelled = [False]

    def cancel():
        return cancelled[0]

    # 在 builder 前就取消
    cancelled[0] = True
    with pytest.raises(AgentCancelled):
        alt.convert_repo(repo, lambda ev: None, is_cancelled=cancel)


# ---- CLI 集成:非标准仓库 + --alt,不伪造 SHA ----

def test_install_alt_non_standard_no_fake_sha(monkeypatch, tmp_path):
    src = tmp_path / "nonsrc"
    _write_skill(src / "my-skill", "my-skill")  # 有 skill 但没有 cckit.yaml

    monkeypatch.setattr(alt, "check_sdk_available", lambda: True)
    monkeypatch.setattr(alt, "kit_builder_status", lambda: KitBuilderStatus("ready"))
    monkeypatch.setattr(alt, "run_agent", _fake_run_agent())

    alt.install_alt(str(src), is_local_path=True, assume_yes=True,
                    confirm=lambda _: True)

    info = registry.get_kit("my-kit")
    assert info is not None
    assert info["source"]["sha"] is None          # 不伪造 SHA
    assert info["source"]["url"] == str(src.resolve())  # 保留原始来源
    assert (config.store_dir() / "my-kit" / "cckit.yaml").is_file()


def test_install_alt_standard_repo_delegates(monkeypatch, tmp_path):
    # 标准仓库(带 cckit.yaml)+ --alt:走现有安装流程,不调用 run_agent。
    src = tmp_path / "stdsrc"
    _write_skill(src / "my-skill", "my-skill")
    _write(src / "cckit.yaml", _minimal_cckit_yaml())

    called = {"agent": False}
    real_run_agent = alt.run_agent

    def spy_run_agent(*a, **k):
        called["agent"] = True
        return real_run_agent(*a, **k)

    monkeypatch.setattr(alt, "run_agent", spy_run_agent)
    monkeypatch.setattr(alt, "check_sdk_available", lambda: True)

    alt.install_alt(str(src), is_local_path=True, assume_yes=True, confirm=lambda _: True)

    assert called["agent"] is False  # 标准仓库不调用 Claude Code
    assert registry.get_kit("my-kit") is not None


def test_install_alt_missing_sdk_hint(monkeypatch, tmp_path):
    src = tmp_path / "nonsrc"
    _write_skill(src / "my-skill", "my-skill")

    monkeypatch.setattr(alt, "check_sdk_available", lambda: False)

    with pytest.raises(AltError) as ei:
        alt.install_alt(str(src), is_local_path=True, assume_yes=True)
    assert "cckit[alt]" in str(ei.value)


def test_install_alt_cleans_temp_on_failure(monkeypatch, tmp_path):
    src = tmp_path / "nonsrc"
    _write_skill(src / "my-skill", "my-skill")

    monkeypatch.setattr(alt, "check_sdk_available", lambda: True)
    monkeypatch.setattr(alt, "kit_builder_status", lambda: KitBuilderStatus("ready"))
    monkeypatch.setattr(alt, "run_agent",
                        lambda p, c, s, e=None, ic=None, ch=None: (_ for _ in ()).throw(
                            AltError("boom")))

    with pytest.raises(AltError):
        alt.install_alt(str(src), is_local_path=True, assume_yes=True)

    # 临时目录全部清理
    leftovers = [p for p in tmp_path.parent.iterdir() if p.name.startswith("cckit-alt-")]
    assert leftovers == []


def test_convert_repo_tool_summary():
    assert alt._tool_input_summary({"command": "ls -la"}) == "ls -la"
    assert "Bash" in alt._tool_input_summary({"name": "Bash", "input": {}})
    long = alt._tool_input_summary({"command": "x" * 500})
    assert len(long) <= 161


def test_cli_non_standard_suggests_alt(capsys, tmp_path):
    from cckit import cli
    src = tmp_path / "nonsrc"
    _write_skill(src / "my-skill", "my-skill")  # 无 cckit.yaml
    rc = cli.main(["add", str(src), "--local"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "--alt" in err
    assert "cckit[alt]" in err
