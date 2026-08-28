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
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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


def _registry_meta(reg: dict, kit: str, name: str) -> tuple[str | None, dict[str, str]]:
    """返回 (version, envs: {runtime: env_dir});registry 无记录时返回 (None, {})。"""
    kit_info = reg.get("kits", {}).get(kit)
    if not kit_info:
        return None, {}
    for sk in kit_info.get("skills", []):
        if sk.get("name") == name:
            return kit_info.get("version"), (sk.get("envs") or {})
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
            if is_ln:
                target = entry.resolve()
                managed, kit = _resolve_managed(target, store)
                if managed:
                    # 按 (kit, name) 去重:同名 skill 不同 kit 各装一份时,
                    # 一个被 link 不能吞掉另一个未 link 的(见 M1)。
                    linked_managed.add((kit, name))
                    version, envs = _registry_meta(reg, kit, name)
                    env_ok = _env_status(envs)
                else:
                    kit, version, env_ok = None, None, None
            else:
                target = entry
                managed, kit, version, env_ok = False, None, None, None
            st = _derive_state(True, overrides.get(name))
            result.append(SkillState(name, kit, sc, st, managed, env_ok,
                                     _desc_chars(target), version))

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
                                         kit_info.get("version")))

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
                global_state = get_state(name, "global")
                if name in proj_ov:
                    st = _derive_state(True, proj_ov[name])
                    result.append(SkillState(name, kit_name, "project", st, True,
                                             env_ok,
                                             _desc_chars(store / kit_name / name),
                                             kit_info.get("version"), True,
                                             global_state, True))
                else:
                    result.append(SkillState(name, kit_name, "project", global_state,
                                             True, env_ok,
                                             _desc_chars(store / kit_name / name),
                                             kit_info.get("version"), True,
                                             global_state, False))

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
