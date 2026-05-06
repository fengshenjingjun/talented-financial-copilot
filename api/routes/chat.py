"""Chat endpoints: single-turn REST + SSE streaming."""
from __future__ import annotations

import json
import time
import uuid
import logging
from typing import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage

from api.schemas import ChatRequest, ChatResponse
from graph.state import FinancialAgentState
from security.input_guard import InputGuard

logger = logging.getLogger(__name__)
router = APIRouter()
_input_guard = InputGuard()

# Only stream tokens from these nodes; router/risk nodes output internal JSON
_STREAMING_NODES = frozenset({
    "chat_node", "stock_diagnosis_node",
    "stock_selection_node", "customer_service_node",
})

_graph = None


def _get_graph():
    global _graph
    if _graph is None:
        from graph.workflow import build_graph
        _graph = build_graph()
    return _graph


def _build_state(request: ChatRequest, session_state: dict) -> FinancialAgentState:
    return {
        "session_id": request.session_id or str(uuid.uuid4()),
        "user_id": request.user_id,
        "messages": session_state.get("messages", []) + [HumanMessage(content=request.message)],
        "current_scene": session_state.get("current_scene", "unknown"),
        "scene_history": session_state.get("scene_history", []),
        "detected_intents": [],
        "temp_params": {},
        "user_context": session_state.get("user_context", {}),
        "tool_call_log": [],
        "reasoning_trace": [],
        "visualization_data": [],
        "risk_check_result": {},
        "security_check_result": {},
        "error_flag": False,
        "error_message": "",
        "agent_responses": {},
        "final_response": "",
    }


def _api_input_guard_check(message: str) -> tuple[bool, str]:
    """Fast API-layer input guard check. Returns (ok, block_reason)."""
    result = _input_guard.scan(message)
    if result.action == "block":
        return False, (
            "检测到输入包含可疑的攻击特征，为了保障系统安全，该请求已被拦截。"
            "如有疑问请联系客服。"
        )
    return True, ""


_session_cache: dict[str, dict] = {}


