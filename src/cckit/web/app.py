"""cckit Web 后端(FastAPI app),只绑定 127.0.0.1。

所有状态读写 / 安装 / 诊断都只调 cckit.state / cckit.installer / cckit.doctor,
不直接碰文件系统或 settings.json(见 Docs/09)。错误统一捕获 CckitError 转 JSON。
安装与诊断的进度用 SSE(Server-Sent Events) 流式返回。
"""
from __future__ import annotations

import asyncio
import json
import queue
import shutil
import threading
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import alt, config, doctor, installer, projects, registry, state
from ..errors import CckitError
from ..manifest import MissingManifestError

CCKIT_VERSION = "0.3.1"

app = FastAPI(title="cckit web", version=CCKIT_VERSION)


# ---- 错误契约 ----

@app.exception_handler(CckitError)
async def _cckit_error_handler(request: Request, exc: CckitError):
    return JSONResponse(status_code=400, content={"error": {"message": str(exc)}})


@app.exception_handler(RequestValidationError)
async def _validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"error": {"message": "请求参数无效"}})


# ---- 请求模型 ----

class ScopeBody(BaseModel):
    path: str


class SetStateBody(BaseModel):
    state: str
    scope: str = "global"
    root: str | None = None


class RemoveKitBody(BaseModel):
    keep_env: bool = False


class AddPreviewBody(BaseModel):
    source: str
    ref: str | None = None
    local: bool = False
    project: bool = False
    root: str | None = None
    only: str | None = None
    alt: bool = False


class AddExecuteBody(BaseModel):
    preview_id: str
    no_enable: bool = False


class DoctorBody(BaseModel):
    fix: bool = False


class EnvSetBody(BaseModel):
    kit: str
    name: str
    value: str | None = None        # None = 清除该变量
    skill: str | None = None        # None = kit 级(kit_env 声明的值)
    scope: str = "global"
    root: str | None = None


class ConfWriteBody(BaseModel):
    kit: str
    skill: str
    path: str                       # conf_files 里的相对路径
    content: str
    scope: str = "global"
    root: str | None = None


def _to_path(root: str | None) -> Path | None:
    return Path(root) if root else None


def _scope_val(scope: str) -> str:
    return scope if scope in ("global", "project") else "global"


# ---- 作用域 ----

@app.get("/api/scopes")
def get_scopes():
    return {"scopes": [asdict(s) for s in state.list_scopes()]}


@app.post("/api/scopes")
def add_scope(body: ScopeBody):
    projects.add(body.path)
    return {"scopes": [asdict(s) for s in state.list_scopes()]}


@app.delete("/api/scopes")
def remove_scope(body: ScopeBody):
    projects.remove(body.path)
    return {"scopes": [asdict(s) for s in state.list_scopes()]}


# ---- skill 列表与状态 ----

@app.get("/api/skills")
def get_skills(scope: str = "global", root: str | None = None):
    scope_val = _scope_val(scope)
    r = _to_path(root)
    skills = state.list_skills(scope_val, r)
    used, limit = state.budget(scope_val, r)
    return {
        "skills": [asdict(s) for s in skills],
        # kit 级(kit_env)声明单独给一份:它在 kit 卡片的头部渲染,不属于单个 skill
        "kit_env": {name: (info.get("kit_env") or [])
                    for name, info in registry.load().get("kits", {}).items()},
        "budget": {"used": used, "limit": limit},
    }


@app.post("/api/skills/{name}/state")
def set_skill_state(name: str, body: SetStateBody):
    r = _to_path(body.root)
    ret = state.set_state(name, body.state, body.scope, root=r)
    return {"message": ret or f"{name} → {body.state}({body.scope}),新会话生效"}


# ---- kit ----

@app.get("/api/kits")
def get_kits():
    kits = []
    for name, info in registry.load().get("kits", {}).items():
        kits.append({
            "name": name,
            "version": info.get("version"),
            "source": (info.get("source") or {}).get("url"),
            "ref": (info.get("source") or {}).get("ref"),
            "sha": (info.get("source") or {}).get("sha"),
            "installed_at": info.get("installed_at"),
            "store": info.get("store"),
        })
    return {"kits": kits}


