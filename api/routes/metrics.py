"""Metrics endpoint."""
from __future__ import annotations

from fastapi import APIRouter

from observability.metrics import metrics

router = APIRouter()


@router.get("/metrics")
async def get_metrics() -> dict:
    return metrics.report()
