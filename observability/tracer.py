"""
Full-chain structured tracer.
In production, ship spans to LangSmith, OpenTelemetry, or a self-hosted trace store.
"""
from __future__ import annotations

import time
import logging
import structlog

from typing import Any

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
)

_log = structlog.get_logger("financial_copilot")


class Tracer:
    def __init__(self) -> None:
        self._spans: list[dict[str, Any]] = []

    def span(
        self,
        session_id: str,
        user_id: str,
        node: str,
        scene: str,
        **extra: Any,
    ) -> "_Span":
        return _Span(self, session_id, user_id, node, scene, extra)

    def record(self, span: dict[str, Any]) -> None:
        self._spans.append(span)
        _log.info(
            "node_completed",
            session=span["session_id"],
            node=span["node"],
            scene=span["scene"],
            duration_ms=span.get("duration_ms"),
            success=span.get("success"),
            error=span.get("error"),
        )

    def log_tool_call(
        self, session_id: str, tool: str, success: bool, duration_ms: float
    ) -> None:
        _log.info(
            "tool_call",
            session=session_id,
            tool=tool,
            success=success,
            duration_ms=duration_ms,
        )

    def log_risk_event(
        self, session_id: str, layer: str, blocked: bool, reason: str
    ) -> None:
        level = "warning" if blocked else "info"
        getattr(_log, level)(
            "risk_event",
            session=session_id,
            layer=layer,
            blocked=blocked,
            reason=reason,
        )

    def get_spans(self) -> list[dict[str, Any]]:
        return list(self._spans)


class _Span:
    def __init__(
        self,
        parent: Tracer,
        session_id: str,
        user_id: str,
        node: str,
        scene: str,
        extra: dict,
    ) -> None:
        self._parent = parent
        self._data: dict[str, Any] = {
            "session_id": session_id,
            "user_id": user_id,
            "node": node,
            "scene": scene,
            **extra,
        }
        self._start = time.time()

    def __enter__(self) -> "_Span":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._data["duration_ms"] = round((time.time() - self._start) * 1000, 2)
        self._data["success"] = exc_type is None
        if exc_type:
            self._data["error"] = str(exc_val)
        self._parent.record(self._data)

    def annotate(self, **kv: Any) -> None:
        self._data.update(kv)


tracer = Tracer()
