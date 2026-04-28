"""
FastAPI application entry point.

Start with:
    uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import logging
import os

from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.WARNING)

from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles

from api.middleware import register_middleware
from api.routes.chat import router as chat_router
from api.routes.metrics import router as metrics_router
from api.websocket import websocket_chat

app = FastAPI(
    title="金融智能对话系统 API",
    description="Multi-agent financial copilot — REST + SSE + WebSocket",
    version="2.0.0",
)

register_middleware(app)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(chat_router, prefix="/api")
app.include_router(metrics_router, prefix="/api")


# ── WebSocket ─────────────────────────────────────────────────────────────────
@app.websocket("/ws/chat")
async def ws_chat_endpoint(websocket: WebSocket) -> None:
    await websocket_chat(websocket)


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


# ── Serve built frontend (if present) ────────────────────────────────────────
_frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(_frontend_dist):
    app.mount("/", StaticFiles(directory=_frontend_dist, html=True), name="frontend")
