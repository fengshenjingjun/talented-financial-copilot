"""
客服 Agent — 强RAG模式，答案100%来自知识库。
"""
from __future__ import annotations

import json
import time
import logging
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage, AIMessage

from config.llm_factory import create_llm
from config.prompts import PROMPTS
from tools.rag_tools import RAG_TOOLS
from security.prompt_armor import PromptArmor
from security.tool_guard import tool_guard

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
        armor = PromptArmor(core_prompt=PROMPTS["customer_service_system"])
        messages = armor.build(
            user_text=user_text,
            history=dialog_history[-4:],
        )

        tool_calls_this_run: list[dict] = []
        reasoning_steps: list[dict] = []

        reasoning_steps.append({
            "step_id": "step_001",
            "timestamp": time.time(),
            "type": "intent_detection",
            "description": f"客服查询: {user_text[:60]}",
            "details": {},
        })

        response = self._llm.invoke(messages)
        messages.append(response)

        tool_calls = getattr(response, "tool_calls", None) or []
        if tool_calls:
            for tc in tool_calls:
                tool_name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                tool_args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                tool_id = (tc.get("id") or "") if isinstance(tc, dict) else (getattr(tc, "id", "") or "")

                step: dict[str, Any] = {
                    "step_id": f"step_{len(reasoning_steps)+1:03d}",
                    "timestamp": time.time(),
                    "type": "tool_call",
                    "description": f"检索知识库: {tool_name}",
                    "details": {"tool_name": tool_name, "args": tool_args},
                }
                reasoning_steps.append(step)

                t0 = time.time()
                result = self._call_rag_tool(tool_name, tool_args)
                step["details"]["duration_ms"] = int((time.time() - t0) * 1000)
                step["details"]["result_summary"] = f"检索到 {len(str(result))} 字符" if not result.get("error") else f"错误: {result['error']}"

                tool_calls_this_run.append({"tool": tool_name, "args": tool_args, "result": result})
                messages.append(
                    ToolMessage(
                        content=json.dumps(result, ensure_ascii=False),
                        tool_call_id=tool_id,
                    )
                )
            response = self._llm.invoke(messages)

        reasoning_steps.append({
            "step_id": f"step_{len(reasoning_steps)+1:03d}",
            "timestamp": time.time(),
            "type": "synthesis",
            "description": "基于知识库生成客服回答",
            "details": {"tool_calls_count": len(tool_calls_this_run)},
        })

        final_text = _str_content(response.content)
        return {
            "response": final_text,
            "tool_calls": tool_calls_this_run,
            "error": None,
            "reasoning_steps": reasoning_steps,
            "charts": [],
        }

    def _call_rag_tool(self, name: str, args: Any, session_id: str = "global") -> dict:
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

        # Layer 3: Tool Guard validation
        check = tool_guard.validate_call(session_id, name, args)
        if not check["ok"]:
            return {"error": check["reason"], "tool": name}

        try:
            result = fn.invoke(args)
            return tool_guard.sanitise_return(name, result)
        except Exception as exc:
            return {"error": str(exc)}
