"""
LangGraph Workflow — 全局状态机
节点流程：
  preprocess → pre_risk → router → dispatch
     ↓ (parallel via Send)
  [stock_diagnosis | stock_selection | customer_service | chat]
     ↓
  merge → post_risk → persist → END
"""
from __future__ import annotations

import time
import uuid
import logging
from typing import Any

from langchain_core.messages import HumanMessage, AIMessage
from langgraph.graph import StateGraph, END, START
from langgraph.types import Send, Command

from graph.state import FinancialAgentState
from agents.router_agent import RouterAgent
from agents.stock_diagnosis_agent import StockDiagnosisAgent
from agents.stock_selection_agent import StockSelectionAgent
from agents.customer_service_agent import CustomerServiceAgent
from agents.chat_agent import ChatAgent
from risk.pre_filter import pre_filter
from risk.post_filter import post_filter
from storage.session import session_store
from storage.history import history_store
from observability.tracer import tracer
from observability.metrics import metrics
from utils.exception_handler import handle_exceptions

logger = logging.getLogger(__name__)

# ── Singletons (one instance per process) ────────────────────────────────────
_router = RouterAgent()
_stock_diagnosis = StockDiagnosisAgent()
_stock_selection = StockSelectionAgent()
_customer_service = CustomerServiceAgent()
_chat = ChatAgent()


# ── Helper ────────────────────────────────────────────────────────────────────

def _get_dialog_history(state: FinancialAgentState) -> list[dict]:
    """Extract plain dict history from LangChain messages for agent context."""
    history = []
    for msg in state.get("messages", []):
        if isinstance(msg, HumanMessage):
            history.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            history.append({"role": "assistant", "content": msg.content})
    return history


def _latest_user_text(state: FinancialAgentState) -> str:
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            return str(msg.content)
    return ""


# ══════════════════════════════════════════════════════════════════════════════
# Node definitions
# ══════════════════════════════════════════════════════════════════════════════

def preprocess_node(state: FinancialAgentState) -> dict[str, Any]:
    """输入清洗 + 会话状态绑定。"""
    session_id = state.get("session_id") or str(uuid.uuid4())
    user_id = state.get("user_id") or "anonymous"

    # Restore persistent scene from session store
    persisted = session_store.get(session_id)
    current_scene = persisted.get("current_scene", state.get("current_scene", "unknown"))

    return {
        "session_id": session_id,
        "user_id": user_id,
        "current_scene": current_scene,
        "error_flag": False,
        "error_message": "",
    }


@handle_exceptions(
    tier="complete",
    fallback_value={
        "final_response": "抱歉，系统暂时无法处理您的请求，请稍后再试。如需帮助，请联系客服热线。",
        "error_flag": True,
    },
    metrics_key="workflow.pre_risk",
    log_level="error",
)
def pre_risk_node(state: FinancialAgentState) -> dict[str, Any]:
    """前置风控：敏感词检测，命中则直接终止并返回拦截提示。"""
    user_text = _latest_user_text(state)
    result = pre_filter(user_text)

    tracer.log_risk_event(
        state["session_id"], "pre_filter",
        blocked=not result["passed"],
        reason=result.get("blocked_reason", ""),
    )

    if not result["passed"]:
        metrics.risk_blocked("pre_filter")
        block_msg = f"⚠️ 您的问题包含违规内容，无法回答。（{result['blocked_reason']}）"
        return {
            "risk_check_result": {"pre_passed": False, "blocked_reason": result["blocked_reason"]},
            "final_response": block_msg,
            "error_flag": True,
            "error_message": result["blocked_reason"],
        }

    return {
        "risk_check_result": {"pre_passed": True},
    }


@handle_exceptions(
    tier="complete",
    fallback_value={},
    metrics_key="workflow.router",
    log_level="error",
)
def router_node(state: FinancialAgentState) -> dict[str, Any]:
    """三级意图识别 + 场景路由。"""
    if state.get("error_flag"):
        return {}

    user_text = _latest_user_text(state)
    routing = _router.route(
        user_text,
        state.get("current_scene", "unknown"),
        list(state.get("scene_history", [])),
    )

    primary = routing.get("primary_intent", "chat")
    metrics.scene_hit(primary)

    logger.info(
        "router: intents=%s confidence=%.2f reason=%s",
        routing.get("intents"),
        routing.get("confidence", 0),
        routing.get("reason", ""),
    )

    return {
        "detected_intents": routing.get("intents", [primary]),
        "current_scene": primary,
        "scene_history": [primary],
        "temp_params": {
            "stock_codes": routing.get("stock_codes", []),
            "keywords": routing.get("keywords", []),
            "needs_data": routing.get("needs_data", False),
        },
    }


def dispatch_node(state: FinancialAgentState) -> Command:
    """
    分发节点：根据检测到的意图向对应Agent节点发送 Command+Send 命令。
    多意图时并行触发多个Agent（LangGraph fan-out）。
    """
    if state.get("error_flag"):
        # Skip agent nodes entirely, go straight to merge
        return Command(goto="merge")

    intents = state.get("detected_intents", ["chat"])
    sends = [Send(f"{intent}_node", state) for intent in intents]
    return Command(goto=sends)


