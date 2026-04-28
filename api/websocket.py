"""WebSocket handler for bidirectional real-time chat."""
from __future__ import annotations

import json
import logging
import uuid

from fastapi import WebSocket, WebSocketDisconnect
from langchain_core.messages import HumanMessage

from graph.state import FinancialAgentState

logger = logging.getLogger(__name__)

# Shared session state cache (same as in routes/chat.py for simplicity)
# Production: use Redis-backed session store
_ws_sessions: dict[str, dict] = {}


def _get_graph():
    # Lazy import avoids circular dependency during module load
    from api.routes.chat import _get_graph as _g
    return _g()


async def websocket_chat(websocket: WebSocket) -> None:
    """Handle a single WebSocket connection — multiple messages per connection."""
    await websocket.accept()
    connection_id = str(uuid.uuid4())
    session_id: str | None = None

    logger.info("WebSocket connected: %s", connection_id)

    try:
        graph = _get_graph()

        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"error": "Invalid JSON"})
                continue

            message = data.get("message", "").strip()
            if not message:
                await websocket.send_json({"error": "Empty message"})
                continue

            session_id = data.get("session_id") or session_id or str(uuid.uuid4())
            user_id = data.get("user_id", "anonymous")

            prior_state = _ws_sessions.get(session_id, {})

            state: FinancialAgentState = {
                "session_id": session_id,
                "user_id": user_id,
                "messages": prior_state.get("messages", []) + [HumanMessage(content=message)],
                "current_scene": prior_state.get("current_scene", "unknown"),
                "scene_history": prior_state.get("scene_history", []),
                "detected_intents": [],
                "temp_params": {},
                "user_context": prior_state.get("user_context", {}),
                "tool_call_log": [],
                "risk_check_result": {},
                "error_flag": False,
                "error_message": "",
                "agent_responses": {},
                "final_response": "",
            }

            # Send ack so UI shows typing indicator
            await websocket.send_json({"event": "thinking", "session_id": session_id})

            try:
                async for event in graph.astream_events(state, version="v2"):
                    event_type = event.get("event", "")

                    if event_type == "on_chat_model_stream":
                        chunk = event.get("data", {}).get("chunk")
                        if chunk and hasattr(chunk, "content") and chunk.content:
                            await websocket.send_json({
                                "event": "token",
                                "token": chunk.content,
                                "session_id": session_id,
                            })

                    elif event_type == "on_chain_end" and event.get("name") == "LangGraph":
                        output = event.get("data", {}).get("output", {})
                        final_response = output.get("final_response", "")
                        scene = output.get("current_scene", "unknown")

                        _ws_sessions[session_id] = {
                            "messages": list(output.get("messages", []))[-20:],
                            "current_scene": scene,
                            "scene_history": list(output.get("scene_history", [])),
                            "user_context": output.get("user_context", {}),
                        }

                        await websocket.send_json({
                            "event": "done",
                            "response": final_response,
                            "scene": scene,
                            "session_id": session_id,
                            "error": output.get("error_message") or None,
                        })

            except Exception as exc:
                logger.exception("Graph error for session %s", session_id)
                await websocket.send_json({
                    "event": "error",
                    "error": str(exc),
                    "session_id": session_id,
                })

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: %s (session=%s)", connection_id, session_id)
    except Exception as exc:
        logger.exception("WebSocket error: %s", exc)
        try:
            await websocket.send_json({"event": "error", "error": str(exc)})
        except Exception:
            pass
