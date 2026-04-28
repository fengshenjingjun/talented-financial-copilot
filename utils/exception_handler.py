"""
Unified exception capture decorator with three-tier degradation strategy.

Tier 1 — complete: hard failure (LLM down, security violation)
    → set error_flag=True, return generic safe message, log ERROR
Tier 2 — partial: degraded mode (some tools failed, rate-limited)
    → continue with available data, add disclaimer, log WARNING
Tier 3 — fallback: graceful (optional tool timeout, JSON parse error)
    → use cached/default value silently, log INFO
"""
from __future__ import annotations

import functools
import logging
import signal
import time
from typing import Any, Callable, Literal

logger = logging.getLogger(__name__)

DegradationTier = Literal["complete", "partial", "fallback"]

# Scene-specific fallback messages
_SCENE_FALLBACKS: dict[str, dict[str, Any]] = {
    "stock_diagnosis": {
        "response": "抱歉，个股分析服务暂时不可用。请稍后重试或联系客服。",
        "error": "stock_diagnosis_unavailable",
    },
    "stock_selection": {
        "response": "抱歉，选股服务暂时不可用。请稍后重试或联系客服。",
        "error": "stock_selection_unavailable",
    },
    "customer_service": {
        "response": "抱歉，客服系统暂时无法响应。请拨打客服热线：400-XXX-XXXX",
        "error": "customer_service_unavailable",
    },
    "chat": {
        "response": "抱歉，我暂时无法回答您的问题，请稍后重试。",
        "error": "chat_unavailable",
    },
}

_GENERIC_FALLBACK = {
    "response": "抱歉，系统暂时无法处理您的请求，请稍后再试。如需帮助，请联系客服热线。",
    "error": "system_unavailable",
}

_DEGRADED_PREFIXES: dict[str, str] = {
    "stock_diagnosis": "（部分数据暂时不可用，基于可用信息提供分析）\n\n",
    "stock_selection": "（部分板块数据缺失，仅供参考）\n\n",
    "customer_service": "（知识库检索受限，以下为通用回答）\n\n",
    "chat": "（系统降级运行中）\n\n",
}


def handle_exceptions(
    tier: DegradationTier = "partial",
    fallback_value: Any = None,
    log_level: str = "warning",
    metrics_key: str | None = None,
    retry_count: int = 0,
    timeout_seconds: int | None = None,
    scene_context: str | None = None,
) -> Callable:
    """
    Decorator for three-tier exception degradation on agent nodes and methods.

    Args:
        tier: Degradation strategy on unrecoverable failure
        fallback_value: Explicit return value on failure (overrides scene defaults)
        log_level: Python log level string for exceptions ("error"/"warning"/"info")
        metrics_key: Dot-notation key for metrics counter (e.g. "agent.stock_diagnosis")
        retry_count: How many times to retry before giving up (0 = no retry)
        timeout_seconds: Per-call wall-clock timeout enforced via SIGALRM (Unix only)
        scene_context: Scene name for context-aware fallback message selection
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Lazy imports to avoid circular deps
            from observability.metrics import metrics
            from observability.tracer import tracer

            # Extract state dict for error_flag injection (workflow nodes pass it as args[0])
            state: dict | None = None
            first_arg = args[0] if args else None
            if isinstance(first_arg, dict):
                state = first_arg
            # If it's a method call (self, state, ...), check args[1]
            elif len(args) > 1 and isinstance(args[1], dict):
                state = args[1]

            session_id: str | None = state.get("session_id") if state else None

            start_time = time.time()
            attempts = 0
            last_exc: Exception | None = None

            while attempts <= retry_count:
                try:
                    if timeout_seconds:
                        result = _execute_with_timeout(func, args, kwargs, timeout_seconds)
                    else:
                        result = func(*args, **kwargs)

                    latency_ms = (time.time() - start_time) * 1000
                    if metrics_key:
                        metrics.record_latency(metrics_key, latency_ms)

                    if attempts > 0:
                        logger.info("%s succeeded after %d retries", func.__name__, attempts)

                    return result

                except Exception as exc:
                    attempts += 1
                    last_exc = exc

                    log_fn = getattr(logger, log_level, logger.warning)
                    log_fn(
                        "%s failed (attempt %d/%d): %s",
                        func.__name__, attempts, retry_count + 1, exc,
                        exc_info=True,
                    )

                    if metrics_key:
                        metrics.error(metrics_key)

                    if session_id:
                        tracer.log_risk_event(
                            session_id, f"exception.{func.__name__}",
                            blocked=False, reason=str(exc),
                        )

                    # Tier "complete" skips retries immediately
                    if tier == "complete" or attempts > retry_count:
                        break

            return _apply_degradation(
                func.__name__,
                exc=last_exc,
                tier=tier,
                fallback_value=fallback_value,
                state=state,
                scene_context=scene_context,
            )

        return wrapper
    return decorator


def _execute_with_timeout(
    func: Callable, args: tuple, kwargs: dict, timeout_seconds: int
) -> Any:
    """Execute with SIGALRM timeout.

    SIGALRM only works on Unix AND only in the main thread.
    When called from a worker thread (e.g. FastAPI's thread-pool), skip the
    timeout silently rather than raising ValueError.
    """
    import threading
    in_main_thread = threading.current_thread() is threading.main_thread()

    if not in_main_thread:
        # Worker thread — cannot use SIGALRM; run without timeout
        return func(*args, **kwargs)

    try:
        def _handler(signum: int, frame: Any) -> None:
            raise TimeoutError(f"{func.__name__} timed out after {timeout_seconds}s")

        old_handler = signal.signal(signal.SIGALRM, _handler)
        signal.alarm(timeout_seconds)
        try:
            return func(*args, **kwargs)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
    except AttributeError:
        # Windows — SIGALRM not available; run without timeout
        return func(*args, **kwargs)


def _apply_degradation(
    func_name: str,
    exc: Exception | None,
    tier: DegradationTier,
    fallback_value: Any,
    state: dict | None,
    scene_context: str | None,
) -> Any:
    if tier == "complete":
        logger.error("Complete failure in %s: %s", func_name, exc)
        payload = fallback_value or _SCENE_FALLBACKS.get(scene_context or "", _GENERIC_FALLBACK)

        if state is not None:
            state["error_flag"] = True
            state["error_message"] = str(exc)
            # If the caller is a workflow node that writes final_response, pre-populate it
            if "final_response" in state and not state.get("final_response"):
                state["final_response"] = payload.get("response", "")

        return payload

    if tier == "partial":
        logger.warning("Partial degradation in %s: %s", func_name, exc)
        prefix = _DEGRADED_PREFIXES.get(scene_context or "", "（系统降级运行中）\n\n")
        degraded: dict[str, Any] = {
            "response": prefix + "由于技术问题，以下回答可能不完整，请谨慎参考。",
            "degraded": True,
            "error": str(exc),
            "tool_calls": [],
        }
        if fallback_value and isinstance(fallback_value, dict):
            degraded = {**degraded, **fallback_value}
        return degraded

    # tier == "fallback"
    logger.info("Fallback mode in %s: %s", func_name, exc)
    return fallback_value if fallback_value is not None else {"response": "", "error": None}
