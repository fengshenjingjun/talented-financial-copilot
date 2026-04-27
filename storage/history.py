"""
Dialog history store — MongoDB in production, in-memory list as fallback.
Persists full conversation turns for audit, fine-tuning, and replay.
"""
from __future__ import annotations

import time
from typing import Any


class HistoryStore:
    """In-memory dialog history store."""

    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []

    def append(
        self,
        session_id: str,
        user_id: str,
        role: str,
        content: str,
        scene: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._records.append({
            "session_id": session_id,
            "user_id": user_id,
            "role": role,
            "content": content,
            "scene": scene,
            "timestamp": time.time(),
            "metadata": metadata or {},
        })

    def get_session_history(self, session_id: str, limit: int = 20) -> list[dict[str, Any]]:
        records = [r for r in self._records if r["session_id"] == session_id]
        return records[-limit:]

    def get_all(self) -> list[dict[str, Any]]:
        return list(self._records)

    def count(self) -> int:
        return len(self._records)


# Singleton
history_store = HistoryStore()
