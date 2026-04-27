"""
Configurable risk rules — update here without touching agent code.
All lists/patterns are loaded at import time; hot-reload possible via
a config-center push (e.g. Redis pub/sub) in production.
"""

RISK_RULES = {
    # ── Pre-filter: block before reaching any agent ───────────────────────────
    "blocked_keywords": [
        "内幕消息", "内幕信息", "庄家", "坐庄", "拉抬", "对倒",
        "操纵市场", "洗盘", "割韭菜", "跑路", "非法集资",
        "老鼠仓", "利用未公开信息", "股市黑幕",
    ],

    # ── Post-filter: flag phrases that may constitute investment advice ────────
    "investment_advice_patterns": [
        "强烈推荐买入", "强烈推荐", "一定会涨", "必定上涨", "稳赚不赔",
        "百分之百", "必涨", "肯定涨", "建议买入", "建议买",
        "建议卖出", "建议卖", "赶紧买", "赶快买", "抄底",
        "逃顶", "割仓", "清仓", "满仓", "加仓",
        "现在是最佳买点", "现在买", "马上买",
    ],

    # ── Scenes that MUST append a risk disclaimer ─────────────────────────────
    "disclaimer_required_scenes": [
        "stock_diagnosis",
        "stock_selection",
    ],

    # ── Data validation rules ─────────────────────────────────────────────────
    "data_validation": {
        "pe_ratio": {"min": -500, "max": 5000},        # PE range sanity
        "pb_ratio": {"min": 0, "max": 200},
        "change_pct": {"min": -20.0, "max": 20.0},    # A-share daily limit ±20%
        "roe": {"min": -100, "max": 100},
    },

    # ── Tool call requirements per scene ─────────────────────────────────────
    "mandatory_tools": {
        "stock_diagnosis": ["get_stock_quote"],         # must call at least these
        "stock_selection": ["get_sector_data"],
        "customer_service": ["search_faq"],
        "chat": [],                                     # no mandatory tools
    },
}
