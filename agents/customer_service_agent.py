"""
客服 Agent — 强RAG模式，答案100%来自知识库。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage, AIMessage

from config.settings import settings
from config.prompts import PROMPTS
from tools.rag_tools import RAG_TOOLS

logger = logging.getLogger(__name__)


class CustomerServiceAgent:
    def __init__(self) -> None:
        self._llm = ChatAnthropic(
            model=settings.analysis_model,
            temperature=0.1,  # very low — deterministic service answers
            api_key=settings.anthropic_api_key,
        ).bind_tools(RAG_TOOLS)

    def run(
        self,
        user_text: str,
        dialog_history: list[dict],
    ) -> dict[str, Any]:
        messages = [SystemMessage(content=PROMPTS["customer_service_system"])]

        for turn in dialog_history[-4:]:
            role = turn.get("role", "user")
            if role == "user":
                messages.append(HumanMessage(content=turn["content"]))
            else:
                messages.append(AIMessage(content=turn["content"]))

        messages.append(HumanMessage(content=user_text))

        tool_calls_this_run: list[dict] = []

        # First pass — always try to retrieve from knowledge base
        response = self._llm.invoke(messages)
        messages.append(response)

        if response.tool_calls:
            for tc in response.tool_calls:
                result = self._call_rag_tool(tc["name"], tc["args"])
                tool_calls_this_run.append({
                    "tool": tc["name"],
                    "args": tc["args"],
                    "result": result,
                })
                messages.append(
                    ToolMessage(
                        content=json.dumps(result, ensure_ascii=False),
                        tool_call_id=tc["id"],
                    )
                )
            # Second pass — generate final answer based on retrieved context
            response = self._llm.invoke(messages)

        final_text = response.content if isinstance(response.content, str) else ""
        return {
            "response": final_text,
            "tool_calls": tool_calls_this_run,
            "error": None,
        }

    def _call_rag_tool(self, name: str, args: dict) -> dict:
        from tools.rag_tools import search_faq, search_research_reports, search_knowledge_base
        _map = {
            "search_faq": search_faq,
            "search_research_reports": search_research_reports,
            "search_knowledge_base": search_knowledge_base,
        }
        fn = _map.get(name)
        if fn is None:
            return {"error": f"未知RAG工具: {name}"}
        try:
            return fn.invoke(args)
        except Exception as exc:
            return {"error": str(exc)}