@handle_exceptions(
    tier="partial",
    fallback_value={"agent_responses": {}, "tool_call_log": []},
    metrics_key="workflow.stock_diagnosis",
    scene_context="stock_diagnosis",
    retry_count=1,
    timeout_seconds=60,
)
def stock_diagnosis_node(state: FinancialAgentState) -> dict[str, Any]:
    """诊股 Agent 节点。"""
    user_text = _latest_user_text(state)
    temp = state.get("temp_params", {})
    history = _get_dialog_history(state)

    t0 = time.time()
    result = _stock_diagnosis.run(
        user_text=user_text,
        stock_codes=temp.get("stock_codes", []),
        dialog_history=history,
        tool_call_log=list(state.get("tool_call_log", [])),
    )
    metrics.record_latency("agent.stock_diagnosis", (time.time() - t0) * 1000)

    tool_log = [{"agent": "stock_diagnosis", **tc} for tc in result.get("tool_calls", [])]
    return {
        "agent_responses": {"stock_diagnosis": result.get("response", "")},
        "tool_call_log": tool_log,
        "reasoning_trace": [
            {**step, "agent": "stock_diagnosis"}
            for step in result.get("reasoning_steps", [])
        ],
        "visualization_data": [
            {**chart, "agent": "stock_diagnosis"}
            for chart in result.get("charts", [])
        ],
    }


@handle_exceptions(
    tier="partial",
    fallback_value={"agent_responses": {}, "tool_call_log": []},
    metrics_key="workflow.stock_selection",
    scene_context="stock_selection",
    retry_count=1,
    timeout_seconds=60,
)
def stock_selection_node(state: FinancialAgentState) -> dict[str, Any]:
    """选股 Agent 节点。"""
    user_text = _latest_user_text(state)
    temp = state.get("temp_params", {})
    history = _get_dialog_history(state)

    t0 = time.time()
    result = _stock_selection.run(
        user_text=user_text,
        keywords=temp.get("keywords", []),
        dialog_history=history,
    )
    metrics.record_latency("agent.stock_selection", (time.time() - t0) * 1000)

    tool_log = [{"agent": "stock_selection", **tc} for tc in result.get("tool_calls", [])]
    return {
        "agent_responses": {"stock_selection": result.get("response", "")},
        "tool_call_log": tool_log,
        "reasoning_trace": [
            {**step, "agent": "stock_selection"}
            for step in result.get("reasoning_steps", [])
        ],
        "visualization_data": [
            {**chart, "agent": "stock_selection"}
            for chart in result.get("charts", [])
        ],
    }


@handle_exceptions(
    tier="partial",
    fallback_value={"agent_responses": {}, "tool_call_log": []},
    metrics_key="workflow.customer_service",
    scene_context="customer_service",
    retry_count=1,
    timeout_seconds=60,
)
def customer_service_node(state: FinancialAgentState) -> dict[str, Any]:
    """客服 Agent 节点。"""
    user_text = _latest_user_text(state)
    history = _get_dialog_history(state)

    t0 = time.time()
    result = _customer_service.run(
        user_text=user_text,
        dialog_history=history,
    )
    metrics.record_latency("agent.customer_service", (time.time() - t0) * 1000)

    tool_log = [{"agent": "customer_service", **tc} for tc in result.get("tool_calls", [])]
    return {
        "agent_responses": {"customer_service": result.get("response", "")},
        "tool_call_log": tool_log,
        "reasoning_trace": [
            {**step, "agent": "customer_service"}
            for step in result.get("reasoning_steps", [])
        ],
        "visualization_data": [
            {**chart, "agent": "customer_service"}
            for chart in result.get("charts", [])
        ],
    }


@handle_exceptions(
    tier="fallback",
    fallback_value={"agent_responses": {"chat": "抱歉，我暂时无法回答，请稍后再试。"}},
    metrics_key="workflow.chat",
    scene_context="chat",
)
def chat_node(state: FinancialAgentState) -> dict[str, Any]:
    """闲聊 Agent 节点。"""
    user_text = _latest_user_text(state)
    history = _get_dialog_history(state)

    t0 = time.time()
    result = _chat.run(user_text=user_text, dialog_history=history)
    metrics.record_latency("agent.chat", (time.time() - t0) * 1000)

    return {
        "agent_responses": {"chat": result.get("response", "")},
        "reasoning_trace": [
            {**step, "agent": "chat"}
            for step in result.get("reasoning_steps", [])
        ],
        "visualization_data": [],
    }


