"""Run history API endpoints for the dashboard."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from proof_agent.contracts.dashboard import RunPurpose
from proof_agent.contracts.receipt import ReceiptOutcome
from proof_agent.observability.api.dependencies import get_operator_identity, get_store
from proof_agent.observability.api.operator_identity import (
    OperatorIdentityContext,
    OperatorPermission,
    require_operator_permission,
)
from proof_agent.observability.api.serializers import serialize_run_detail, serialize_run_summary
from proof_agent.observability.storage.run_store import RunStore

router = APIRouter(tags=["runs"])


@router.get("/runs")
def list_runs(
    *,
    outcome: str | None = Query(None, description="Filter by receipt outcome"),
    run_purpose: str | None = Query(
        None,
        description="Filter by run purpose: production, validation, evaluation_sample, or all",
    ),
    search: str | None = Query(None, description="Search run ID or question text"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    store: RunStore = Depends(get_store),
) -> dict[str, Any]:
    """List run summaries with optional filtering and pagination."""
    outcome_enum = _parse_outcome(outcome)
    purpose_filter = _parse_run_purpose(run_purpose)
    runs, total = store.list_runs(
        outcome=outcome_enum,
        run_purpose=purpose_filter,
        search=search,
        limit=limit,
        offset=offset,
    )
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


@router.get("/runs/{run_id}/validation-capture")
def get_validation_capture(
    run_id: str,
    request: Request,
    store: RunStore = Depends(get_store),
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Get a sensitive validation-only capture artifact for authorized operators."""

    require_operator_permission(identity, OperatorPermission.AGENT_VALIDATE)
    detail = store.get_run_detail(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    if detail.run_purpose is not RunPurpose.VALIDATION:
        raise HTTPException(status_code=404, detail=f"Validation capture not found: {run_id}")
    if not detail.validation_capture_id:
        raise HTTPException(status_code=404, detail=f"Validation capture not found: {run_id}")

    configuration_store = getattr(request.app.state, "agent_configuration_store", None)
    if configuration_store is None:
        raise HTTPException(status_code=404, detail=f"Validation capture not found: {run_id}")
    artifact = configuration_store.get_sensitive_validation_capture_artifact(
        detail.validation_capture_id
    )
    if artifact is None or artifact.run_id != run_id:
        raise HTTPException(status_code=404, detail=f"Validation capture not found: {run_id}")
    if _iso_timestamp_expired(artifact.expires_at):
        raise HTTPException(status_code=404, detail=f"Validation capture not found: {run_id}")
    payload = configuration_store.read_sensitive_validation_capture_payload(artifact.capture_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Validation capture not found: {run_id}")
    return {
        "metadata": artifact.model_dump(mode="json"),
        "payload": payload,
    }


def _iso_timestamp_expired(value: str) -> bool:
    if not value:
        return True
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed <= datetime.now(UTC)


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


def _parse_run_purpose(value: str | None) -> RunPurpose | None:
    """Convert a query string into a RunPurpose enum, defaulting to production."""
    if value is None:
        return RunPurpose.PRODUCTION
    normalized = value.lower()
    if normalized == "all":
        return None
    try:
        return RunPurpose(normalized)
    except ValueError:
        valid = ", ".join([*(purpose.value for purpose in RunPurpose), "all"])
        raise HTTPException(
            status_code=400,
            detail=f"Invalid run_purpose filter: {value}. Valid values: {valid}",
        ) from None
