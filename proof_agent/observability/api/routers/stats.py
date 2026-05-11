"""Aggregated statistics API endpoint for the dashboard overview."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from proof_agent.observability.api.dependencies import get_store
from proof_agent.observability.storage.run_store import RunStore

router = APIRouter(tags=["stats"])


@router.get("/stats")
def get_stats(
    store: RunStore = Depends(get_store),
) -> dict[str, Any]:
    """Return aggregated run statistics for the Overview page."""
    return store.get_stats()
