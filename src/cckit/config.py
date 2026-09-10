"""cckit 的路径与平台解析。

集中处理三类"环境相关"的问题:
  - cckit 自身的数据目录(CCKIT_HOME 可覆盖 ~/.cckit)
  - Claude Code 配置目录(必须经 CLAUDE_CONFIG_DIR 解析,禁止硬编码 ~/.claude)
  - 当前项目根(向上找 .claude 目录或 cckit.lock 文件)

平台名只做 sys.platform → manifest 平台名的映射,不做行为分支。
真正的平台行为分支只存在于适配层:link.py(链接)与 env.py(解释器路径)。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 清单预算上限缺省值:约 256k token 上下文的 1%,按 ~4 字符/token 估算。
# skillListingBudgetFraction 会按比例缩放它,见 state.budget()。
DEFAULT_BUDGET_LIMIT_CHARS = 10240


def cckit_home() -> Path:
    """cckit 数据目录。CCKIT_HOME 覆盖,缺省 ~/.cckit。"""
    env = os.environ.get("CCKIT_HOME")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".cckit"


def store_dir() -> Path:
    """kit 真实文件的存放处,全局唯一一份。"""
    return cckit_home() / "store"


def envs_dir() -> Path:
    """每 skill 一个独立环境(venv / node_modules)。"""
    return cckit_home() / "envs"


def logs_dir() -> Path:
    """日志与临时目录。"""
    return cckit_home() / "logs"


def registry_path() -> Path:
    """registry.json 的位置。"""
    return cckit_home() / "registry.json"


def usage_log_path() -> Path:
    """用量统计,追加式 JSONL,天然并发安全(见 Docs/09)。"""
    return cckit_home() / "usage.jsonl"


def user_envs_path() -> Path:
    """用户在 CLI / Web 填写的环境变量值。

    与 `envs/` 目录**不是一回事**:那个是每 skill 一个的 venv/node_modules,
    这个是"环境变量键值对"。按 `{作用域}|{kit}[|{skill}]` 分桶存放,
    由 `cckit exec` 注入(`state` 负责读写)。
    """
    return cckit_home() / "envs.json"


def claude_config_dir() -> Path:
    """Claude Code 配置目录。

    回落顺序(已核实):CLAUDE_CONFIG_DIR > XDG_CONFIG_HOME/claude > ~/.claude。
    不可硬编码 ~/.claude —— CC 二进制允许重定向配置目录(见 Docs/06 2.5)。
    """
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    if env:
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg).expanduser() / "claude"
    return Path.home() / ".claude"


def project_root(start: Path | None = None) -> Path | None:
    """向上找项目根:含 cckit.lock 文件,或含 .claude/ 目录(排除全局配置目录)。

    全局 CC 配置目录(CLAUDE_CONFIG_DIR 或 ~/.claude)不是"项目",必须排除 ——
    否则从任意目录向上找都会停在用户家目录,把全局 skills 误当成项目 skill。
    """
    cc_dirs = {claude_config_dir().resolve(), (Path.home() / ".claude").resolve()}
    cur = Path(start or os.getcwd()).resolve()
    for d in (cur, *cur.parents):
        if (d / "cckit.lock").is_file():
            return d
        claude = d / ".claude"
        if claude.is_dir() and claude.resolve() not in cc_dirs:
            return d
    return None


def platform_name() -> str:
    """sys.platform → manifest 平台名。只做命名映射,不做行为分支。"""
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"
