"""Run history API endpoints for the dashboard."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from proof_agent.observability.api.dependencies import get_store
from proof_agent.observability.api.serializers import serialize_run_detail, serialize_run_summary
from proof_agent.contracts.receipt import ReceiptOutcome
from proof_agent.observability.storage.run_store import RunStore

router = APIRouter(tags=["runs"])


@router.get("/runs")
def list_runs(
    *,
    outcome: str | None = Query(None, description="Filter by receipt outcome"),
    search: str | None = Query(None, description="Search run ID or question text"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    store: RunStore = Depends(get_store),
) -> dict[str, Any]:
    """List run summaries with optional filtering and pagination."""
    outcome_enum = _parse_outcome(outcome)
    runs, total = store.list_runs(outcome=outcome_enum, search=search, limit=limit, offset=offset)
    return {
        "data": [serialize_run_summary(run) for run in runs],
        "meta": {"total": total, "limit": limit, "offset": offset},
    }


@router.get("/runs/{run_id}")
def get_run(
    run_id: str,
    store: RunStore = Depends(get_store),
) -> dict[str, Any]:
    """Get full run detail by run ID."""
    detail = store.get_run_detail(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return serialize_run_detail(detail)


@router.get("/runs/{run_id}/trace")
def get_run_trace(
    run_id: str,
    store: RunStore = Depends(get_store),
) -> dict[str, Any]:
    """Get trace events for a specific run."""
    detail = store.get_run_detail(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return {
        "run_id": run_id,
        "events": list(detail.trace_events),
        "event_count": len(detail.trace_events),
    }


@router.get("/runs/{run_id}/receipt")
def get_run_receipt(
    run_id: str,
    store: RunStore = Depends(get_store),
) -> dict[str, Any]:
    """Get the governance receipt markdown for a specific run."""
    detail = store.get_run_detail(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return {
        "run_id": run_id,
        "receipt_markdown": detail.receipt_markdown,
    }


@router.post("/runs/{run_id}/approve/{approval_id}")
def approve_tool_call(
    run_id: str,
    approval_id: str,
    store: RunStore = Depends(get_store),
) -> dict[str, Any]:
    """Approve a pending tool execution. (Not Implemented in MVP)"""
    raise HTTPException(
        status_code=501, 
        detail="Dashboard execution resumption is not implemented in the current MVP. Use the CLI to approve."
    )


@router.post("/runs/{run_id}/deny/{approval_id}")
def deny_tool_call(
    run_id: str,
    approval_id: str,
    store: RunStore = Depends(get_store),
) -> dict[str, Any]:
    """Deny a pending tool execution. (Not Implemented in MVP)"""
    raise HTTPException(
        status_code=501, 
        detail="Dashboard execution resumption is not implemented in the current MVP. Use the CLI to deny."
    )


def _parse_outcome(value: str | None) -> ReceiptOutcome | None:
    """Convert a query string into a ReceiptOutcome enum, or None."""
    if value is None:
        return None
    try:
        return ReceiptOutcome(value)
    except ValueError:
        valid = ", ".join(o.value for o in ReceiptOutcome)
        raise HTTPException(
            status_code=400,
            detail=f"Invalid outcome filter: {value}. Valid values: {valid}",
        ) from None
