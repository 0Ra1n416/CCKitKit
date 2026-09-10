"""cckit.state —— 唯一允许读写 skill 状态的模块。

CLI 与未来的 Web 都只走这里,不允许调用方直接碰文件系统或 settings.json
(Docs/09)。启用状态是派生的:现场扫 link + 读 settings.json 的
skillOverrides,不落库 —— CC 只读这两处,存了必然漂移。

写 settings.json 三条硬要求(Docs/09 / D-14):
  1. 文件锁 os.open(O_CREAT|O_EXCL)(含陈旧锁超时+mtime 清理)
  2. 原子替换(临时文件 + os.replace)
  3. 只改 skillOverrides 键,其余用户配置原样保留
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable, Literal

from . import config, link, manifest, projects, registry
from . import env as env_mod
from .errors import CckitError

Scope = Literal["global", "project"]
StateName = Literal["installed", "enabled", "name-only", "off"]

_LOCK_TIMEOUT = 10.0
_BUDGET_FRACTION_DEFAULT = 0.01


@dataclass
class SkillState:
    name: str
    kit: str | None                 # 非 cckit 管理时为 None
    scope: Scope
    state: StateName
    managed: bool                   # False = 用户手写或插件带的,只读
    env_ok: bool | None             # None = 该 skill 无需 env
    desc_chars: int                 # 用于预算统计
    version: str | None
    is_global_skill: bool = False   # project 作用域下,此条目是「全局 skill 的项目覆盖/跟随」
    global_state: str | None = None # 全局 skill 在全局作用域的状态(供项目覆盖决策)
    override: bool = False          # 全局 skill 是否带项目级覆盖(off/name-only)
    envs: list[dict] = field(default_factory=list)       # skill 级环境变量声明
    conf_files: list[str] = field(default_factory=list)  # 可改配置文件,相对 skill 根
    missing_env: list[str] = field(default_factory=list)  # 声明 required 却还没值的变量名


@dataclass
class EnvRequirement:
    """一条环境变量需求 + 它当前是否有着落。

    值来源优先 cckit 存储(~/.cckit/envs.json),没有则回落 os.environ。
    调用方(CLI / Web)自行决定是否回显 `value` —— 密钥类应面具化。
    """
    name: str
    level: str          # "kit"(kit_env 声明) | "skill"(skill 的 env 声明)
    required: bool
    description: str
    value: str | None   # 当前生效的值;None = 尚未设置


@dataclass
class ScopeEntry:
    path: str                       # "global" 或项目绝对路径
    source: str                     # "global" | "installed" | "watched"
    has_skills: bool


# ---- 路径与读取 ----

def _scope_skills_dir(scope: Scope, root: Path | None = None) -> Path | None:
    if scope == "global":
        return config.claude_config_dir() / "skills"
    r = root or config.project_root()
    if r is None:
        return None
    return r / ".claude" / "skills"


def _scope_settings_path(scope: Scope, root: Path | None = None) -> Path:
    if scope == "global":
        return config.claude_config_dir() / "settings.json"
    r = root or config.project_root()
    if r is None:
        raise CckitError("不在项目内(.claude / cckit.lock 均未找到),无法操作项目作用域")
    return r / ".claude" / "settings.local.json"


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise CckitError(f"{path} 不是合法 JSON,已损坏: {e}") from e
    if not isinstance(data, dict):
        raise CckitError(f"{path} 顶层不是 JSON object,已损坏")
    return data


def read_settings(scope: Scope = "global", root: Path | None = None) -> dict:
    """只读 settings 完整 dict。doctor / budget 读非 skillOverrides 键也走这里。"""
    return _read_json(_scope_settings_path(scope, root))


def _read_overrides(scope: Scope, root: Path | None = None) -> dict:
    ov = read_settings(scope, root).get("skillOverrides", {})
    return ov if isinstance(ov, dict) else {}


# ---- 锁与原子写 ----

def _acquire_lock(lock_path: Path, timeout: float = _LOCK_TIMEOUT) -> None:
    """跨平台文件锁:os.open(O_CREAT|O_EXCL)。陈旧锁按 mtime 超时后强制清理。"""
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                mtime = os.path.getmtime(lock_path)
            except OSError:
                continue  # 锁刚被删,重试
            if time.time() - mtime > timeout:
                # 陈旧锁:进程崩溃遗留
                try:
                    os.unlink(lock_path)
                except OSError:
                    pass
                continue
            if time.monotonic() > deadline:
                raise CckitError(f"等待文件锁超时(可能其他 cckit 卡住): {lock_path}")
            time.sleep(0.05)
            continue
        try:
            os.write(fd, str(os.getpid()).encode())
        finally:
            os.close(fd)
        return


def _release_lock(lock_path: Path) -> None:
    try:
        os.unlink(lock_path)
    except OSError:
        pass


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _write_override(scope: Scope, name: str, value: str | None,
                    root: Path | None = None) -> None:
    """锁 + 原子写 + 只改 skillOverrides。value=None 表示删除该键。"""
    path = _scope_settings_path(scope, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".cckit.lock")
    _acquire_lock(lock_path)
    try:
        data = _read_json(path)
        overrides = data.get("skillOverrides", {})
        overrides = overrides if isinstance(overrides, dict) else {}
        if value is None:
            overrides.pop(name, None)
        else:
            overrides[name] = value
        if overrides:
            data["skillOverrides"] = overrides
        else:
            data.pop("skillOverrides", None)
        _atomic_write_json(path, data)
    finally:
        _release_lock(lock_path)


def remove_overrides(names: list[str], scope: Scope = "global",
                     root: Path | None = None) -> None:
    """批量清掉若干 skill 的 skillOverrides 条目(供 remove 清理残留)。"""
    path = _scope_settings_path(scope, root=root)
    if not path.exists():
        return
    lock_path = path.with_name(path.name + ".cckit.lock")
    _acquire_lock(lock_path)
    try:
        data = _read_json(path)
        overrides = data.get("skillOverrides", {})
        if isinstance(overrides, dict):
            for n in names:
                overrides.pop(n, None)
            if overrides:
                data["skillOverrides"] = overrides
            else:
                data.pop("skillOverrides", None)
        _atomic_write_json(path, data)
    finally:
        _release_lock(lock_path)


# ---- 用户填写的环境变量(envs.json) ----
#
# 与 envs/ 目录(每 skill 一个 venv)**无关**:这里存的是"环境变量名 → 值"。
# 刻意不写 Claude Code 的 settings.json —— 那会把用户的 model/env/permissions
# 一起卷进写入路径(见 TODO 决策 D-3.7)。改由 `cckit exec` 注入。
#
# 分桶键:{作用域}|{kit}[|{skill}]。作用域为 "global" 或项目根绝对路径,
# 与 registry 的 known_scopes 表示一致。按 (kit, skill) 分桶意味着**不需要**
# 变量引用计数:删一个 skill 只删它自己那份,不会波及别的 skill。

_KIT_ENV_BUCKET = "kit_env"
_SKILL_ENV_BUCKET = "skill_env"


def _scope_key(scope: Scope, root: Path | None = None) -> str:
    """envs.json 的分桶前缀:全局为 "global",项目为项目根的绝对路径。"""
    if scope == "global":
        return "global"
    r = root or config.project_root()
    if r is None:
        raise CckitError("不在项目内,无法定位项目作用域的环境变量")
    return str(r)


def _env_bucket_key(scope: Scope, kit: str, skill: str | None = None,
                    root: Path | None = None) -> str:
    """桶键:{作用域}|{kit}[|{skill}]。"""
    key = f"{_scope_key(scope, root)}|{kit}"
    return f"{key}|{skill}" if skill else key


def read_user_envs() -> dict:
    """读整个 envs.json。不存在返回空;损坏时抛受检 CckitError。"""
    return _read_json(config.user_envs_path())


def _mutate_user_envs(mutate: Callable[[dict], None]) -> None:
    """读—改—写全程持锁 + 原子替换,与写 settings.json 同一套纪律(D-14)。"""
    path = config.user_envs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".cckit.lock")
    _acquire_lock(lock_path)
    try:
        data = _read_json(path)
        data.setdefault("version", 1)
        mutate(data)
        _atomic_write_json(path, data)
    finally:
        _release_lock(lock_path)


def set_user_env(name: str, value: str | None, *, kit: str,
                 skill: str | None = None, scope: Scope = "global",
                 root: Path | None = None) -> None:
    """记录用户填的环境变量值。value=None 表示删掉该条目。

    skill=None 写 kit 级桶(kit_env 声明的值);否则写 skill 级桶。
    条目清空后顺手删掉空桶,不给文件留残渣。
    """
    bucket = _SKILL_ENV_BUCKET if skill else _KIT_ENV_BUCKET
    key = _env_bucket_key(scope, kit, skill, root)

    def mutate(data: dict) -> None:
        section = data.setdefault(bucket, {})
        entries = section.setdefault(key, {})
        if value is None:
            entries.pop(name, None)
            if not entries:
                section.pop(key, None)
        else:
            entries[name] = value
        if not section:
            data.pop(bucket, None)

    _mutate_user_envs(mutate)


def remove_user_envs(kit: str, scope: Scope = "global", *,
                     skill: str | None = None, root: Path | None = None) -> None:
    """删掉某个 kit(或它下面某个 skill)在该作用域下的用户值。

    skill=None 时清 kit 级桶 + 该 kit 的全部 skill 级桶(卸载整个 kit 用)。
    """
    prefix = f"{_scope_key(scope, root)}|{kit}"
    only = f"{prefix}|{skill}" if skill else None

    def matches(key: str) -> bool:
        if only is not None:
            return key == only
        return key == prefix or key.startswith(prefix + "|")

    def mutate(data: dict) -> None:
        for bucket in (_KIT_ENV_BUCKET, _SKILL_ENV_BUCKET):
            section = data.get(bucket)
            if not isinstance(section, dict):
                continue
            for key in [k for k in section if matches(k)]:
                section.pop(key, None)
            if not section:
                data.pop(bucket, None)

    _mutate_user_envs(mutate)


def _env_values(user_envs: dict, scope: Scope, kit: str, skill: str | None = None,
                root: Path | None = None) -> dict[str, str]:
    """从**已读入**的 envs.json 里取值:kit 级为底,skill 级覆盖。

    与 `stored_env` 分开,是因为 `list_skills` 要读一次文件给几十个 skill 复用,
    不能每个 skill 都去读一遍 envs.json。
    """
    values = dict((user_envs.get(_KIT_ENV_BUCKET) or {}).get(
        _env_bucket_key(scope, kit, None, root)) or {})
    if skill:
        values.update((user_envs.get(_SKILL_ENV_BUCKET) or {}).get(
            _env_bucket_key(scope, kit, skill, root)) or {})
    return values


def stored_env(scope: Scope, kit: str, skill: str | None = None,
               root: Path | None = None) -> dict[str, str]:
    """该 skill 生效的 cckit 存储值:kit 级为底,skill 级覆盖。"""
    return _env_values(read_user_envs(), scope, kit, skill, root)


def missing_required_env(kit_info: dict, skill_rec: dict,
                         values: dict[str, str]) -> list[str]:
    """声明了 `required: true`、却到现在还没有值的变量名。

    判定口径与 `cckit exec` 注入时一致:
      - `kit_env` 是 kit 级共用,对 kit 下**每个** skill 都算数;
      - 同名变量 skill 级声明覆盖 kit 级(与 `env_requirements` 的取舍相同);
      - 值先看 cckit 存储,再看调用方的进程环境。
    """
    skill_decls = list(skill_rec.get("env") or [])
    overridden = {d.get("name") for d in skill_decls if d.get("name")}
    decls = [d for d in (kit_info.get("kit_env") or [])
             if d.get("name") not in overridden] + skill_decls

    missing: list[str] = []
    seen: set[str] = set()
    for decl in decls:
        name = decl.get("name")
        if not name or name in seen:
            continue
        seen.add(name)
        if not decl.get("required"):
            continue
        if not values.get(name) and not os.environ.get(name):
            missing.append(name)
    return missing


def env_scope_of(s: SkillState) -> Scope:
    """该条目环境变量值所在的作用域。

    全局 skill 罗列在项目作用域时(D-15),它的值仍在全局桶里 —— 跟随的是
    skill 本身装在哪,而不是当前在看哪个作用域。
    """
    return "global" if s.is_global_skill else s.scope


def _registry_skill(kit: str, skill: str) -> dict:
    """registry 里该 skill 的快照记录;没有则空 dict。"""
    info = registry.get_kit(kit) or {}
    return next((s for s in info.get("skills", []) if s.get("name") == skill), {}) or {}


def skill_store_dir(kit: str, skill: str) -> Path:
    """skill 在 store 里的目录,conf_files 的相对路径以它为根。"""
    info = registry.get_kit(kit)
    if not info:
        raise CckitError(f"kit {kit!r} 不在 registry 中")
    return Path(info["store"]) / skill


def conf_files(kit: str, skill: str) -> list[str]:
    """该 skill 声明可改的配置文件(相对 skill 根)。"""
    return list(_registry_skill(kit, skill).get("conf_files") or [])


def env_requirements(kit: str, skill: str | None, scope: Scope = "global",
                     root: Path | None = None) -> list[EnvRequirement]:
    """列出 kit(或某个 skill)声明的环境变量,以及当前取值。

    声明取自 registry 快照(D-3.9),不现场读 manifest。
    同一个变量在 kit_env 与 skill 的 env 里都出现时,只保留 skill 那条
    (skill 级覆盖 kit 级),避免同一变量列两行。
    """
    info = registry.get_kit(kit)
    if info is None:
        return []
    skill_decls: list[dict] = []
    if skill:
        skill_decls = _registry_skill(kit, skill).get("env") or []
    overridden = {d.get("name") for d in skill_decls if d.get("name")}
    values = stored_env(scope, kit, skill, root)

    out: list[EnvRequirement] = []
    for level, decls in (("kit", info.get("kit_env") or []), ("skill", skill_decls)):
        for decl in decls:
            name = decl.get("name")
            if not name or (level == "kit" and name in overridden):
                continue
            out.append(EnvRequirement(
                name=name,
                level=level,
                required=bool(decl.get("required")),
                description=str(decl.get("description") or ""),
                value=values.get(name) or os.environ.get(name) or None,
            ))
    return out


# ---- 可修改的配置文件(conf_files) ----
#
# 文件就在 skill 目录里(store/<kit>/<skill>/<相对路径>)。CLI 与 Web 都只走这几个
# 函数读写 —— Web 端点绝不能自己拼路径,否则"保存配置"会变成任意文件写入。

_CONF_MAX_BYTES = 256 * 1024


def ensure_config_editable(scope: Scope, root: Path | None, kit: str,
                           skill: str | None) -> None:
    """禁止改 installed 态 skill 的配置(UI 禁用了,服务端也要拦)。

    skill=None 表示 kit 级(kit_env 的值),只要 kit 在 registry 里即可。

    非 cckit 管理的 skill(用户手写 / 插件带的)在 `list_skills` 里 `kit` 恒为 None,
    因此按 (kit, skill) 定位永远匹配不到它们 —— 这类 skill 压根无法被本端点寻址,
    不需要额外的 managed 判断(判了也是死代码)。
    """
    if skill is None:
        if registry.get_kit(kit) is None:
            raise CckitError(f"kit {kit!r} 不在 registry 中")
        return
    item = next((s for s in list_skills(scope, root)
                 if s.kit == kit and s.name == skill), None)
    if item is None:
        raise CckitError(f"skill {skill!r} 不在 kit {kit!r} 中(或不在当前作用域)")
    if item.state == "installed":
        raise CckitError(f"skill {skill!r} 尚未启用(installed 态),不能修改配置")


def resolve_conf_path(kit: str, skill: str, rel: str) -> Path:
    """把 conf_files 里的相对路径解析成绝对路径,并确认它落在 skill 目录内。

    两道闸:① 必须**逐字命中** registry 快照里的声明(客户端传来的路径一律不可信);
    ② 解析后仍要在 skill 目录内(防 `..` 与符号链接逃逸)。
    """
    declared = conf_files(kit, skill)
    norm = str(PurePosixPath(rel.replace("\\", "/")))
    if norm not in declared:
        raise CckitError(f"{rel!r} 不在 {skill!r} 声明的 conf_files 里")

    skill_dir = skill_store_dir(kit, skill)
    target = (skill_dir / norm).resolve()
    try:
        target.relative_to(skill_dir.resolve())
    except ValueError:
        raise CckitError(f"配置文件路径越出 skill 目录: {rel}")
    return target


def read_conf_file(kit: str, skill: str, rel: str) -> str:
    """读一个可修改的配置文件。只支持 UTF-8 文本,且限制体积。"""
    target = resolve_conf_path(kit, skill, rel)
    if not target.is_file():
        raise CckitError(f"配置文件不存在: {rel}")
    if target.stat().st_size > _CONF_MAX_BYTES:
        raise CckitError(
            f"配置文件过大({target.stat().st_size} 字节),超过 "
            f"{_CONF_MAX_BYTES} 字节上限,请在编辑器里打开")
    try:
        return target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise CckitError(f"{rel} 不是 UTF-8 文本,无法在这里编辑")


def write_conf_file(kit: str, skill: str, rel: str, content: str) -> None:
    """写回一个可修改的配置文件(临时文件 + 原子替换,避免写坏用户的配置)。"""
    target = resolve_conf_path(kit, skill, rel)
    if len(content.encode("utf-8")) > _CONF_MAX_BYTES:
        raise CckitError(f"内容过大,超过 {_CONF_MAX_BYTES} 字节上限")
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix="." + target.name + ".",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ---- 派生状态 ----

def _derive_state(has_link: bool, override: str | None) -> str:
    if not has_link:
        return "installed"
    if override == "off":
        return "off"
    if override == "name-only":
        return "name-only"
    return "enabled"


def _resolve_managed(target: Path, store: Path) -> tuple[bool, str | None]:
    """target 是否落在 store 内;是则返回 (True, kit 名)。"""
    try:
        rel = target.relative_to(store)
    except ValueError:
        return False, None
    if len(rel.parts) < 2:
        return False, None
    return True, rel.parts[0]


def resolve_managed_kit(target: Path) -> str | None:
    """target 是否落在 store 内;是则返回 kit 名,否则 None。doctor 复用。"""
    managed, kit = _resolve_managed(target, config.store_dir())
    return kit if managed else None


def scope_skills_dirs() -> list[tuple[Scope, Path]]:
    """所有可能存在 link 的 skills 目录(含 known_scopes 里的历史项目目录)。

    doctor 用它枚举 link、remove 用它清理残留。与 list_skills 共用同一份
    作用域解析逻辑,避免两套扫描漂移(见 Docs/09:状态读写统一走 state)。
    """
    dirs: list[tuple[Scope, Path]] = []
    dirs.append(("global", config.claude_config_dir() / "skills"))
    root = config.project_root()
    if root:
        dirs.append(("project", root / ".claude" / "skills"))
    for kit_info in registry.load().get("kits", {}).values():
        for sc in kit_info.get("known_scopes", []):
            if sc and sc != "global":
                dirs.append(("project", Path(sc) / ".claude" / "skills"))
    return dirs


def _registry_meta(reg: dict, kit: str, name: str) -> tuple[str | None, dict]:
    """返回 (version, skill 快照记录);registry 无该 skill 时记录为 {}。

    注意记录里 `envs`(运行时→venv 目录)与 `env`(环境变量声明)是两回事。
    """
    kit_info = reg.get("kits", {}).get(kit)
    if not kit_info:
        return None, {}
    for sk in kit_info.get("skills", []):
        if sk.get("name") == name:
            return kit_info.get("version"), sk
    return kit_info.get("version"), {}


def _env_status(envs: dict[str, str]) -> bool | None:
    """所有已建 env 都健康才 True;无 env(纯 prompt)为 None;任一损坏为 False。"""
    if not envs:
        return None
    return all(env_mod.check_env(Path(d), rt) for rt, d in envs.items())


def _desc_chars(skill_dir: Path) -> int:
    fm = manifest.read_skill_frontmatter(skill_dir)
    d = str(fm.get("description") or "")
    w = str(fm.get("when_to_use") or "")
    return len(d) + len(w)


# ---- 对外 API ----

def list_skills(scope: Scope | None = None, root: Path | None = None) -> list[SkillState]:
    """列出 skill。scope=None 列出全部作用域。

    同时列出非 cckit 管理的 skill(managed=False,只读)。
    启用状态现场从 link + skillOverrides 派生,不读任何落库的启用状态。
    root 显式指定 project 作用域的项目根(Web 侧栏选中任意项目);scope 为
    project/None 且 root 缺省时回落 config.project_root()(cwd,CLI 行为不变)。
    """
    reg = registry.load()
    store = config.store_dir()
    # 一次读入,给下面几十个 skill 复用(不能每个 skill 读一遍 envs.json)
    user_envs = read_user_envs()
    scopes: list[Scope] = ["global", "project"] if scope is None else [scope]
    result: list[SkillState] = []
    linked_managed: set[tuple[str, str]] = set()

    for sc in scopes:
        skills_dir = _scope_skills_dir(sc, root)
        if skills_dir is None or not skills_dir.is_dir():
            continue
        overrides = _read_overrides(sc, root)
        for entry in sorted(skills_dir.iterdir()):
            name = entry.name
            if name == "synced":
                continue
            is_ln = link.is_link(entry) or link.is_dangling(entry)
            if not is_ln and not entry.is_dir():
                continue
            decl_env: list[dict] = []
            decl_conf: list[str] = []
            decl_missing: list[str] = []
            if is_ln:
                target = entry.resolve()
                managed, kit = _resolve_managed(target, store)
                if managed:
                    # 按 (kit, name) 去重:同名 skill 不同 kit 各装一份时,
                    # 一个被 link 不能吞掉另一个未 link 的(见 M1)。
                    linked_managed.add((kit, name))
                    version, rec = _registry_meta(reg, kit, name)
                    env_ok = _env_status(rec.get("envs") or {})
                    decl_env = list(rec.get("env") or [])
                    decl_conf = list(rec.get("conf_files") or [])
                    decl_missing = missing_required_env(
                        reg.get("kits", {}).get(kit, {}), rec,
                        _env_values(user_envs, sc, kit, name, root))
                else:
                    kit, version, env_ok = None, None, None
            else:
                target = entry
                managed, kit, version, env_ok = False, None, None, None
            st = _derive_state(True, overrides.get(name))
            result.append(SkillState(name, kit, sc, st, managed, env_ok,
                                     _desc_chars(target), version,
                                     envs=decl_env, conf_files=decl_conf,
                                     missing_env=decl_missing))

    # 已安装但未建 link 的 managed skill → installed。归属作用域由 kit 的
    # known_scopes 决定,不硬编码 "global"(项目 kit 的未 link skill 应报 project)。
    proj_root = root or config.project_root()
    for kit_name, kit_info in reg.get("kits", {}).items():
        known = kit_info.get("known_scopes") or []
        for sk in kit_info.get("skills", []):
            name = sk.get("name")
            if not name or (kit_name, name) in linked_managed:
                continue
            for sc in scopes:
                in_scope = ("global" in known) if sc == "global" else (
                    proj_root is not None and str(proj_root) in known)
                if not in_scope:
                    continue
                env_ok = _env_status(sk.get("envs") or {})
                result.append(SkillState(name, kit_name, sc, "installed", True,
                                         env_ok, _desc_chars(store / kit_name / name),
                                         kit_info.get("version"),
                                         envs=list(sk.get("env") or []),
                                         conf_files=list(sk.get("conf_files") or []),
                                         missing_env=missing_required_env(
                                             kit_info, sk,
                                             _env_values(user_envs, sc, kit_name,
                                                         name, root))))

    # 全局 kit 的 skill 在项目作用域:列出所有全局 skill(D-15)。
    # 有效状态 = 项目级覆盖(off/name-only)若有;否则跟随全局状态。
    # 注意:project skill 若有同名全局 skill,覆盖是写给项目 kit 的(见 set_state
    # 的定位顺序),不能误归属到全局 kit。故这里只对"项目作用域无同名 kit"的
    # 全局 skill 补项目级条目。
    if (scope is None or scope == "project") and proj_root is not None:
        proj_ov = _read_overrides("project", root)
        project_kit_names = {
            sk.get("name")
            for kit_info in reg.get("kits", {}).values()
            if registry._kit_in_scope(kit_info, "project", root)
            for sk in kit_info.get("skills", [])
            if sk.get("name")
        }
        for kit_name, kit_info in reg.get("kits", {}).items():
            known = kit_info.get("known_scopes") or []
            if "global" not in known:
                continue  # 只有全局 kit 有"项目级覆盖"语义
            for sk in kit_info.get("skills", []):
                name = sk.get("name")
                if not name:
                    continue
                if name in project_kit_names:
                    continue  # 同名项目 kit 存在,覆盖归属项目 kit,不补全局条目
                env_ok = _env_status(sk.get("envs") or {})
                # 这些是全局 skill 在项目作用域的视图:它的值存在**全局**桶里(D-15)
                extra = {"envs": list(sk.get("env") or []),
                         "conf_files": list(sk.get("conf_files") or []),
                         "missing_env": missing_required_env(
                             kit_info, sk,
                             _env_values(user_envs, "global", kit_name, name))}
                global_state = get_state(name, "global")
                if name in proj_ov:
                    st = _derive_state(True, proj_ov[name])
                    result.append(SkillState(name, kit_name, "project", st, True,
                                             env_ok,
                                             _desc_chars(store / kit_name / name),
                                             kit_info.get("version"), True,
                                             global_state, True, **extra))
                else:
                    result.append(SkillState(name, kit_name, "project", global_state,
                                             True, env_ok,
                                             _desc_chars(store / kit_name / name),
                                             kit_info.get("version"), True,
                                             global_state, False, **extra))

    return result


def get_state(name: str, scope: Scope = "global", root: Path | None = None) -> str:
    """返回 skill 在指定作用域的当前状态。

    项目作用域下,全局 skill 可能没有项目 link,只有 settings.local.json 的
    覆盖(off/name-only/on);此时按覆盖推导,而不是一律报 installed。
    """
    skills_dir = _scope_skills_dir(scope, root)
    link_path = skills_dir / name if skills_dir else None
    has_link = bool(link_path and (link.is_link(link_path) or link.is_dangling(link_path)))
    if has_link:
        return _derive_state(True, _read_overrides(scope, root).get(name))
    if scope == "project" and skills_dir is not None:
        ov = _read_overrides("project", root).get(name)
        if ov is not None:
            return _derive_state(True, ov)
    return "installed"


_STATE_TO_OVERRIDE = {"enabled": "on", "name-only": "name-only", "off": "off"}


def _kit_is_global(kit_name: str) -> bool:
    """kit 是否装在全局作用域(known_scopes 含 "global")。"""
    info = registry.get_kit(kit_name)
    return bool(info) and "global" in (info.get("known_scopes") or [])


def _resolve_for_project(name: str, root: Path | None = None) -> tuple[str, bool]:
    """项目作用域定位 skill 的 kit:先项目后全局。返回 (kit_name, is_global_kit)。

    项目作用域装过 → 项目 kit(is_global=False);没装但全局有 → 全局 kit
    (is_global=True);两处都没有或同名歧义 → 报错。
    """
    matches = registry.find_skill_matches(name, "project", root)
    if len(matches) > 1:
        kits = ", ".join(k for k, _ in matches)
        raise CckitError(f"skill {name!r} 在多个 kit 中出现({kits}),无法唯一定位")
    if matches:
        return matches[0][0], False
    gmatches = registry.find_skill_matches(name, "global", root)
    if len(gmatches) > 1:
        kits = ", ".join(k for k, _ in gmatches)
        raise CckitError(f"skill {name!r} 在多个 kit 中出现({kits}),无法唯一定位")
    if not gmatches:
        raise CckitError(f"skill {name!r} 不在 registry 中(project 作用域)(不是 cckit 管理或未安装)")
    return gmatches[0][0], True


def set_state(name: str, state: StateName, scope: Scope = "global",
              kit: str | None = None, root: Path | None = None) -> None | str:
    """把 skill 切到四态之一。enabled/name-only/off 需要 link;installed 删 link。

    kit 缺省时按 skill 名在 registry 里唯一查找;多个 kit 同名时报错。
    add 流程知道确切的 kit,应显式传 kit 避免同名歧义。

    特例(D-15):全局 kit 的 skill 在项目作用域开关时,不建/不删项目 link ——
    off/name-only 只写 settings.local.json 的 skillOverrides,并把项目根记入
    override_scopes;enabled 清掉项目覆盖=跟随全局(返回同步提示)。三个例外会报错:
    全局 installed 时 enable/name-only --project(没有"只在项目里启用"的概念)、
    全局 off 时 name-only --project、installed --project(即 disable --purge
    --project,无项目 link 可删)。
    全局作用域 purge 时,同时清掉该 skill 在各项目根的项目级覆盖,避免孤儿覆盖。
    """
    if state not in ("installed", "enabled", "name-only", "off"):
        raise CckitError(f"未知状态 {state!r}")
    if kit is not None:
        kit_name = kit
        is_global_kit = _kit_is_global(kit_name)
    elif scope == "project":
        kit_name, is_global_kit = _resolve_for_project(name, root)
    else:
        kit_name, _ = registry.find_skill(name, scope)
        is_global_kit = True

    if scope == "project" and is_global_kit:
        if (state == "enabled" or state == "name-only") and get_state(name, "global") == "installed":
            # 全局 skill installed时，没有"只在项目里启用"的概念:它在项目里可不可见只取决于全局
            # 有没有 link。这里不能静默当成"清掉项目覆盖"成功返回(没有覆盖时是纯
            # no-op,会误导用户),直接给出正确做法。
            raise CckitError(
                f"{name} 是全局 skill，请去掉 --project 在全局启用，"
                f"如需只安装到项目，请 remove 后重新 add"
            )
        if state == "name-only" and get_state(name, "global") == "off":
            raise CckitError(
                f"{name} 目前在全局作用域是 off 状态，无法在项目作用域设置为 name-only。"
            )
        if state == "installed":
            # disable <name> --purge --project 指令不允许操作全局 skill 的 link。
            raise CckitError(
                f"{name} 是全局 skill，无法在项目作用域删除 link。"
                "如需在项目作用域禁用，请使用 disable <name> --project。"
                "如需解除全局link，请去掉 --project 在全局作用域执行 disable <name> --purge。"
            )
        # 全局 skill 的项目级覆盖:不碰 link,只写 settings.local.json 的
        # skillOverrides。off/name-only 写覆盖并记入 override_scopes;
        value = _STATE_TO_OVERRIDE[state] if state in ("off", "name-only") else None
        _write_override("project", name, value, root)
        if value is not None:
            proj_root = root or config.project_root()
            if proj_root is not None:
                registry.add_override_scope(kit_name, str(proj_root))
        else:
            # 其他enable --project 代表"清掉项目覆盖、回到跟随全局",不建 link,不报错,直接返回。
            return f"{name} 在项目作用域已与全局同步({get_state(name, 'global')}),新会话生效"
        return

    target = config.store_dir() / kit_name / name
    skills_dir = _scope_skills_dir(scope, root)
    if skills_dir is None:
        raise CckitError("无法确定作用域 skills 目录(项目作用域需在项目内)")
    link_path = skills_dir / name

    if state == "installed":
        if link.is_link(link_path) or link.is_dangling(link_path):
            link.remove(link_path)
        _write_override(scope, name, None, root)
        if scope == "global":
            # 全局 purge 同时清掉该 skill 在各项目根的项目级覆盖,避免孤儿覆盖(见 D-15)。
            info = registry.get_kit(kit_name)
            for scope_value in (info or {}).get("override_scopes") or []:
                if scope_value and scope_value != "global":
                    remove_overrides([name], "project", root=Path(scope_value))
        return

    if not target.is_dir():
        raise CckitError(f"store 目标不存在(可能被手动删除): {target}")
    if link.is_link(link_path):
        pass
    elif link_path.exists():
        raise CckitError(f"{link_path} 已存在且是真实目录(用户手写 skill),拒绝覆盖")
    else:
        link.create(target, link_path)
    _write_override(scope, name, _STATE_TO_OVERRIDE[state], root)
    return


def budget(scope: Scope | None = None, root: Path | None = None) -> tuple[int, int]:
    """清单预算:(已用字符, 上限)。

    scope 缺省(None)统计全部作用域;`list --project` 传 "project" 只算项目。
    root 显式指定 project 作用域的项目根(与 list_skills 语义一致)。
    上限 = 缺省 config.DEFAULT_BUDGET_LIMIT_CHARS 字符 × skillListingBudgetFraction / 0.01。
    只统计 enabled 态的 skill —— name-only / off / installed 的 description
    不进上下文,不占预算。
    """
    used = sum(
        s.desc_chars
        for s in list_skills(scope, root)
        if s.state == "enabled" and not s.is_global_skill
    )
    settings = read_settings("global")
    fraction = settings.get("skillListingBudgetFraction", _BUDGET_FRACTION_DEFAULT)
    try:
        fraction = float(fraction)
    except (TypeError, ValueError):
        fraction = _BUDGET_FRACTION_DEFAULT
    if fraction <= 0:
        fraction = _BUDGET_FRACTION_DEFAULT
    limit = int(config.DEFAULT_BUDGET_LIMIT_CHARS * fraction / _BUDGET_FRACTION_DEFAULT)
    return used, limit


def list_scopes() -> list[ScopeEntry]:
    """返回侧栏作用域清单:全局 + registry 历史项目 + 关注项目(去重)。

    source 语义:
      - "global": 全局作用域(固定一条)
      - "installed": 曾在某项目根装过/覆盖过的历史项目(registry 的
        known_scopes + override_scopes)
      - "watched": 用户在 projects.json 里持续关注的项目(可能无 skill)
    has_skills 用 list_skills 现场派生(该作用域下是否有任何 skill)。
    """
    entries: list[ScopeEntry] = []
    seen: set[str] = {"global"}
    entries.append(ScopeEntry("global", "global", bool(list_skills("global"))))

    reg = registry.load()
    reg_projects: set[str] = set()
    for kit_info in reg.get("kits", {}).values():
        for key in ("known_scopes", "override_scopes"):
            for sc in kit_info.get(key) or []:
                if sc and sc != "global":
                    reg_projects.add(str(sc))

    watched = projects.load()

    for p in sorted(reg_projects):
        if p not in seen:
            seen.add(p)
            entries.append(ScopeEntry(p, "installed", bool(list_skills("project", Path(p)))))
    for p in sorted(watched):
        if p not in seen:
            seen.add(p)
            entries.append(ScopeEntry(p, "watched", bool(list_skills("project", Path(p)))))

    return entries
