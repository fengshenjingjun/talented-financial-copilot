"""Pydantic request/response models for the chat API."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: str | None = None
    user_id: str = "anonymous"


class ChatResponse(BaseModel):
    response: str
    session_id: str
    scene: str
    latency_ms: float
    degraded: bool = False
    error: str | None = None


class MetricsResponse(BaseModel):
    uptime_seconds: float
    counters: dict
    latency: dict
