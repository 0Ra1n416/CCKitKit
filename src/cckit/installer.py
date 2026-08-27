"""cckit add 的完整安装流程,以及 remove 的卸载流程。

add:clone → 锁 commit sha → 校验 manifest → lint → 展示计划等确认 →
移入 store → 建 env → 跑 postinstall → 写 registry → 建 link 启用。
安装是确定性的,不调 LLM(见 D-01)。

硬性要求(见 Docs/07):
  - 锁 commit sha,不锁分支/tag
  - 安装前展示计划并等确认(-y 跳过,文档需警示)
  - postinstall 只允许操作 kit 自己的目录(靠声明+审查+文档,不强制沙箱)
  - 系统级依赖只检查存在性 + 给当前平台 hint,绝不自动安装
"""
from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import config, env as env_mod, lint, link, manifest, registry, state
from .errors import CckitError


class InstallError(CckitError):
    """安装失败。"""


@dataclass
class Plan:
    """安装前展示给用户的执行计划。"""
    source: str
    ref: str | None
    sha: str | None
    kit: str
    version: str
    description: str
    python_packages: list[str] = field(default_factory=list)
    node_packages: list[str] = field(default_factory=list)
    postinstall: list[dict] = field(default_factory=list)
    system_missing: list[dict] = field(default_factory=list)
    skills: list[dict] = field(default_factory=list)


