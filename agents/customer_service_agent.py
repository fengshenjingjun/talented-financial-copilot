"""
客服 Agent — 强RAG模式，答案100%来自知识库。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage, AIMessage

from config.llm_factory import create_llm
from config.prompts import PROMPTS
from tools.rag_tools import RAG_TOOLS

logger = logging.getLogger(__name__)


def _str_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(block.get("text", ""))
        return "".join(parts)
    return "" if content is None else str(content)


class CustomerServiceAgent:
    def __init__(self) -> None:
        self._llm = create_llm(tier="analysis", temperature=0.1, bind_tools=RAG_TOOLS)

    def run(
        self,
        user_text: str,
        dialog_history: list[dict],
    ) -> dict[str, Any]:
        messages = [SystemMessage(content=PROMPTS["customer_service_system"])]

        for turn in dialog_history[-4:]:
            role = turn.get("role", "user")
            content = _str_content(turn.get("content", ""))
            if role == "user":
                messages.append(HumanMessage(content=content))
            else:
                messages.append(AIMessage(content=content))

        messages.append(HumanMessage(content=user_text))

        tool_calls_this_run: list[dict] = []

        response = self._llm.invoke(messages)
        messages.append(response)

        tool_calls = getattr(response, "tool_calls", None) or []
        if tool_calls:
            for tc in tool_calls:
                tool_name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                tool_args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                tool_id = (tc.get("id") or "") if isinstance(tc, dict) else (getattr(tc, "id", "") or "")

                result = self._call_rag_tool(tool_name, tool_args)
                tool_calls_this_run.append({"tool": tool_name, "args": tool_args, "result": result})
                messages.append(
                    ToolMessage(
                        content=json.dumps(result, ensure_ascii=False),
                        tool_call_id=tool_id,
                    )
                )
            response = self._llm.invoke(messages)

        final_text = _str_content(response.content)
        return {
            "response": final_text,
            "tool_calls": tool_calls_this_run,
            "error": None,
        }

    def _call_rag_tool(self, name: str, args: Any) -> dict:
        from tools.rag_tools import search_faq, search_research_reports, search_knowledge_base
        _map = {
            "search_faq": search_faq,
            "search_research_reports": search_research_reports,
            "search_knowledge_base": search_knowledge_base,
        }
        fn = _map.get(name)
        if fn is None:
            return {"error": f"未知RAG工具: {name}"}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}
        elif not isinstance(args, dict):
            args = {}
        try:
            return fn.invoke(args)
        except Exception as exc:
            return {"error": str(exc)}
