from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from proof_agent.contracts.ports.run_queue import (
    RunClaimRejectedError,
    RunIdempotencyConflictError,
    RunQueueOverloadedError,
    RunQueueRepository,
    RunConversationBusyError,
)
from proof_agent.contracts.ports.conversations import ConversationRepository
from proof_agent.contracts.dashboard import RunPurpose
from proof_agent.contracts.conversation import ConversationRecord
from proof_agent.contracts.receipt import ReceiptOutcome
from proof_agent.contracts.run_execution import RunLifecycleState, RunQueueRecord
from proof_agent.delivery.published_agents import PublishedAgentRegistry
from proof_agent.delivery.run_cancellation_service import RunCancellationService
from proof_agent.delivery.run_submission_service import (
    RunSubmissionRejectedError,
    RunSubmissionService,
)
from proof_agent.delivery.run_progress_service import RunProgressService
from proof_agent.delivery.run_artifact_results import (
    RunArtifactResultError,
    RunArtifactResultReader,
)
from proof_agent.observability.api.dependencies import get_operator_identity
from proof_agent.observability.api.operator_identity import (
    OperatorIdentityContext,
    OperatorPermission,
    require_operator_permission,
)
from proof_agent.observability.api.serializers import serialize_run_detail
from proof_agent.observability.storage.conversation_store import ConversationStore


router = APIRouter(tags=["run-queue"])


class QueuedRunSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1, max_length=255)
    question: str = Field(min_length=1, max_length=32_768)
    conversation_id: str | None = None
    allow_untrusted_web_supplement: bool = False


@router.get("/stats")
def get_queue_stats(
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, object]:
    """Project Dashboard statistics only from the durable production queue."""

    require_operator_permission(identity, OperatorPermission.RUN_VIEW)
    repository = _repository(request)
    _, total = repository.list_page(
        limit=1,
        offset=0,
        run_purpose=RunPurpose.PRODUCTION,
    )
    distribution: dict[str, int] = {}
    for receipt_outcome in ReceiptOutcome:
        _, count = repository.list_page(
            limit=1,
            offset=0,
            run_purpose=RunPurpose.PRODUCTION,
            receipt_outcome=receipt_outcome,
        )
        if count:
            distribution[receipt_outcome.value] = count
    return {
        "total_runs": total,
        "outcome_distribution": distribution,
        "pending_approvals": distribution.get(
            ReceiptOutcome.WAITING_FOR_APPROVAL.value,
            0,
        ),
    }


