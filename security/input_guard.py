"""
Layer 1 — Input Guard
═════════════════════
Sanitise and validate user input BEFORE it reaches any LLM.

Defences:
  • Keyword / pattern matching (Chinese + English injection lexicon)
  • Encoding-obfuscation detection (base64, URL-encoding, Unicode escapes)
  • Delimiter-injection detection (markers that try to break prompt boundaries)
  • Heuristic scoring classifier (light-weight, zero external dependencies)
"""
from __future__ import annotations

import base64
import json
import logging
import re
import urllib.parse
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ── Injection keyword lexicon (Chinese + English) ────────────────────────────

_INJECTION_KEYWORDS: list[str] = [
    # Chinese
    "忽略指令", "重置指令", "系统指令", "扮演管理员", "忽略之前的",
    "忘记之前", "覆盖设定", "解除限制", "去掉限制", "突破限制",
    "你是", "你现在是", "请扮演", "进入角色", "开发者模式",
    "越狱", "忽略上面", "忽略以下", "以上无效", "以下无效",
    # English
    "ignore previous", "ignore above", "ignore below", "ignore the",
    "system prompt", "system instruction", "developer mode",
    "jailbreak", "DAN", "do anything now", "root access",
    "override instructions", "disregard", "forget everything",
    "you are now", "pretend to be", "act as", "roleplay as",
    "new instructions", "updated instructions", "replace your",
    "your new role", "admin mode", "sudo", "root user",
    # Delimiter attacks
    "--- system", "--- user", "--- assistant", "### system", "### instruction",
    "<<<system>>>", "[system]", "(system)", "<system>", "</system>",
    "<|im_start|>", "<|im_end|>", "<|system|>", "<|user|>", "<|assistant|>",
    "USER:", "ASSISTANT:", "SYSTEM:", "INSTRUCTION:",
]

_INJECTION_PATTERNS: list[re.Pattern] = [
    # Attempts to inject new JSON fields
    re.compile(r'"\s*(?:role|system|instruction|model)\s*"\s*:\s*"', re.IGNORECASE),
    # XML tag injection
    re.compile(r'<\s*(?:system|instruction|prompt|config)[^>]*>', re.IGNORECASE),
    # Markdown code fence with system-looking content
    re.compile(r'```\s*(?:system|yaml|json)\s*', re.IGNORECASE),
    # Repeated boundary markers (trying to break out)
    re.compile(r'(<\s*<\s*<|>\s*>\s*>|\[-\]-\{-\}|\{\{\{)\s*(?:user|system|input|output)', re.IGNORECASE),
]

# ── Obfuscation detection ────────────────────────────────────────────────────

_OBFUSCATION_SIGNATURES: list[tuple[str, re.Pattern, Callable]] = [
    ("base64", re.compile(r'^(?:[A-Za-z0-9+/]{4})+(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$'), base64.b64decode),
    ("url_encoded", re.compile(r'%[0-9A-Fa-f]{2}'), urllib.parse.unquote),
    ("unicode_escaped", re.compile(r'\\u[0-9a-fA-F]{4}'), lambda s: re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), s)),
    ("html_entities", re.compile(r'&(?:#[0-9]+|#[xX][0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]*);'), lambda s: __import__("html").unescape(s)),
]

# ── Heuristic scoring weights ────────────────────────────────────────────────

_HEURISTIC_RULES: list[tuple[str, int]] = [
    ("keyword_match", 30),
    ("pattern_match", 25),
    ("delimiter_heavy", 20),      # many special chars / boundaries
    ("obfuscation_detected", 25), # encoding tricks
    ("repetition_anomaly", 15),   # same marker repeated many times
    ("length_anomaly", 10),       # extremely long input
]

_THRESHOLD_BLOCK = 70   # score >= 70  → block immediately
_THRESHOLD_WARN = 40    # score >= 40  → warn + log + tag
_THRESHOLD_MAX = 100


@dataclass
class InputGuardResult:
    passed: bool
    action: str          # "pass" | "warn" | "block"
    score: int           # 0-100 heuristic score
    reasons: list[str] = field(default_factory=list)
    cleaned_text: str = ""
    original_text: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "action": self.action,
            "score": self.score,
            "reasons": self.reasons,
            "cleaned_text": self.cleaned_text,
            "tags": self.tags,
        }


