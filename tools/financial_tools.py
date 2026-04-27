"""
Financial data tools — mock implementations.
In production, replace each function body with real API calls
(e.g. Tushare, AKShare, Wind, Bloomberg).

All tools are registered with the gateway at module import.
"""
from __future__ import annotations

import random
from typing import Any

from langchain_core.tools import tool


# ── Mock data helpers ──────────────────────────────────────────────────────────

_STOCK_DB: dict[str, dict[str, Any]] = {
    "600519": {
        "name": "贵州茅台",
        "price": 1680.0,
        "change_pct": 1.23,
        "pe": 28.5,
        "pb": 10.2,
        "roe": 35.6,
        "revenue_yoy": 18.2,
        "net_profit_yoy": 19.5,
        "debt_ratio": 15.3,
        "industry": "白酒",
        "market_cap": "21120亿",
    },
    "000858": {
        "name": "五粮液",
        "price": 148.0,
        "change_pct": -0.54,
        "pe": 22.1,
        "pb": 7.8,
        "roe": 31.2,
        "revenue_yoy": 12.1,
        "net_profit_yoy": 14.3,
        "debt_ratio": 11.7,
        "industry": "白酒",
        "market_cap": "5740亿",
    },
    "300750": {
        "name": "宁德时代",
        "price": 212.0,
        "change_pct": 2.15,
        "pe": 18.9,
        "pb": 4.3,
        "roe": 22.8,
        "revenue_yoy": 33.5,
        "net_profit_yoy": 41.2,
        "debt_ratio": 43.2,
        "industry": "新能源电池",
        "market_cap": "5220亿",
    },
}

_SECTOR_DB: dict[str, dict[str, Any]] = {
    "白酒": {
        "change_pct": 0.85,
        "turnover": "234亿",
        "volume_ratio": 1.23,
        "north_flow": "+12.3亿",
        "pe_median": 24.6,
        "top_stocks": ["贵州茅台(+1.23%)", "五粮液(-0.54%)", "洋河股份(+0.32%)"],
        "sentiment": "偏强",
    },
    "新能源": {
        "change_pct": 1.87,
        "turnover": "876亿",
        "volume_ratio": 1.54,
        "north_flow": "+23.1亿",
        "pe_median": 19.2,
        "top_stocks": ["宁德时代(+2.15%)", "比亚迪(+1.8%)", "亿纬锂能(+2.6%)"],
        "sentiment": "强势",
    },
}


# ── LangChain tool definitions ────────────────────────────────────────────────

@tool
def get_stock_quote(stock_code: str) -> dict[str, Any]:
    """获取个股实时行情，包括价格、涨跌幅、市值。stock_code为6位股票代码。"""
    code = stock_code.strip()
    if code in _STOCK_DB:
        data = _STOCK_DB[code].copy()
        data["stock_code"] = code
        data["data_source"] = "mock_api"
        return data
    return {
        "error": f"未找到股票代码 {code} 的行情数据",
        "stock_code": code,
    }


@tool
def get_financial_report(stock_code: str, period: str = "latest") -> dict[str, Any]:
    """获取个股财务报表数据，包括营收、净利润、ROE、负债率。period可为'latest'/'2023'/'2022'。"""
    code = stock_code.strip()
    if code in _STOCK_DB:
        d = _STOCK_DB[code]
        return {
            "stock_code": code,
            "name": d["name"],
            "period": period,
            "revenue_yoy": d["revenue_yoy"],
            "net_profit_yoy": d["net_profit_yoy"],
            "roe": d["roe"],
            "debt_ratio": d["debt_ratio"],
            "data_source": "mock_financial_api",
        }
    return {"error": f"未找到 {code} 财务数据", "stock_code": code}


@tool
def get_valuation(stock_code: str) -> dict[str, Any]:
    """获取个股估值指标，包括PE、PB、PS以及行业横向对比。"""
    code = stock_code.strip()
    if code in _STOCK_DB:
        d = _STOCK_DB[code]
        industry = d["industry"]
        return {
            "stock_code": code,
            "name": d["name"],
            "pe": d["pe"],
            "pb": d["pb"],
            "industry": industry,
            "industry_pe_median": _SECTOR_DB.get(industry, {}).get("pe_median", "N/A"),
            "valuation_comment": (
                "估值低于行业中位数，相对合理"
                if d["pe"] < _SECTOR_DB.get(industry, {}).get("pe_median", 9999)
                else "估值高于行业中位数"
            ),
            "data_source": "mock_valuation_api",
        }
    return {"error": f"未找到 {code} 估值数据", "stock_code": code}


@tool
def get_sector_data(sector_name: str) -> dict[str, Any]:
    """获取板块整体行情，包括涨跌幅、成交额、北向资金流向、龙头股表现。"""
    for key, val in _SECTOR_DB.items():
        if key in sector_name or sector_name in key:
            return {"sector": key, **val, "data_source": "mock_sector_api"}
    return {
        "error": f"未找到板块 '{sector_name}' 的数据，请尝试其他板块名称",
        "sector": sector_name,
    }


@tool
def get_stock_screening(
    min_roe: float = 0.0,
    max_pe: float = 9999.0,
    industry: str = "",
) -> dict[str, Any]:
    """
    按量化条件筛选股票（返回板块统计，不推荐个股）。
    min_roe: 最低ROE，max_pe: 最高PE，industry: 行业过滤。
    """
    matched = []
    for code, d in _STOCK_DB.items():
        if d["roe"] >= min_roe and d["pe"] <= max_pe:
            if not industry or industry in d["industry"]:
                matched.append({"code": code, "name": d["name"], "pe": d["pe"], "roe": d["roe"]})
    return {
        "query": {"min_roe": min_roe, "max_pe": max_pe, "industry": industry},
        "count": len(matched),
        "sample": matched[:5],
        "note": "筛选结果仅供参考，不构成投资建议",
        "data_source": "mock_screening_api",
    }


# ── Collect all tools for LangChain bind_tools ────────────────────────────────
FINANCIAL_TOOLS = [
    get_stock_quote,
    get_financial_report,
    get_valuation,
    get_sector_data,
    get_stock_screening,
]
