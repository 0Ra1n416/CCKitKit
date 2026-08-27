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


def test_semantic_ok(tmp_path):
    data = _load_fixture()
    for sk in data["skills"]:
        (tmp_path / sk["name"]).mkdir()
        (tmp_path / sk["name"] / "SKILL.md").write_text(
            "---\ndescription: x\n---\n", encoding="utf-8")
        for script in sk.get("scripts") or []:
            sp = tmp_path / sk["name"] / script
            sp.parent.mkdir(parents=True, exist_ok=True)
            sp.write_text("", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("requests\n", encoding="utf-8")
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