@app.post("/api/kits/{kit}/remove")
def remove_kit(kit: str, body: RemoveKitBody):
    installer.remove_kit(kit, keep_env=body.keep_env)
    return {"message": f"已移除 {kit}"}


# ---- 配置:环境变量值 + 可修改的配置文件 ----
#
# 读写的路径解析与校验全在 state 里(见 Docs/09):端点绝不自己拼文件路径,
# 否则"保存配置"会变成任意文件写入。

@app.get("/api/config")
def get_config(scope: str = "global", root: str | None = None,
               kit: str = "", skill: str | None = None):
    """某个 skill 的配置需求;skill 省略时只返回 kit 级(kit_env)的那份。

    环境变量带上当前取值供弹窗预填;conf_files 只给相对路径,内容按需再取。
    """
    scope_val = _scope_val(scope)
    r = _to_path(root)
    return {
        "envs": [asdict(x) for x in state.env_requirements(kit, skill, scope_val, r)],
        "conf_files": state.conf_files(kit, skill) if skill else [],
    }


@app.post("/api/config/env")
def set_config_env(body: EnvSetBody):
    scope_val = _scope_val(body.scope)
    r = _to_path(body.root)
    state.ensure_config_editable(scope_val, r, body.kit, body.skill)

    req = next((x for x in state.env_requirements(body.kit, body.skill, scope_val, r)
                if x.name == body.name), None)
    if req is None:
        raise CckitError(f"{body.name!r} 不在声明的环境变量里")
    # 声明在 kit 级就写 kit 桶、在 skill 级就写 skill 桶 —— 与 exec 注入时的查找一致
    owner = body.skill if req.level == "skill" else None
    state.set_user_env(req.name, body.value, kit=body.kit, skill=owner,
                       scope=scope_val, root=r)
    return {"message": f"{body.name} 已保存" if body.value is not None
                       else f"{body.name} 已清除"}


@app.get("/api/config/conf")
def read_config_conf(scope: str = "global", root: str | None = None,
                     kit: str = "", skill: str = "", path: str = ""):
    state.ensure_config_editable(_scope_val(scope), _to_path(root), kit, skill)
    return {"path": path, "content": state.read_conf_file(kit, skill, path)}


@app.put("/api/config/conf")
def write_config_conf(body: ConfWriteBody):
    state.ensure_config_editable(_scope_val(body.scope), _to_path(body.root),
                                 body.kit, body.skill)
    state.write_conf_file(body.kit, body.skill, body.path, body.content)
    return {"message": f"{body.path} 已保存"}


# ---- add:两阶段(计划预览 → 确认执行) ----

_STAGED: dict[str, tuple[installer.StagedInstall, float]] = {}
_STAGED_LOCK = threading.Lock()
_STAGED_TTL = 1800.0  # 30 分钟未确认则回收


def _prune_staged() -> None:
    now = time.time()
    with _STAGED_LOCK:
        expired = [pid for pid, (_, t) in _STAGED.items() if now - t > _STAGED_TTL]
        for pid in expired:
            staged, _ = _STAGED.pop(pid)
            staged.cleanup()


@app.post("/api/add/preview")
def add_preview(body: AddPreviewBody):
    _prune_staged()
    try:
        staged = installer.stage_install(
            body.source, ref=body.ref, project=body.project, only=body.only,
            is_local_path=body.local, root=_to_path(body.root))
    except MissingManifestError:
        # 非标准仓库:alt 开启时交给三阶段转换流程,否则维持原拒绝行为。
        if body.alt:
            return {"non_standard": True}
        raise
    preview_id = uuid.uuid4().hex
    with _STAGED_LOCK:
        _STAGED[preview_id] = (staged, time.time())
    return {
        "preview_id": preview_id,
        "kit_name": staged.kit_name,
        "plan": asdict(staged.plan),
        "lint_msgs": [{"level": m.level, "message": m.message} for m in staged.lint_msgs],
        "project_warns": staged.project_warns,
    }


@app.delete("/api/add/preview/{preview_id}")
def cancel_preview(preview_id: str):
    with _STAGED_LOCK:
        entry = _STAGED.pop(preview_id, None)
    if entry:
        entry[0].cleanup()
    return {"message": "已取消"}


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