# ---- clone ----
def _clone(source: str, ref: str | None, tmp_root: Path, is_local_path: bool) -> tuple[Path, str | None]:
    """clone 到临时目录,返回 (kit 目录, commit sha)。本地非 git 目录 sha 为 None。"""
    tmp_dir = tmp_root / "kit"
    if is_local_path:
        p = Path(source).expanduser().resolve()
        if not p.is_dir():
            raise InstallError(f"本地路径不存在或不是目录: {source}")
        if (p / ".git").is_dir():
            subprocess.run(["git", "clone", "--quiet", str(p), str(tmp_dir)], check=True)
            if ref:
                subprocess.run(["git", "-C", str(tmp_dir), "checkout", "--quiet", ref], check=True)
            sha = subprocess.run(
                ["git", "-C", str(tmp_dir), "rev-parse", "HEAD"],
                capture_output=True, text=True, check=True).stdout.strip()
        else:
            shutil.copytree(p, tmp_dir, ignore=shutil.ignore_patterns(".git"))
            sha = None
    else:
        subprocess.run(["git", "clone", "--quiet", source, str(tmp_dir)], check=True)
        if ref:
            subprocess.run(["git", "-C", str(tmp_dir), "checkout", "--quiet", ref], check=True)
        sha = subprocess.run(
            ["git", "-C", str(tmp_dir), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True).stdout.strip()
    return tmp_dir, sha


# ---- 计划 ----

def _read_requirements(path: Path | None) -> list[str]:
    if not path or not path.is_file():
        return []
    return [ln.strip() for ln in path.read_text(encoding="utf-8", errors="replace").splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


def _read_package_deps(path: Path | None) -> list[str]:
    if not path or not path.is_file():
        return []
    try:
        pkg = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    deps = {}
    deps.update(pkg.get("dependencies") or {})
    deps.update(pkg.get("devDependencies") or {})
    return [f"{k}@{v}" for k, v in deps.items()]


def compute_plan(source: str, ref: str | None, sha: str | None,
                 data: dict, kit_dir: Path) -> Plan:
    """根据 manifest + 依赖文件 + 系统探测,算出要展示的执行计划。"""
    requires = data.get("requires") or {}
    py_file = (requires.get("python") or {}).get("file")
    node_file = (requires.get("node") or {}).get("file")
    plan = Plan(
        source=source, ref=ref, sha=sha, kit=data["kit"], version=data.get("version", ""),
        description=data.get("description", ""),
        python_packages=_read_requirements(kit_dir / py_file) if py_file else [],
        node_packages=_read_package_deps(kit_dir / node_file) if node_file else [],
        postinstall=list(data.get("postinstall") or []),
        skills=list(data.get("skills") or []),
    )
    platform = config.platform_name()
    for dep in requires.get("system", []):
        if shutil.which(dep["bin"]) is None:
            plan.system_missing.append({
                "bin": dep["bin"],
                "hint": (dep.get("hint") or {}).get(platform),
            })
    return plan


def render_plan(plan: Plan) -> str:
    """把计划渲染成给用户看的文本(完整列出包、postinstall、缺失系统依赖、来源+sha)。"""
    lines = [f"来源: {plan.source}"]
    if plan.ref:
        lines.append(f"ref : {plan.ref}")
    lines.append(f"sha : {plan.sha or '(本地目录,无 git)'}")
    lines.append(f"kit : {plan.kit} {plan.version}")
    lines.append(f"说明: {plan.description}")
    lines.append("")
    lines.append("将安装的 skill:")
    for sk in plan.skills:
        needs = ", ".join(sk.get("needs", [])) or "(纯 prompt)"
        lines.append(f"  - {sk['name']}  needs: {needs}")
    if plan.python_packages:
        lines.append("")
        lines.append("Python 包(requirements.txt):")
        for p in plan.python_packages:
            lines.append(f"  - {p}")
    if plan.node_packages:
        lines.append("")
        lines.append("Node 包(package.json):")
        for p in plan.node_packages:
            lines.append(f"  - {p}")
    if plan.postinstall:
        lines.append("")
        lines.append("将执行的 postinstall:")
        for step in plan.postinstall:
            lines.append(f"  - {step['run']}  (when: {step.get('when', 'always')})")
    if plan.system_missing:
        lines.append("")
        lines.append("缺失的系统依赖(只提示,不自动装):")
        for d in plan.system_missing:
            lines.append(f"  - {d['bin']}  →  {d.get('hint') or '(无 hint)'}")
    lines.append("")
    lines.append("⚠️  安装一个 kit 等同于在本机运行该仓库作者的代码。请只安装你信任的来源。")
    return "\n".join(lines)


# ---- env / postinstall ----

def build_envs(data: dict, kit_dir: Path) -> dict[str, dict[str, Path]]:
    """按 skills 的 needs 为每个 skill 建 env。返回 {name: {runtime: env_dir}}。

    一个 skill 可同时需要 python 与 node(各自建独立 env);needs 不含
    python/node 的纯 prompt skill 返回 {}。中途某 skill 失败时清掉本次已建
    的 env 再抛,避免留下孤儿 env(否则 install 的回滚拿不到 env_dirs)。
    """
    requires = data.get("requires") or {}
    runtime = requires.get("runtime") or {}
    py_constraint = runtime.get("python")
    py_file = (requires.get("python") or {}).get("file")
    node_file = (requires.get("node") or {}).get("file")
    req_path = kit_dir / py_file if py_file else None
    pkg_path = kit_dir / node_file if node_file else None

    result: dict[str, dict[str, Path]] = {}
    created: list[Path] = []
    try:
        for sk in data.get("skills", []):
            name = sk["name"]
            needs = set(sk.get("needs", []))
            envs: dict[str, Path] = {}
            if "python" in needs:
                env_dir = config.envs_dir() / f"{data['kit']}__{name}__python"
                env_mod.create_python_env(env_dir, py_constraint, req_path)
                created.append(env_dir)
                envs["python"] = env_dir
            if "node" in needs:
                env_dir = config.envs_dir() / f"{data['kit']}__{name}__node"
                env_mod.create_node_env(env_dir, pkg_path)
                created.append(env_dir)
                envs["node"] = env_dir
            result[name] = envs
    except Exception:
        for d in created:
            shutil.rmtree(d, ignore_errors=True)
        raise
    return result


def _script_interpreter(script: Path, py_interp: Path | None) -> str:
    ext = script.suffix.lower()
    if ext == ".py":
        return str(py_interp) if py_interp else "python"
    if ext in (".js", ".mjs"):
        return "node"
    raise InstallError(f"不支持的 postinstall 脚本类型 {script.name}(v0.1 仅支持 .py/.js)")


def run_postinstall(steps: list[dict], kit_dir: Path,
                    envs: dict[str, dict[str, Path]]) -> None:
    """执行 postinstall。when=python/node 仅在对应环境建好后执行。

    脚本 cwd 为 kit 根;约束:只允许操作 kit 自己的目录(靠声明+审查+文档)。
    """
    python_envs = [d for m in envs.values() for rt, d in m.items() if rt == "python"]
    node_built = any(rt == "node" for m in envs.values() for rt in m)
    py_interp = env_mod.python_interpreter(python_envs[0]) if python_envs else None
    for step in steps:
        run = step.get("run")
        when = step.get("when", "always")
        script = kit_dir / run
        if not script.is_file():
            raise InstallError(f"postinstall 脚本不存在: {run}")
        if when == "python" and py_interp is None:
            continue
        if when == "node" and not node_built:
            continue
        interp = _script_interpreter(script, py_interp)
        env = os.environ.copy()
        env["CCKIT_KIT_DIR"] = str(kit_dir)
        subprocess.run([interp, str(script)], cwd=str(kit_dir), env=env, check=True)


# ---- registry 记录 ----

def _registry_record(source: str, ref: str | None, sha: str | None, data: dict,
                     store_target: Path, envs: dict[str, dict[str, Path]],
                     scope: str) -> dict:
    root = config.project_root()
    known = "global" if scope == "global" else str(root)
    skills = []
    for sk in data.get("skills", []):
        skills.append({
            "name": sk["name"],
            "envs": {rt: str(d) for rt, d in envs[sk["name"]].items()},
            "needs": list(sk.get("needs", [])),
        })
    return {
        "source": {"url": source, "ref": ref, "sha": sha},
        "version": data.get("version"),
        "installed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "store": str(store_target),
        "skills": skills,
        "known_scopes": [known],
        "override_scopes": [],
    }


def _installed_descriptions() -> list[str]:
    """已装 skill 的 description 列表,供 lint 语义重叠检测。"""
    store = config.store_dir()
    descs: list[str] = []
    if store.is_dir():
        for skill_dir in store.glob("*/*"):
            if not skill_dir.is_dir():
                continue
            d = str(manifest.read_skill_frontmatter(skill_dir).get("description") or "").strip()
            if d:
                descs.append(d)
    return descs


# ---- add 主流程 ----

def install(source: str, *, ref: str | None = None, project: bool = False,
            no_enable: bool = False, only: str | None = None,
            assume_yes: bool = False, is_local_path: bool = False) -> None:
    """安装一个 kit。破坏性/高风险操作在非 -y 时需确认。

    is_local_path=True 时把 source 当本地目录(非 git 目录则 copytree、无 sha);
    否则当 git URL 直接交给 `git clone`。
    """
    scope = "project" if project else "global"
    if project:
        # 项目作用域:确保项目根存在。尚无 .claude / cckit.lock 时以 cwd 为项目根,
        # 并建出 .claude 目录(否则 set_state 无法定位项目 skills 目录)。
        root = config.project_root() or Path.cwd().resolve()
        (root / ".claude").mkdir(parents=True, exist_ok=True)
    tmp_root = Path(tempfile.mkdtemp(prefix="cckit-clone-"))
    store_target: Path | None = None
    env_dirs: list[Path] = []
    reg_added = False
    kit_name: str | None = None
    try:
        kit_dir, sha = _clone(source, ref, tmp_root, is_local_path)

        # 校验 manifest(存在性 → schema → 语义)。失败即中止,不留残留。
        data = manifest.load(kit_dir / "cckit.yaml")
        manifest.validate_schema(data)
        manifest.semantic_check(data, kit_dir)
        kit_name = data["kit"]

        # --only 提前校验:写错名字直接报错,而不是静默不 link(见 M4)
        only_names: set[str] | None = None
        if only:
            only_names = {s.strip() for s in only.split(",") if s.strip()}
            if not only_names:
                raise InstallError("--only 没有指定任何有效的 skill 名")
            unknown = only_names - {sk["name"] for sk in data.get("skills", [])}
            if unknown:
                raise InstallError(
                    f"--only 指定的 skill 不在 kit 中: {', '.join(sorted(unknown))}")

        # lint。error 中止;warn 展示。
        msgs = lint.lint_kit(kit_dir, data, _installed_descriptions())
        for m in msgs:
            print(f"[{m.level}] {m.message}")
        if any(m.level == "error" for m in msgs):
            raise InstallError("lint 发现错误,已中止(未留下任何残留)")

        kit = data["kit"]
        store_target = config.store_dir() / kit
        if store_target.exists():
            raise InstallError(f"kit {kit!r} 已安装(store 已存在),请先 `cckit remove {kit}`")

        # 项目安装时检测同名全局 skill(全局盖项目,见 Docs/06 2.3)
        if project:
            global_names = {s.name for s in state.list_skills("global")}
            for sk in data.get("skills", []):
                if sk["name"] in global_names:
                    print(f"[warn] 全局已存在同名 skill {sk['name']!r},"
                          f"全局会覆盖项目版(enterprise > personal > project)")

        # 展示计划并等确认
        plan = compute_plan(source, ref, sha, data, kit_dir)
        print(render_plan(plan))
        sys.stdout.flush()  # 确认前把计划刷出:uv/npm 子进程直接写 fd,绕过缓冲
        if not assume_yes:
            ans = input("继续安装? [y/N] ").strip().lower()
            if ans not in ("y", "yes"):
                raise InstallError("已取消安装")
        else:
            print("[warn] -y 已跳过确认。安装等于运行仓库作者代码,请自行确认来源可信。")
        sys.stdout.flush()  # -y 路径无 input,补一次 flush 保证计划先于子进程输出

        # 移入 store
        config.store_dir().mkdir(parents=True, exist_ok=True)
        shutil.move(str(kit_dir), str(store_target))
        kit_dir = store_target

        # 建 env
        envs = build_envs(data, store_target)
        env_dirs = [d for m in envs.values() for d in m.values()]

        # postinstall
        run_postinstall(data.get("postinstall") or [], store_target, envs)

        # 写 registry(先于 link —— set_state 需要 registry 定位 skill)
        registry.add_kit(kit, _registry_record(source, ref, sha, data, store_target, envs, scope))
        reg_added = True

        # 建 link 启用
        if not no_enable:
            for sk in data.get("skills", []):
                if only_names is not None and sk["name"] not in only_names:
                    continue
                state.set_state(sk["name"], "enabled", scope, kit=kit)

        used, limit = state.budget()
        print(f"已安装 {kit} {data.get('version', '')}")
        print(f"清单预算: {used} / {limit} 字符")
        print("提示:开关改动将在新会话生效。")
    except Exception:
        # 回滚:临时目录、store、env、registry 记录(尽力而为)
        shutil.rmtree(tmp_root, ignore_errors=True)
        if store_target is not None and store_target.exists():
            shutil.rmtree(store_target, ignore_errors=True)
        for d in env_dirs:
            shutil.rmtree(d, ignore_errors=True)
        if reg_added and kit_name:
            registry.remove_kit(kit_name)
        raise
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


# ---- remove ----

def _skills_dir_for_scope(scope_value: str) -> Path | None:
    if scope_value == "global":
        return config.claude_config_dir() / "skills"
    return Path(scope_value) / ".claude" / "skills"


def remove_kit(kit: str, keep_env: bool = False) -> None:
    """删 link → 删 env → 删 store → 清 registry 与 skillOverrides 残留。"""
    info = registry.get_kit(kit)
    if info is None:
        raise CckitError(f"kit {kit!r} 未安装")
    names = [sk["name"] for sk in info.get("skills", [])]

    # 删 link(所有 known_scopes)
    for scope_value in info.get("known_scopes", []):
        skills_dir = _skills_dir_for_scope(scope_value)
        if skills_dir is None:
            continue
        for name in names:
            lp = skills_dir / name
            if link.is_link(lp) or link.is_dangling(lp):
                link.remove(lp)

    # 删 env
    if not keep_env:
        for sk in info.get("skills", []):
            for env_dir in (sk.get("envs") or {}).values():
                shutil.rmtree(Path(env_dir), ignore_errors=True)

    # 删 store
    store = Path(info.get("store", ""))
    if store.exists():
        shutil.rmtree(store, ignore_errors=True)

    # 清 registry
    registry.remove_kit(kit)

    # 清 skillOverrides 残留
    for scope_value in info.get("known_scopes", []):
        if scope_value == "global":
            state.remove_overrides(names, "global")
        else:
            state.remove_overrides(names, "project", root=Path(scope_value))
    # 清项目级覆盖残留(全局 kit 的 skill 被 --project 覆盖时记入 override_scopes)
    for scope_value in info.get("override_scopes", []):
        if scope_value and scope_value != "global":
            state.remove_overrides(names, "project", root=Path(scope_value))
