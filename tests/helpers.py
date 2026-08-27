"""测试辅助:在隔离的临时目录里装一个最小的 kit(写 store + registry)。

env 变量由 conftest 的 autouse fixture 指到临时目录,所以这里直接调 cckit
的 config / registry / env 模块即可,不会污染真实环境。
"""
from __future__ import annotations

import os
from pathlib import Path

from cckit import config, env as env_mod, registry


def install_kit_skill(skill: str = "foo", runtime: str | None = None,
                      needs: list[str] | None = None, desc: str = "test skill"):
    """装一个只有单个 skill 的 kit,返回 (store 目录, env 目录或 None)。"""
    kit = "testkit"
    store = config.store_dir() / kit
    skill_dir = store / skill
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\ndescription: {desc}\n---\n", encoding="utf-8")

    env_dir = None
    if runtime:
        env_dir = config.envs_dir() / f"{kit}__{skill}"
        env_dir.mkdir(parents=True)
        # 造一个可执行的解释器占位(check_env 只查存在 + 可执行)
        interp = env_mod.python_interpreter(env_dir)
        interp.parent.mkdir(parents=True, exist_ok=True)
        interp.write_bytes(b"")
        os.chmod(interp, 0o755)

    registry.add_kit(kit, {
        "source": {"url": "https://example.com/testkit", "ref": None, "sha": "abc123"},
        "version": "1.0.0",
        "installed_at": "2026-08-27T00:00:00Z",
        "store": str(store),
        "skills": [{
            "name": skill,
            "env": str(env_dir) if env_dir else None,
            "runtime": runtime,
            "needs": needs or [],
        }],
        "known_scopes": ["global"],
    })
    return store, env_dir
