"""
选股 Agent — 板块与行业分析
约束：禁止推荐个股、禁止具体投资策略。所有数据来自工具。
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

_MAX_TOOL_ROUNDS = 3


class StockSelectionAgent:
    def __init__(self) -> None:
        self._llm = ChatAnthropic(
            model=settings.analysis_model,
            temperature=settings.analysis_temperature,
            api_key=settings.anthropic_api_key,
        ).bind_tools(FINANCIAL_TOOLS)

    def run(
        self,
        user_text: str,
        keywords: list[str],
        dialog_history: list[dict],
    ) -> dict[str, Any]:
        messages = [SystemMessage(content=PROMPTS["stock_selection_system"])]

        for turn in dialog_history[-4:]:
            role = turn.get("role", "user")
            if role == "user":
                messages.append(HumanMessage(content=turn["content"]))
            else:
                messages.append(AIMessage(content=turn["content"]))

        hint = f"（相关关键词：{', '.join(keywords)}）" if keywords else ""
        messages.append(HumanMessage(content=f"{user_text}{hint}"))

        tool_calls_this_run: list[dict] = []

        for _ in range(_MAX_TOOL_ROUNDS):
            response = self._llm.invoke(messages)
            messages.append(response)

            if not response.tool_calls:
                break

            for tc in response.tool_calls:
                tool_name = tc["name"]
                tool_args = tc["args"]
                result = self._call_tool(tool_name, tool_args)
                tool_calls_this_run.append({
                    "tool": tool_name,
                    "args": tool_args,
                    "result": result,
                })
                messages.append(
                    ToolMessage(
                        content=json.dumps(result, ensure_ascii=False),
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
            get_stock_quote, get_sector_data, get_stock_screening,
            get_financial_report, get_valuation,
        )
        _map = {
            "get_stock_quote": get_stock_quote,
            "get_sector_data": get_sector_data,
            "get_stock_screening": get_stock_screening,
            "get_financial_report": get_financial_report,
            "get_valuation": get_valuation,
        }
        fn = _map.get(name)
        if fn is None:
            return {"error": f"未知工具: {name}"}
        try:
            return fn.invoke(args)
        except Exception as exc:
            return {"error": str(exc)}
