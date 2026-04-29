"""
选股 Agent — 板块与行业分析
约束：禁止推荐个股、禁止具体投资策略。所有数据来自工具。
"""
from __future__ import annotations

import json
import time
import logging
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage, AIMessage

from config.llm_factory import create_llm
from config.prompts import PROMPTS
from tools.financial_tools import FINANCIAL_TOOLS

logger = logging.getLogger(__name__)

_MAX_TOOL_ROUNDS = 3


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


def _summarize_result(result: dict) -> str:
    if "error" in result:
        return f"错误: {result['error']}"
    keys = [k for k in result if k not in ("data_source",)]
    return f"返回字段: {', '.join(keys[:6])}"


def _make_sector_chart(result: dict) -> dict | None:
    sector = result.get("sector", "板块")
    top_stocks = result.get("top_stocks", [])
    if not top_stocks:
        return None
    names, changes = [], []
    for s in top_stocks:
        if isinstance(s, str) and "(" in s and "%" in s:
            parts = s.rsplit("(", 1)
            name = parts[0].strip()
            pct_str = parts[1].rstrip(")%").strip()
            try:
                names.append(name)
                changes.append(round(float(pct_str), 2))
            except ValueError:
                pass
    if not names:
        return None
    colors = ["#22c55e" if v >= 0 else "#ef4444" for v in changes]
    return {
        "chart_id": f"sector_{sector}_{int(time.time())}",
        "type": "bar",
        "title": f"{sector} 板块龙头涨跌",
        "data": {
            "tooltip": {"trigger": "axis"},
            "xAxis": {"type": "category", "data": names},
            "yAxis": {"type": "value", "axisLabel": {"formatter": "{value}%"}},
            "series": [{
                "name": "涨跌幅",
                "type": "bar",
                "data": [{"value": v, "itemStyle": {"color": c}} for v, c in zip(changes, colors)],
            }],
        },
        "metadata": {"sector": sector, "data_source": result.get("data_source", "unknown")},
    }


def _make_screening_chart(result: dict) -> dict | None:
    sample = result.get("sample", [])
    if not sample:
        return None
    names = [f"{s.get('name', s.get('code', '?'))}" for s in sample]
    roes = [round(float(s.get("roe", 0)), 2) for s in sample]
    return {
        "chart_id": f"screening_{int(time.time())}",
        "type": "bar",
        "title": "筛选结果 ROE 对比",
        "data": {
            "tooltip": {"trigger": "axis"},
            "xAxis": {"type": "category", "data": names},
            "yAxis": {"type": "value", "axisLabel": {"formatter": "{value}%"}},
            "series": [{"name": "ROE(%)", "type": "bar", "data": roes, "itemStyle": {"color": "#4f7fff"}}],
        },
        "metadata": {"query": result.get("query", {}), "data_source": result.get("data_source", "unknown")},
    }


class StockSelectionAgent:
    def __init__(self) -> None:
        self._llm = create_llm(tier="analysis", bind_tools=FINANCIAL_TOOLS)

    def run(
        self,
        user_text: str,
        keywords: list[str],
        dialog_history: list[dict],
    ) -> dict[str, Any]:
        messages = [SystemMessage(content=PROMPTS["stock_selection_system"])]

        for turn in dialog_history[-4:]:
            role = turn.get("role", "user")
            content = _str_content(turn.get("content", ""))
            if role == "user":
                messages.append(HumanMessage(content=content))
            else:
                messages.append(AIMessage(content=content))

        hint = f"（相关关键词：{', '.join(keywords)}）" if keywords else ""
        messages.append(HumanMessage(content=f"{user_text}{hint}"))

        tool_calls_this_run: list[dict] = []
        reasoning_steps: list[dict] = []
        charts: list[dict] = []
        response: Any = None

        reasoning_steps.append({
            "step_id": "step_001",
            "timestamp": time.time(),
            "type": "intent_detection",
            "description": f"分析板块/选股意图: {user_text[:60]}",
            "details": {"keywords": keywords},
        })

        for _ in range(_MAX_TOOL_ROUNDS):
            response = self._llm.invoke(messages)
            tool_calls = getattr(response, "tool_calls", None) or []

            if not tool_calls:
                messages.append(AIMessage(content=_str_content(response.content)))
                break

            messages.append(response)

            for tc in tool_calls:
                tool_name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                tool_args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                tool_id = (tc.get("id") or "") if isinstance(tc, dict) else (getattr(tc, "id", "") or "")

                step: dict[str, Any] = {
                    "step_id": f"step_{len(reasoning_steps)+1:03d}",
                    "timestamp": time.time(),
                    "type": "tool_call",
                    "description": f"调用工具 {tool_name}",
                    "details": {"tool_name": tool_name, "args": tool_args},
                }
                reasoning_steps.append(step)

                t0 = time.time()
                result = self._call_tool(tool_name, tool_args)
                step["details"]["result_summary"] = _summarize_result(result)
                step["details"]["duration_ms"] = int((time.time() - t0) * 1000)

                if not result.get("error"):
                    if tool_name == "get_sector_data":
                        chart = _make_sector_chart(result)
                        if chart:
                            charts.append(chart)
                    elif tool_name == "get_stock_screening":
                        chart = _make_screening_chart(result)
                        if chart:
                            charts.append(chart)

                tool_calls_this_run.append({"tool": tool_name, "args": tool_args, "result": result})
                messages.append(
                    ToolMessage(
                        content=json.dumps(result, ensure_ascii=False),
                        tool_call_id=tool_id,
                    )
                )

        reasoning_steps.append({
            "step_id": f"step_{len(reasoning_steps)+1:03d}",
            "timestamp": time.time(),
            "type": "synthesis",
            "description": "综合板块数据，生成回答",
            "details": {"tool_calls_count": len(tool_calls_this_run), "charts_count": len(charts)},
        })

        final_text = _str_content(response.content) if response is not None else ""
        return {
            "response": final_text,
            "tool_calls": tool_calls_this_run,
            "error": None,
            "reasoning_steps": reasoning_steps,
            "charts": charts,
        }

    def _call_tool(self, name: str, args: Any) -> dict:
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
