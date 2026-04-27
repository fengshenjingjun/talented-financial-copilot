"""
Pre-filter: runs before any agent sees the user input.
Blocks content that contains illegal keywords immediately.
"""
from __future__ import annotations

from tools.risk_tools import detect_blocked_keywords


def pre_filter(user_text: str) -> dict:
    """
    Returns:
        {
            "passed": bool,
            "blocked_reason": str | None,
            "cleaned_text": str,   # whitespace-normalized
        }
    """
    cleaned = " ".join(user_text.split())
    blocked, keywords = detect_blocked_keywords(cleaned)

    if blocked:
        return {
            "passed": False,
            "blocked_reason": f"输入包含违禁词：{', '.join(keywords)}",
            "cleaned_text": cleaned,
        }

    return {
        "passed": True,
        "blocked_reason": None,
        "cleaned_text": cleaned,
    }
