"""Service layer for feedback persistence via Supabase."""
from __future__ import annotations

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_supabase = None


def _get_supabase_client():
    global _supabase
    if _supabase is None:
        try:
            from supabase import create_client
        except ImportError:
            raise RuntimeError("supabase package not installed. Run: pip install supabase")
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError("Supabase credentials not configured (SUPABASE_URL, SUPABASE_KEY)")
        _supabase = create_client(url, key)
    return _supabase


async def store_feedback(
    message_id: str,
    session_id: str,
    rating: int,
    comment: Optional[str] = None,
) -> str:
    """Store feedback in Supabase and return the feedback ID."""
    client = _get_supabase_client()

    data = {
        "message_id": message_id,
        "session_id": session_id,
        "rating": rating,
        "comment": comment,
    }

    response = client.table("user_feedback").insert(data).execute()

    if not response.data:
        raise RuntimeError("Failed to insert feedback: empty response")

    feedback_id = response.data[0]["id"]
    logger.info("Feedback stored: %s (rating=%d)", feedback_id, rating)
    return feedback_id
