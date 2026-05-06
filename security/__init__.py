"""
Security Layer — Four-tier defense against prompt injection attacks.

Layers:
  1. Input Guard   (input_guard.py)  — sanitisation + heuristic classifier
  2. Prompt Armor  (prompt_armor.py) — prompt pyramid + instruction boundaries
  3. Tool Guard    (tool_guard.py)   — least privilege + param validation
  4. Audit Guard   (audit_guard.py) — behavioural audit + anomaly alerts
"""
from __future__ import annotations

from security.input_guard import InputGuard, InputGuardResult
from security.prompt_armor import PromptArmor
from security.tool_guard import ToolGuard, PermissionLevel, validate_tool_params
from security.audit_guard import AuditGuard, AlertRule

__all__ = [
    "InputGuard",
    "InputGuardResult",
    "PromptArmor",
    "ToolGuard",
    "PermissionLevel",
    "validate_tool_params",
    "AuditGuard",
    "AlertRule",
]
