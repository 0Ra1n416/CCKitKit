"""installer:计划计算与渲染(不触发网络/uv 的部分)。"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from cckit import config, installer, link, manifest, registry, state
from cckit.errors import CckitError


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


# ---- 同名 skill:同一作用域内拒绝安装 ----

def _write(path: Path, text: str) -> None:
    """以 LF 写入(Windows 上 write_text 会转成 CRLF,触发 lint 噪声)。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def _make_kit_src(root: Path, kit: str, skills: list[str]) -> Path:
    """造一个本地 kit 源码目录(stage_install 走 is_local_path,不碰网络)。"""
    src = root / f"src-{kit}"
    manifest_text = ("cckit: 1\n" f"kit: {kit}\n" "version: 0.1.0\n"
                     "description: test kit\n" "skills:\n")
    for s in skills:
        manifest_text += f"  - name: {s}\n    needs: []\n"
    _write(src / "cckit.yaml", manifest_text)
    for s in skills:
        _write(src / s / "SKILL.md", f"---\nname: {s}\ndescription: {kit} 的 {s}\n---\n")
    return src


def _install_other_kit(kit: str, skill: str, *, scope: str = "global",
                       root: Path | None = None, link_it: bool = True) -> None:
    """模拟"先装的另一个 kit":写 store + registry,link_it=False 则不建 link。"""
    store_skill = config.store_dir() / kit / skill
    _write(store_skill / "SKILL.md", f"---\ndescription: {kit} 的 {skill}\n---\n")
    registry.add_kit(kit, {
        "source": {"url": f"https://x/{kit}", "ref": None, "sha": None},
        "version": "1.0.0",
        "store": str(config.store_dir() / kit),
        "skills": [{"name": skill, "envs": {}, "needs": []}],
        "known_scopes": ["global" if scope == "global" else str(root)],
        "override_scopes": [],
    })
    if link_it:
        state.set_state(skill, "enabled", scope, kit=kit, root=root)


def test_stage_install_rejects_same_name_in_global(tmp_path):
    """同名 skill 已在全局占用 → 拒绝,并指名占用者(否则 link 建不上,静默失效)。"""
    _install_other_kit("kit-a", "foo")
    src = _make_kit_src(tmp_path, "kit-b", ["foo"])

    with pytest.raises(installer.InstallError) as ei:
        installer.stage_install(str(src), is_local_path=True)

    msg = str(ei.value)
    assert "foo" in msg and "kit-a" in msg
    assert not (config.store_dir() / "kit-b").exists()  # 没留下残留


def test_stage_install_rejects_same_name_in_project(tmp_path):
    """项目作用域同理:link 落点同是 <root>/.claude/skills/<name>。"""
    root = tmp_path / "proj"
    (root / ".claude").mkdir(parents=True)
    _install_other_kit("kit-a", "foo", scope="project", root=root)
    src = _make_kit_src(tmp_path, "kit-b", ["foo"])

    with pytest.raises(installer.InstallError) as ei:
        installer.stage_install(str(src), is_local_path=True, project=True, root=root)

    assert "项目作用域" in str(ei.value)


def test_stage_install_allows_same_name_when_not_linked(tmp_path):
    """另一个 kit 只是装进 store 没建 link(--no-enable)时不冲突:
    没有 link 就不占名字,这正是 list 按 (kit, name) 去重的前提(见 M1)。"""
    _install_other_kit("kit-a", "foo", link_it=False)
    src = _make_kit_src(tmp_path, "kit-b", ["foo"])

    staged = installer.stage_install(str(src), is_local_path=True)
    staged.cleanup()  # 没抛异常即通过


def test_stage_install_only_bypasses_conflict(tmp_path):
    """--only 排除掉的 skill 本次不建 link,不参与冲突检查。"""
    _install_other_kit("kit-a", "foo")
    src = _make_kit_src(tmp_path, "kit-b", ["foo", "bar"])

    staged = installer.stage_install(str(src), is_local_path=True, only="bar")
    staged.cleanup()


