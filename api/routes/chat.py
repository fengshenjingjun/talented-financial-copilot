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

logger = logging.getLogger(__name__)
router = APIRouter()

# Module-level graph (compiled once on first request)
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
        "risk_check_result": {},
        "error_flag": False,
        "error_message": "",
        "agent_responses": {},
        "final_response": "",
    }


# In-memory session cache (keyed by session_id → last state snapshot)
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
    )


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """SSE streaming chat endpoint.

    Providers that support token-level streaming (Anthropic, OpenAI) emit
    on_chat_model_stream events — tokens appear progressively.
    Non-streaming providers (Qwen, etc.) don't emit those events, so we
    fall back to sending the full response as one chunk when the graph finishes.
    """
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

                # Token-level streaming (Anthropic / OpenAI)
                if event_type == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        payload = json.dumps(
                            {"token": chunk.content}, ensure_ascii=False
                        )
                        yield f"data: {payload}\n\n"
                        tokens_streamed += 1

                # Graph finished — always fired at the end regardless of provider
                elif event_type == "on_chain_end" and event_name == "LangGraph":
                    output = event.get("data", {}).get("output", {})
                    final_response = output.get("final_response", "")
                    scene = output.get("current_scene", "unknown")

                    _update_session_cache(session_id, output)

                    # If no streaming tokens arrived (e.g. Qwen / non-streaming
                    # provider), send the full response as a single chunk now.
                    if tokens_streamed == 0 and final_response:
                        payload = json.dumps(
                            {"token": final_response}, ensure_ascii=False
                        )
                        yield f"data: {payload}\n\n"

                    done_payload = json.dumps(
                        {"done": True, "session_id": session_id, "scene": scene},
                        ensure_ascii=False,
                    )
                    yield f"data: {done_payload}\n\n"
                    finished = True

            # Safety net: if astream_events ended without on_chain_end "LangGraph"
            # (can happen with some LangGraph builds), fall back to invoke.
            if not finished:
                logger.warning(
                    "astream_events ended without LangGraph on_chain_end for "
                    "session %s — falling back to invoke",
                    session_id,
                )
                result = graph.invoke(state)
                final_response = result.get("final_response", "")
                scene = result.get("current_scene", "unknown")
                _update_session_cache(session_id, result)

                if final_response:
                    yield f"data: {json.dumps({'token': final_response}, ensure_ascii=False)}\n\n"

                yield f"data: {json.dumps({'done': True, 'session_id': session_id, 'scene': scene}, ensure_ascii=False)}\n\n"

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
