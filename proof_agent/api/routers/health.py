"""Health check endpoint for the dashboard API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from proof_agent.api.dependencies import get_store
from proof_agent.storage.run_store import RunStore

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check(
    store: RunStore = Depends(get_store),
) -> dict[str, Any]:
    """Return a readiness summary with basic diagnostics."""
    stats = store.get_stats()
    return {
        "status": "ok",
        "version": "0.1.0",
        "history_dir": str(store.history_dir),
        "total_runs": stats["total_runs"],
    }
