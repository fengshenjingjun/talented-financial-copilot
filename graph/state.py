from __future__ import annotations

from typing import Annotated, Any, Sequence
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


def _merge_dict(existing: dict, update: dict) -> dict:
    """Shallow-merge dict updates into existing state."""
    return {**existing, **update}


def _append_list(existing: list, update: list) -> list:
    return existing + update


class FinancialAgentState(TypedDict):
    # ── Identity ───────────────────────────────────────────────────────────────
    session_id: str
    user_id: str

    # ── Dialog (langgraph add_messages reducer deduplicates by id) ─────────────
    messages: Annotated[Sequence[BaseMessage], add_messages]

    # ── Scene management ───────────────────────────────────────────────────────
    current_scene: str          # stock_diagnosis | stock_selection | customer_service | chat
    scene_history: Annotated[list[str], _append_list]
    detected_intents: list[str] # may contain multiple intents

    # ── Extracted params ───────────────────────────────────────────────────────
    temp_params: Annotated[dict[str, Any], _merge_dict]   # stock_code, keywords, …
    user_context: Annotated[dict[str, Any], _merge_dict]  # longer-lived context

    # ── Observability ──────────────────────────────────────────────────────────
    tool_call_log: Annotated[list[dict[str, Any]], _append_list]

    # ── Structured output ─────────────────────────────────────────────────────
    reasoning_trace: Annotated[list[dict[str, Any]], _append_list]
    visualization_data: Annotated[list[dict[str, Any]], _append_list]

    # ── Risk control ──────────────────────────────────────────────────────────
    risk_check_result: Annotated[dict[str, Any], _merge_dict]

    # ── Error handling ────────────────────────────────────────────────────────
    error_flag: bool
    error_message: str

    # ── Output ────────────────────────────────────────────────────────────────
    agent_responses: Annotated[dict[str, str], _merge_dict]  # {scene: text}
    final_response: str