def _update_session_cache(session_id: str, output: dict) -> None:
    _session_cache[session_id] = {
        "messages": list(output.get("messages", []))[-20:],
        "current_scene": output.get("current_scene", "unknown"),
        "scene_history": list(output.get("scene_history", [])),
        "user_context": output.get("user_context", {}),
    }


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Single-turn synchronous chat endpoint."""
    # API-layer input guard (Layer 1 defence — early exit)
    ok, block_reason = _api_input_guard_check(request.message)
    if not ok:
        return ChatResponse(
            response=block_reason,
            session_id=request.session_id or str(uuid.uuid4()),
            scene="blocked",
            latency_ms=0.0,
            degraded=False,
            error="input_guard_blocked",
        )

    graph = _get_graph()
    session_id = request.session_id or str(uuid.uuid4())

    prior_state = _session_cache.get(session_id, {})
    state = _build_state(request, prior_state)
    state["session_id"] = session_id

    t0 = time.time()
    result = graph.invoke(state)
    latency_ms = (time.time() - t0) * 1000

    _update_session_cache(session_id, result)

    response_text = result.get("final_response", "")
    degraded = bool(result.get("agent_responses", {}) and
                    any(r.get("degraded") for r in result["agent_responses"].values()
                        if isinstance(r, dict)))

    return ChatResponse(
        response=response_text,
        session_id=session_id,
        scene=result.get("current_scene", "unknown"),
        latency_ms=round(latency_ms, 2),
        degraded=degraded,
        error=result.get("error_message") or None,
        reasoning_trace=result.get("reasoning_trace", []),
        visualization_data=result.get("visualization_data", []),
        tool_call_log=result.get("tool_call_log", []),
    )


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """SSE streaming chat endpoint."""
    # API-layer input guard (Layer 1 defence — early exit)
    ok, block_reason = _api_input_guard_check(request.message)
    if not ok:
        async def _blocked_stream() -> AsyncGenerator[str, None]:
            payload = json.dumps({"token": block_reason}, ensure_ascii=False)
            yield f"data: {payload}\n\n"
            done = json.dumps({"done": True, "error": "input_guard_blocked"}, ensure_ascii=False)
            yield f"data: {done}\n\n"
        return StreamingResponse(
            _blocked_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    graph = _get_graph()
    session_id = request.session_id or str(uuid.uuid4())
    prior_state = _session_cache.get(session_id, {})
    state = _build_state(request, prior_state)
    state["session_id"] = session_id

    async def event_generator() -> AsyncGenerator[str, None]:
        tokens_streamed = 0
        finished = False

        try:
            async for event in graph.astream_events(state, version="v2"):
                event_type = event.get("event", "")
                event_name = event.get("name", "")

                if event_type == "on_chat_model_stream":
                    node = event.get("metadata", {}).get("langgraph_node", "")
                    if node not in _STREAMING_NODES:
                        continue
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        payload = json.dumps({"token": chunk.content}, ensure_ascii=False)
                        yield f"data: {payload}\n\n"
                        tokens_streamed += 1

                elif event_type == "on_tool_start":
                    payload = json.dumps({
                        "event": "tool_call",
                        "tool_name": event.get("name", ""),
                        "status": "started",
                    }, ensure_ascii=False)
                    yield f"data: {payload}\n\n"

                elif event_type == "on_tool_end":
                    payload = json.dumps({
                        "event": "tool_call",
                        "tool_name": event.get("name", ""),
                        "status": "completed",
                    }, ensure_ascii=False)
                    yield f"data: {payload}\n\n"

                elif event_type == "on_chain_end" and event_name == "LangGraph":
                    output = event.get("data", {}).get("output", {})
                    final_response = output.get("final_response", "")
                    scene = output.get("current_scene", "unknown")

                    _update_session_cache(session_id, output)

                    if tokens_streamed == 0 and final_response:
                        payload = json.dumps({"token": final_response}, ensure_ascii=False)
                        yield f"data: {payload}\n\n"

                    reasoning_trace = output.get("reasoning_trace", [])
                    visualization_data = output.get("visualization_data", [])

                    for step in reasoning_trace:
                        yield f"data: {json.dumps({'event': 'reasoning_step', 'step': step}, ensure_ascii=False)}\n\n"

                    for chart in visualization_data:
                        yield f"data: {json.dumps({'event': 'chart_data', 'chart': chart}, ensure_ascii=False)}\n\n"

                    done_payload = json.dumps({
                        "done": True,
                        "session_id": session_id,
                        "scene": scene,
                        "reasoning_trace": reasoning_trace,
                        "visualization_data": visualization_data,
                        "tool_call_log": output.get("tool_call_log", []),
                    }, ensure_ascii=False)
                    yield f"data: {done_payload}\n\n"
                    finished = True

            if not finished:
                logger.warning(
                    "astream_events ended without LangGraph on_chain_end for session %s — falling back to invoke",
                    session_id,
                )
                result = graph.invoke(state)
                final_response = result.get("final_response", "")
                scene = result.get("current_scene", "unknown")
                _update_session_cache(session_id, result)

                if final_response:
                    yield f"data: {json.dumps({'token': final_response}, ensure_ascii=False)}\n\n"

                done_payload = json.dumps({
                    "done": True,
                    "session_id": session_id,
                    "scene": scene,
                    "reasoning_trace": result.get("reasoning_trace", []),
                    "visualization_data": result.get("visualization_data", []),
                    "tool_call_log": result.get("tool_call_log", []),
                }, ensure_ascii=False)
                yield f"data: {done_payload}\n\n"

        except Exception as exc:
            logger.exception("SSE stream error for session %s", session_id)
            error_payload = json.dumps({"error": str(exc)}, ensure_ascii=False)
            yield f"data: {error_payload}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
