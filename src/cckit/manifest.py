"""cckit.yaml 的加载与校验。

三步:存在性检查 → yaml.safe_load → JSON Schema 校验 → 语义检查
(needs 引用、skill 目录与 skills[] 一致、platforms 匹配当前平台、依赖文件存在、
conf_files 路径安全且存在)。
没有 cckit.yaml 直接拒绝 —— 这是"合法 kit"的唯一判据(见 Docs/03)。

另外提供 SKILL.md frontmatter 的读取(供 lint / state 读 description)。
"""
from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath

import yaml

from . import config, schema
from .errors import CckitError


class ManifestError(CckitError):
    """cckit.yaml 不合法。"""


class MissingManifestError(ManifestError):
    """仓库根目录没有 cckit.yaml(非标准仓库)。

    与"cckit.yaml 存在但内容不合法"区分开:前者是 alt 流程的触发条件
    (普通 Skill 仓库),后者是标准仓库但 manifest 坏了,alt 不应接手。
    """


def load(manifest_path: Path) -> dict:
    """读 cckit.yaml;没有它直接拒绝。"""
    if not manifest_path.exists():
        raise MissingManifestError(
            f"找不到 cckit.yaml: {manifest_path}(没有它,cckit 拒绝安装)")
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

    # 6. conf_files[] 必须是 skill 目录内的相对路径且真实存在
    # CLI 与 Web 都按这个路径读写用户配置,逃逸出去就成了任意文件读写
    for sk in data.get("skills", []):
        sdir = kit_dir / sk["name"]
        for rel in sk.get("conf_files") or []:
            _check_conf_file(sk["name"], sdir, rel)


def _check_conf_file(skill_name: str, skill_dir: Path, rel: str) -> None:
    """校验单条 conf_files:非空、非绝对、不逃逸,且真实存在。"""
    if not _is_safe_skill_rel(rel):
        raise ManifestError(
            f"skill {skill_name!r} 的 conf_files 必须是 skill 目录内的相对路径: {rel!r}")
    # 反斜杠统一按分隔符处理:否则 Windows 作者写的 `sub\\f.json` 会绕过 `..` 检查
    target = skill_dir / str(PurePosixPath(rel.replace("\\", "/")))
    if not target.is_file():
        raise ManifestError(f"skill {skill_name!r} 声明的 conf_files 不存在: {rel}")
    # 纵深防御:哪怕路径本身合法,若它经符号链接指到 skill 目录之外也拒绝
    try:
        target.resolve().relative_to(skill_dir.resolve())
    except ValueError:
        raise ManifestError(
            f"skill {skill_name!r} 的 conf_files 指向 skill 目录之外: {rel}")


def _is_safe_skill_rel(rel: str) -> bool:
    """相对路径是否安全:非空、非绝对、且不含 `..` 逃逸。

    两种 Path 都要查:Windows 上 `C:\\x` 与 POSIX 上 `/x` 都得拒绝。
    """
    if not rel or not rel.strip():
        return False
    if PurePosixPath(rel).is_absolute() or PureWindowsPath(rel).is_absolute():
        return False
    return ".." not in PurePosixPath(rel.replace("\\", "/")).parts


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
