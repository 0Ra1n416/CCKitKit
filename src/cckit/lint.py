"""kit 的 lint 检查。

覆盖:skill 名合法性(小写 kebab-case、Windows 保留名、仅大小写不同的重名、
synced 保留)、description 质量(缺失=error、含触发条件=warn、超 1536=warn、
与已装 skill 语义重叠=warn)、CRLF 检查、prompt injection 启发式扫描
(07 第 6 条)、依赖 typosquatting 提示(07 第 7 条)。

全部是确定性的启发式,不调 LLM。返回 LintMessage 列表,级别 error / warn。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import manifest

# Windows 保留名(大小写不敏感)
WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *[f"com{i}" for i in range(1, 10)],
    *[f"lpt{i}" for i in range(1, 10)],
}
SYNCED_RESERVED = "synced"

# description 触发条件(启发式)
_TRIGGER_RE = re.compile(
    r"(?i)\b(use\s+when|use\s+this\s+(when|if|for)|when\s+(the\s+)?user\s|"
    r"whenever|trigger\s|触发|使用时机|适用于)\b"
)

# prompt injection 启发式(07 第 6 条)。定位是警告,不是可靠防护。
_PROMPT_INJECTION = [
    (re.compile(r"(?i)ignore\s+(all\s+)?(previous|prior|above|earlier)\s+instructions"),
     "要求忽略既有指令"),
    (re.compile(r"(?i)\byou\s+are\s+now\b"), "尝试重新定义助手角色"),
    (re.compile(r"(?i)(cat|read|print|get|open)\s+[`'\"]?\.?env\b"), "要求读取 .env 文件"),
    (re.compile(r"(?i)(id_rsa|ssh[_-]?key|private[_\s]?key|authorized_keys)"),
     "要求访问 SSH 私钥"),
    (re.compile(r"(?i)(curl|wget|fetch|http)\b.{0,80}(--data|-d\s|POST|upload|exfiltrate)"),
     "疑似向外部地址发送数据"),
]

# 知名 PyPI 包,用于 typosquatting 提示(启发式,非全量)
_KNOWN_PYPI = {
    "requests", "numpy", "pandas", "scipy", "matplotlib", "flask", "django",
    "fastapi", "uvicorn", "httpx", "aiohttp", "beautifulsoup4", "lxml",
    "urllib3", "certifi", "idna", "charset-normalizer", "pyyaml", "pytest",
    "pydantic", "sqlalchemy", "click", "jinja2", "pillow", "opencv-python",
    "scikit-learn", "tensorflow", "torch", "tqdm", "rich", "typer",
}

# 知名 npm 包,用于 package.json 依赖的 typosquatting 提示(启发式,非全量)
_KNOWN_NPM = {
    "express", "lodash", "react", "react-dom", "axios", "chalk", "commander",
    "debug", "dotenv", "fs-extra", "inquirer", "minimist", "moment",
    "node-fetch", "typescript", "webpack", "eslint", "prettier", "jest",
    "yargs", "glob", "semver", "uuid", "winston", "zod", "next", "vue",
    "mongoose", "socket.io",
}

_STOP = {
    "the", "and", "for", "you", "this", "that", "with", "from", "your",
    "when", "will", "not", "are", "use", "into", "can", "its", "have",
    "has", "was", "were", "been", "being", "they", "them", "their", "then",
}


@dataclass
class LintMessage:
    level: str      # 'error' | 'warn'
    message: str

class LintKit:
    def __init__(self, kit_dir: Path, data: dict, installed_descs: list[str] | None = None):
        self.kit_dir = kit_dir
        self.data = data
        self.installed_descs = installed_descs or []

    @staticmethod
    def _skill_desc(skill_dir: Path) -> tuple[str, str]:
        fm = manifest.read_skill_frontmatter(skill_dir)
        return (str(fm.get("description") or ""), str(fm.get("when_to_use") or ""))

    def _lint_skill_names(self) -> list[LintMessage]:
        """skill 名合法性:Windows 保留名、synced 保留、仅大小写不同的重名。

        大写检查不在这里 —— add 路径先过 schema(slug pattern 只允许小写),此处
        再查是死代码且误导读者(见 M9)。这里只留 schema 之外才可能出现的约束。
        """
        msgs: list[LintMessage] = []
        names = [sk["name"] for sk in self.data.get("skills", [])]
        by_lower: dict[str, list[str]] = {}
        for n in names:
            ln = n.lower()
            if ln in WINDOWS_RESERVED:
                msgs.append(LintMessage("error", f"skill 名 {n!r} 是 Windows 保留名"))
            if ln == SYNCED_RESERVED:
                msgs.append(LintMessage("error", f"skill 名 {n!r} 是 CC 保留目录名 synced"))
            by_lower.setdefault(ln, []).append(n)
        for ln, lst in by_lower.items():
            if len(lst) > 1:
                msgs.append(LintMessage("error", f"仅大小写不同的重名 skill: {lst}"))
        return msgs

    def _lint_descriptions(self) -> list[LintMessage]:
        msgs: list[LintMessage] = []
        for sk in self.data.get("skills", []):
            desc, when = self._skill_desc(self.kit_dir / sk["name"])
            if not desc.strip():
                msgs.append(LintMessage(
                    "error", f"skill {sk['name']!r} 的 description 缺失(CC 靠它选工具)"))
                continue
            if _TRIGGER_RE.search(desc):
                msgs.append(LintMessage(
                    "warn",
                    f"skill {sk['name']!r} 的 description 含触发条件(如 'Use when...'),"
                    f"应移到 when_to_use"))
            total = len(desc) + len(when)
            if total > 1536:
                msgs.append(LintMessage(
                    "warn",
                    f"skill {sk['name']!r} description+when_to_use 共 {total} 字符,"
                    f"超过 1536 会被 CC 截断"))
            for other in self.installed_descs:
                if TextSimilarity(desc, other).similarity() > 0.9:
                    msgs.append(LintMessage(
                        "warn",
                        f"skill {sk['name']!r} 的 description 与已装 skill 语义重叠"
                        f"(CC 可能挑错工具)"))
                    break
        return msgs

    def _lint_crlf(self) -> list[LintMessage]:
        return CRLFLint(self.kit_dir).lint_crlf()

    def _lint_prompt_injection(self) -> list[LintMessage]:
        msgs: list[LintMessage] = []
        for sk in self.data.get("skills", []):
            md = self.kit_dir / sk["name"] / "SKILL.md"
            if not md.is_file():
                continue
            text = md.read_text(encoding="utf-8", errors="replace")
            for pat, desc in _PROMPT_INJECTION:
                if pat.search(text):
                    msgs.append(LintMessage(
                        "warn",
                        f"skill {sk['name']!r} 的 SKILL.md 疑似 prompt injection:{desc}"))
                    break
        return msgs

    def _lint_typosquatting(self) -> list[LintMessage]:
        return TyposquatLint(self.kit_dir, self.data).lint_typosquatting()

    def lint_kit(self) -> list[LintMessage]:
        """对一个已通过 schema 校验的 kit 做全部 lint。"""
        msgs: list[LintMessage] = []
        msgs += self._lint_skill_names()
        msgs += self._lint_descriptions()
        msgs += self._lint_crlf()
        msgs += self._lint_prompt_injection()
        msgs += self._lint_typosquatting()
        return msgs


class TextSimilarity:
    """文本相似度计算,用于 description 语义重叠提示。

    目前用简单的 token 集交集/并集比值,不调 LLM (基于 token 集合的 Jaccard 相似度)。token 是小写拉丁字母数字
    序列(长度>2)与 CJK 字符(单字+双字 bi-gram),停用词过滤掉。
    """
    def __init__(self, a: str, b: str):
        self.a = a
        self.b = b

    @staticmethod
    def _tokens(text: str) -> set[str]:
        s = text.lower()
        latin = {w for w in re.findall(r"[a-z0-9]{3,}", s) if w not in _STOP}
        cjk = re.findall(r"[一-鿿]", s)
        cjk_bi = {cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1)}
        return latin | set(cjk) | cjk_bi

    def similarity(self) -> float:
        ta, tb = self._tokens(self.a), self._tokens(self.b)
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / len(ta | tb)


class CRLFLint:
    """检查 kit 内文本文件是否含 CRLF 换行,在 Linux 上 .sh 会 bad interpreter。"""
    def __init__(self, kit_dir: Path):
        self.kit_dir = kit_dir

    def _text_files(self) -> list[Path]:
        skip = {".git", "__pycache__", ".venv", "node_modules"}
        out: list[Path] = []
        for f in self.kit_dir.rglob("*"):
            if not f.is_file():
                continue
            if any(part in skip for part in f.parts):
                continue
            if f.stat().st_size > 1_000_000:
                continue
            out.append(f)
        return out

    def lint_crlf(self) -> list[LintMessage]:
        msgs: list[LintMessage] = []
        for f in self._text_files():
            try:
                raw = f.read_bytes()
            except OSError:
                continue
            if b"\r\n" in raw:
                rel = f.relative_to(self.kit_dir)
                msgs.append(LintMessage(
                    "warn",
                    f"{rel} 含 CRLF 换行,在 Linux 上 .sh 会 bad interpreter,建议转 LF"))
        return msgs


class TyposquatLint:
    """检查 kit 内依赖是否疑似 typosquatting,用于提示(07 第 7 条)。"""
    def __init__(self, kit_dir: Path, data: dict):
        self.kit_dir = kit_dir
        self.data = data

    def lint_typosquatting(self) -> list[LintMessage]:
        """typosquatting 提示:requirements.txt(python)与 package.json(node)都扫。"""
        msgs: list[LintMessage] = []
        requires = self.data.get("requires") or {}
        py_file = (requires.get("python") or {}).get("file")
        if py_file:
            req = self.kit_dir / py_file
            if req.is_file():
                msgs += self._typosquat_check(self._parse_requirements(req), _KNOWN_PYPI)
        node_file = (requires.get("node") or {}).get("file")
        if node_file:
            pkg = self.kit_dir / node_file
            if pkg.is_file():
                msgs += self._typosquat_check(self._parse_package_names(pkg), _KNOWN_NPM)
        return msgs

    def _typosquat_check(self, names: list[str], known: set[str]) -> list[LintMessage]:
        """对一组依赖名做 typosquatting 提示(与 known 集比对)。"""
        msgs: list[LintMessage] = []
        for pkg in names:
            name = pkg.lower()
            if name in known:
                continue
            for k in known:
                if abs(len(k) - len(name)) <= 1 and self._lev(name, k) <= 1:
                    msgs.append(LintMessage(
                        "warn",
                        f"依赖 {pkg!r} 与知名包 {k!r} 极其相似,疑似 typosquatting"))
                    break
        return msgs

    @staticmethod
    def _parse_package_names(path: Path) -> list[str]:
        """package.json 的 dependencies + devDependencies 键名。"""
        try:
            pkg = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        deps = {}
        deps.update(pkg.get("dependencies") or {})
        deps.update(pkg.get("devDependencies") or {})
        return list(deps.keys())

    @staticmethod
    def _parse_requirements(path: Path) -> list[str]:
        names: list[str] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            m = re.match(r"^[A-Za-z0-9_.-]+", line)
            if m:
                names.append(m.group(0))
        return names

    @staticmethod
    def _lev(a: str, b: str) -> int:
        """Damerau-Levenshtein 距离(相邻换位计 1),用于 typosquatting 提示。

        用普通 Levenshtein 会把 'reqeusts'(换位)→ 'requests' 算成 2,漏掉最常见的
        手误。相邻换位算 1 才能命中 Docs/07 第 7 条给的示例。
        """
        if not a:
            return len(b)
        if not b:
            return len(a)
        la, lb = len(a), len(b)
        d = [[0] * (lb + 1) for _ in range(la + 1)]
        for i in range(la + 1):
            d[i][0] = i
        for j in range(lb + 1):
            d[0][j] = j
        for i in range(1, la + 1):
            for j in range(1, lb + 1):
                cost = 0 if a[i - 1] == b[j - 1] else 1
                d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
                if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                    d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
        return d[la][lb]
