"""管理员通知(`cckit web --notice TITLE FILE`):启动校验、注入、正文端点。

与其它 web 测试一样直接调端点函数,不经过 ASGI 客户端。
"""
from __future__ import annotations

import importlib

import pytest
from fastapi import HTTPException

from cckit.errors import CckitError

web = importlib.import_module("cckit.web.app")

HTML = "<html><head><title>x</title></head><body></body></html>"


@pytest.fixture(autouse=True)
def _reset_notice():
    web._NOTICE = None
    yield
    web._NOTICE = None


# ---- 启动时校验 ----

def test_set_notice_rejects_missing_file(tmp_path):
    """路径写错要当场失败,别等用户点开弹窗才发现。"""
    with pytest.raises(CckitError) as exc:
        web._set_notice("t", str(tmp_path / "nope.md"))
    assert "不存在" in str(exc.value)


def test_set_notice_rejects_directory(tmp_path):
    d = tmp_path / "adir"
    d.mkdir()
    with pytest.raises(CckitError):
        web._set_notice("t", str(d))


def test_set_notice_returns_title_and_records_path(tmp_path):
    f = tmp_path / "n.md"
    f.write_text("hi", encoding="utf-8")
    assert web._set_notice("维护通知", str(f)) == "维护通知"   # 返回值供注入前端
    assert web._NOTICE == {"title": "维护通知", "path": f}


# ---- 正文端点 ----

def test_get_info_404_without_notice():
    """没配 --notice 时 404 —— 前端据此不渲染控件。"""
    with pytest.raises(HTTPException) as exc:
        web.get_info()
    assert exc.value.status_code == 404


def test_get_info_returns_title_and_content(tmp_path):
    f = tmp_path / "n.md"
    f.write_text("第一行\n第二行\n", encoding="utf-8")
    web._set_notice("标题", str(f))
    assert web.get_info() == {"title": "标题", "content": "第一行\n第二行\n"}


def test_get_info_reads_file_on_each_call(tmp_path):
    """每次请求现读 —— 改了公告不用重启服务。"""
    f = tmp_path / "n.md"
    f.write_text("旧", encoding="utf-8")
    web._set_notice("t", str(f))
    assert web.get_info()["content"] == "旧"
    f.write_text("新", encoding="utf-8")
    assert web.get_info()["content"] == "新"


def test_get_info_rejects_oversized_file(tmp_path):
    f = tmp_path / "big.md"
    f.write_text("x" * (web._NOTICE_MAX_BYTES + 1), encoding="utf-8")
    web._NOTICE = {"title": "t", "path": f}
    with pytest.raises(CckitError) as exc:
        web.get_info()
    assert "过大" in str(exc.value)


def test_get_info_survives_non_utf8(tmp_path):
    """非 UTF-8 文件不该把面板打挂(errors=replace)。"""
    f = tmp_path / "bad.md"
    f.write_bytes(b"\xff\xfe bad \x80 bytes")
    web._NOTICE = {"title": "t", "path": f}
    assert "bad" in web.get_info()["content"]


# ---- 注入 index.html ----

def test_inject_notice_adds_script_into_head():
    out = web._inject_notice(HTML, "维护通知")
    assert "__CCKIT_NOTICE_TITLE__" in out
    assert out.index("__CCKIT_NOTICE_TITLE__") < out.index("<body>")


def test_inject_notice_escapes_script_tag():
    """标题里带 </script> 不能跳出去(注入值是运维输入,仍要转义)。"""
    out = web._inject_notice(HTML, "</script><script>alert(1)</script>")
    head = out.split("<body>")[0]
    value = head.split("__CCKIT_NOTICE_TITLE__=", 1)[1]
    assert "</script><script>alert" not in value      # 没有原样的闭合标签
    assert "\u003c/script\u003e" in value            # 被转成了 unicode 转义


def test_inject_notice_is_noop_without_title():
    assert web._inject_notice(HTML, None) == HTML
    assert web._inject_notice(HTML, "") == HTML