@app.post("/api/add/execute")
def add_execute(body: AddExecuteBody):
    with _STAGED_LOCK:
        entry = _STAGED.pop(body.preview_id, None)
    if entry is None:
        raise CckitError("安装预览已过期或不存在,请重新添加")
    staged, _ = entry

    def gen():
        try:
            for ev in installer.execute_install(staged, no_enable=body.no_enable):
                yield _sse({"event": "progress", "stage": ev.stage,
                            "status": ev.status, "message": ev.message})
            yield _sse({"event": "done", "message": "安装完成"})
        except CckitError as e:
            yield _sse({"event": "error", "message": str(e)})
        except Exception as e:
            yield _sse({"event": "error", "message": str(e)})

    return StreamingResponse(gen(), media_type="text/event-stream")


# ---- alt:非标准仓库三阶段转换(后台线程 + 队列 + SSE) ----

class AltFixBody(BaseModel):
    action: str                    # "install" | "enable"


class AltStartBody(BaseModel):
    source: str
    ref: str | None = None
    local: bool = False
    project: bool = False
    root: str | None = None
    only: str | None = None


class AltCancelBody(BaseModel):
    session_id: str


class AltCompleteBody(BaseModel):
    session_id: str


class _AltSession:
    def __init__(self, source: str, ref: str | None, local: bool,
                 project: bool, root: Path | None, only: str | None):
        self.id = uuid.uuid4().hex
        self.source = source
        self.ref = ref
        self.local = local
        self.project = project
        self.root = root
        self.only = only
        self.status = "running"        # running | done | cancelled | error
        self.error = ""
        self.tmp_root: Path | None = None
        self.repo_dir: Path | None = None
        self.cancel_event = threading.Event()
        self.client_holder: dict = {}   # {"client": ClaudeSDKClient, "loop": loop}
        self.queue: queue.Queue = queue.Queue()
        self.thread: threading.Thread | None = None
        self.created = time.time()
        self.lock = threading.Lock()

    def cleanup(self) -> None:
        if self.tmp_root is not None:
            shutil.rmtree(self.tmp_root, ignore_errors=True)
            self.tmp_root = None
            self.repo_dir = None

    def request_cancel(self) -> None:
        """设置取消标志并(尽力)请求 SDK client 中断。线程安全,可重复调用。"""
        self.cancel_event.set()
        client = self.client_holder.get("client")
        loop = self.client_holder.get("loop")
        if client is not None and loop is not None and not loop.is_closed():
            try:
                asyncio.run_coroutine_threadsafe(client.interrupt(), loop)
            except Exception:
                pass


_ALT_SESSIONS: dict[str, _AltSession] = {}
_ALT_LOCK = threading.Lock()
_ALT_TTL = 1800.0  # 30 分钟未完成则回收


def _prune_alt() -> None:
    now = time.time()
    with _ALT_LOCK:
        expired = [sid for sid, s in _ALT_SESSIONS.items() if now - s.created > _ALT_TTL]
        for sid in expired:
            sess = _ALT_SESSIONS.pop(sid)
            # 中断 client + 设取消标志;仍在运行的线程会在注意到取消后自行清理临时目录,
            # 只有已结束的线程才在这里清理 tmp_root(否则会删掉正在被操作的目录)。
            sess.request_cancel()
            if sess.thread is None or not sess.thread.is_alive():
                sess.cleanup()


def _alt_worker(sess: _AltSession) -> None:
    def emit(ev) -> None:
        sess.queue.put(("event", ev))

    try:
        tmp_root, repo_dir = alt.run_alt_conversion(
            sess.source, sess.ref, sess.local, emit,
            is_cancelled=sess.cancel_event.is_set,
            client_holder=sess.client_holder)
        with sess.lock:
            sess.tmp_root = tmp_root
            sess.repo_dir = repo_dir
            sess.status = "done"
        sess.queue.put(("done", {"repo_dir": str(repo_dir)}))
    except alt.AgentCancelled:
        with sess.lock:
            sess.status = "cancelled"
        sess.cleanup()
        sess.queue.put(("cancelled", ""))
    except CckitError as e:
        with sess.lock:
            sess.status = "error"
            sess.error = str(e)
        sess.cleanup()
        sess.queue.put(("error", str(e)))
    except Exception as e:
        with sess.lock:
            sess.status = "error"
            sess.error = str(e)
        sess.cleanup()
        sess.queue.put(("error", str(e)))


