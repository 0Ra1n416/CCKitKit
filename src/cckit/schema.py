"""cckit.yaml 的 JSON Schema 加载器。

schema 的源文件在 Docs/schema/cckit.schema.json;这里在包内保留一份副本
(src/cckit/cckit.schema.json),运行时无需依赖文档目录。测试会校验两份一致。

homepage 的 `format: uri` 用自定义 checker 校验(仅靠 stdlib urllib.parse)。
jsonschema 自带的 uri checker 依赖可选的 rfc3987,未装时静默放行一切 ——
等于没校验,所以这里显式实现一个宽松但有效的版本。
"""
from __future__ import annotations

import json
from importlib import resources
from urllib.parse import urlparse

from jsonschema import Draft202012Validator, FormatChecker


def _is_uri(instance: object) -> bool:
    """宽松但有效的 URI 校验:非空、无空白、有 scheme。"""
    if not isinstance(instance, str) or not instance.strip():
        return False
    if any(ch.isspace() for ch in instance):
        return False
    try:
        parsed = urlparse(instance)
    except ValueError:
        return False
    return bool(parsed.scheme)


def load() -> dict:
    """读入 JSON Schema dict。"""
    text = resources.files("cckit").joinpath("cckit.schema.json").read_text(encoding="utf-8")
    return json.loads(text)


def validator() -> Draft202012Validator:
    """构造一个 Draft 2020-12 校验器,带 format_checker 真正校验 homepage 的 uri。"""
    checker = FormatChecker()
    checker.checks("uri")(_is_uri)
    return Draft202012Validator(load(), format_checker=checker)
