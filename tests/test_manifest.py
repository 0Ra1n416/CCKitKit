"""manifest 模块:JSON Schema 校验与语义检查。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cckit import config, manifest, schema
from cckit.errors import CckitError

FIXTURE = Path(__file__).parent.parent / "Docs" / "examples" / "video-toolkit" / "cckit.yaml"
SCHEMA_DOC = Path(__file__).parent.parent / "Docs" / "schema" / "cckit.schema.json"


def _load_fixture() -> dict:
    return manifest.load(FIXTURE)


def test_fixture_passes_schema():
    manifest.validate_schema(_load_fixture())  # 不抛即通过


def test_embedded_schema_matches_docs():
    docs = json.loads(SCHEMA_DOC.read_text(encoding="utf-8"))
    assert schema.load() == docs


def test_missing_cckit_yaml_rejected(tmp_path):
    with pytest.raises(CckitError):
        manifest.load(tmp_path / "cckit.yaml")


def test_schema_reports_errors():
    data = _load_fixture()
    data["version"] = "not-a-semver"  # 违反 pattern
    with pytest.raises(CckitError) as exc:
        manifest.validate_schema(data)
    assert "version" in str(exc.value)


def test_needs_reference_to_undeclared_system(tmp_path):
    data = _load_fixture()
    data["skills"][0]["needs"] = ["nonexistent-dep"]
    with pytest.raises(CckitError) as exc:
        manifest.semantic_check(data, tmp_path)
    assert "needs" in str(exc.value)


def test_skill_dir_mismatch(tmp_path):
    data = _load_fixture()
    (tmp_path / "requirements.txt").write_text("", encoding="utf-8")  # 让依赖文件检查先过
    with pytest.raises(CckitError) as exc:
        manifest.semantic_check(data, tmp_path)
    assert "缺少对应目录" in str(exc.value)


def _materialize(tmp_path, data) -> None:
    """把 fixture 的 skills 落到磁盘:目录 + SKILL.md + scripts[] + conf_files[]。"""
    for sk in data["skills"]:
        sdir = tmp_path / sk["name"]
        sdir.mkdir()
        (sdir / "SKILL.md").write_text(
            "---\ndescription: x\n---\n", encoding="utf-8")
        for script in sk.get("scripts") or []:
            sp = sdir / script
            sp.parent.mkdir(parents=True, exist_ok=True)
            sp.write_text("", encoding="utf-8")
        for conf in sk.get("conf_files") or []:
            cp = sdir / conf
            cp.parent.mkdir(parents=True, exist_ok=True)
            cp.write_text("{}", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("requests\n", encoding="utf-8")


def test_semantic_ok(tmp_path):
    data = _load_fixture()
    _materialize(tmp_path, data)
    manifest.semantic_check(data, tmp_path)  # 不抛即通过


def test_script_path_missing(tmp_path):
    data = _load_fixture()
    for sk in data["skills"]:
        (tmp_path / sk["name"]).mkdir()
        (tmp_path / sk["name"] / "SKILL.md").write_text(
            "---\ndescription: x\n---\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("requests\n", encoding="utf-8")
    # burn-subtitles 声明了 scripts/burn.py,但没建该文件
    with pytest.raises(CckitError) as exc:
        manifest.semantic_check(data, tmp_path)
    assert "脚本不存在" in str(exc.value)


# ---- conf_files:路径安全与存在性 ----

def test_conf_file_missing(tmp_path):
    """声明了 config.json 但 skill 目录里没有 → 拒绝(CLI/Web 要按它读写)。"""
    data = _load_fixture()          # fixture 自带 conf_files,这里刻意不建它
    for sk in data["skills"]:
        sdir = tmp_path / sk["name"]
        sdir.mkdir()
        (sdir / "SKILL.md").write_text("---\ndescription: x\n---\n", encoding="utf-8")
        for script in sk.get("scripts") or []:
            sp = sdir / script
            sp.parent.mkdir(parents=True, exist_ok=True)
            sp.write_text("", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("requests\n", encoding="utf-8")

    with pytest.raises(CckitError) as exc:
        manifest.semantic_check(data, tmp_path)
    assert "conf_files 不存在" in str(exc.value)


@pytest.mark.parametrize("bad", [
    "../outside.json",           # 向上逃逸
    "sub/../../outside.json",    # 中途逃逸
    "..\\outside.json",          # 反斜杠同样要拦
    "/etc/passwd",               # POSIX 绝对路径
    "C:\\Windows\\win.ini",      # Windows 绝对路径
    "",                          # 空串
])
def test_conf_file_escape_rejected(tmp_path, bad):
    """conf_files 逃出 skill 目录 → 拒绝(否则 CLI/Web 变成任意文件读写)。"""
    data = _load_fixture()
    data["skills"][0].pop("conf_files", None)
    _materialize(tmp_path, data)               # 先把正常结构物化出来
    data["skills"][0]["conf_files"] = [bad]    # 再注入非法路径

    with pytest.raises(CckitError) as exc:
        manifest.semantic_check(data, tmp_path)
    assert "相对路径" in str(exc.value)


def test_schema_rejects_uppercase():
    data = _load_fixture()
    data["skills"][0]["name"] = "BurnSubs"  # 大写,违反 slug pattern
    with pytest.raises(CckitError):
        manifest.validate_schema(data)


def test_schema_rejects_bad_uri():
    data = _load_fixture()
    data["homepage"] = "http://exa mple.com"  # 含空格,非法 URI
    with pytest.raises(CckitError):
        manifest.validate_schema(data)


# ---- 顶层 env 已改名为 kit_env ----

def test_kit_env_accepted():
    """fixture 用的就是 kit_env,应通过。"""
    manifest.validate_schema(_load_fixture())


def test_legacy_top_level_env_rejected():
    """旧的顶层 env 不再被接受 —— 是"明确拒绝"而非静默忽略(见 TODO D-3.3)。"""
    data = _load_fixture()
    data["env"] = data.pop("kit_env")
    with pytest.raises(CckitError) as exc:
        manifest.validate_schema(data)
    assert "env" in str(exc.value)


def test_skill_env_and_conf_files_accepted():
    """skill 级 env 与 conf_files 是本次新增的可选字段。"""
    manifest.validate_schema(_load_fixture())
    data = _load_fixture()
    for sk in data["skills"]:
        sk.pop("env", None)
        sk.pop("conf_files", None)
    manifest.validate_schema(data)  # 都不写也应通过(可选)


def test_platform_rejected(tmp_path):
    data = _load_fixture()
    cur = config.platform_name()
    bad = [p for p in ("windows", "linux", "macos") if p != cur]
    data["platforms"] = bad
    with pytest.raises(CckitError):
        manifest.semantic_check(data, tmp_path)


def test_read_skill_frontmatter(tmp_path):
    (tmp_path / "SKILL.md").write_text(
        "---\nname: foo\ndescription: bar\nwhen_to_use: when x\n---\nbody\n", encoding="utf-8")
    fm = manifest.read_skill_frontmatter(tmp_path)
    assert fm["description"] == "bar"
    assert fm["when_to_use"] == "when x"
