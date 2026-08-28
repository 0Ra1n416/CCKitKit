"""cckit Web 后端(惰性 import,fastapi/uvicorn 缺失时由 CLI 层给出友好提示)。"""
from .app import app, serve

__all__ = ["app", "serve"]