@app.get("/api/add/alt/check")
def alt_check():
    """alt 开关开启时的前置条件检查(与 CLI 一致)。"""
    if not alt.check_sdk_available():
        return {
            "sdk_available": False,
            "status": "missing_extra",
            "reason": alt._SDK_INSTALL_HINT,
            "auto_fix": None,
        }
    st = alt.kit_builder_status()
    return {
        "sdk_available": True,
        "status": st.status,
        "reason": st.reason,
        "auto_fix": st.auto_fix,
    }


@app.post("/api/add/alt/fix")
def alt_fix(body: AltFixBody):
    alt.apply_kit_builder_fix(body.action)
    return {"message": "kit-builder 已就绪"}


@app.post("/api/add/alt/start")
def alt_start(body: AltStartBody):
    _prune_alt()
    sess = _AltSession(body.source, body.ref, body.local, body.project,
                       _to_path(body.root), body.only)
    with _ALT_LOCK:
        _ALT_SESSIONS[sess.id] = sess
    sess.thread = threading.Thread(target=_alt_worker, args=(sess,), daemon=True)
    sess.thread.start()

    def gen():
        try:
            while True:
                kind, payload = sess.queue.get()
                if kind == "event":
                    yield _sse({"event": "alt_progress", "session_id": sess.id,
                                "stage": payload.stage, "kind": payload.kind,
                                "message": payload.message})
                elif kind == "done":
                    yield _sse({"event": "alt_done", "session_id": sess.id,
                                "repo_dir": payload["repo_dir"]})
                    break
                elif kind == "cancelled":
                    yield _sse({"event": "alt_cancelled", "session_id": sess.id})
                    break
                else:  # error
                    yield _sse({"event": "alt_error", "session_id": sess.id,
                                "message": payload})
                    break
        finally:
            # 流被关闭(浏览器断开 / 提前取消)时,取消后台任务,避免孤儿 Claude Code 子进程与临时目录。
            sess.request_cancel()

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/add/alt/cancel")
def alt_cancel(body: AltCancelBody):
    with _ALT_LOCK:
        sess = _ALT_SESSIONS.get(body.session_id)
    if sess is None:
        return {"message": "任务不存在"}
    sess.request_cancel()
    if sess.thread is not None:
        sess.thread.join(timeout=15)
    stopped = sess.thread is None or not sess.thread.is_alive()
    return {
        "message": "已终止" if stopped else "已请求终止,后台清理仍在进行",
        "stopped": stopped,
    }


@app.post("/api/add/alt/complete")
def alt_complete(body: AltCompleteBody):
    """三阶段成功后,把转换出的临时 Kit 交给现有本地安装流程(stage_install)。"""
    _prune_staged()
    with _ALT_LOCK:
        sess = _ALT_SESSIONS.get(body.session_id)
    if sess is None:
        raise CckitError("转换任务不存在或已过期")
    with sess.lock:
        if sess.status != "done" or sess.repo_dir is None:
            raise CckitError("转换尚未完成或已失败,无法继续安装")
        repo_dir = sess.repo_dir

    try:
        staged = installer.stage_install(str(repo_dir), is_local_path=True,
                                         project=sess.project, only=sess.only, root=sess.root)
        # alt 不记录改造后 SHA,保留原始来源信息(见 TODO 2.4)。
        staged.source = sess.source
        staged.ref = sess.ref
        staged.sha = None
        staged.plan.source = sess.source
        staged.plan.ref = sess.ref
        staged.plan.sha = None

        preview_id = uuid.uuid4().hex
        with _STAGED_LOCK:
            _STAGED[preview_id] = (staged, time.time())

        return {
            "preview_id": preview_id,
            "kit_name": staged.kit_name,
            "plan": asdict(staged.plan),
            "lint_msgs": [{"level": m.level, "message": m.message} for m in staged.lint_msgs],
            "project_warns": staged.project_warns,
        }
    finally:
        # 无论 stage_install 成败,都清掉 alt 会话与临时目录(转换结果已复制进
        # stage_install 自己的临时目录,alt 临时目录不再需要)。
        with _ALT_LOCK:
            _ALT_SESSIONS.pop(sess.id, None)
        sess.cleanup()


