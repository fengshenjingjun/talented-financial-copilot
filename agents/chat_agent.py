"""
闲聊 Agent — 轻量化对话，无工具调用，弱风控。
"""
from __future__ import annotations

import time
import logging
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from config.llm_factory import create_llm
from config.prompts import PROMPTS

logger = logging.getLogger(__name__)


class ChatAgent:
    def __init__(self) -> None:
        self._llm = create_llm(tier="chat")

    def run(
        self,
        user_text: str,
        dialog_history: list[dict],
    ) -> dict[str, Any]:
        messages = [SystemMessage(content=PROMPTS["chat_system"])]

        for turn in dialog_history[-6:]:
            role = turn.get("role", "user")
            if role == "user":
                messages.append(HumanMessage(content=turn["content"]))
            else:
                messages.append(AIMessage(content=turn["content"]))

        messages.append(HumanMessage(content=user_text))

        reasoning_steps = [
            {
                "step_id": "step_001",
                "timestamp": time.time(),
                "type": "intent_detection",
                "description": f"闲聊对话: {user_text[:60]}",
                "details": {},
            }
        ]

        try:
            response = self._llm.invoke(messages)
            reasoning_steps.append({
                "step_id": "step_002",
                "timestamp": time.time(),
                "type": "synthesis",
                "description": "生成对话回复",
                "details": {},
            })
            return {
                "response": response.content,
                "tool_calls": [],
                "error": None,
                "reasoning_steps": reasoning_steps,
                "charts": [],
            }
        except Exception as exc:
            logger.exception("Chat agent failed")
            return {
                "response": "抱歉，我暂时无法回答，请稍后再试。",
                "tool_calls": [],
                "error": str(exc),
                "reasoning_steps": reasoning_steps,
                "charts": [],
            }
