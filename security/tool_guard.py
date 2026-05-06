"""
Layer 3 — Tool Guard
════════════════════
Last line of defence: even if the LLM is tricked into emitting a malicious
ToolCall, the tool layer must refuse to execute it.

Defences:
  • Permission-level tagging (READ / WRITE / DELETE / ADMIN)
  • Parameter schema validation via Pydantic models
  • Human-in-the-loop gating for destructive operations
  • Per-session tool-call rate limits (prevents tool-spam exfiltration)
  • Output allow-listing (tools may only return pre-defined fields)
"""
from __future__ import annotations

import functools
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class PermissionLevel(Enum):
    READ = "read"       # Safe: query data, no side effects
    WRITE = "write"     # Mutating: could change state
    DELETE = "delete"   # Destructive: irreversible
    ADMIN = "admin"     # Dangerous: arbitrary execution


class ToolCallRateLimiter:
    """Per-session token-bucket limiter for tool calls."""

    def __init__(self, calls_per_minute: float = 30.0) -> None:
        self._rate = calls_per_minute / 60.0
        self._buckets: dict[str, dict[str, Any]] = {}

    def acquire(self, session_id: str, tool_name: str) -> bool:
        key = f"{session_id}:{tool_name}"
        now = time.time()
        bucket = self._buckets.get(key)
        if bucket is None:
            self._buckets[key] = {"tokens": self._rate * 60, "last_refill": now}
            bucket = self._buckets[key]

        elapsed = now - bucket["last_refill"]
        bucket["tokens"] = min(self._rate * 60, bucket["tokens"] + elapsed * self._rate)
        bucket["last_refill"] = now

        if bucket["tokens"] >= 1:
            bucket["tokens"] -= 1
            return True
        return False

    def reset(self, session_id: str) -> None:
        keys_to_remove = [k for k in self._buckets if k.startswith(f"{session_id}:")]
        for k in keys_to_remove:
            del self._buckets[k]


# ── Pydantic-style param validation (lightweight, no heavy schema deps) ──────

@dataclass
class ParamRule:
    name: str
    required: bool = True
    type_: type = str
    min_value: Any = None
    max_value: Any = None
    allowed_values: list[Any] | None = None
    regex: str | None = None
    max_length: int | None = None


@dataclass
class ToolSchema:
    name: str
    permission: PermissionLevel
    params: list[ParamRule] = field(default_factory=list)
    require_human_confirm: bool = False
    allowed_return_keys: list[str] | None = None


