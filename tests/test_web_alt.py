"""Web 后端的 alt 端点(直接调用端点函数,不经过 ASGI 测试客户端)。"""
from __future__ import annotations

import importlib

import pytest

from cckit import alt, state

# cckit.web.__init__ 把 `app`(FastAPI 实例)覆盖到了 `cckit.web.app` 属性上,
# 直接 `import cckit.web.app` 会拿到实例而非模块,故用 importlib 取真模块。
web = importlib.import_module("cckit.web.app")

from test_alt import _install_kit_builder, _minimal_cckit_yaml, _write, _write_skill


@pytest.fixture(autouse=True)
def _clear_sessions():
    web._ALT_SESSIONS.clear()
    web._STAGED.clear()
    yield
    web._ALT_SESSIONS.clear()
    web._STAGED.clear()


def test_add_preview_non_standard_without_alt(tmp_path):
    src = tmp_path / "nonsrc"
    _write_skill(src / "my-skill", "my-skill")  # 无 cckit.yaml
    body = web.AddPreviewBody(source=str(src), local=True)
    from cckit.manifest import MissingManifestError
    with pytest.raises(MissingManifestError):
        web.add_preview(body)


def test_add_preview_non_standard_with_alt(tmp_path):
    src = tmp_path / "nonsrc"
    _write_skill(src / "my-skill", "my-skill")
    body = web.AddPreviewBody(source=str(src), local=True, alt=True)
    assert web.add_preview(body) == {"non_standard": True}


def test_add_preview_standard_with_alt(tmp_path):
    src = tmp_path / "stdsrc"
    _write_skill(src / "my-skill", "my-skill")
    _write(src / "cckit.yaml", _minimal_cckit_yaml())
    body = web.AddPreviewBody(source=str(src), local=True, alt=True)
    res = web.add_preview(body)
    assert res["kit_name"] == "my-kit"
    assert "preview_id" in res


def test_alt_check_missing_extra(monkeypatch):
    monkeypatch.setattr(alt, "check_sdk_available", lambda: False)
    res = web.alt_check()
    assert res["sdk_available"] is False
    assert res["status"] == "missing_extra"


def test_alt_check_ready(monkeypatch):
    monkeypatch.setattr(alt, "check_sdk_available", lambda: True)
    _install_kit_builder(monkeypatch)
    res = web.alt_check()
    assert res["status"] == "ready"


def test_alt_fix_enable(monkeypatch):
    _install_kit_builder(monkeypatch)
    state.set_state("kit-builder", "off", "global", kit="kit-builder")
    web.alt_fix(web.AltFixBody(action="enable"))
    assert alt.kit_builder_status().status == "ready"


def test_alt_complete_hands_to_local_install(tmp_path):
    # 模拟一个已完成的三阶段转换会话
    src = tmp_path / "nonsrc"
    _write_skill(src / "my-skill", "my-skill")
    sess = web._AltSession(str(src), None, True, False, None, None)
    repo = tmp_path / "converted"
    _write_skill(repo / "my-skill", "my-skill")
    _write(repo / "cckit.yaml", _minimal_cckit_yaml())
    sess.status = "done"
    sess.repo_dir = repo
    sess.tmp_root = tmp_path / "alt-tmp"
    sess.tmp_root.mkdir()
    web._ALT_SESSIONS[sess.id] = sess

    res = web.alt_complete(web.AltCompleteBody(session_id=sess.id))

    assert res["kit_name"] == "my-kit"
    assert "preview_id" in res
    # 会话被移除,临时目录被清理
    assert sess.id not in web._ALT_SESSIONS
    assert not (tmp_path / "alt-tmp").exists()


def test_alt_complete_not_done_raises(tmp_path):
    sess = web._AltSession(str(tmp_path), None, True, False, None, None)
    sess.status = "running"
    web._ALT_SESSIONS[sess.id] = sess
    with pytest.raises(Exception):
        web.alt_complete(web.AltCompleteBody(session_id=sess.id))


def test_alt_complete_cleans_on_stage_failure(monkeypatch, tmp_path):
    # stage_install 失败时也要清掉 alt 会话与临时目录(见 TODO 4.6.4)。
    src = tmp_path / "nonsrc"
    _write_skill(src / "my-skill", "my-skill")
    sess = web._AltSession(str(src), None, True, False, None, None)
    repo = tmp_path / "converted"
    _write_skill(repo / "my-skill", "my-skill")
    _write(repo / "cckit.yaml", _minimal_cckit_yaml())
    sess.status = "done"
    sess.repo_dir = repo
    sess.tmp_root = tmp_path / "alt-tmp"
    sess.tmp_root.mkdir()
    web._ALT_SESSIONS[sess.id] = sess

    def boom(*a, **k):
        raise Exception("kit 已安装")

    monkeypatch.setattr(web.installer, "stage_install", boom)

    with pytest.raises(Exception):
        web.alt_complete(web.AltCompleteBody(session_id=sess.id))
    assert sess.id not in web._ALT_SESSIONS
    assert not (tmp_path / "alt-tmp").exists()
