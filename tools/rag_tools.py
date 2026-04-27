"""
RAG retrieval tools — mock Milvus/ES/MySQL implementations.
In production, replace with real vector DB queries (Milvus) and ES full-text search.
"""
from __future__ import annotations

from langchain_core.tools import tool

# ── Mock knowledge bases ───────────────────────────────────────────────────────

_FAQ_DB: list[dict] = [
    {
        "q": "如何开户",
        "a": "您可以通过我们的APP完成在线开户，全程约15分钟，需准备身份证和银行卡。",
        "category": "账户",
    },
    {
        "q": "佣金费率是多少",
        "a": "股票交易佣金为万分之二点五，最低5元。ETF基金佣金为万分之一点五。",
        "category": "费率",
    },
    {
        "q": "T+1是什么意思",
        "a": "T+1指当日买入的股票需要等到下一个交易日才能卖出，是A股市场的交易规则。",
        "category": "规则",
    },
    {
        "q": "涨跌停规则",
        "a": "A股主板和创业板涨跌幅限制为±10%（科创板为±20%），ST股票为±5%。",
        "category": "规则",
    },
    {
        "q": "融资融券条件",
        "a": "开通融资融券须满足：开户满6个月、日均资产20万元以上、通过知识测评。",
        "category": "业务",
    },
]

_RESEARCH_DB: list[dict] = [
    {
        "title": "白酒行业2024年中期研究报告",
        "summary": "白酒行业整体需求稳健，高端化趋势持续，龙头企业市场份额进一步集中。",
        "source": "国泰君安",
        "date": "2024-07",
    },
    {
        "title": "新能源行业跟踪报告",
        "summary": "动力电池出货量同比增长35%，储能业务高速增长，海外市场拓展顺利。",
        "source": "中信证券",
        "date": "2024-08",
    },
]


def _simple_keyword_match(query: str, records: list[dict], field: str) -> list[dict]:
    """Simple keyword overlap scoring (replaces vector similarity in mock)."""
    scored = []
    q_tokens = set(query)
    for r in records:
        text = str(r.get(field, ""))
        overlap = len(set(text) & q_tokens)
        if overlap > 0:
            scored.append((overlap, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored]


# ── LangChain tool definitions ────────────────────────────────────────────────

@tool
def search_faq(query: str, top_k: int = 3) -> dict:
    """从FAQ知识库检索与用户问题最相关的答案。query为用户问题文本。"""
    results = _simple_keyword_match(query, _FAQ_DB, "q")[:top_k]
    if not results:
        results = _simple_keyword_match(query, _FAQ_DB, "a")[:top_k]
    return {
        "query": query,
        "results": results,
        "source": "FAQ知识库",
        "count": len(results),
    }


@tool
def search_research_reports(query: str, top_k: int = 3) -> dict:
    """从研究报告库检索相关研报摘要。query为搜索关键词或问题。"""
    results = _simple_keyword_match(query, _RESEARCH_DB, "title")[:top_k]
    if not results:
        results = _simple_keyword_match(query, _RESEARCH_DB, "summary")[:top_k]
    return {
        "query": query,
        "results": results,
        "source": "研报知识库",
        "count": len(results),
    }


@tool
def search_knowledge_base(query: str, top_k: int = 5) -> dict:
    """综合检索（FAQ + 研报），适用于通用问答场景。"""
    faq_results = _simple_keyword_match(query, _FAQ_DB, "q")[:2]
    report_results = _simple_keyword_match(query, _RESEARCH_DB, "title")[:2]
    return {
        "query": query,
        "faq_results": faq_results,
        "report_results": report_results,
        "source": "综合知识库",
    }


RAG_TOOLS = [search_faq, search_research_reports, search_knowledge_base]
