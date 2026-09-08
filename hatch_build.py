"""hatch 构建钩子:把 skills/kit-builder 与前端产物 web/dist 作为 package data 打进 wheel。

- skills/kit-builder:alt 流程的自举工具可信来源,始终随包分发(见 alt.kit_builder_source_dir)。
- web/dist:若前端已构建,打进 wheel(完整构建);未构建则不含前端(纯本体构建)。

要点:wheel 是从 sdist 解压目录构建的(uv build),所以 sdist 阶段要把 web/dist
以**原始路径**带进 sdist,否则 wheel 阶段在解压目录里找不到它。skills/kit-builder
是 git 跟踪文件,sdist 默认已含,无需在 sdist 阶段 force_include(见 Docs/11-web-panel.md)。
"""
from __future__ import annotations

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        force = build_data.setdefault("force_include", {})

        # kit-builder 自举工具:alt 流程的可信来源,始终随包分发。
        kb = Path(self.root) / "skills" / "kit-builder"
        if self.target_name == "wheel" and (kb / "cckit.yaml").is_file():
            force[str(kb)] = "cckit/skills/kit-builder"

        dist = Path(self.root) / "web" / "dist"
        if not (dist / "index.html").is_file():
            return
        if self.target_name == "sdist":
            # sdist 保留原始路径,供 wheel 阶段从解压目录读取
            force[str(dist)] = "web/dist"
        else:  # wheel
            # wheel 阶段把解压目录里的 web/dist 放到最终位置 cckit/web/static
            force[str(dist)] = "cckit/web/static"
