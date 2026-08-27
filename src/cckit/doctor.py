"""cckit doctor —— 只诊断不自动修,每项给出可复制修复命令。

检查项覆盖 Docs/04 的 doctor 表:uv 在 PATH、悬空 link、link 指向与 registry
一致、env 完整+解释器可执行、系统依赖、disableSkillShellExecution、清单预算、
同名冲突。这些大多是"不检查就 debug 一整天"的静默失效。
--fix 只处理明确安全的项:清理悬空 link、重建损坏的 python env。
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from . import config, env as env_mod, link, manifest, registry, state
from .errors import CckitError


@dataclass
class Finding:
    check: str
    status: str  # ok | warn | error
    message: str
    fix: str | None = None


def run(fix: bool = False) -> list[Finding]:
    findings: list[Finding] = []

    # 1. uv 是否在 PATH
    if shutil.which("uv"):
        findings.append(Finding("uv", "ok", "uv 在 PATH 中"))
    else:
        findings.append(Finding(
            "uv", "error", "找不到 uv,无法建 env",
            "安装 uv: https://docs.astral.sh/uv/getting-started/installation/"))

    findings += _check_links()
    findings += _check_envs()
    findings += _check_system_deps()
    findings += _check_shell_execution()
    findings += _check_budget()
    findings += _check_name_conflicts()

    if fix:
        _apply_fixes(findings)

    return findings


def _check_links() -> list[Finding]:
    findings: list[Finding] = []
    # 复用 state 的作用域/link 解析,不自己扫目录(避免两套扫描逻辑漂移)
    for _, d in state.scope_skills_dirs():
        if not d.is_dir():
            continue
        for entry in d.iterdir():
            if link.is_dangling(entry):
                findings.append(Finding(
                    "link", "error", f"悬空链接: {entry}(目标已消失)",
                    f"清理:`cckit doctor --fix` 或手动删除 {entry}"))
            elif link.is_link(entry):
                target = entry.resolve()
                kit = state.resolve_managed_kit(target)
                if kit:
                    rec = registry.get_kit(kit)
                    rec_store = rec.get("store") if rec else None
                    if rec_store and Path(rec_store) != target.parent:
                        findings.append(Finding(
                            "link", "warn",
                            f"link {entry} 指向 {target},与 registry 记录 {rec_store} 不一致(手工改动导致漂移)",
                            f"重建:`cckit remove {kit}` 后重新 add"))
    return findings


def _check_envs() -> list[Finding]:
    findings: list[Finding] = []
    for kit, info in registry.load().get("kits", {}).items():
        for sk in info.get("skills", []):
            runtime = sk.get("runtime")
            if runtime is None:
                continue
            env_dir = Path(sk["env"]) if sk.get("env") else None
            ok = env_dir is not None and env_mod.check_env(env_dir, runtime)
            if ok:
                findings.append(Finding("env", "ok", f"{kit}/{sk['name']} env 完整"))
            else:
                findings.append(Finding(
                    "env", "error", f"{kit}/{sk['name']} env 缺失或解释器不可执行",
                    f"重建:`cckit doctor --fix` 或 `cckit remove {kit}` 后重新 add"))
    return findings


def _check_system_deps() -> list[Finding]:
    findings: list[Finding] = []
    platform = config.platform_name()
    for kit, info in registry.load().get("kits", {}).items():
        mf = Path(info.get("store", "")) / "cckit.yaml"
        if not mf.is_file():
            continue
        data = manifest.load(mf)
        for dep in (data.get("requires") or {}).get("system", []):
            bin_ = dep["bin"]
            if shutil.which(bin_):
                findings.append(Finding("system", "ok", f"{bin_} 可用({kit})"))
            else:
                hint = (dep.get("hint") or {}).get(platform)
                findings.append(Finding(
                    "system", "warn", f"{bin_} 缺失({kit})",
                    hint or f"请手动安装 {bin_}"))
    return findings


def _check_shell_execution() -> list[Finding]:
    findings: list[Finding] = []
    for scope, label in (("global", "全局"), ("project", "项目")):
        try:
            settings = state.read_settings(scope)
        except CckitError:
            continue
        if settings.get("disableSkillShellExecution"):
            findings.append(Finding(
                "settings", "error",
                f"{label} settings 开启了 disableSkillShellExecution,"
                f"所有带脚本 skill 会静默失效",
                f"把 {label} settings.json 的 disableSkillShellExecution 改为 false 或删除"))
    return findings


def _check_budget() -> list[Finding]:
    used, limit = state.budget()
    if used > limit:
        return [Finding(
            "budget", "error",
            f"清单预算超限: {used} / {limit} 字符,description 会被静默丢弃",
            "把不常用 skill 降为 name-only:`cckit name-only <skill>`")]
    return [Finding("budget", "ok", f"清单预算: {used} / {limit} 字符")]


def _check_name_conflicts() -> list[Finding]:
    findings: list[Finding] = []
    # 复用 state.list_skills 的扫描结果,不自己枚举目录
    by_name: dict[str, set[tuple[str, str | None]]] = {}
    for s in state.list_skills(None):
        if s.state == "installed":
            continue  # 没 link 不被扫描,不参与覆盖
        by_name.setdefault(s.name, set()).add((s.scope, s.kit))
    for name, identities in sorted(by_name.items()):
        g = {kit for scope, kit in identities if scope == "global"}
        p = {kit for scope, kit in identities if scope == "project"}
        if not g or not p:
            continue
        # 同一个 managed kit 的 skill 同时出现在全局与项目作用域 = D-15 的
        # "全局 skill 按项目覆盖",不是同名冲突;同名冲突必须来自不同来源。
        if g == p and len(g) == 1 and None not in g:
            continue
        findings.append(Finding(
            "conflict", "warn",
            f"同名 skill {name!r} 同时存在全局与项目,全局会覆盖项目版",
            f"二选一:`cckit disable {name}`(全局)或 `cckit disable {name} --project`"))
    return findings


def _apply_fixes(findings: list[Finding]) -> None:
    """只做明确安全的修复:清理悬空 link、重建损坏的 python env。"""
    for _, d in state.scope_skills_dirs():
        if not d.is_dir():
            continue
        for entry in d.iterdir():
            if link.is_dangling(entry):
                link.remove(entry)

    for kit, info in registry.load().get("kits", {}).items():
        mf = Path(info.get("store", "")) / "cckit.yaml"
        if not mf.is_file():
            continue
        data = manifest.load(mf)
        requires = data.get("requires") or {}
        py_file = (requires.get("python") or {}).get("file")
        req = Path(info.get("store", "")) / py_file if py_file else None
        constraint = (requires.get("runtime") or {}).get("python")
        for sk in info.get("skills", []):
            if sk.get("runtime") != "python":
                continue
            env_dir = Path(sk["env"])
            if not env_mod.check_env(env_dir, "python"):
                env_mod.create_python_env(env_dir, constraint, req)
