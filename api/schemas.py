"""Pydantic request/response models for the chat API."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: str | None = None
    user_id: str = "anonymous"


class ReasoningStep(BaseModel):
    step_id: str
    timestamp: float
    type: str
    description: str
    details: dict
    agent: str | None = None


class ChartData(BaseModel):
    chart_id: str
    type: str
    title: str
    data: dict
    metadata: dict | None = None
    agent: str | None = None


class ChatResponse(BaseModel):
    response: str
    session_id: str
    scene: str
    latency_ms: float
    degraded: bool = False
    error: str | None = None
    reasoning_trace: list[ReasoningStep] = []
    visualization_data: list[ChartData] = []
    tool_call_log: list[dict] = []


class FeedbackRequest(BaseModel):
    message_id: str
    session_id: str
    rating: int  # 1 = thumbs down, 2 = thumbs up
    comment: str | None = None
    timestamp: float | None = None


class MetricsResponse(BaseModel):
    uptime_seconds: float
    counters: dict
    latency: dict
