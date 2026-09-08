"""Web 根路径前缀(--base)的纯函数测试:规范化与 index.html 注入。

直接调模块函数,不经过 ASGI 测试客户端(仓库未依赖 httpx)。
"""
from __future__ import annotations

import importlib

# 与 test_web_alt.py 同理:cckit.web.__init__ 把 app 覆盖到了 cckit.web.app 属性上。
web = importlib.import_module("cckit.web.app")


def test_normalize_base_root():
    assert web._normalize_base("") == ""
    assert web._normalize_base("/") == ""
    assert web._normalize_base("  ") == ""


def test_normalize_base_subpath():
    assert web._normalize_base("/cckit") == "/cckit"
    assert web._normalize_base("/cckit/") == "/cckit"
    assert web._normalize_base("cckit") == "/cckit"
    assert web._normalize_base("cckit/") == "/cckit"
    assert web._normalize_base("/cckit/nested/") == "/cckit/nested"


def test_normalize_base_collapses_slashes():
    assert web._normalize_base("//cckit//") == "/cckit"
    assert web._normalize_base("/cckit//nested/") == "/cckit/nested"
    assert web._normalize_base("///") == ""


def test_inject_base_adds_script():
    html = "<!doctype html><html><head><title>x</title></head><body></body></html>"
    out = web._inject_base(html, "/cckit")
    assert '<script>window.__CCKIT_BASE__="/cckit";</script>' in out
    assert out.startswith("<!doctype html><html><head>")


def test_inject_base_escapes_angle_brackets():
    html = "<head></head>"
    out = web._inject_base(html, "</script><script>alert(1)</script>")
    # 注入值里的 < > 被转义成 \u003c / \u003e,不会跳出 <script> 标签
    assert "\\u003c/script\\u003e" in out
    assert out.count("<script>") == 1
    assert out.count("</script>") == 1


def test_inject_base_root_is_noop():
    html = "<head></head>"
    assert web._inject_base(html, "") == html
