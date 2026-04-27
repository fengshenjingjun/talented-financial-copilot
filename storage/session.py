"""
Session store — Redis in production, in-memory dict as fallback.
Stores per-session scene labels and context for multi-turn coherence.
"""
from __future__ import annotations

import json
import time
from typing import Any


class SessionStore:
    """In-memory session store (swap _backend for Redis in production)."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        self._ttl: dict[str, float] = {}
        self._default_ttl = 3600  # 1 hour

    # ── Public API ─────────────────────────────────────────────────────────────

    def get(self, session_id: str) -> dict[str, Any]:
        self._evict_expired()
        return self._store.get(session_id, {})

    def set(self, session_id: str, data: dict[str, Any], ttl: int | None = None) -> None:
        self._store[session_id] = data
        self._ttl[session_id] = time.time() + (ttl or self._default_ttl)

    def update(self, session_id: str, patch: dict[str, Any]) -> None:
        current = self.get(session_id)
        current.update(patch)
        self.set(session_id, current)

    def delete(self, session_id: str) -> None:
        self._store.pop(session_id, None)
        self._ttl.pop(session_id, None)

    def get_scene(self, session_id: str) -> str:
        return self.get(session_id).get("current_scene", "unknown")

    def set_scene(self, session_id: str, scene: str) -> None:
        self.update(session_id, {"current_scene": scene})

    # ── Internal ───────────────────────────────────────────────────────────────

    def _evict_expired(self) -> None:
        now = time.time()
        expired = [k for k, exp in self._ttl.items() if exp < now]
        for k in expired:
            self._store.pop(k, None)
            self._ttl.pop(k, None)


# Singleton for the process
session_store = SessionStore()
