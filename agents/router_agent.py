"""
Router Agent — 三级意图识别引擎
Level 1: 关键词强匹配（零延迟）
Level 2: LLM语义分类（haiku，低延迟）
Level 3: 上下文修正（场景锁定逻辑）
"""
from __future__ import annotations

import json
import re
import logging
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage

from config.llm_factory import create_llm
from config.prompts import PROMPTS
from security.prompt_armor import PromptArmor

logger = logging.getLogger(__name__)

# ── Level-1 keyword maps ───────────────────────────────────────────────────────

_STOCK_DIAGNOSIS_KEYWORDS = [
    "诊股", "分析", "基本面", "技术面", "财报", "估值", "PE", "PB", "ROE",
    "K线", "个股", "这只股", "这支股", "怎么样", "走势", "涨幅", "跌幅",
]
_STOCK_SELECTION_KEYWORDS = [
    "选股", "板块", "行业", "概念股", "龙头股", "涨停", "热门", "排行榜",
    "量化", "指标筛选", "市场整体", "大盘", "沪深",
]
_CUSTOMER_SERVICE_KEYWORDS = [
    "开户", "佣金", "费率", "T+1", "涨停板", "规则", "账户", "充值",
    "提现", "融资", "融券", "工单", "客服", "投诉", "功能",
]
_STOCK_CODE_PATTERN = re.compile(r"\b([036]\d{5}|[68]\d{5})\b")


class RouterAgent:
    def __init__(self) -> None:
        self._llm = create_llm(tier="router")

    def route(self, user_text: str, current_scene: str, scene_history: list[str]) -> dict[str, Any]:
        """
        Returns routing decision:
        {
            "intents": list[str],
            "primary_intent": str,
            "stock_codes": list[str],
            "keywords": list[str],
            "needs_data": bool,
            "confidence": float,
            "reason": str,
        }
        """
        # Level 1 — keyword matching
        keyword_result = self._keyword_match(user_text)
        if keyword_result["confidence"] >= 0.9:
            return keyword_result

        # Level 2 — LLM semantic classification
        llm_result = self._llm_classify(user_text, current_scene, scene_history)

        # Level 3 — context correction (scene lock)
        return self._apply_scene_lock(llm_result, current_scene)

    # ── Level 1 ───────────────────────────────────────────────────────────────

    def _keyword_match(self, text: str) -> dict[str, Any]:
        codes = _STOCK_CODE_PATTERN.findall(text)
        intents: list[str] = []
        keywords: list[str] = []

        for kw in _STOCK_DIAGNOSIS_KEYWORDS:
            if kw in text:
                if "stock_diagnosis" not in intents:
                    intents.append("stock_diagnosis")
                keywords.append(kw)

        for kw in _STOCK_SELECTION_KEYWORDS:
            if kw in text:
                if "stock_selection" not in intents:
                    intents.append("stock_selection")
                keywords.append(kw)

        for kw in _CUSTOMER_SERVICE_KEYWORDS:
            if kw in text:
                if "customer_service" not in intents:
                    intents.append("customer_service")
                keywords.append(kw)

        # Stock code alone implies diagnosis
        if codes and "stock_diagnosis" not in intents:
            intents.append("stock_diagnosis")

        if not intents:
            return {
                "intents": ["chat"],
                "primary_intent": "chat",
                "stock_codes": codes,
                "keywords": keywords,
                "needs_data": False,
                "confidence": 0.5,
                "reason": "无明确金融关键词，归为闲聊",
            }

        primary = intents[0]
        return {
            "intents": intents,
            "primary_intent": primary,
            "stock_codes": codes,
            "keywords": keywords,
            "needs_data": primary in ("stock_diagnosis", "stock_selection"),
            "confidence": 0.9,
            "reason": f"关键词匹配命中：{', '.join(keywords[:3])}",
        }

    # ── Level 2 ───────────────────────────────────────────────────────────────

    def _llm_classify(
        self, text: str, current_scene: str, scene_history: list[str]
    ) -> dict[str, Any]:
        context_hint = ""
        if current_scene and current_scene != "unknown":
            context_hint = f"当前会话场景：{current_scene}，历史场景：{scene_history[-3:]}"

        armor = PromptArmor(core_prompt=PROMPTS["router_system"])
        messages = armor.build(
            user_text=text,
            context=context_hint,
        )
        try:
            response = self._llm.invoke(messages)
            raw = response.content.strip()
            # Strip markdown code fences if present
            raw = re.sub(r"```(?:json)?\s*", "", raw).strip("`").strip()
            result = json.loads(raw)
            # Normalise field names
            if "intents" not in result:
                result["intents"] = [result.get("primary_intent", "chat")]
            return result
        except Exception as exc:
            logger.warning("LLM routing failed: %s", exc)
            return {
                "intents": ["chat"],
                "primary_intent": "chat",
                "stock_codes": [],
                "keywords": [],
                "needs_data": False,
                "confidence": 0.3,
                "reason": f"LLM分类失败，降级为闲聊: {exc}",
            }

    # ── Level 3 ───────────────────────────────────────────────────────────────

    def _apply_scene_lock(
        self, result: dict[str, Any], current_scene: str
    ) -> dict[str, Any]:
        """
        Scene locking: if the user's message is ambiguous (confidence < 0.6)
        and we already have a stable scene, keep the current scene.
        """
        if (
            current_scene
            and current_scene != "unknown"
            and result.get("confidence", 0) < 0.6
        ):
            result["intents"] = [current_scene]
            result["primary_intent"] = current_scene
            result["reason"] += f"（场景锁定，延续 {current_scene}）"
        return result