@router.get("/runs")
def list_queued_runs(
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
    outcome: str | None = Query(default=None),
    run_purpose: str | None = Query(default="production"),
    state: str | None = Query(default=None),
    search: str | None = Query(default=None, min_length=1, max_length=256),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    require_operator_permission(identity, OperatorPermission.RUN_VIEW)
    try:
        purpose = None if run_purpose == "all" else RunPurpose(run_purpose)
        outcome_filter = None if outcome is None else ReceiptOutcome(outcome)
        states = () if state is None else (RunLifecycleState(state),)
        records, total = _repository(request).list_page(
            limit=limit,
            offset=offset,
            run_purpose=purpose,
            search=search,
            states=states,
            receipt_outcome=outcome_filter,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="invalid_run_filter") from exc
    return {
        "data": [_summary_projection(record) for record in records],
        "meta": {"total": total, "limit": limit, "offset": offset},
    }


@router.post("/runs", status_code=202)
def submit_run(
    body: QueuedRunSubmission,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
    idempotency_key: str = Header(
        min_length=1,
        max_length=128,
        alias="Idempotency-Key",
    ),
) -> JSONResponse:
    require_operator_permission(identity, OperatorPermission.RUN_SUBMIT)
    published_agent = _registry(request).resolve(body.agent_id)
    if published_agent is None:
        raise HTTPException(status_code=404, detail="published_agent_not_found")
    conversation_turn_count = None
    if body.conversation_id is not None:
        conversation = _conversation(request, body.conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="conversation_not_found")
        if conversation.agent_id != body.agent_id:
            raise HTTPException(status_code=409, detail="conversation_agent_mismatch")
        conversation_turn_count = len(conversation.turns)
    try:
        record, created = RunSubmissionService(_repository(request)).submit(
            published_agent=published_agent,
            question=body.question,
            operator_subject=identity.operator_id,
            idempotency_key=idempotency_key,
            permission_mapping_version_id=identity.permission_mapping_version_id,
            permission_epoch=identity.permission_epoch,
            institution_authorization=identity.institution_authorization,
            conversation_id=body.conversation_id,
            conversation_turn_count=conversation_turn_count,
            allow_untrusted_web_supplement=body.allow_untrusted_web_supplement,
        )
    except RunQueueOverloadedError as exc:
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(exc.retry_after_seconds)},
            content={
                "detail": "run_queue_overloaded",
                "capacity": exc.capacity,
            },
        )
    except RunIdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail="idempotency_conflict") from exc
    except RunConversationBusyError as exc:
        raise HTTPException(status_code=409, detail="conversation_run_active") from exc
    except (RunSubmissionRejectedError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    response = _projection(record)
    response["created"] = created
    return JSONResponse(status_code=202, content=response)


@router.get("/runs/{run_id}")
def get_queued_run(
    run_id: str,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    require_operator_permission(identity, OperatorPermission.RUN_VIEW)
    try:
        record = _repository(request).get(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="run_not_found") from exc
    if record is None:
        raise HTTPException(status_code=404, detail="run_not_found")
    queue_projection = _projection(record)
    if not record.result.result_available:
        return queue_projection
    if _result_reader(request) is None:
        return queue_projection
    detail = _load_result(request, record)
    final_output = next(
        (
            event.get("payload")
            for event in reversed(detail["trace_events"])
            if event.get("event_type") == "final_output"
        ),
        None,
    )
    exact_queue_projection = dict(queue_projection)
    if exact_queue_projection["outcome"] is None:
        exact_queue_projection.pop("outcome")
    for field in _RESULT_DETAIL_FIELDS:
        exact_queue_projection.pop(field, None)
    return {
        **detail,
        **exact_queue_projection,
        "final_output": final_output,
    }


@router.get("/runs/{run_id}/trace")
def get_queued_run_trace(
    run_id: str,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    require_operator_permission(identity, OperatorPermission.RUN_VIEW)
    record = _require_record(request, run_id)
    detail = _load_result(request, record)
    return {
        "run_id": run_id,
        "events": detail["trace_events"],
        "event_count": len(detail["trace_events"]),
    }


@router.get("/runs/{run_id}/receipt")
def get_queued_run_receipt(
    run_id: str,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    require_operator_permission(identity, OperatorPermission.RUN_VIEW)
    record = _require_record(request, run_id)
    detail = _load_result(request, record)
    return {
        "run_id": run_id,
        "receipt_markdown": detail["receipt_markdown"],
    }


@router.get("/runs/{run_id}/progress")
async def stream_run_progress(
    run_id: str,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> StreamingResponse:
    require_operator_permission(identity, OperatorPermission.RUN_VIEW)
    repository = _repository(request)
    try:
        record = repository.get(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="run_not_found") from exc
    if record is None:
        raise HTTPException(status_code=404, detail="run_not_found")
    service = RunProgressService(repository)
    return StreamingResponse(
        service.stream(run_id=run_id, disconnected=request.is_disconnected),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/runs/{run_id}/cancel", status_code=202)
def cancel_run(
    run_id: str,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> JSONResponse:
    require_operator_permission(identity, OperatorPermission.RUN_CANCEL)
    try:
        record = RunCancellationService(_repository(request)).cancel(
            run_id=run_id,
            operator_subject=identity.operator_id,
        )
    except (RunClaimRejectedError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="run_cancel_rejected") from exc
    return JSONResponse(status_code=202, content=_projection(record))


def _projection(record: RunQueueRecord) -> dict[str, Any]:
    run_id = record.request.run_id
    failure_code = None if record.failure is None else record.failure.code.value
    return {
        "contract_version": record.request.contract_version,
        "run_id": run_id,
        "state": record.state.value,
        "state_version": record.state_version,
        "question": record.request.question,
        "run_purpose": record.request.run_purpose.value,
        "agent_id": record.request.agent_id,
        "agent_version_id": record.request.agent_version_id,
        "result_available": record.result.result_available,
        "artifact_manifest_id": record.result.artifact_manifest_id,
        "outcome": (
            None
            if record.result.receipt_outcome is None
            else record.result.receipt_outcome.value
        ),
        "failure_code": failure_code,
        "error_code": failure_code,
        "enqueued_at": record.enqueued_at.isoformat(),
        "started_at": (
            None if record.started_at is None else record.started_at.isoformat()
        ),
        "completed_at": (
            None if record.completed_at is None else record.completed_at.isoformat()
        ),
        "updated_at": record.updated_at.isoformat(),
        "created_at": record.enqueued_at.isoformat(),
        "draft_id": None,
        "validation_capture_id": None,
        "approval_status": None,
        "trace_events": [],
        "receipt_markdown": "",
        "evidence_chunks": [],
        "citation_refs": [],
        "policy_decisions": [],
        "model_usage": {},
        "approval_state": None,
        "pending_approvals": [],
        "governance_details": {},
        "workflow_projection": {
            "template_name": None,
            "template_descriptor_version": None,
            "stage_configuration_source": {},
            "stages": [],
        },
        "progress_url": f"/api/runs/{run_id}/progress",
    }


def _summary_projection(record: RunQueueRecord) -> dict[str, Any]:
    projection = _projection(record)
    for field in _RESULT_DETAIL_FIELDS:
        projection.pop(field)
    return projection


_RESULT_DETAIL_FIELDS = (
    "trace_events",
    "receipt_markdown",
    "evidence_chunks",
    "citation_refs",
    "policy_decisions",
    "model_usage",
    "approval_state",
    "pending_approvals",
    "governance_details",
    "workflow_projection",
)


def _repository(request: Request) -> RunQueueRepository:
    repository = getattr(request.app.state, "run_queue_repository", None)
    if repository is None:
        raise HTTPException(status_code=503, detail="run_queue_unavailable")
    return cast(RunQueueRepository, repository)


def _registry(request: Request) -> PublishedAgentRegistry:
    return cast(PublishedAgentRegistry, request.app.state.published_agents)


def _result_reader(request: Request) -> RunArtifactResultReader | None:
    reader = getattr(request.app.state, "run_artifact_result_reader", None)
    return None if reader is None else cast(RunArtifactResultReader, reader)


def _require_record(request: Request, run_id: str) -> RunQueueRecord:
    try:
        record = _repository(request).get(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="run_not_found") from exc
    if record is None:
        raise HTTPException(status_code=404, detail="run_not_found")
    return record


def _load_result(request: Request, record: RunQueueRecord) -> dict[str, Any]:
    reader = _result_reader(request)
    if reader is None:
        raise HTTPException(status_code=503, detail="run_result_reader_unavailable")
    try:
        return serialize_run_detail(reader.load(record))
    except RunArtifactResultError as exc:
        raise HTTPException(status_code=503, detail="run_result_unavailable") from exc


def _conversation(request: Request, conversation_id: str) -> ConversationRecord | None:
    repository = getattr(request.app.state, "conversation_repository", None)
    if repository is not None:
        return cast(ConversationRepository, repository).get(conversation_id)
    store = getattr(request.app.state, "conversation_store", None)
    if store is None:
        return None
    return cast(ConversationStore, store).get_conversation(conversation_id)


__all__ = ["router"]