def test_stage_install_rejects_non_managed_dir(tmp_path):
    """cckit 之外的用户手写 skill 目录同样占名字,不覆盖。"""
    _write(config.claude_config_dir() / "skills" / "foo" / "SKILL.md", "手写的")
    src = _make_kit_src(tmp_path, "kit-b", ["foo"])

    with pytest.raises(installer.InstallError) as ei:
        installer.stage_install(str(src), is_local_path=True)

    assert "用户手写" in str(ei.value)


def test_stage_install_rejects_dangling_link(tmp_path):
    """悬空 link 也占名字 —— set_state 见到 link 就 pass,不指出来会同样建不上。"""
    _install_other_kit("kit-a", "foo")
    shutil.rmtree(config.store_dir() / "kit-a")  # 目标没了 → link 悬空
    src = _make_kit_src(tmp_path, "kit-b", ["foo"])

    with pytest.raises(installer.InstallError) as ei:
        installer.stage_install(str(src), is_local_path=True)

    assert "doctor --fix" in str(ei.value)


# ---- store 不含 .git ----

def test_clone_strips_git(tmp_path, monkeypatch):
    """clone 出的 kit 目录不带 .git:store 只要文件树。

    留着 .git 会把只读的对象文件带进 store —— 那是 Windows 上 remove 删不干净的
    源头(见 fsutil.rmtree)。
    """
    def fake_run(argv, **kw):
        if argv[0] == "git" and argv[1] == "clone":
            out = Path(argv[-1])
            obj = out / ".git" / "objects" / "ab" / "cdef"
            obj.parent.mkdir(parents=True)
            obj.write_bytes(b"x")
            os.chmod(obj, 0o400)  # git 在 Windows 上就是这么写的
            (out / "cckit.yaml").write_text("x", encoding="utf-8")
        elif argv[-1] == "HEAD":
            return subprocess.CompletedProcess(argv, 0, "sha123\n", "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(installer.subprocess, "run", fake_run)
    kit_dir, sha = installer._clone("https://x/y.git", None, tmp_path, False)

    assert sha == "sha123"
    assert (kit_dir / "cckit.yaml").is_file()
    assert not (kit_dir / ".git").exists()


# ---- store 已有残留时的报错 ----

def test_stage_install_reports_orphan_store(tmp_path):
    """store 有同名目录但 registry 无记录 = 上次 remove 没删干净的残留。

    这种情况必须和"真装过"分开说:否则用户卡在 add 说"已存在"、remove 说"未安装",
    两头都走不通。"""
    _write(config.store_dir() / "kit-b" / "foo" / "SKILL.md", "---\ndescription: x\n---\n")
    src = _make_kit_src(tmp_path, "kit-b", ["foo"])

    with pytest.raises(installer.InstallError) as ei:
        installer.stage_install(str(src), is_local_path=True)

    msg = str(ei.value)
    assert "残留" in msg
    assert "cckit remove kit-b" in msg


def test_stage_install_reports_real_install(tmp_path):
    """registry 有记录 = 真装过,报错仍旧指向 remove。"""
    _install_other_kit("kit-a", "foo", link_it=False)
    src = _make_kit_src(tmp_path, "kit-a", ["foo"])

    with pytest.raises(installer.InstallError) as ei:
        installer.stage_install(str(src), is_local_path=True)

    assert "已安装" in str(ei.value)


# ---- remove:只读文件与半截残留 ----

def test_remove_kit_deletes_store_with_readonly_files(tmp_path):
    """store 里有只读文件(等效 .git/objects)时也要删干净。

    旧实现 shutil.rmtree(ignore_errors=True) 在 Windows 上会静默跳过只读对象文件,
    留下 .git 骨架 → 之后 add 永远报"store 已存在"。"""
    _install_other_kit("kit-a", "foo", link_it=False)
    store = config.store_dir() / "kit-a"
    obj = store / ".git" / "objects" / "ab" / "cdef"
    obj.parent.mkdir(parents=True)
    obj.write_bytes(b"x")
    os.chmod(obj, 0o400)

    installer.remove_kit("kit-a")

    assert not store.exists()
    assert registry.get_kit("kit-a") is None


def test_remove_kit_cleans_orphan_store(tmp_path):
    """registry 无记录但 store 目录还在(老版本 remove 的半截产物)→ remove 清掉它。

    这是用户唯一的出路:否则 add 说"已存在"、remove 说"未安装"。"""
    _write(config.store_dir() / "kit-a" / "foo" / "SKILL.md", "---\ndescription: x\n---\n")

    installer.remove_kit("kit-a")

    assert not (config.store_dir() / "kit-a").exists()


def test_remove_kit_orphan_sweeps_envs_by_name(tmp_path):
    """孤儿清理连 env 一起收:registry 没了就拿不到 envs 映射,按命名约定兜底。"""
    _write(config.store_dir() / "kit-a" / "foo" / "SKILL.md", "---\ndescription: x\n---\n")
    env_dir = config.envs_dir() / "kit-a__foo__python"
    env_dir.mkdir(parents=True)

    installer.remove_kit("kit-a")

    assert not env_dir.exists()


def test_remove_kit_orphan_keeps_env_with_keep_env(tmp_path):
    _write(config.store_dir() / "kit-a" / "foo" / "SKILL.md", "---\ndescription: x\n---\n")
    env_dir = config.envs_dir() / "kit-a__foo__python"
    env_dir.mkdir(parents=True)

    installer.remove_kit("kit-a", keep_env=True)

    assert env_dir.is_dir()
    assert not (config.store_dir() / "kit-a").exists()


def test_remove_kit_unknown_name_still_raises(tmp_path):
    """什么都没有时保持原语义:报"未安装",不能变成静默成功。"""
    with pytest.raises(CckitError) as ei:
        installer.remove_kit("nope")

    assert "未安装" in str(ei.value)


def test_remove_kit_orphan_also_clears_links_into_it(tmp_path):
    """孤儿残留清理要连 link 一起收:留着就是悬空 link,照样占住 skill 名挡住 add。"""
    store = config.store_dir() / "kit-a"
    _write(store / "foo" / "SKILL.md", "---\ndescription: x\n---\n")
    entry = config.claude_config_dir() / "skills" / "foo"
    link.create(store / "foo", entry)

    installer.remove_kit("kit-a")

    assert not store.exists()
    assert not os.path.lexists(entry)


def test_remove_kit_clears_links_outside_known_scopes(tmp_path):
    """registry 不知道的 link(别的项目根里建的)也要收干净,否则留下悬空 link。"""
    _install_other_kit("kit-a", "foo", link_it=False)
    (tmp_path / ".claude").mkdir()          # cwd 成为项目根 → 该作用域会被扫描
    entry = tmp_path / ".claude" / "skills" / "foo"
    link.create(config.store_dir() / "kit-a" / "foo", entry)

    installer.remove_kit("kit-a")

    assert not os.path.lexists(entry)
    assert not (config.store_dir() / "kit-a").exists()


def test_remove_kit_sweeps_dangling_links_when_store_already_gone(tmp_path):
    """store 已被手动删掉时,remove 仍要收掉指向它的悬空 link(否则挡住下一次 add)。"""
    _install_other_kit("kit-a", "foo", link_it=False)
    store = config.store_dir() / "kit-a"
    (tmp_path / ".claude").mkdir()          # cwd 成为项目根 → 该作用域会被扫描
    entry = tmp_path / ".claude" / "skills" / "foo"
    link.create(store / "foo", entry)
    shutil.rmtree(store)                    # 目标没了 → link 悬空

    installer.remove_kit("kit-a")

    assert not os.path.lexists(entry)


def test_remove_kit_does_not_report_success_when_store_survives(tmp_path, monkeypatch):
    """删不掉时抛受检错误、registry 保持不动,而不是打印"已移除"留下残留。"""
    _install_other_kit("kit-a", "foo", link_it=False)

    def boom(path, **kw):
        raise PermissionError(f"被占用: {path}")

    monkeypatch.setattr(installer.fsutil, "rmtree", boom)

    with pytest.raises(CckitError) as ei:
        installer.remove_kit("kit-a")

    assert "手动删除" in str(ei.value)
    assert registry.get_kit("kit-a") is not None  # 未改动,重试 remove 即可
