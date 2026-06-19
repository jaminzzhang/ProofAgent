"""Global approval queue API endpoint for the dashboard."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from proof_agent.observability.api.dependencies import get_store
from proof_agent.observability.storage.run_store import RunStore

router = APIRouter(tags=["approvals"])


@router.get("/approvals")
def list_approvals(
    *,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: str = Query("all", pattern="^(all|pending|expired)$"),
    store: RunStore = Depends(get_store),
) -> dict[str, Any]:
    """List unresolved pending approval queue items.

    `status` scopes the queue: `pending` (not lapsed), `expired` (lapsed
    while unresolved), or `all`. The returned `total` reflects the scoped
    set so the dashboard pager stays consistent.
    """

    approvals, total = store.list_pending_approvals(
        limit=limit, offset=offset, status=status  # type: ignore[arg-type]
    )
    return {
        "data": approvals,
        "meta": {"total": total, "limit": limit, "offset": offset, "status": status},
    }
