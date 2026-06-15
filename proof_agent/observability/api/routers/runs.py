"""Run history API endpoints for the dashboard."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from proof_agent.contracts import TraceEventType
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
from proof_agent.runtime.approval_resume import LangGraphApprovalResumeRegistry
from proof_agent.runtime.langgraph_runner import resume_langgraph_approval

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
    payload = configuration_store.read_sensitive_validation_capture_payload(
        artifact.capture_id
    )
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Validation capture not found: {run_id}")
    return {
        "metadata": artifact.model_dump(mode="json"),
        "payload": payload,
    }


@router.post("/runs/{run_id}/approvals/{approval_id}/approve")
def approve_tool_call(
    run_id: str,
    approval_id: str,
    request: Request,
    store: RunStore = Depends(get_store),
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Record approval for a pending tool execution."""

    require_operator_permission(identity, OperatorPermission.APPROVAL_RESOLVE)
    resumed = _resume_pending_approval_if_possible(
        run_id=run_id,
        approval_id=approval_id,
        approved=True,
        identity=identity,
        request=request,
        store=store,
    )
    if resumed is not None:
        return resumed
    return _resolve_pending_approval(
        run_id=run_id,
        approval_id=approval_id,
        event_type=TraceEventType.APPROVAL_GRANTED,
        event_status="ok",
        resolved_state="granted",
        identity=identity,
        store=store,
    )


