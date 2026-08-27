"""cckit exec —— skill 脚本的统一入口。

定位 skill/env、解析解释器、注入 CCKIT_SKILL_DIR / CCKIT_KIT_DIR /
CCKIT_ENV_DIR 与 manifest env 变量、记录用量(追加 ~/.cckit/usage.jsonl,
天然并发安全)、cwd 保持调用方 cwd。scripts 未在 manifest 声明的路径拒绝执行。
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
from pathlib import Path

from . import config, env as env_mod, manifest, registry
from .errors import CckitError


class ExecError(CckitError):
    """exec 失败。"""


def run(skill: str, script: str, args: list[str], scope: str = "global") -> int:
    # 按作用域定位:同名 skill 全局/项目各装一份时,靠 scope 消歧。
    kit_name, skill_info = registry.find_skill(skill, scope)
    kit_info = registry.get_kit(kit_name)
    runtime = skill_info.get("runtime")

    if runtime is None:
        raise ExecError(f"skill {skill!r} 是纯 prompt skill(needs 为空),没有可执行脚本")

    store = Path(kit_info["store"])
    data = manifest.load(store / "cckit.yaml")
    skill_def = next((s for s in data.get("skills", []) if s["name"] == skill), None)
    if skill_def is None:
        raise ExecError(f"skill {skill!r} 不在 kit {kit_name} 的 skills[] 中")

    # 脚本白名单:未在 manifest scripts[] 声明的路径拒绝执行
    whitelist = set(skill_def.get("scripts") or [])
    if script not in whitelist:
        raise ExecError(f"脚本 {script!r} 未在 manifest 的 scripts[] 中声明,拒绝执行")

    skill_dir = (store / skill).resolve()
    script_path = (skill_dir / script).resolve()
    if not script_path.is_file():
        raise ExecError(f"脚本不存在: {script_path}")
    if not script_path.is_relative_to(skill_dir):
        raise ExecError(f"脚本路径越出 skill 目录,拒绝执行: {script}")

    # 解析解释器
    env_dir = Path(skill_info["env"]) if skill_info.get("env") else None
    if runtime == "python":
        if env_dir is None or not env_mod.check_env(env_dir, "python"):
            raise ExecError(f"skill {skill!r} 的 env 缺失或损坏,请运行 `cckit doctor`")
        interp = str(env_mod.python_interpreter(env_dir))
    elif runtime == "node":
        if env_dir is None or not env_mod.check_env(env_dir, "node"):
            raise ExecError(f"skill {skill!r} 的 env 缺失或损坏,请运行 `cckit doctor`")
        interp = "node"
    else:
        raise ExecError(f"不支持的 runtime {runtime!r}")

    # 注入环境变量
    env = os.environ.copy()
    env["CCKIT_SKILL_DIR"] = str(skill_dir)
    env["CCKIT_KIT_DIR"] = str(store)
    env["CCKIT_ENV_DIR"] = str(env_dir) if env_dir else ""
    if runtime == "node" and env_dir is not None:
        # node_modules 装在 env 目录下,require() 需要 NODE_PATH 才找得到
        env["NODE_PATH"] = str(env_dir / "node_modules")
    for var in data.get("env", []):
        name = var.get("name")
        if not name:
            continue
        if name in os.environ:
            env[name] = os.environ[name]
        elif var.get("required"):
            raise ExecError(
                f"缺少必需的 manifest 环境变量 {name!r}({var.get('description', '')})")

    _record_usage(skill, kit_name, script, runtime)

    # cwd 保持调用方 cwd(不 chdir),相对路径正常解析。
    cmd = [interp, str(script_path), *args]
    try:
        proc = subprocess.run(cmd, env=env)
    except FileNotFoundError as e:
        raise ExecError(f"无法执行 {interp}: {e}")
    return proc.returncode


def _record_usage(skill: str, kit: str, script: str, runtime: str) -> None:
    path = config.usage_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "skill": skill,
        "kit": kit,
        "script": script,
        "runtime": runtime,
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
