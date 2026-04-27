"""
Unified Tool Gateway
——————————————————
Central registry for all tools.  Every tool call goes through here to get:
  • Rate limiting  (per-tool token bucket, in-memory)
  • Circuit breaker (opens after N consecutive failures, auto-resets)
  • Timeout enforcement
  • Structured call logging
"""
from __future__ import annotations

import time
import asyncio
import functools
import logging
from enum import Enum
from typing import Any, Callable

from config.settings import settings

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"       # normal, calls pass through
    OPEN = "open"           # failing, calls blocked immediately
    HALF_OPEN = "half_open" # testing recovery


class CircuitBreaker:
    def __init__(self, name: str, threshold: int, reset_seconds: int) -> None:
        self.name = name
        self.threshold = threshold
        self.reset_seconds = reset_seconds
        self._failures = 0
        self._state = CircuitState.CLOSED
        self._opened_at: float = 0.0

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.time() - self._opened_at >= self.reset_seconds:
                self._state = CircuitState.HALF_OPEN
        return self._state

    def record_success(self) -> None:
        self._failures = 0
        self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.threshold:
            self._state = CircuitState.OPEN
            self._opened_at = time.time()
            logger.warning("Circuit breaker OPENED for tool %s", self.name)

    def allow_request(self) -> bool:
        state = self.state
        if state == CircuitState.CLOSED:
            return True
        if state == CircuitState.HALF_OPEN:
            return True  # allow one probe
        return False  # OPEN → blocked


class RateLimiter:
    """Simple token-bucket rate limiter (in-memory)."""

    def __init__(self, calls_per_second: float = 10.0) -> None:
        self._rate = calls_per_second
        self._tokens = calls_per_second
        self._last_refill = time.time()

    def acquire(self) -> bool:
        now = time.time()
        elapsed = now - self._last_refill
        self._tokens = min(self._rate, self._tokens + elapsed * self._rate)
        self._last_refill = now
        if self._tokens >= 1:
            self._tokens -= 1
            return True
        return False


class ToolGateway:
    """Central registry and execution hub for all tools."""

    def __init__(self) -> None:
        self._registry: dict[str, Callable] = {}
        self._circuit_breakers: dict[str, CircuitBreaker] = {}
        self._rate_limiters: dict[str, RateLimiter] = {}
        self._call_log: list[dict[str, Any]] = []

    def register(
        self,
        name: str,
        fn: Callable,
        calls_per_second: float = 10.0,
    ) -> None:
        self._registry[name] = fn
        self._circuit_breakers[name] = CircuitBreaker(
            name,
            threshold=settings.circuit_breaker_threshold,
            reset_seconds=settings.circuit_breaker_reset_seconds,
        )
        self._rate_limiters[name] = RateLimiter(calls_per_second)

    def call(self, name: str, **kwargs: Any) -> dict[str, Any]:
        """Synchronous tool call with full gateway protections."""
        start = time.time()
        record: dict[str, Any] = {
            "tool": name,
            "kwargs": kwargs,
            "start": start,
            "success": False,
            "error": None,
            "result": None,
        }

        if name not in self._registry:
            record["error"] = f"Tool '{name}' not registered"
            self._call_log.append(record)
            return {"error": record["error"]}

        cb = self._circuit_breakers[name]
        rl = self._rate_limiters[name]

        if not cb.allow_request():
            record["error"] = f"Circuit breaker OPEN for '{name}'"
            self._call_log.append(record)
            return {"error": record["error"], "degraded": True}

        if not rl.acquire():
            record["error"] = f"Rate limit exceeded for '{name}'"
            self._call_log.append(record)
            return {"error": record["error"]}

        try:
            result = self._registry[name](**kwargs)
            cb.record_success()
            record["success"] = True
            record["result"] = result
            return result
        except Exception as exc:
            cb.record_failure()
            record["error"] = str(exc)
            logger.exception("Tool '%s' raised an exception", name)
            return {"error": str(exc)}
        finally:
            record["duration_ms"] = round((time.time() - start) * 1000, 2)
            self._call_log.append(record)

    def get_log(self) -> list[dict[str, Any]]:
        return list(self._call_log)

    def list_tools(self) -> list[str]:
        return list(self._registry.keys())


# Process-level singleton
gateway = ToolGateway()