@router.post("/runs/{run_id}/approvals/{approval_id}/deny")
def deny_tool_call(
    run_id: str,
    approval_id: str,
    request: Request,
    store: RunStore = Depends(get_store),
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Record denial for a pending tool execution."""

    require_operator_permission(identity, OperatorPermission.APPROVAL_RESOLVE)
    resumed = _resume_pending_approval_if_possible(
        run_id=run_id,
        approval_id=approval_id,
        approved=False,
        identity=identity,
        request=request,
        store=store,
    )
    if resumed is not None:
        return resumed
    return _resolve_pending_approval(
        run_id=run_id,
        approval_id=approval_id,
        event_type=TraceEventType.APPROVAL_DENIED,
        event_status="blocked",
        resolved_state="denied",
        identity=identity,
        store=store,
    )


def _resume_pending_approval_if_possible(
    *,
    run_id: str,
    approval_id: str,
    approved: bool,
    identity: OperatorIdentityContext,
    request: Request,
    store: RunStore,
) -> dict[str, Any] | None:
    detail = store.get_run_detail(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    _get_pending_approval_or_raise(detail, approval_id)

    registry = _approval_resume_registry(request)
    with registry.claim(run_id) as claim:
        if not claim.acquired:
            raise HTTPException(
                status_code=409,
                detail=f"Approval resume already in progress: {approval_id}",
            )

        detail = store.get_run_detail(run_id)
        if detail is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        pending = _get_pending_approval_or_raise(detail, approval_id)
        _raise_if_pending_approval_expired(
            run_id=run_id,
            approval_id=approval_id,
            pending=pending,
            actor=identity.operator_id,
            store=store,
        )

        context = registry.get(run_id)
        if context is None:
            return None

        resume_langgraph_approval(
            context.agent_yaml,
            runs_dir=context.runs_dir,
            run_id=context.run_id,
            question=context.question,
            approval_id=approval_id,
            approved=approved,
            actor=identity.operator_id,
            checkpointer=context.checkpointer,
            store=store,
            manifest=context.manifest,
            resolved_knowledge_bindings=context.resolved_knowledge_bindings,
            configuration_store=context.configuration_store,
            run_purpose=context.run_purpose,
            agent_id=context.agent_id,
            agent_version_id=context.agent_version_id,
            draft_id=context.draft_id,
            allow_untrusted_web_supplement=context.allow_untrusted_web_supplement,
            execution_input=context.workflow_template_execution_input,
        )
        registry.discard(run_id)
    updated = store.get_run_detail(run_id)
    if updated is None:
        raise HTTPException(status_code=500, detail=f"Run disappeared after resume: {run_id}")
    return serialize_run_detail(updated)


def _resolve_pending_approval(
    *,
    run_id: str,
    approval_id: str,
    event_type: TraceEventType,
    event_status: Literal["ok", "blocked", "waiting", "error"],
    resolved_state: str,
    identity: OperatorIdentityContext,
    store: RunStore,
) -> dict[str, Any]:
    detail = store.get_run_detail(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    pending = _find_pending_approval(detail.pending_approvals, approval_id)
    if pending is None:
        if _has_terminal_approval(detail.trace_events, approval_id):
            raise HTTPException(
                status_code=409,
                detail=f"Approval already resolved: {approval_id}",
            )
        raise HTTPException(
            status_code=404,
            detail=f"Pending approval not found: {approval_id}",
        )
    _raise_if_pending_approval_expired(
        run_id=run_id,
        approval_id=approval_id,
        pending=pending,
        actor=identity.operator_id,
        store=store,
    )

    appended = store.append_trace_event(
        run_id,
        event_type=event_type,
        status=event_status,
        payload={
            "approval_id": approval_id,
            "tool_name": pending.get("tool_name"),
            "action_id": pending.get("action_id"),
            "state": resolved_state,
            "actor": identity.operator_id,
            "permission": OperatorPermission.APPROVAL_RESOLVE.value,
        },
    )
    if not appended:
        raise HTTPException(status_code=500, detail=f"Trace not appendable for run: {run_id}")

    updated = store.get_run_detail(run_id)
    if updated is None:
        raise HTTPException(status_code=500, detail=f"Run disappeared after update: {run_id}")
    return serialize_run_detail(updated)


def _raise_if_pending_approval_expired(
    *,
    run_id: str,
    approval_id: str,
    pending: dict[str, Any],
    actor: str,
    store: RunStore,
) -> None:
    if not _pending_approval_expired(pending):
        return
    appended = store.append_trace_event(
        run_id,
        event_type=TraceEventType.APPROVAL_TIMEOUT,
        status="blocked",
        payload={
            "approval_id": approval_id,
            "tool_name": pending.get("tool_name"),
            "action_id": pending.get("action_id"),
            "state": "timed_out",
            "expires_at": pending.get("expires_at"),
            "actor": actor,
        },
    )
    if not appended:
        raise HTTPException(status_code=500, detail=f"Trace not appendable for run: {run_id}")
    raise HTTPException(status_code=409, detail=f"Approval expired: {approval_id}")


def _pending_approval_expired(pending: dict[str, Any]) -> bool:
    expires_at = pending.get("expires_at")
    if not isinstance(expires_at, str) or not expires_at:
        return True
    try:
        parsed = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed <= datetime.now(UTC)


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


def _find_pending_approval(
    pending_approvals: tuple[dict[str, Any], ...],
    approval_id: str,
) -> dict[str, Any] | None:
    return next(
        (
            approval
            for approval in pending_approvals
            if approval.get("approval_id") == approval_id
        ),
        None,
    )


def _get_pending_approval_or_raise(
    detail: Any,
    approval_id: str,
) -> dict[str, Any]:
    pending = _find_pending_approval(detail.pending_approvals, approval_id)
    if pending is not None:
        return pending
    if _has_terminal_approval(detail.trace_events, approval_id):
        raise HTTPException(
            status_code=409,
            detail=f"Approval already resolved: {approval_id}",
        )
    raise HTTPException(
        status_code=404,
        detail=f"Pending approval not found: {approval_id}",
    )


def _has_terminal_approval(
    trace_events: tuple[dict[str, Any], ...],
    approval_id: str,
) -> bool:
    return any(
        event.get("event_type")
        in {
            TraceEventType.APPROVAL_GRANTED.value,
            TraceEventType.APPROVAL_DENIED.value,
            TraceEventType.APPROVAL_TIMEOUT.value,
        }
        and event.get("payload", {}).get("approval_id") == approval_id
        for event in trace_events
    )


def _approval_resume_registry(request: Request) -> LangGraphApprovalResumeRegistry:
    registry = getattr(request.app.state, "approval_resume_registry", None)
    if isinstance(registry, LangGraphApprovalResumeRegistry):
        return registry
    store = getattr(request.app.state, "store", None)
    root = (
        store.history_dir.parent / "approval_resume"
        if isinstance(store, RunStore)
        else Path("runs/approval_resume")
    )
    return LangGraphApprovalResumeRegistry(root)


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
