"""cckit.yaml 的加载与校验。

三步:存在性检查 → yaml.safe_load → JSON Schema 校验 → 语义检查
(needs 引用、skill 目录与 skills[] 一致、platforms 匹配当前平台、依赖文件存在)。
没有 cckit.yaml 直接拒绝 —— 这是"合法 kit"的唯一判据(见 Docs/03)。

另外提供 SKILL.md frontmatter 的读取(供 lint / state 读 description)。
"""
from __future__ import annotations

from pathlib import Path

import yaml

from . import config, schema
from .errors import CckitError


class ManifestError(CckitError):
    """cckit.yaml 不合法。"""


def load(manifest_path: Path) -> dict:
    """读 cckit.yaml;没有它直接拒绝。"""
    if not manifest_path.exists():
        raise ManifestError(f"找不到 cckit.yaml: {manifest_path}(没有它,cckit 拒绝安装)")
    try:
        with open(manifest_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ManifestError(f"cckit.yaml 解析失败: {e}")
    if not isinstance(data, dict):
        raise ManifestError("cckit.yaml 顶层必须是 mapping")
    return data


def validate_schema(data: dict) -> None:
    """JSON Schema 校验(Draft 2020-12),一次报出全部错误。"""
    errors = sorted(schema.validator().iter_errors(data), key=lambda e: list(e.path))
    if errors:
        lines = [
            "  - " + ("/".join(map(str, e.path)) or "(root)") + ": " + e.message
            for e in errors
        ]
        raise ManifestError("cckit.yaml 未通过 JSON Schema 校验:\n" + "\n".join(lines))


def semantic_check(data: dict, kit_dir: Path, platform: str | None = None) -> None:
    """schema 之外的语义约束,涉及文件系统与当前平台。"""
    platform = platform or config.platform_name()

    # 1. 平台匹配:当前平台不在 platforms 内直接拒绝
    plats = data.get("platforms")
    if plats and platform not in plats:
        raise ManifestError(f"当前平台 {platform} 不在 kit 声明的 platforms {plats} 中")

    # 2. needs 引用:非 python/node 的值必须声明在 requires.system[].bin
    # 注意:requires.system[].version / version_cmd 校验在 installer.py 的 compute_plan() 的 _check_system_version() 里做,这里不重复做
    requires = data.get("requires") or {}
    system_bins = {d.get("bin") for d in (requires.get("system") or [])}
    for sk in data.get("skills", []):
        for need in sk.get("needs", []):
            if need in ("python", "node"):
                continue
            if need not in system_bins:
                raise ManifestError(
                    f"skill {sk['name']!r} 的 needs 引用了未声明的系统依赖 {need!r}")

    # 3. 依赖文件存在性(requirements.txt / package.json)
    for key in ("python", "node"):
        fname = (requires.get(key) or {}).get("file")
        if fname and not (kit_dir / fname).is_file():
            raise ManifestError(f"requires.{key}.file 指向的文件不存在: {fname}")

    # 4. skill 目录与 skills[] 一致
    for sk in data.get("skills", []):
        sdir = kit_dir / sk["name"]
        if not sdir.is_dir():
            raise ManifestError(f"skill {sk['name']!r} 缺少对应目录: {sdir}")
        if not (sdir / "SKILL.md").is_file():
            raise ManifestError(f"skill {sk['name']!r} 缺少 SKILL.md")

    # 5. scripts[] 声明的脚本路径必须存在(相对 skill 目录,与 exec 白名单一致)
    for sk in data.get("skills", []):
        sdir = kit_dir / sk["name"]
        for script in sk.get("scripts") or []:
            if not (sdir / script).is_file():
                raise ManifestError(
                    f"skill {sk['name']!r} 声明的脚本不存在: {script}")


def read_skill_frontmatter(skill_dir: Path) -> dict:
    """读 skill 目录下 SKILL.md 的 YAML frontmatter,失败返回空 dict。"""
    md = skill_dir / "SKILL.md"
    if not md.is_file():
        return {}
    text = md.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}
    fm = "\n".join(lines[1:end])
    try:
        data = yaml.safe_load(fm)
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}
