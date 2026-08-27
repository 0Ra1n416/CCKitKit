"""pytest 全局夹具:把 cckit 数据目录与 CC 配置目录指到临时目录,避免污染真实环境。

每个测试拿到独立 tmp_path,CCKIT_HOME / CLAUDE_CONFIG_DIR 都被重定向,cwd 也
切到临时目录(避免 project_root 向上找到仓库外的 .claude)。
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("CCKIT_HOME", str(tmp_path / "cckit-home"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-config"))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.chdir(tmp_path)
