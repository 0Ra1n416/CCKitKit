"""skill 运行环境:uv venv 创建与依赖安装、解释器解析。

平台差异(venv 布局:Windows Scripts/ vs POSIX bin/)只在这里出现,
上层只问"这个 skill 的解释器在哪",不关心平台。
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .errors import CckitError


def python_interpreter(env_dir: Path) -> Path:
    """venv 内 python 解释器路径。Windows 在 Scripts/,POSIX 在 bin/。"""
    if os.name == "nt":
        return env_dir / "Scripts" / "python.exe"
    return env_dir / "bin" / "python"


def create_python_env(env_dir: Path, python_constraint: str | None = None,
                      requirements: Path | None = None) -> None:
    """uv venv 建环境,并按 requirements.txt 装依赖(uv pip install)。"""
    env_dir.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["uv", "venv", str(env_dir)]
    if python_constraint:
        cmd += ["--python", python_constraint]
    subprocess.run(cmd, check=True)
    if requirements and requirements.is_file():
        interp = python_interpreter(env_dir)
        subprocess.run(
            ["uv", "pip", "install", "-r", str(requirements), "--python", str(interp)],
            check=True,
        )


def create_node_env(env_dir: Path, package_json: Path | None = None) -> None:
    """Node 环境:把 package.json 拷进 env 目录再 npm install。

    Windows 上 npm 是 npm.cmd(批处理),`subprocess.run(["npm", ...])` 会抛
    FileNotFoundError(WinError 2)。这里经 `cmd /c` 转发,不用 shell=True
    (避免 env_dir 含空格/特殊字符时的命令注入风险)。
    """
    env_dir.mkdir(parents=True, exist_ok=True)
    if package_json and package_json.is_file():
        shutil.copy(package_json, env_dir / "package.json")
        cmd = ["npm", "install", "--prefix", str(env_dir)]
        if os.name == "nt":
            cmd = ["cmd", "/c", *cmd]
        subprocess.run(cmd, check=True)


def check_env(env_dir: Path, runtime: str) -> bool:
    """env 是否完整且解释器可执行。"""
    if runtime == "python":
        p = python_interpreter(env_dir)
        return p.is_file() and os.access(p, os.X_OK)
    if runtime == "node":
        return (env_dir / "node_modules").is_dir()
    return False
