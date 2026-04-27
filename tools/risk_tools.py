"""
Risk detection tools — used internally by the pre/post filter layers.
Not exposed to the LLM directly (they are called by the risk modules).
"""
from __future__ import annotations

import re
from typing import Any

from config.risk_rules import RISK_RULES


def detect_blocked_keywords(text: str) -> tuple[bool, list[str]]:
    """Returns (is_blocked, matched_keywords)."""
    found = [kw for kw in RISK_RULES["blocked_keywords"] if kw in text]
    return bool(found), found


def detect_investment_advice(text: str) -> tuple[bool, list[str]]:
    """Returns (has_advice, matched_patterns)."""
    found = [p for p in RISK_RULES["investment_advice_patterns"] if p in text]
    return bool(found), found


def validate_financial_data(data: dict[str, Any]) -> list[str]:
    """Returns list of validation error messages (empty = OK)."""
    errors: list[str] = []
    rules = RISK_RULES["data_validation"]
    for field, bounds in rules.items():
        if field in data:
            val = data[field]
            if val is not None and not (bounds["min"] <= val <= bounds["max"]):
                errors.append(
                    f"{field}={val} 超出合理范围 [{bounds['min']}, {bounds['max']}]"
                )
    return errors


RISK_TOOLS = {
    "detect_blocked_keywords": detect_blocked_keywords,
    "detect_investment_advice": detect_investment_advice,
    "validate_financial_data": validate_financial_data,
}
