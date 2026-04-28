"""
诊股 Agent — 个股全方位分析
强制工具锁：所有数值类问题必须经过工具调用，禁止杜撰数据。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage, AIMessage

from config.llm_factory import create_llm
from config.prompts import PROMPTS
from tools.financial_tools import FINANCIAL_TOOLS

logger = logging.getLogger(__name__)

_MAX_TOOL_ROUNDS = 3


def _str_content(content: Any) -> str:
    """Normalize LLM response content to plain string.

    Some providers (Qwen/DashScope) return content as a list of blocks.
    ChatTongyi's internal formatter then does content[0] on an empty list
    → IndexError. We normalize early to avoid this.
    """
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


class StockDiagnosisAgent:
    def __init__(self) -> None:
        self._llm = create_llm(tier="analysis", bind_tools=FINANCIAL_TOOLS)

    def run(
        self,
        user_text: str,
        stock_codes: list[str],
        dialog_history: list[dict],
        tool_call_log: list[dict],
    ) -> dict[str, Any]:
        messages = [SystemMessage(content=PROMPTS["stock_diagnosis_system"])]

        for turn in dialog_history[-4:]:
            role = turn.get("role", "user")
            content = _str_content(turn.get("content", ""))
            if role == "user":
                messages.append(HumanMessage(content=content))
            else:
                messages.append(AIMessage(content=content))

        hint = f"（股票代码：{', '.join(stock_codes)}）" if stock_codes else ""
        messages.append(HumanMessage(content=f"{user_text}{hint}"))

        tool_calls_this_run: list[dict] = []
        response: Any = None

        for _ in range(_MAX_TOOL_ROUNDS):
            response = self._llm.invoke(messages)

            tool_calls = getattr(response, "tool_calls", None) or []

            if not tool_calls:
                # No more tool calls — done
                messages.append(AIMessage(content=_str_content(response.content)))
                break

            # Append original response to preserve tool_call metadata for LLM history
            messages.append(response)

            for tc in tool_calls:
                tool_name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                tool_args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                tool_id = (tc.get("id") or "") if isinstance(tc, dict) else (getattr(tc, "id", "") or "")

                tool_result = self._call_tool(tool_name, tool_args)
                tool_calls_this_run.append({"tool": tool_name, "args": tool_args, "result": tool_result})
                messages.append(
                    ToolMessage(
                        content=json.dumps(tool_result, ensure_ascii=False),
                        tool_call_id=tool_id,
                    )
                )

        final_text = _str_content(response.content) if response is not None else ""
        return {
            "response": final_text,
            "tool_calls": tool_calls_this_run,
            "error": None,
        }

    def _call_tool(self, name: str, args: Any) -> dict:
        from tools.financial_tools import (
            get_stock_quote, get_financial_report, get_valuation,
            get_sector_data, get_stock_screening,
        )
        _map = {
            "get_stock_quote": get_stock_quote,
            "get_financial_report": get_financial_report,
            "get_valuation": get_valuation,
            "get_sector_data": get_sector_data,
            "get_stock_screening": get_stock_screening,
        }
        fn = _map.get(name)
        if fn is None:
            return {"error": f"未知工具: {name}"}
        # Normalize args: some providers return JSON string or list instead of dict
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
            logger.warning("Tool %s failed: %s", name, exc)
            return {"error": str(exc)}
