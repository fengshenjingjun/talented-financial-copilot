"""
诊股 Agent — 个股全方位分析
强制工具锁：所有数值类问题必须经过工具调用，禁止杜撰数据。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage, AIMessage

from config.settings import settings
from config.prompts import PROMPTS
from tools.financial_tools import FINANCIAL_TOOLS

logger = logging.getLogger(__name__)

_MAX_TOOL_ROUNDS = 3  # prevent infinite tool loops


class StockDiagnosisAgent:
    def __init__(self) -> None:
        self._llm = ChatAnthropic(
            model=settings.analysis_model,
            temperature=settings.analysis_temperature,
            api_key=settings.anthropic_api_key,
        ).bind_tools(FINANCIAL_TOOLS)

    def run(
        self,
        user_text: str,
        stock_codes: list[str],
        dialog_history: list[dict],
        tool_call_log: list[dict],
    ) -> dict[str, Any]:
        """
        Returns {
            "response": str,      # final answer text
            "tool_calls": list,   # tools invoked during this run
            "error": str | None,
        }
        """
        messages = [SystemMessage(content=PROMPTS["stock_diagnosis_system"])]

        # Inject recent dialog context (last 4 turns)
        for turn in dialog_history[-4:]:
            role = turn.get("role", "user")
            if role == "user":
                messages.append(HumanMessage(content=turn["content"]))
            else:
                messages.append(AIMessage(content=turn["content"]))

        # Current user question
        hint = f"（股票代码：{', '.join(stock_codes)}）" if stock_codes else ""
        messages.append(HumanMessage(content=f"{user_text}{hint}"))

        tool_calls_this_run: list[dict] = []

        for _ in range(_MAX_TOOL_ROUNDS):
            response = self._llm.invoke(messages)
            messages.append(response)

            if not response.tool_calls:
                break  # LLM finished, no more tool calls

            # Execute each tool call
            for tc in response.tool_calls:
                tool_name = tc["name"]
                tool_args = tc["args"]
                tool_result = self._call_tool(tool_name, tool_args)
                tool_calls_this_run.append({
                    "tool": tool_name,
                    "args": tool_args,
                    "result": tool_result,
                })
                messages.append(
                    ToolMessage(
                        content=json.dumps(tool_result, ensure_ascii=False),
                        tool_call_id=tc["id"],
                    )
                )

        final_text = response.content if isinstance(response.content, str) else ""
        return {
            "response": final_text,
            "tool_calls": tool_calls_this_run,
            "error": None,
        }

    def _call_tool(self, name: str, args: dict) -> dict:
        from tools.financial_tools import (
            get_stock_quote,
            get_financial_report,
            get_valuation,
            get_sector_data,
            get_stock_screening,
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
        try:
            return fn.invoke(args)
        except Exception as exc:
            logger.warning("Tool %s failed: %s", name, exc)
            return {"error": str(exc)}
