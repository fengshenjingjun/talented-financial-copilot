"""
闲聊 Agent — 轻量化对话，无工具调用，弱风控。
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from config.settings import settings
from config.prompts import PROMPTS

logger = logging.getLogger(__name__)


class ChatAgent:
    def __init__(self) -> None:
        self._llm = ChatAnthropic(
            model=settings.chat_model,
            temperature=settings.chat_temperature,
            api_key=settings.anthropic_api_key,
        )

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

        try:
            response = self._llm.invoke(messages)
            return {
                "response": response.content,
                "tool_calls": [],
                "error": None,
            }
        except Exception as exc:
            logger.exception("Chat agent failed")
            return {
                "response": "抱歉，我暂时无法回答，请稍后再试。",
                "tool_calls": [],
                "error": str(exc),
            }