# ---- doctor(SSE 流式) ----

@app.post("/api/doctor")
def run_doctor(body: DoctorBody):
    q: queue.Queue = queue.Queue()

    def worker():
        try:
            findings = doctor.run(fix=body.fix, on_event=lambda m: q.put(("progress", m)))
            q.put(("done", findings))
        except CckitError as e:
            q.put(("error", str(e)))
        except Exception as e:
            q.put(("error", str(e)))

    threading.Thread(target=worker, daemon=True).start()

    def gen():
        while True:
            kind, payload = q.get()
            if kind == "progress":
                yield _sse({"event": "progress", "message": payload})
            elif kind == "done":
                yield _sse({"event": "done", "findings": [asdict(f) for f in payload]})
                break
            else:
                yield _sse({"event": "error", "message": payload})
                break

    return StreamingResponse(gen(), media_type="text/event-stream")


# ---- 静态托管(前端 dist 存在时挂载) ----

def _normalize_base(base: str) -> str:
    """规范化根路径前缀:根部署(""或"/")返回 "",其余折叠重复斜杠并确保以 / 开头、无尾斜杠。"""
    b = (base or "").strip()
    if not b or b == "/":
        return ""
    parts = [seg for seg in b.split("/") if seg]
    if not parts:
        return ""
    return "/" + "/".join(parts)


def _inject_base(html: str, base: str) -> str:
    """把 window.__CCKIT_BASE__ 注入 index.html 的 <head>,前端运行时据此拼 /api 前缀。

    对注入值做 < > & 转义,防止 --base 携带的字符跳出 <script> 标签(防御性,非用户输入)。
    """
    if not base:
        return html
    value = (json.dumps(base)
             .replace("<", "\\u003c")
             .replace(">", "\\u003e")
             .replace("&", "\\u0026"))
    script = f"<script>window.__CCKIT_BASE__={value};</script>"
    return html.replace("<head>", "<head>" + script, 1)


def _mount_static(static_dir: str, base: str = "") -> None:
    """挂载前端静态产物 + SPA fallback(不遮挡 /api)。base 非空时注入 __CCKIT_BASE__。"""
    sd = Path(static_dir).resolve()
    if not (sd / "index.html").is_file():
        return
    assets = sd / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    index_html = _inject_base((sd / "index.html").read_text(encoding="utf-8"), base)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def _spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="not found")
        candidate = sd / full_path
        if full_path and candidate.is_file():
            return FileResponse(str(candidate))
        return HTMLResponse(index_html)


def _default_static_dir() -> Path | None:
    """定位前端静态产物:优先包内(cckit/web/static),回落源码 web/dist。"""
    pkg = Path(__file__).parent / "static"
    if (pkg / "index.html").is_file():
        return pkg
    src = Path(__file__).resolve().parents[3] / "web" / "dist"
    if (src / "index.html").is_file():
        return src
    return None


def serve(host: str = "127.0.0.1", port: int = 8000,
          static_dir: str | None = None, base: str = "") -> None:
    """启动 uvicorn。host 默认 127.0.0.1;部署时显式传 0.0.0.0(见 Docs/09 安全要求)。

    base 非空时把整站挂到该根路径前缀下(如 --base /cckit → /cckit/api、/cckit/assets),
    便于经反向代理挂到 dashboard 子路径、用 iframe 嵌入而不与宿主页 /api 冲突。

    static_dir 缺省时自动定位前端产物(包内 static → 源码 web/dist);找不到则只跑 API。
    """
    import uvicorn

    base = _normalize_base(base)
    target = Path(static_dir) if static_dir else _default_static_dir()
    if target is not None:
        _mount_static(str(target), base=base)

    root_app = app
    if base:
        # 把现有 app(所有 /api/* 与 /assets)整体挂到前缀下,代理只需原样透传 /base/*。
        parent = FastAPI(title="cckit web", version=CCKIT_VERSION)
        parent.mount(base, app, name="cckit")
        root_app = parent
    uvicorn.run(root_app, host=host, port=port)