@handle_exceptions(
    tier="fallback",
    fallback_value={"final_response": "抱歉，我暂时无法处理您的请求，请稍后重试。"},
    metrics_key="workflow.merge",
)
def merge_node(state: FinancialAgentState) -> dict[str, Any]:
    """合并多Agent回复（多意图时拼接；单意图直接透传）。"""
    if state.get("error_flag"):
        return {}

    responses = state.get("agent_responses", {})
    if not responses:
        return {
            "final_response": "抱歉，我暂时无法处理您的请求，请稍后重试。",
            "error_flag": True,
        }

    if len(responses) == 1:
        raw = next(iter(responses.values()))
    else:
        # Multi-intent: join with a clear separator
        parts = []
        scene_labels = {
            "stock_diagnosis": "【个股分析】",
            "stock_selection": "【板块行情】",
            "customer_service": "【平台客服】",
            "chat": "【对话】",
        }
        for scene, text in responses.items():
            label = scene_labels.get(scene, f"【{scene}】")
            parts.append(f"{label}\n{text}")
        raw = "\n\n---\n\n".join(parts)

    return {
        "final_response": raw,
        "reasoning_trace": [],    # already accumulated; return empty to avoid re-append
        "visualization_data": [],
    }


@handle_exceptions(
    tier="complete",
    fallback_value={},
    metrics_key="workflow.post_risk",
    log_level="error",
)
def post_risk_node(state: FinancialAgentState) -> dict[str, Any]:
    """后置风控：合规过滤 + 强制风险提示。"""
    if state.get("error_flag") and not state.get("final_response"):
        return {}

    scene = state.get("current_scene", "chat")
    text = state.get("final_response", "")
    result = post_filter(text, scene)

    if not result["passed"]:
        tracer.log_risk_event(
            state["session_id"], "post_filter",
            blocked=True,
            reason=f"过滤违规话术: {result['blocked_phrases']}",
        )
        metrics.risk_blocked("post_filter")

    return {
        "final_response": result["filtered_text"],
        "risk_check_result": {
            "post_passed": result["passed"],
            "blocked_phrases": result["blocked_phrases"],
            "disclaimer_added": result["disclaimer_added"],
        },
    }


@handle_exceptions(
    tier="fallback",
    fallback_value={},
    metrics_key="workflow.persist",
)
def persist_node(state: FinancialAgentState) -> dict[str, Any]:
    """持久化：更新 session store + 写入 dialog history。"""
    session_id = state["session_id"]
    user_id = state["user_id"]
    scene = state.get("current_scene", "unknown")

    session_store.set_scene(session_id, scene)
    session_store.update(session_id, {
        "user_context": state.get("user_context", {}),
        "temp_params": state.get("temp_params", {}),
    })

    user_text = _latest_user_text(state)
    final = state.get("final_response", "")

    history_store.append(session_id, user_id, "user", user_text, scene)
    history_store.append(session_id, user_id, "assistant", final, scene)

    # Append AI message back to the message chain for next turn
    return {
        "messages": [AIMessage(content=final)],
    }


def error_handler_node(state: FinancialAgentState) -> dict[str, Any]:
    """降级处理：Agent异常时返回安全兜底回答。"""
    err = state.get("error_message", "未知错误")
    logger.error("Error handler invoked: %s", err)
    fallback = (
        "抱歉，系统暂时无法处理您的请求，请稍后再试。"
        "如需帮助，请联系客服热线。"
    )
    if not state.get("final_response"):
        return {"final_response": fallback}
    return {}


# ══════════════════════════════════════════════════════════════════════════════
# Graph construction
# ══════════════════════════════════════════════════════════════════════════════

def build_graph() -> StateGraph:
    graph = StateGraph(FinancialAgentState)

    # ── Register nodes ────────────────────────────────────────────────────────
    graph.add_node("preprocess", preprocess_node)
    graph.add_node("pre_risk", pre_risk_node)
    graph.add_node("router", router_node)
    graph.add_node("dispatch", dispatch_node)
    graph.add_node("stock_diagnosis_node", stock_diagnosis_node)
    graph.add_node("stock_selection_node", stock_selection_node)
    graph.add_node("customer_service_node", customer_service_node)
    graph.add_node("chat_node", chat_node)
    graph.add_node("merge", merge_node)
    graph.add_node("post_risk", post_risk_node)
    graph.add_node("persist", persist_node)
    graph.add_node("error_handler", error_handler_node)

    # ── Linear edges ─────────────────────────────────────────────────────────
    graph.add_edge(START, "preprocess")
    graph.add_edge("preprocess", "pre_risk")

    # After pre_risk: if blocked, skip to error_handler; else continue to router
    graph.add_conditional_edges(
        "pre_risk",
        lambda s: "error_handler" if s.get("error_flag") else "router",
        {"router": "router", "error_handler": "error_handler"},
    )

    graph.add_edge("router", "dispatch")
    # dispatch_node returns Command(goto=...) which handles fan-out internally

    # All agent nodes → merge
    for node in [
        "stock_diagnosis_node",
        "stock_selection_node",
        "customer_service_node",
        "chat_node",
    ]:
        graph.add_edge(node, "merge")

    graph.add_edge("merge", "post_risk")
    graph.add_edge("post_risk", "persist")
    graph.add_edge("persist", END)
    graph.add_edge("error_handler", END)

    return graph.compile()
