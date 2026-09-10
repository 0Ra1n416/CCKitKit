"""cckit add 的完整安装流程,以及 remove 的卸载流程。

add:clone → 锁 commit sha → 校验 manifest → lint → 展示计划等确认 →
移入 store → 建 env → 跑 postinstall → 写 registry → 建 link 启用。
安装是确定性的,不调 LLM(见 D-01)。

硬性要求(见 Docs/07):
  - 锁 commit sha,不锁分支/tag
  - 安装前展示计划并等确认(-y 跳过,文档需警示)
  - postinstall 只允许操作 kit 自己的目录(靠声明+审查+文档,不强制沙箱)
  - 系统级依赖只检查存在性 + 版本约束比对 + 给当前平台 hint,绝不自动安装;
    version_cmd 收紧为 `<bin> <版本标志>` 白名单,拒绝任意命令执行
"""
from __future__ import annotations

import datetime
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion

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
    system_version_warn: list[dict] = field(default_factory=list)
    system_version_error: list[dict] = field(default_factory=list)
    skills: list[dict] = field(default_factory=list)


@dataclass
class StagedInstall:
    """stage_install 的结果:已 clone + 校验通过、等待确认的安装。"""
    source: str
    ref: str | None
    sha: str | None
    is_local_path: bool
    scope: str                      # "global" | "project"
    root: Path | None               # project 作用域的项目根
    tmp_root: Path                  # 临时 clone 目录(execute 结束时清理)
    kit_dir: Path                   # clone 出的 kit 目录(execute 时 move 进 store)
    kit_name: str
    data: dict                      # cckit.yaml 解析结果
    plan: Plan
    lint_msgs: list                 # lint.LintMessage 列表(可能含 error,由调用方决定是否继续)
    only_names: set[str] | None
    project_warns: list[str]        # 项目安装时的同名全局 skill 警告

    def cleanup(self) -> None:
        """放弃安装时清理临时 clone 目录(幂等)。"""
        shutil.rmtree(self.tmp_root, ignore_errors=True)


@dataclass
class ProgressEvent:
    """execute_install 的进度事件(供 CLI print / Web SSE 流式)。"""
    stage: str                      # store | env | postinstall | registry | link | done
    status: str = "done"            # done(正常进度);error 由异常承载,不进这里
    message: str = ""


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

# ---- 系统依赖版本约束 ----

_VERSION_RE = re.compile(r"\d+(?:\.\d+)+")
_ALLOWED_VERSION_FLAGS = frozenset({"--version", "-V", "-v", "version", "-version"})


def _unsafe_version_cmd(argv: list[str], bin_name: str) -> str | None:
    """校验 version_cmd 是否落在白名单内,返回不安全原因;None = 安全可执行。

    白名单只允许 `<bin> <版本标志>`:第一个词必须等于 bin,后跟且仅跟一个
    版本标志。其余(多余参数、其它标志、别的二进制)一律拒绝 —— 作者写的
    version_cmd 会在用户确认安装之前就执行,必须收紧到"只读的版本查询"。
    """
    if not argv:
        return "命令为空"
    if argv[0] != bin_name:
        return f"命令 {argv[0]!r} 不是依赖 {bin_name!r} 本身"
    if len(argv) != 2:
        return f"参数个数必须恰为 2(<bin> <版本标志>),实际 {len(argv)}"
    if argv[1] not in _ALLOWED_VERSION_FLAGS:
        return f"版本标志 {argv[1]!r} 不在白名单 {sorted(_ALLOWED_VERSION_FLAGS)!r}"
    return None


def _version_satisfies(installed: str, constraint: str) -> bool:
    """按约束判断已装版本是否满足(基于 PEP 440 的 SpecifierSet)。"""
    try:
        return SpecifierSet(constraint).contains(installed)
    except (InvalidSpecifier, InvalidVersion) as e:
        raise ValueError(f"无法解析版本约束 {constraint!r}: {e}") from e