class InputGuard:
    """
    Stateful per-request input sanitiser.
    Stateless between requests (no session memory required).
    """

    def __init__(
        self,
        block_threshold: int = _THRESHOLD_BLOCK,
        warn_threshold: int = _THRESHOLD_WARN,
        max_length: int = 8000,
    ) -> None:
        self.block_threshold = block_threshold
        self.warn_threshold = warn_threshold
        self.max_length = max_length

    # ── Public API ────────────────────────────────────────────────────────────

    def scan(self, text: str) -> InputGuardResult:
        """
        Run full input-guard pipeline.
        Returns an InputGuardResult with action recommendation.
        """
        if not text:
            return InputGuardResult(
                passed=True, action="pass", score=0,
                cleaned_text="", original_text=text,
            )

        original = text
        score = 0
        reasons: list[str] = []
        tags: list[str] = []

        # 1. Normalise whitespace (preserves meaning, removes injection formatting)
        cleaned = self._normalise(text)

        # 2. Keyword matching (Chinese + English)
        kw_score, kw_hits = self._score_keywords(cleaned)
        if kw_hits:
            score += kw_score
            reasons.append(f"命中注入关键词: {', '.join(kw_hits[:5])}")
            tags.append("keyword_injection")

        # 3. Regex pattern matching
        pat_score, pat_hits = self._score_patterns(cleaned)
        if pat_hits:
            score += pat_score
            reasons.append(f"命中注入模式: {', '.join(pat_hits[:3])}")
            tags.append("pattern_injection")

        # 4. Obfuscation detection (decode and re-scan)
        obf_score, obf_reasons = self._score_obfuscation(original)
        if obf_reasons:
            score += obf_score
            reasons.extend(obf_reasons)
            tags.append("obfuscation")

        # 5. Heuristic anomalies
        anomaly_score, anomaly_reasons = self._score_anomalies(cleaned)
        if anomaly_reasons:
            score += anomaly_score
            reasons.extend(anomaly_reasons)
            tags.extend(["anomaly"] if anomaly_reasons else [])

        # 6. Length check
        if len(original) > self.max_length:
            score += 10
            reasons.append(f"输入过长 ({len(original)} > {self.max_length})")
            tags.append("length_anomaly")
            cleaned = cleaned[: self.max_length]

        score = min(score, _THRESHOLD_MAX)

        if score >= self.block_threshold:
            return InputGuardResult(
                passed=False,
                action="block",
                score=score,
                reasons=reasons,
                cleaned_text=cleaned,
                original_text=original,
                tags=tags,
            )

        if score >= self.warn_threshold:
            return InputGuardResult(
                passed=True,
                action="warn",
                score=score,
                reasons=reasons,
                cleaned_text=cleaned,
                original_text=original,
                tags=tags,
            )

        return InputGuardResult(
            passed=True,
            action="pass",
            score=score,
            reasons=reasons,
            cleaned_text=cleaned,
            original_text=original,
            tags=tags,
        )

    def sanitise_for_prompt(self, text: str) -> str:
        """
        Fast path: only normalisation + stripping of known boundary markers.
        Used when the full heuristic scan already passed.
        """
        cleaned = self._normalise(text)
        # Strip known injection delimiters that could break prompt boundaries
        cleaned = re.sub(r'[<\[{\-]+\s*(?:system|instruction|prompt|config)\s*[>\]}\-]+', '', cleaned, flags=re.IGNORECASE)
        # Strip our own boundary markers to prevent user from injecting them
        for marker in ("<<<USER_INPUT_START>>>", "<<<USER_INPUT_END>>>", "<<<EXTERNAL_DATA_START>>>", "<<<EXTERNAL_DATA_END>>>", "<<<", ">>>"):
            cleaned = cleaned.replace(marker, "")
        return cleaned

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _normalise(text: str) -> str:
        # Collapse whitespace but preserve newlines (they may be meaningful)
        lines = text.splitlines()
        cleaned_lines = [" ".join(line.split()) for line in lines]
        return "\n".join(cleaned_lines)

    def _score_keywords(self, text: str) -> tuple[int, list[str]]:
        lower = text.lower()
        hits = [kw for kw in _INJECTION_KEYWORDS if kw.lower() in lower]
        if not hits:
            return 0, []
        # More hits → higher score, capped
        score = min(30 + (len(hits) - 1) * 5, 50)
        return score, hits

    def _score_patterns(self, text: str) -> tuple[int, list[str]]:
        hits: list[str] = []
        for pat in _INJECTION_PATTERNS:
            if pat.search(text):
                hits.append(pat.pattern[:40] + "...")
        if not hits:
            return 0, []
        score = min(25 + (len(hits) - 1) * 8, 45)
        return score, hits

    def _score_obfuscation(self, text: str) -> tuple[int, list[str]]:
        score = 0
        reasons: list[str] = []

        for name, regex, decoder in _OBFUSCATION_SIGNATURES:
            if not regex.search(text):
                continue

            # Attempt decode
            try:
                decoded = decoder(text)
                if isinstance(decoded, bytes):
                    decoded = decoded.decode("utf-8", errors="ignore")
            except Exception:
                continue

            # Re-scan decoded text for keywords
            _, kw_hits = self._score_keywords(decoded)
            _, pat_hits = self._score_patterns(decoded)

            if kw_hits or pat_hits:
                score += 25
                reasons.append(f"检测到{name}编码混淆，解码后命中攻击特征")
                break  # One obfuscation hit is enough

        return score, reasons

    def _score_anomalies(self, text: str) -> tuple[int, list[str]]:
        score = 0
        reasons: list[str] = []

        # Delimiter-heavy input
        delim_count = len(re.findall(r'[<\[{\-\|#*`\'>\]}]', text))
        if delim_count > 30:
            score += 20
            reasons.append(f"特殊符号密度异常 ({delim_count} 个分隔符)")
        elif delim_count > 15:
            score += 10
            reasons.append(f"特殊符号密度偏高 ({delim_count} 个分隔符)")

        # Repetition anomaly
        lines = text.splitlines()
        if len(lines) > 3:
            line_counts = Counter(lines)
            most_common = line_counts.most_common(1)[0]
            if most_common[1] >= 5:
                score += 15
                reasons.append(f"重复行异常 ('{most_common[0][:20]}...' 重复 {most_common[1]} 次)")

        return score, reasons


# ── Module-level singleton for convenience ───────────────────────────────────
_default_guard = InputGuard()


def scan_input(text: str) -> InputGuardResult:
    """Convenience function using the default InputGuard instance."""
    return _default_guard.scan(text)
