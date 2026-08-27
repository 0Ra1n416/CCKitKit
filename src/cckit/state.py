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

from . import config, link, manifest, registry
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


# ---- 路径与读取 ----

def _scope_skills_dir(scope: Scope) -> Path | None:
    if scope == "global":
        return config.claude_config_dir() / "skills"
    root = config.project_root()
    if root is None:
        return None
    return root / ".claude" / "skills"


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


def read_settings(scope: Scope = "global") -> dict:
    """只读 settings 完整 dict。doctor / budget 读非 skillOverrides 键也走这里。"""
    return _read_json(_scope_settings_path(scope))


def _read_overrides(scope: Scope) -> dict:
    ov = read_settings(scope).get("skillOverrides", {})
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


def _write_override(scope: Scope, name: str, value: str | None) -> None:
    """锁 + 原子写 + 只改 skillOverrides。value=None 表示删除该键。"""
    path = _scope_settings_path(scope)
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


def _registry_meta(reg: dict, kit: str, name: str) -> tuple[str | None, str | None, str | None]:
    """返回 (version, env_dir, runtime);registry 无记录时返回 (None, None, None)。"""
    kit_info = reg.get("kits", {}).get(kit)
    if not kit_info:
        return None, None, None
    for sk in kit_info.get("skills", []):
        if sk.get("name") == name:
            return kit_info.get("version"), sk.get("env"), sk.get("runtime")
    return kit_info.get("version"), None, None


def _env_status(env_dir: str | None, runtime: str | None) -> bool | None:
    if runtime is None:
        return None
    if not env_dir:
        return False
    return env_mod.check_env(Path(env_dir), runtime)


def _desc_chars(skill_dir: Path) -> int:
    fm = manifest.read_skill_frontmatter(skill_dir)
    d = str(fm.get("description") or "")
    w = str(fm.get("when_to_use") or "")
    return len(d) + len(w)


# ---- 对外 API ----

def list_skills(scope: Scope | None = None) -> list[SkillState]:
    """列出 skill。scope=None 列出全部作用域。

    同时列出非 cckit 管理的 skill(managed=False,只读)。
    启用状态现场从 link + skillOverrides 派生,不读任何落库的启用状态。
    """
    reg = registry.load()
    store = config.store_dir()
    scopes: list[Scope] = ["global", "project"] if scope is None else [scope]
    result: list[SkillState] = []
    linked_managed: set[tuple[str, str]] = set()

    for sc in scopes:
        skills_dir = _scope_skills_dir(sc)
        if skills_dir is None or not skills_dir.is_dir():
            continue
        overrides = _read_overrides(sc)
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
                    version, env_dir, runtime = _registry_meta(reg, kit, name)
                    env_ok = _env_status(env_dir, runtime)
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
    root = config.project_root()
    for kit_name, kit_info in reg.get("kits", {}).items():
        known = kit_info.get("known_scopes") or []
        for sk in kit_info.get("skills", []):
            name = sk.get("name")
            if not name or (kit_name, name) in linked_managed:
                continue
            for sc in scopes:
                in_scope = ("global" in known) if sc == "global" else (
                    root is not None and str(root) in known)
                if not in_scope:
                    continue
                env_ok = _env_status(sk.get("env"), sk.get("runtime"))
                result.append(SkillState(name, kit_name, sc, "installed", True,
                                         env_ok, _desc_chars(store / kit_name / name),
                                         kit_info.get("version")))

    return result


def get_state(name: str, scope: Scope = "global") -> str:
    """返回 skill 在指定作用域的当前状态。"""
    skills_dir = _scope_skills_dir(scope)
    link_path = skills_dir / name if skills_dir else None
    has_link = bool(link_path and (link.is_link(link_path) or link.is_dangling(link_path)))
    if not has_link:
        return "installed"
    ov = _read_overrides(scope).get(name)
    return _derive_state(True, ov)


_STATE_TO_OVERRIDE = {"enabled": "on", "name-only": "name-only", "off": "off"}


def set_state(name: str, state: StateName, scope: Scope = "global",
              kit: str | None = None) -> None:
    """把 skill 切到四态之一。enabled/name-only/off 需要 link;installed 删 link。

    kit 缺省时按 skill 名在 registry 里唯一查找;多个 kit 同名时报错。
    add 流程知道确切的 kit,应显式传 kit 避免同名歧义。
    """
    if state not in ("installed", "enabled", "name-only", "off"):
        raise CckitError(f"未知状态 {state!r}")
    if kit is not None:
        kit_name = kit
    else:
        # 按作用域定位 kit:同名 skill 全局/项目各装一份时,靠 scope 消歧。
        kit_name, _ = registry.find_skill(name, scope)
    target = config.store_dir() / kit_name / name
    skills_dir = _scope_skills_dir(scope)
    if skills_dir is None:
        raise CckitError("无法确定作用域 skills 目录(项目作用域需在项目内)")
    link_path = skills_dir / name

    if state == "installed":
        if link.is_link(link_path) or link.is_dangling(link_path):
            link.remove(link_path)
        _write_override(scope, name, None)
        return

    if not target.is_dir():
        raise CckitError(f"store 目标不存在(可能被手动删除): {target}")
    if link.is_link(link_path):
        pass
    elif link_path.exists():
        raise CckitError(f"{link_path} 已存在且是真实目录(用户手写 skill),拒绝覆盖")
    else:
        link.create(target, link_path)
    _write_override(scope, name, _STATE_TO_OVERRIDE[state])


def budget(scope: Scope | None = None) -> tuple[int, int]:
    """清单预算:(已用字符, 上限)。

    scope 缺省(None)统计全部作用域;`list --project` 传 "project" 只算项目。
    上限 = 缺省 config.DEFAULT_BUDGET_LIMIT_CHARS 字符 × skillListingBudgetFraction / 0.01。
    只统计 enabled 态的 skill —— name-only / off / installed 的 description
    不进上下文,不占预算。
    """
    used = sum(s.desc_chars for s in list_skills(scope) if s.state == "enabled")
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
