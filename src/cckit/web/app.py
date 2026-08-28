"""cckit Web 后端(FastAPI app),只绑定 127.0.0.1。

所有状态读写 / 安装 / 诊断都只调 cckit.state / cckit.installer / cckit.doctor,
不直接碰文件系统或 settings.json(见 Docs/09)。错误统一捕获 CckitError 转 JSON。
安装与诊断的进度用 SSE(Server-Sent Events) 流式返回。
"""
from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import config, doctor, installer, projects, registry, state
from ..errors import CckitError

app = FastAPI(title="cckit web", version="0.2.1")


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


class AddExecuteBody(BaseModel):
    preview_id: str
    no_enable: bool = False


class DoctorBody(BaseModel):
    fix: bool = False


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
    staged = installer.stage_install(
        body.source, ref=body.ref, project=body.project, only=body.only,
        is_local_path=body.local, root=_to_path(body.root))
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

def _mount_static(static_dir: str) -> None:
    """挂载前端静态产物 + SPA fallback(不遮挡 /api)。"""
    sd = Path(static_dir).resolve()
    if not (sd / "index.html").is_file():
        return
    assets = sd / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def _spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="not found")
        candidate = sd / full_path
        if full_path and candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(sd / "index.html"))


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
          static_dir: str | None = None) -> None:
    """启动 uvicorn。host 默认 127.0.0.1;部署时显式传 0.0.0.0(见 Docs/09 安全要求)。

    static_dir 缺省时自动定位前端产物(包内 static → 源码 web/dist);找不到则只跑 API。
    """
    import uvicorn

    target = Path(static_dir) if static_dir else _default_static_dir()
    if target is not None:
        _mount_static(str(target))
    uvicorn.run(app, host=host, port=port)
