"""关注项目清单 ~/.cckit/projects.json 的读写。

与 registry.json 分工:registry 存"装了什么"(文件系统观测不到的东西),
projects 存"用户想持续关注哪些项目目录"(声明式)。关注目录即使当前没有
任何 skill 也在侧栏显示,并可提前建出 .claude 目录使其成为合法项目作用域
(config.project_root 靠 .claude / cckit.lock 判定项目根)。

写入原子(临时文件 + os.replace),避免半截 JSON。
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from . import config
from .errors import CckitError


def _path() -> Path:
    return config.cckit_home() / "projects.json"


def load() -> list[str]:
    """读关注项目清单;不存在返回 [];损坏时抛受检 CckitError。"""
    p = _path()
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            raise CckitError(f"projects.json 不是合法 JSON,已损坏: {e}") from e
    projs = data.get("projects") if isinstance(data, dict) else None
    return [str(x) for x in projs] if isinstance(projs, list) else []


def _save(paths: list[str]) -> None:
    """原子写:临时文件 + os.replace。"""
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".projects-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "projects": paths}, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def add(path: str) -> None:
    """关注一个项目目录:resolve 成绝对路径、去重、写清单,并确保 .claude 目录存在。"""
    p = Path(path).expanduser().resolve()
    s = str(p)
    paths = load()
    if s not in paths:
        paths.append(s)
        _save(paths)
    # 若 .claude 不存在则建出(含父目录),使其成为合法项目作用域。
    (p / ".claude").mkdir(parents=True, exist_ok=True)


def remove(path: str) -> None:
    """取消关注一个项目目录(不存在则 no-op)。"""
    s = str(Path(path).expanduser().resolve())
    paths = load()
    if s in paths:
        paths.remove(s)
        _save(paths)
