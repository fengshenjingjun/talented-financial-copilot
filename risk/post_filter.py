"""
Post-filter: runs after every agent generates a response.
  1. Detects and strips investment-advice phrases
  2. Appends mandatory risk disclaimer for financial scenes
"""
from __future__ import annotations

import re

from tools.risk_tools import detect_investment_advice
from config.risk_rules import RISK_RULES
from config.prompts import PROMPTS


def post_filter(text: str, scene: str) -> dict:
    """
    Returns:
        {
            "passed": bool,
            "filtered_text": str,      # cleaned + disclaimer appended
            "blocked_phrases": list,
            "disclaimer_added": bool,
        }
    """
    has_advice, phrases = detect_investment_advice(text)
    filtered = text

    # Strip detected advice phrases by replacing them with a safe neutral phrase
    for phrase in phrases:
        filtered = filtered.replace(phrase, "[已过滤]")

    disclaimer_added = False
    if scene in RISK_RULES["disclaimer_required_scenes"]:
        if PROMPTS["risk_disclaimer"] not in filtered:
            filtered += PROMPTS["risk_disclaimer"]
            disclaimer_added = True

    return {
        "passed": not has_advice,  # flagged but not blocked; phrase is stripped
        "filtered_text": filtered,
        "blocked_phrases": phrases,
        "disclaimer_added": disclaimer_added,
    }
