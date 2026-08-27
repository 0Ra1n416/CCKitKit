"""registry.json 的读写。

registry 只存"从文件系统观测不出来"的东西:kit 来源(URL/ref/sha)、版本、
envs 路径映射(每个 skill 的 runtime → env_dir)、known_scopes。启用状态是派生的,不写这里(见 state.py)。
写入必须原子(临时文件 + os.replace),避免半截 JSON。
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from . import config
from .errors import CckitError


def load() -> dict:
    """读 registry;不存在时返回空结构;损坏时抛受检 CckitError(不静默、不裸 traceback)。"""
    path = config.registry_path()
    if not path.exists():
        return {"version": 1, "kits": {}}
    with open(path, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            raise CckitError(f"registry.json 不是合法 JSON,已损坏: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("kits"), dict):
        raise CckitError(f"registry.json 结构损坏: {path}")
    data.setdefault("version", 1)
    return data


def save(data: dict) -> None:
    """原子写:临时文件 + os.replace。"""
    path = config.registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".registry-", suffix=".tmp")
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


def get_kit(name: str) -> dict | None:
    """按 kit 名取记录,不存在返回 None。"""
    return load().get("kits", {}).get(name)


def add_kit(name: str, info: dict) -> None:
    """新增或覆盖一个 kit 记录。"""
    data = load()
    data.setdefault("kits", {})[name] = info
    save(data)


def remove_kit(name: str) -> dict | None:
    """删除一个 kit 记录,返回被删内容(不存在返回 None)。"""
    data = load()
    info = data.get("kits", {}).pop(name, None)
    if info is not None:
        save(data)
    return info


def add_override_scope(name: str, scope_value: str) -> None:
    """把项目根追加进 kit 的 override_scopes(去重)。

    override_scopes 记录"仅在项目级 override 过、无 link"的项目根,供 remove
    清理 settings.local.json 的 skillOverrides 残留。它与 known_scopes 刻意分离:
    known_scopes 表示"安装过",参与 find_skill / list_skills 的作用域定位;
    override_scopes 表示"被项目覆盖过",若混入 known_scopes 会把全局 kit 误判成
    项目 kit,进而污染 find_skill 消歧与 list_skills 的 installed 归属。
    """
    data = load()
    info = data.get("kits", {}).get(name)
    if info is None:
        raise CckitError(f"kit {name!r} 不在 registry 中")
    scopes = info.get("override_scopes")
    if not isinstance(scopes, list):
        scopes = []
    if scope_value not in scopes:
        scopes.append(scope_value)
        info["override_scopes"] = scopes
        save(data)


def _kit_in_scope(info: dict, scope: str) -> bool:
    """kit 的 known_scopes 是否包含给定作用域。

    project 作用域按当前项目根路径比对(与 installer 写 known_scopes 时一致)。
    """
    scopes = info.get("known_scopes") or []
    if scope == "global":
        return "global" in scopes
    root = config.project_root()
    return root is not None and str(root) in scopes


def find_skill_matches(name: str, scope: str | None = None) -> list[tuple[str, dict]]:
    """返回所有匹配的 (kit, skill) 列表,不报错(0 或 >1 都原样返回)。

    供 state.set_state 的项目作用域回退逻辑用:先找项目 kit,没有时再回退全局
    kit —— 但必须保留"多个 kit 同名"的歧义,不能把它静默吞成"回退全局"。
    """
    matches: list[tuple[str, dict]] = []
    for kit, info in load().get("kits", {}).items():
        if scope is not None and not _kit_in_scope(info, scope):
            continue
        for sk in info.get("skills", []):
            if sk.get("name") == name:
                matches.append((kit, sk))
    return matches


def find_skill(name: str, scope: str | None = None) -> tuple[str, dict]:
    """按 skill 名查找,要求唯一;0 或 >1 都报错。

    scope 给定时("global"/"project")只在对应作用域内找 —— 同名 skill
    全局与项目各装一份时,靠作用域即可唯一定位(见 Docs/04:所有命令默认
    全局,`--project` 作用项目)。scope=None 时在全部 kit 里找。
    """
    matches = find_skill_matches(name, scope)
    if not matches:
        where = f"({scope} 作用域)" if scope else ""
        raise CckitError(f"skill {name!r} 不在 registry 中{where}(不是 cckit 管理或未安装)")
    if len(matches) > 1:
        kits = ", ".join(k for k, _ in matches)
        raise CckitError(f"skill {name!r} 在多个 kit 中出现({kits}),无法唯一定位")
    return matches[0]
