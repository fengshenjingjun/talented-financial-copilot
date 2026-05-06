"""
Layer 4 — Audit Guard
═════════════════════
Behavioural audit + anomaly detection.
Even if layers 1-3 are bypassed, we must be able to DETECT and STOP
ongoing attacks via real-time monitoring.

Capabilities:
  • Per-session tool-call sequence logging
  • Anomaly rule engine (threshold-based + pattern-based)
  • Real-time alerting (metrics + structured logs)
  • Emergency circuit breaker (auto-block session on anomaly)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from observability.metrics import metrics
from observability.tracer import tracer

logger = logging.getLogger(__name__)


@dataclass
class AlertRule:
    name: str
    description: str
    severity: str  # "info" | "warning" | "critical"
    condition: Callable[["SessionAuditLog"], bool]


@dataclass
class ToolCallRecord:
    timestamp: float
    tool_name: str
    args: dict[str, Any]
    success: bool
    error: str | None = None


@dataclass
class SessionAuditLog:
    session_id: str
    user_id: str
    created_at: float = field(default_factory=time.time)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    input_guard_scores: list[int] = field(default_factory=list)
    blocked_events: list[dict[str, Any]] = field(default_factory=list)
    response_lengths: list[int] = field(default_factory=list)
    fired_alerts: set[str] = field(default_factory=set)

    @property
    def tool_call_count(self) -> int:
        return len(self.tool_calls)

    @property
    def unique_tools(self) -> set[str]:
        return {tc.tool_name for tc in self.tool_calls}

    @property
    def error_rate(self) -> float:
        if not self.tool_calls:
            return 0.0
        errors = sum(1 for tc in self.tool_calls if not tc.success)
        return errors / len(self.tool_calls)

    @property
    def avg_input_guard_score(self) -> float:
        if not self.input_guard_scores:
            return 0.0
        return sum(self.input_guard_scores) / len(self.input_guard_scores)


# ── Built-in anomaly rules ───────────────────────────────────────────────────

_BUILTIN_RULES: list[AlertRule] = [
    AlertRule(
        name="tool_spam",
        description="单个会话在60秒内调用超过10次工具",
        severity="warning",
        condition=lambda log: sum(
            1 for tc in log.tool_calls if time.time() - tc.timestamp <= 60
        ) > 10,
    ),
    AlertRule(
        name="high_error_rate",
        description="工具错误率超过50%（可能是探测攻击）",
        severity="critical",
        condition=lambda log: log.tool_call_count >= 4 and log.error_rate > 0.5,
    ),
    AlertRule(
        name="input_guard_warning_streak",
        description="连续3次输入层评分超过警告阈值",
        severity="warning",
        condition=lambda log: len([s for s in log.input_guard_scores if s >= 40]) >= 3,
    ),
    AlertRule(
        name="rapid_tool_diversity",
        description="短时间内调用超过5种不同工具（扫描行为）",
        severity="warning",
        condition=lambda log: len(log.unique_tools) > 5,
    ),
]


class AuditGuard:
    """
    Per-session audit log collector + anomaly detector.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, SessionAuditLog] = {}
        self._rules: list[AlertRule] = list(_BUILTIN_RULES)
        self._blocked_sessions: set[str] = set()

    # ── Public API ────────────────────────────────────────────────────────────

    def start_session(self, session_id: str, user_id: str) -> None:
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionAuditLog(
                session_id=session_id, user_id=user_id,
            )

    def record_input_guard(self, session_id: str, score: int, blocked: bool) -> None:
        log = self._get_log(session_id)
        log.input_guard_scores.append(score)
        if blocked:
            log.blocked_events.append({
                "timestamp": time.time(),
                "layer": "input_guard",
                "reason": "blocked_by_input_guard",
            })
            metrics.inc("security.input_guard.blocked")
        else:
            metrics.inc("security.input_guard.scanned")

    def record_tool_call(
        self,
        session_id: str,
        tool_name: str,
        args: dict[str, Any],
        success: bool,
        error: str | None = None,
    ) -> None:
        log = self._get_log(session_id)
        log.tool_calls.append(ToolCallRecord(
            timestamp=time.time(),
            tool_name=tool_name,
            args=args,
            success=success,
            error=error,
        ))
        metrics.tool_called(tool_name, success)

        # Run anomaly detection after every tool call
        self._check_anomalies(log)

    def record_response(self, session_id: str, response_text: str) -> None:
        log = self._get_log(session_id)
        log.response_lengths.append(len(response_text))

    def is_session_blocked(self, session_id: str) -> bool:
        return session_id in self._blocked_sessions

    def block_session(self, session_id: str, reason: str) -> None:
        self._blocked_sessions.add(session_id)
        logger.critical("SESSION BLOCKED: %s | reason=%s", session_id, reason)
        tracer.log_risk_event(session_id, "audit_guard", blocked=True, reason=reason)
        metrics.inc("security.session.blocked")

    def unblock_session(self, session_id: str) -> None:
        self._blocked_sessions.discard(session_id)
        logger.info("SESSION UNBLOCKED: %s", session_id)

    def get_session_summary(self, session_id: str) -> dict[str, Any]:
        log = self._sessions.get(session_id)
        if log is None:
            return {}
        return {
            "session_id": log.session_id,
            "user_id": log.user_id,
            "duration_seconds": round(time.time() - log.created_at, 1),
            "tool_call_count": log.tool_call_count,
            "unique_tools": sorted(log.unique_tools),
            "error_rate": round(log.error_rate, 2),
            "avg_input_guard_score": round(log.avg_input_guard_score, 2),
            "blocked_events": log.blocked_events,
            "blocked": session_id in self._blocked_sessions,
        }

    def add_rule(self, rule: AlertRule) -> None:
        self._rules.append(rule)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _get_log(self, session_id: str) -> SessionAuditLog:
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionAuditLog(
                session_id=session_id, user_id="unknown",
            )
        return self._sessions[session_id]

    def _check_anomalies(self, log: SessionAuditLog) -> None:
        for rule in self._rules:
            try:
                if rule.condition(log):
                    self._fire_alert(log, rule)
            except Exception as exc:
                logger.warning("Alert rule '%s' evaluation failed: %s", rule.name, exc)

    def _fire_alert(self, log: SessionAuditLog, rule: AlertRule) -> None:
        if rule.name in log.fired_alerts:
            return
        log.fired_alerts.add(rule.name)

        if rule.severity == "critical":
            # Auto-block on critical anomalies
            self.block_session(log.session_id, f"audit_rule:{rule.name}")

        logger.log(
            logging.CRITICAL if rule.severity == "critical" else logging.WARNING,
            "AUDIT ALERT [%s] session=%s user=%s | %s",
            rule.severity.upper(), log.session_id, log.user_id, rule.description,
        )
        tracer.log_risk_event(
            log.session_id, f"audit.{rule.name}",
            blocked=(rule.severity == "critical"),
            reason=rule.description,
        )
        metrics.inc(f"security.alert.{rule.severity}")


# ── Module singleton ─────────────────────────────────────────────────────────

audit_guard = AuditGuard()
