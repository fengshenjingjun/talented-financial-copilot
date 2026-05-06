"""
诊股 Agent — 个股全方位分析
强制工具锁：所有数值类问题必须经过工具调用，禁止杜撰数据。
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
from security.prompt_armor import PromptArmor
from security.tool_guard import tool_guard, PermissionLevel, ToolSchema, ParamRule

logger = logging.getLogger(__name__)

_MAX_TOOL_ROUNDS = 3


def _str_content(content: Any) -> str:
    """Normalize LLM response content to plain string."""
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
    keys = [k for k in result if k not in ("data_source", "stock_code")]
    return f"返回字段: {', '.join(keys[:6])}"


def _make_metrics_chart(result: dict, stock_code: str) -> dict | None:
    name = result.get("name", stock_code)
    metric_keys = {"pe": "市盈率", "pb": "市净率", "roe": "ROE(%)", "revenue_yoy": "营收增速(%)", "net_profit_yoy": "净利增速(%)"}
    names, values = [], []
    for k, label in metric_keys.items():
        v = result.get(k)
        if v is not None:
            try:
                names.append(label)
                values.append(round(float(v), 2))
            except (ValueError, TypeError):
                pass
    if not names:
        return None
    return {
        "chart_id": f"metrics_{stock_code}_{int(time.time())}",
        "type": "bar",
        "title": f"{name} 核心指标",
        "data": {
            "tooltip": {"trigger": "axis"},
            "xAxis": {"type": "category", "data": names},
            "yAxis": {"type": "value"},
            "series": [{"name": "数值", "type": "bar", "data": values, "itemStyle": {"color": "#4f7fff"}}],
        },
        "metadata": {"stock_code": stock_code, "data_source": result.get("data_source", "unknown")},
    }


def _make_valuation_chart(result: dict, stock_code: str) -> dict | None:
    name = result.get("name", stock_code)
    pe = result.get("pe")
    pb = result.get("pb")
    industry_pe = result.get("industry_pe_median")
    if pe is None:
        return None
    categories = ["PE(市盈率)", "PB(市净率)"]
    stock_vals = [round(float(pe), 2), round(float(pb), 2) if pb is not None else 0]
    series = [{"name": name, "type": "bar", "data": stock_vals, "itemStyle": {"color": "#4f7fff"}}]
    if industry_pe and industry_pe != "N/A":
        try:
            series.append({
                "name": "行业中位",
                "type": "bar",
                "data": [round(float(industry_pe), 2), 0],
                "itemStyle": {"color": "#22c55e"},
            })
        except (ValueError, TypeError):
            pass
    return {
        "chart_id": f"valuation_{stock_code}_{int(time.time())}",
        "type": "bar",
        "title": f"{name} 估值对比",
        "data": {
            "tooltip": {"trigger": "axis"},
            "legend": {"data": [s["name"] for s in series]},
            "xAxis": {"type": "category", "data": categories},
            "yAxis": {"type": "value"},
            "series": series,
        },
        "metadata": {"stock_code": stock_code, "data_source": result.get("data_source", "unknown")},
    }


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
        hint = f"（股票代码：{', '.join(stock_codes)}）" if stock_codes else ""
        context = f"当前分析目标股票代码：{', '.join(stock_codes)}" if stock_codes else ""

        armor = PromptArmor(core_prompt=PROMPTS["stock_diagnosis_system"])
        messages = armor.build(
            user_text=f"{user_text}{hint}",
            history=dialog_history[-4:],
            context=context,
        )

        tool_calls_this_run: list[dict] = []
        reasoning_steps: list[dict] = []
        charts: list[dict] = []
        response: Any = None

        reasoning_steps.append({
            "step_id": "step_001",
            "timestamp": time.time(),
            "type": "intent_detection",
            "description": f"分析用户意图: {user_text[:60]}",
            "details": {"stock_codes": stock_codes},
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
                tool_result = self._call_tool(tool_name, tool_args)
                step["details"]["result_summary"] = _summarize_result(tool_result)
                step["details"]["duration_ms"] = int((time.time() - t0) * 1000)

                stock_code = tool_args.get("stock_code", stock_codes[0] if stock_codes else "")
                if not tool_result.get("error"):
                    if tool_name in ("get_stock_quote", "get_financial_report"):
                        chart = _make_metrics_chart(tool_result, stock_code)
                        if chart:
                            charts.append(chart)
                    elif tool_name == "get_valuation":
                        chart = _make_valuation_chart(tool_result, stock_code)
                        if chart:
                            charts.append(chart)

                tool_calls_this_run.append({"tool": tool_name, "args": tool_args, "result": tool_result})
                messages.append(
                    ToolMessage(
                        content=json.dumps(tool_result, ensure_ascii=False),
                        tool_call_id=tool_id,
                    )
                )

        reasoning_steps.append({
            "step_id": f"step_{len(reasoning_steps)+1:03d}",
            "timestamp": time.time(),
            "type": "synthesis",
            "description": "综合分析，生成回答",
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

    def _call_tool(self, name: str, args: Any, session_id: str = "global") -> dict:
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
            logger.warning("Tool %s failed: %s", name, exc)
            return {"error": str(exc)}
