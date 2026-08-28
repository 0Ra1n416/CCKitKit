"""hatch 构建钩子:若前端产物 web/dist 存在,把它作为 package data 打进 wheel。

这样「完整构建」(先 `cd web && npm run build` 再 `uv build`)产出的 wheel 自带
前端,用户 `uv tool install 'cckit[web]'` 后 `cckit web` 一键启动;「纯本体构建」
(不跑前端构建)则 wheel 不含前端,核心安装保持纯净(见 Docs/11-web-panel.md)。

要点:wheel 是从 sdist 解压目录构建的(uv build),所以 sdist 阶段要把 web/dist
以**原始路径**带进 sdist,否则 wheel 阶段在解压目录里找不到它。
"""
from __future__ import annotations

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        dist = Path(self.root) / "web" / "dist"
        if not (dist / "index.html").is_file():
            return
        if self.target_name == "sdist":
            # sdist 保留原始路径,供 wheel 阶段从解压目录读取
            build_data.setdefault("force_include", {})[str(dist)] = "web/dist"
        else:  # wheel
            # wheel 阶段把解压目录里的 web/dist 放到最终位置 cckit/web/static
            build_data.setdefault("force_include", {})[str(dist)] = "cckit/web/static"
