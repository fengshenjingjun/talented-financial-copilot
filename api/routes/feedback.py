"""User feedback endpoint."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from api.schemas import FeedbackRequest

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/feedback")
async def submit_feedback(request: FeedbackRequest) -> dict:
    """Submit thumbs up/down feedback for a message."""
    try:
        from services.feedback_service import store_feedback

        feedback_id = await store_feedback(
            message_id=request.message_id,
            session_id=request.session_id,
            rating=request.rating,
            comment=request.comment,
        )
        return {"success": True, "feedback_id": feedback_id}

    except RuntimeError as exc:
        # Supabase not configured or unavailable
        if "not configured" in str(exc) or "not installed" in str(exc):
            logger.warning("Feedback storage unavailable: %s", exc)
            raise HTTPException(status_code=503, detail="Feedback service temporarily unavailable")
        logger.exception("Failed to store feedback")
        raise HTTPException(status_code=500, detail=str(exc))

    except Exception as exc:
        logger.exception("Failed to store feedback")
        raise HTTPException(status_code=500, detail=str(exc))
