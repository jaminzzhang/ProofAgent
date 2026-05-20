"""Internal customer handoff monitor API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from proof_agent.contracts import HandoffReason
from proof_agent.observability.api.dependencies import get_store
from proof_agent.observability.storage.handoff_projection import extract_handoffs
from proof_agent.observability.storage.run_store import RunStore


router = APIRouter(tags=["handoffs"])


@router.get("/handoffs")
def list_handoffs(
    *,
    reason: str | None = Query(None, description="Filter by handoff reason"),
    limit: int = Query(500, ge=1, le=1000),
    store: RunStore = Depends(get_store),
) -> dict[str, Any]:
    """List internal customer handoffs projected from persisted traces."""

    reason_filter = HandoffReason(reason) if reason else None
    runs, _ = store.list_runs(limit=limit, offset=0)
    handoffs = []
    for run in runs:
        detail = store.get_run_detail(run.run_id)
        if detail is None:
            continue
        for handoff in extract_handoffs(detail.trace_events):
            if reason_filter is not None and handoff.reason != reason_filter:
                continue
            handoffs.append(handoff)
    return {"data": [handoff.model_dump(mode="json") for handoff in handoffs]}