class ToolGuard:
    """
    Central registry for tool security policies.
    """

    def __init__(self) -> None:
        self._schemas: dict[str, ToolSchema] = {}
        self._rate_limiter = ToolCallRateLimiter()
        self._pending_confirmations: dict[str, dict[str, Any]] = {}

    def register(self, schema: ToolSchema) -> None:
        self._schemas[schema.name] = schema
        logger.info("Registered tool guard schema for '%s' (permission=%s)", schema.name, schema.permission.value)

    def validate_call(
        self,
        session_id: str,
        tool_name: str,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Validate a tool call. Returns {"ok": True} or {"ok": False, "reason": str}.
        """
        schema = self._schemas.get(tool_name)
        if schema is None:
            # Unknown tools are blocked by default (least privilege)
            return {"ok": False, "reason": f"工具 '{tool_name}' 未注册，拒绝执行"}

        # 1. Rate limit
        if not self._rate_limiter.acquire(session_id, tool_name):
            return {"ok": False, "reason": f"工具 '{tool_name}' 调用频率超限"}

        # 2. Permission check (ADMIN / DELETE require explicit enablement)
        if schema.permission in (PermissionLevel.ADMIN, PermissionLevel.DELETE):
            return {
                "ok": False,
                "reason": f"工具 '{tool_name}' 属于 {schema.permission.value} 级别，已被策略禁用",
            }

        # 3. Parameter validation
        validation_errors = self._validate_params(args, schema)
        if validation_errors:
            return {"ok": False, "reason": f"参数校验失败: {'; '.join(validation_errors)}"}

        # 4. Human-in-the-loop for WRITE-level tools
        if schema.require_human_confirm and schema.permission == PermissionLevel.WRITE:
            confirm_id = f"{session_id}:{tool_name}:{time.time_ns()}"
            self._pending_confirmations[confirm_id] = {
                "session_id": session_id,
                "tool_name": tool_name,
                "args": args,
                "timestamp": time.time(),
            }
            return {
                "ok": False,
                "reason": "该操作需要人工确认",
                "awaiting_confirmation": True,
                "confirmation_id": confirm_id,
            }

        return {"ok": True}

    def confirm(self, confirmation_id: str, approved: bool) -> dict[str, Any]:
        """Approve or reject a pending tool call."""
        pending = self._pending_confirmations.pop(confirmation_id, None)
        if pending is None:
            return {"ok": False, "reason": "确认ID无效或已过期"}
        if not approved:
            return {"ok": False, "reason": "用户拒绝了该操作"}
        # Re-run validation (skipping HITL this time)
        schema = self._schemas.get(pending["tool_name"])
        if schema is None:
            return {"ok": False, "reason": "工具已注销"}
        errors = self._validate_params(pending["args"], schema)
        if errors:
            return {"ok": False, "reason": f"参数校验失败: {'; '.join(errors)}"}
        return {"ok": True, "approved_call": pending}

    def _validate_params(self, args: dict[str, Any], schema: ToolSchema) -> list[str]:
        errors: list[str] = []
        for rule in schema.params:
            value = args.get(rule.name)
            if value is None or value == "":
                if rule.required:
                    errors.append(f"缺少必需参数 '{rule.name}'")
                continue

            expected_types = rule.type_ if isinstance(rule.type_, tuple) else (rule.type_,)
            if not isinstance(value, expected_types):
                type_names = "/".join(t.__name__ for t in expected_types)
                errors.append(f"参数 '{rule.name}' 类型错误，期望 {type_names}")
                continue

            if rule.min_value is not None and value < rule.min_value:
                errors.append(f"参数 '{rule.name}'={value} 小于最小值 {rule.min_value}")

            if rule.max_value is not None and value > rule.max_value:
                errors.append(f"参数 '{rule.name}'={value} 大于最大值 {rule.max_value}")

            if rule.allowed_values is not None and value not in rule.allowed_values:
                errors.append(f"参数 '{rule.name}'={value} 不在允许值列表中")

            if rule.regex is not None:
                if not re.match(rule.regex, str(value)):
                    errors.append(f"参数 '{rule.name}'={value} 格式不符合要求")

            if rule.max_length is not None and len(str(value)) > rule.max_length:
                errors.append(f"参数 '{rule.name}' 长度超过限制 ({rule.max_length})")

        # Reject unknown parameters (prevents parameter pollution)
        known = {r.name for r in schema.params}
        unknown = set(args.keys()) - known
        if unknown:
            errors.append(f"未知参数: {', '.join(unknown)}")

        return errors

    def sanitise_return(self, tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
        """
        Strip any keys from the tool result that are not in the allowed list.
        This prevents a compromised tool from leaking sensitive internal state.
        """
        schema = self._schemas.get(tool_name)
        if schema is None or schema.allowed_return_keys is None:
            return result
        return {k: v for k, v in result.items() if k in schema.allowed_return_keys}


# ── Global singleton ─────────────────────────────────────────────────────────

tool_guard = ToolGuard()


# ── Decorator for legacy tool functions ──────────────────────────────────────

def validate_tool_params(schema: ToolSchema):
    """Decorator that registers a tool with the guard and validates at call time."""
    tool_guard.register(schema)

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            # Attempt to extract session_id from kwargs; fallback to empty
            session_id = kwargs.pop("_session_id", "global")
            # Merge positional args into kwargs for validation (best-effort)
            merged = dict(kwargs)
            check = tool_guard.validate_call(session_id, schema.name, merged)
            if not check["ok"]:
                return {"error": check["reason"], "tool": schema.name}
            result = fn(*args, **kwargs)
            return tool_guard.sanitise_return(schema.name, result)
        return wrapper
    return decorator