def _check_system_version(dep: dict) -> tuple[str | None, str]:
    """检查单个 system 依赖的版本约束,返回 (级别, 消息)。

    - 未声明 version → (None, ""),跳过。
    - 版本满足 → (None, "")。
    - 版本不满足 → ("error", 消息)。
    - 无法运行/解析版本,或 version_cmd 被白名单拒绝 → ("warn", 消息)。
    """
    constraint = dep.get("version")
    if not constraint:
        return None, ""
    bin_name = dep["bin"]
    version_cmd = dep.get("version_cmd") or f"{bin_name} --version"
    try:
        argv = shlex.split(version_cmd)
    except ValueError as e:
        return "warn", f"version_cmd 无法解析: {e}(要求 {constraint})"
    reason = _unsafe_version_cmd(argv, bin_name)
    if reason is not None:
        return "warn", (
            f"version_cmd {version_cmd!r} 被拒绝({reason});"
            f"为安全起见仅允许 <bin> 后跟一个版本标志,请手动验证版本(要求 {constraint})"
        )
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=10)
    except (OSError, ValueError) as e:
        return "warn", f"无法运行版本检查命令 {version_cmd!r}: {e}"
    except subprocess.TimeoutExpired:
        return "warn", f"版本检查命令 {version_cmd!r} 超时,无法验证版本(要求 {constraint})"

    output = (proc.stdout + "\n" + proc.stderr).strip()
    m = _VERSION_RE.search(output) if output else None
    if m is not None:
        try:
            if _version_satisfies(m.group(0), constraint):
                return None, ""
        except ValueError as e:
            return "warn", str(e)
    if proc.returncode != 0:
        return "warn", f"版本检查命令 {version_cmd!r} 失败(exit {proc.returncode}),无法验证版本(要求 {constraint})"
    if m is None:
        return "warn", f"无法从 {version_cmd!r} 的输出解析版本(要求 {constraint})"
    return "error", f"版本不满足:要求 {constraint},当前 {m.group(0)}"


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
            continue
        level, msg = _check_system_version(dep)
        if level == "error":
            plan.system_version_error.append({"bin": dep["bin"], "detail": msg})
        elif level == "warn":
            plan.system_version_warn.append({"bin": dep["bin"], "detail": msg})
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
    if plan.system_version_warn:
        lines.append("")
        lines.append("系统依赖版本无法验证:")
        for d in plan.system_version_warn:
            lines.append(f"  - {d['bin']}  →  {d.get('detail', '')}")
    if plan.system_version_error:
        lines.append("")
        lines.append("系统依赖版本不满足(该 skill 可能无法正常工作):")
        for d in plan.system_version_error:
            lines.append(f"  - {d['bin']}  →  {d.get('detail', '')}")
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
    raise InstallError(f"不支持的 postinstall 脚本类型 {script.name}(v0.2 仅支持 .py/.js)")


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
                     scope: str, root: Path | None = None) -> dict:
    """把 manifest 里"读一次就够"的声明快照进 registry,免得 list / Web 每次现场解析。

    注意两个只差一个字母的字段,含义完全不同(见 Docs/09):
      - `envs`:{runtime: env_dir},python/node **虚拟环境目录**(本函数第一处)
      - `env` :[{name, required, description}],**环境变量**声明,值由用户在
        CLI/Web 填写,存在 ~/.cckit/envs.json
    """
    proj_root = root or config.project_root()
    known = "global" if scope == "global" else str(proj_root)
    skills = []
    for sk in data.get("skills", []):
        skills.append({
            "name": sk["name"],
            "envs": {rt: str(d) for rt, d in envs[sk["name"]].items()},
            "needs": list(sk.get("needs", [])),
            "env": [dict(e) for e in sk.get("env") or []],
            "conf_files": list(sk.get("conf_files") or []),
        })
    return {
        "source": {"url": source, "ref": ref, "sha": sha},
        "version": data.get("version"),
        "installed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "store": str(store_target),
        "kit_env": [dict(e) for e in data.get("kit_env") or []],
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

def _check_scope_name_conflicts(data: dict, skills_dir: Path | None, scope: str,
                                proj_root: Path | None,
                                only_names: set[str] | None) -> None:
    """目标作用域已被同名 skill 占用时拒绝安装(Docs/cli-spec「必须拦截的情况」)。

    CC 的 skill 名字空间是单层的:link 落点是 <skills_dir>/<name>,没有 kit 前缀,
    同一作用域内一个名字只能属于一个 kit。不在这里拦,execute 阶段就会静默失效
    —— set_state 见到已有 link 直接 pass,后装的 skill 只写进 registry 却永远建
    不上 link(在 list 里显示为 installed),此后按名操作还会因归属歧义全部报错。

    --only 排除掉的 skill 本次不建 link,不参与检查。跨作用域(全局 vs 项目)的
    同名是允许的,由 CC 的优先级决定谁生效,不在本检查范围内。
    """
    if skills_dir is None or not skills_dir.is_dir():
        return
    where = "全局作用域" if scope == "global" else f"项目作用域 {proj_root}"
    problems: list[str] = []
    for sk in data.get("skills", []):
        name = sk["name"]
        if only_names is not None and name not in only_names:
            continue
        entry = skills_dir / name
        if link.is_dangling(entry):
            problems.append(f"  - {name}: 已有悬空 link {entry}(目标已不存在)"
                            f" → 先运行 `cckit doctor --fix` 清理")
        elif link.is_link(entry):
            owner = state.resolve_managed_kit(Path(entry).resolve())
            if owner:
                problems.append(
                    f"  - {name}: 已被 kit {owner!r} 占用"
                    f" → 先 `cckit remove {owner}`(或 `cckit disable {name} --purge`)"
                    f"释放该名字")
            else:
                problems.append(f"  - {name}: 已被非 cckit 管理的 link 占用({entry})"
                                f" → 请手动处理")
        elif os.path.lexists(entry):
            problems.append(f"  - {name}: 已存在同名路径 {entry}"
                            f"(cckit 之外的用户手写 skill 或插件)→ 请手动处理")
    if problems:
        raise InstallError(
            f"以下 skill 名在{where}已被占用,同一作用域内 skill 名必须唯一:\n"
            + "\n".join(problems)
            + "\n可用 `--only <skill,...>` 排除这些 skill,或按上面的提示释放该名字后重试。")


def stage_install(source: str, *, ref: str | None = None, project: bool = False,
                  only: str | None = None, is_local_path: bool = False,
                  root: Path | None = None) -> StagedInstall:
    """安装第一阶段:clone → 校验 manifest → lint → 计算计划,不落盘、不执行。

    返回 StagedInstall 供调用方展示计划并决定是否 execute_install。
    lint 的 error 级别**不在此中止**(消息存进 lint_msgs),由调用方决定:
    CLI 展示后中止、Web 展示后禁用确认。硬错误(manifest 无效、store 已存在等)
    在此抛 InstallError 并清理临时目录。
    """
    scope = "project" if project else "global"
    proj_root: Path | None = None
    if project:
        # 项目作用域:显式 root 优先,否则回落到 cwd 项目根 / cwd;确保 .claude 存在。
        proj_root = root or config.project_root() or Path.cwd().resolve()
        (proj_root / ".claude").mkdir(parents=True, exist_ok=True)

    tmp_root = Path(tempfile.mkdtemp(prefix="cckit-clone-"))
    try:
        kit_dir, sha = _clone(source, ref, tmp_root, is_local_path)

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

        msgs = lint.LintKit(kit_dir, data, _installed_descriptions()).lint_kit()

        store_target = config.store_dir() / kit_name
        if store_target.exists():
            raise InstallError(f"kit {kit_name!r} 已安装(store 已存在),请先 `cckit remove {kit_name}`")

        # 目标作用域已有同名 skill → 拒绝(否则 link 建不上,静默失效,见 Docs/cli-spec)
        _check_scope_name_conflicts(
            data,
            _skills_dir_for_scope("global" if scope == "global" else str(proj_root)),
            scope, proj_root, only_names)

        # 项目安装时检测同名全局 skill(全局盖项目,见 Docs/06 2.3)
        project_warns: list[str] = []
        if project:
            global_names = {s.name for s in state.list_skills("global")}
            for sk in data.get("skills", []):
                if sk["name"] in global_names:
                    project_warns.append(
                        f"[warn] 全局已存在同名 skill {sk['name']!r},"
                        f"全局会覆盖项目版(enterprise > personal > project)")

        plan = compute_plan(source, ref, sha, data, kit_dir)

        return StagedInstall(
            source=source, ref=ref, sha=sha, is_local_path=is_local_path,
            scope=scope, root=proj_root, tmp_root=tmp_root, kit_dir=kit_dir,
            kit_name=kit_name, data=data, plan=plan, lint_msgs=msgs,
            only_names=only_names, project_warns=project_warns,
        )
    except Exception:
        shutil.rmtree(tmp_root, ignore_errors=True)
        raise


def execute_install(staged: StagedInstall, *, no_enable: bool = False) -> Iterator[ProgressEvent]:
    """安装第二阶段:移入 store → 建 env → postinstall → registry → link。

    逐 yield ProgressEvent(供 CLI 打印 / Web SSE)。异常时回滚 store/env/registry
    残留并重抛;finally 清理临时 clone 目录。
    """
    kit = staged.kit_name
    data = staged.data
    store_target = config.store_dir() / kit
    env_dirs: list[Path] = []
    reg_added = False
    try:
        config.store_dir().mkdir(parents=True, exist_ok=True)
        shutil.move(str(staged.kit_dir), str(store_target))
        yield ProgressEvent("store", "done", f"已移入 store: {store_target}")

        envs = build_envs(data, store_target)
        env_dirs = [d for m in envs.values() for d in m.values()]
        yield ProgressEvent("env", "done",
                            f"已建 {len(env_dirs)} 个环境" if env_dirs else "无环境依赖(纯 prompt skill)")

        postinstall = data.get("postinstall") or []
        if postinstall:
            yield ProgressEvent("postinstall", "done", f"执行 {len(postinstall)} 个 postinstall 步骤")
            run_postinstall(postinstall, store_target, envs)

        registry.add_kit(kit, _registry_record(
            staged.source, staged.ref, staged.sha, data, store_target, envs,
            staged.scope, staged.root))
        reg_added = True
        yield ProgressEvent("registry", "done", "已写入 registry")

        if not no_enable:
            for sk in data.get("skills", []):
                if staged.only_names is not None and sk["name"] not in staged.only_names:
                    continue
                state.set_state(sk["name"], "enabled", staged.scope, kit=kit, root=staged.root)
            yield ProgressEvent("link", "done", "已启用 skill(新会话生效)")
        else:
            yield ProgressEvent("link", "done", "已安装(未启用,--no-enable)")

        used, limit = state.budget(staged.scope, staged.root)
        yield ProgressEvent("done", "done", f"清单预算: {used} / {limit} 字符")
    except Exception:
        shutil.rmtree(store_target, ignore_errors=True)
        for d in env_dirs:
            shutil.rmtree(d, ignore_errors=True)
        if reg_added and kit:
            registry.remove_kit(kit)
        raise
    finally:
        shutil.rmtree(staged.tmp_root, ignore_errors=True)


def install(source: str, *, ref: str | None = None, project: bool = False,
            no_enable: bool = False, only: str | None = None,
            assume_yes: bool = False, is_local_path: bool = False,
            root: Path | None = None) -> None:
    """CLI 的 add 流程:stage → 展示计划等确认 → execute。行为与拆分前一致。"""
    staged = stage_install(source, ref=ref, project=project, only=only,
                           is_local_path=is_local_path, root=root)
    try:
        for m in staged.lint_msgs:
            print(f"[{m.level}] {m.message}")
        if any(m.level == "error" for m in staged.lint_msgs):
            raise InstallError("lint 发现错误,已中止(未留下任何残留)")
        for w in staged.project_warns:
            print(w)
        print(render_plan(staged.plan))
        sys.stdout.flush()  # 确认前把计划刷出:uv/npm 子进程直接写 fd,绕过缓冲
        if not assume_yes:
            ans = input("继续安装? [y/N] ").strip().lower()
            if ans not in ("y", "yes"):
                raise InstallError("已取消安装")
        else:
            print("[warn] -y 已跳过确认。安装等于运行仓库作者代码,请自行确认来源可信。")
        sys.stdout.flush()

        for _ev in execute_install(staged, no_enable=no_enable):
            pass  # 中间进度不 print(uv/npm 子进程输出已直接透传)

        used, limit = state.budget(staged.scope, staged.root)
        print(f"已安装 {staged.kit_name} {staged.data.get('version', '')}")
        print(f"清单预算: {used} / {limit} 字符")
        print("提示:开关改动将在新会话生效。")
    except Exception:
        staged.cleanup()
        raise


# ---- remove ----

def _skills_dir_for_scope(scope_value: str) -> Path | None:
    if scope_value == "global":
        return config.claude_config_dir() / "skills"
    return Path(scope_value) / ".claude" / "skills"


def remove_kit(kit: str, keep_env: bool = False) -> None:
    """删 link → 删 env → 删 store → 清 registry 与 skillOverrides 残留。

    keep_env 同时保留用户填的环境变量值(~/.cckit/envs.json),便于 remove 后重装调试;
    否则连同 kit 级与各 skill 级的桶一起清掉。
    """
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

    # 清用户填的环境变量值(kit 级桶 + 该 kit 下所有 skill 级桶)
    if not keep_env:
        for scope_value in info.get("known_scopes", []):
            if scope_value == "global":
                state.remove_user_envs(kit, "global")
            else:
                state.remove_user_envs(kit, "project", root=Path(scope_value))
