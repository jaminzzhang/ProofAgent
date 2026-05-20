"""Customer-facing run API with customer-safe response projection."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.capabilities.tools.gateway import ToolGateway
from proof_agent.contracts import (
    AgentManifest,
    CustomerAuthorizationContext,
    CustomerConversationRecord,
    CustomerFeedbackSignal,
    CustomerResponseSnapshot,
    CustomerSafeResponse,
    CustomerSessionType,
    HandoffReason,
    ValidationStatus,
)
from proof_agent.contracts.dashboard import RunDetail
from proof_agent.control.customer import (
    CustomerAccessError,
    extract_claim_id,
    extract_policy_id,
    is_claim_status_question,
    is_policy_status_question,
    is_transactional_customer_action,
    load_mock_customer_context,
    require_claim_access,
    require_policy_access,
)
from proof_agent.control.validators.customer_response import validate_customer_safe_response
from proof_agent.delivery.api import _execute_published_agent_run
from proof_agent.delivery.published_agents import PublishedAgentRegistry
from proof_agent.observability.storage.customer_store import CustomerStore
from proof_agent.observability.storage.run_store import RunStore


router = APIRouter(tags=["customer"])
CustomerResourceResponse = tuple[CustomerSafeResponse, HandoffReason | None]


class CustomerConversationCreateRequest(BaseModel):
    """Request body for creating a customer-facing conversation."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1)
    customer_id: str | None = None


class CustomerRunRequest(BaseModel):
    """Request body for adding one customer-facing run."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)


class CustomerFeedbackRequest(BaseModel):
    """Request body for customer feedback on a safe response turn."""

    model_config = ConfigDict(extra="forbid")

    rating: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=1000)


@router.post("/customer/conversations")
def create_customer_conversation(
    request: CustomerConversationCreateRequest,
    app_request: Request,
) -> dict[str, Any]:
    """Create a customer-facing conversation for a Published Agent."""

    registry = _get_published_agents(app_request)
    if registry.resolve(request.agent_id) is None:
        raise HTTPException(
            status_code=404,
            detail={
                "message": f"Published Agent not found: {request.agent_id}",
                "available_agent_ids": registry.list_agent_ids(),
            },
        )

    record = _get_customer_store(app_request).create_conversation(
        agent_id=request.agent_id,
        customer_ref=request.customer_id,
    )
    return {
        "conversation_id": record.conversation_id,
        "agent_id": record.agent_id,
        "customer_id": record.customer_ref,
    }


@router.get("/customer/conversations/{conversation_id}")
def get_customer_conversation(conversation_id: str, app_request: Request) -> dict[str, Any]:
    """Return customer-safe conversation metadata and snapshots."""

    record = _require_customer_conversation(app_request, conversation_id)
    return _customer_conversation_payload(record)


@router.post("/customer/conversations/{conversation_id}/runs")
def create_customer_run(
    conversation_id: str,
    request: CustomerRunRequest,
    app_request: Request,
) -> dict[str, Any]:
    """Start a governed run and return only the customer-safe response projection."""

    conversation = _require_customer_conversation(app_request, conversation_id)
    registry = _get_published_agents(app_request)
    published_agent = registry.resolve(conversation.agent_id)
    if published_agent is None:
        raise HTTPException(
            status_code=404,
            detail={
                "message": f"Published Agent not found: {conversation.agent_id}",
                "available_agent_ids": registry.list_agent_ids(),
            },
        )

    manifest_path = published_agent.manifest_path
    if is_transactional_customer_action(request.question):
        _result, detail, _manifest = _execute_published_agent_run(
            app_request=app_request,
            manifest_path=manifest_path,
            question=request.question,
            approved=None,
        )
        _append_customer_handoff_event(
            app_request=app_request,
            detail=cast(RunDetail, detail),
            conversation=conversation,
            reason=HandoffReason.TRANSACTIONAL_ACTION_REQUESTED,
            question=request.question,
        )
        safe_response = CustomerSafeResponse(
            message=(
                "I can help with read-only policy and claim questions here, "
                "but I can't make account changes in this chat."
            ),
        )
        return _store_customer_response(
            app_request=app_request,
            conversation=conversation,
            safe_response=safe_response,
            run_id=str(detail.run_id),
            created_at=str(detail.updated_at),
            question=request.question,
        )

    resource_response = _customer_resource_response(
        manifest_path=manifest_path,
        question=request.question,
        conversation=conversation,
    )
    if resource_response is not None:
        safe_preflight_response, handoff_reason = resource_response
        run_id = ""
        created_at = _now()
        if handoff_reason is not None:
            _result, detail, _manifest = _execute_published_agent_run(
                app_request=app_request,
                manifest_path=manifest_path,
                question=request.question,
                approved=None,
            )
            _append_customer_handoff_event(
                app_request=app_request,
                detail=cast(RunDetail, detail),
                conversation=conversation,
                reason=handoff_reason,
                question=request.question,
            )
            run_id = str(detail.run_id)
            created_at = str(detail.updated_at)
        return _store_customer_response(
            app_request=app_request,
            conversation=conversation,
            safe_response=safe_preflight_response,
            run_id=run_id,
            created_at=created_at,
            question=request.question,
        )

    result, detail, _ = _execute_published_agent_run(
        app_request=app_request,
        manifest_path=manifest_path,
        question=request.question,
        approved=None,
    )
    safe_response = CustomerSafeResponse(
        message=str(result.final_output),
        safe_sources=_safe_sources(cast(RunDetail, detail)),
    )
    return _store_customer_response(
        app_request=app_request,
        conversation=conversation,
        safe_response=safe_response,
        run_id=str(detail.run_id),
        created_at=str(detail.updated_at),
        question=request.question,
    )


def _customer_resource_response(
    *,
    manifest_path: Path,
    question: str,
    conversation: CustomerConversationRecord,
) -> CustomerResourceResponse | None:
    manifest = _load_manifest(manifest_path)
    if is_policy_status_question(question):
        context = _load_customer_context(manifest_path, conversation.customer_ref)
        return _policy_status_response(manifest, context, question)
    if is_claim_status_question(question):
        context = _load_customer_context(manifest_path, conversation.customer_ref)
        return _claim_status_response(manifest, context, question)
    return None


def _policy_status_response(
    manifest: AgentManifest,
    context: CustomerAuthorizationContext,
    question: str,
) -> CustomerResourceResponse:
    if context.session_type != CustomerSessionType.AUTHENTICATED or context.customer_ref is None:
        return (
            CustomerSafeResponse(
                message="Please sign in to view policy status for your account.",
            ),
            None,
        )

    policy_id = extract_policy_id(question) or _single_resource_id(context.allowed_policy_ids)
    if policy_id is None:
        return (
            CustomerSafeResponse(
                message="Please provide the policy number you want me to check.",
            ),
            None,
        )
    try:
        require_policy_access(context, policy_id)
    except CustomerAccessError:
        return (
            CustomerSafeResponse(
                message=(
                    "I can't access that policy from this signed-in session. "
                    "I can help with policy status for a policy on your account."
                ),
            ),
            HandoffReason.CROSS_CUSTOMER_ACCESS_ATTEMPT,
        )

    result = ToolGateway.from_file(manifest.tools.file).request_tool(
        tool_name="policy_status_lookup",
        parameters={"customer_id": context.customer_ref, "policy_id": policy_id},
        approved=False,
    )
    status = str((result.result or {}).get("status") or "unknown")
    return (
        CustomerSafeResponse(
            message=f"Your policy status is {status}.",
            safe_sources=("policy_status_lookup",),
        ),
        None,
    )


def _claim_status_response(
    manifest: AgentManifest,
    context: CustomerAuthorizationContext,
    question: str,
) -> CustomerResourceResponse:
    if context.session_type != CustomerSessionType.AUTHENTICATED or context.customer_ref is None:
        return (
            CustomerSafeResponse(
                message="Please sign in to view claim status for your account.",
            ),
            None,
        )

    claim_id = extract_claim_id(question) or _single_resource_id(context.allowed_claim_ids)
    if claim_id is None:
        return (
            CustomerSafeResponse(
                message="Please provide the claim number you want me to check.",
            ),
            None,
        )
    try:
        require_claim_access(context, claim_id)
    except CustomerAccessError:
        return (
            CustomerSafeResponse(
                message=(
                    "I can't access that claim from this signed-in session. "
                    "I can help with claim status for a claim on your account."
                ),
            ),
            HandoffReason.CROSS_CUSTOMER_ACCESS_ATTEMPT,
        )

    result = ToolGateway.from_file(manifest.tools.file).request_tool(
        tool_name="claim_status_lookup",
        parameters={"customer_id": context.customer_ref, "claim_id": claim_id},
        approved=False,
    )
    status = str((result.result or {}).get("status") or "unknown")
    return (
        CustomerSafeResponse(
            message=f"Your claim status is {status}.",
            safe_sources=("claim_status_lookup",),
        ),
        None,
    )


def _load_manifest(manifest_path: Path) -> AgentManifest:
    return load_agent_manifest(manifest_path)


def _load_customer_context(
    manifest_path: Path,
    customer_ref: str | None,
) -> CustomerAuthorizationContext:
    try:
        return load_mock_customer_context(
            manifest_path.parent / "customers.yaml",
            customer_id=customer_ref,
        )
    except CustomerAccessError:
        return CustomerAuthorizationContext(session_type=CustomerSessionType.ANONYMOUS)


def _store_customer_response(
    *,
    app_request: Request,
    conversation: CustomerConversationRecord,
    safe_response: CustomerSafeResponse,
    run_id: str,
    created_at: str,
    question: str,
) -> dict[str, Any]:
    validation = validate_customer_safe_response(safe_response)
    if validation.status == ValidationStatus.FAILED:
        raise HTTPException(
            status_code=500,
            detail={
                "message": validation.reason,
                "validator": validation.validator_name,
            },
        )

    turn_id = f"cust_turn_{uuid4().hex[:8]}"
    snapshot = CustomerResponseSnapshot(
        snapshot_id=f"snap_{uuid4().hex[:8]}",
        conversation_id=conversation.conversation_id,
        turn_id=turn_id,
        run_id=run_id,
        created_at=created_at,
        question=question,
        customer_ref=conversation.customer_ref,
        response=safe_response,
    )
    updated = _get_customer_store(app_request).append_snapshot(
        conversation_id=conversation.conversation_id,
        snapshot=snapshot,
    )
    if updated is None:
        raise HTTPException(
            status_code=404,
            detail=f"Conversation not found: {conversation.conversation_id}",
        )

    payload = safe_response.model_dump(mode="json")
    payload["conversation_id"] = conversation.conversation_id
    payload["turn_id"] = turn_id
    payload["run_id"] = run_id
    return payload


def _append_customer_handoff_event(
    *,
    app_request: Request,
    detail: RunDetail,
    conversation: CustomerConversationRecord,
    reason: HandoffReason,
    question: str,
) -> None:
    trace_path = _get_run_store(app_request).history_dir / detail.run_id / "trace.jsonl"
    if not trace_path.exists():
        return
    event = {
        "schema_version": "trace.v1",
        "run_id": detail.run_id,
        "event_id": f"evt_handoff_{uuid4().hex[:8]}",
        "sequence": _next_trace_sequence(trace_path),
        "timestamp": _now(),
        "event_type": "customer_handoff_created",
        "span_id": "span_customer_handoff",
        "status": "ok",
        "payload": {
            "handoff_id": f"handoff_{uuid4().hex[:8]}",
            "conversation_id": conversation.conversation_id,
            "reason": reason.value,
            "question_summary": question,
            "summary": "Customer requested an account-changing action in read-only chat.",
            "customer_ref": conversation.customer_ref,
        },
        "redaction": {"applied": False, "fields": []},
    }
    with trace_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True))
        handle.write("\n")


def _next_trace_sequence(trace_path: Path) -> int:
    sequence = 0
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            sequence = max(sequence, int(value.get("sequence") or 0))
    return sequence + 1


@router.post("/customer/conversations/{conversation_id}/turns/{turn_id}/feedback")
def record_customer_feedback(
    conversation_id: str,
    turn_id: str,
    request: CustomerFeedbackRequest,
    app_request: Request,
) -> dict[str, Any]:
    """Store observation-only customer feedback for a safe response turn."""

    _require_customer_conversation(app_request, conversation_id)
    feedback = CustomerFeedbackSignal(rating=request.rating, comment=request.comment)
    recorded = _get_customer_store(app_request).record_feedback(
        conversation_id=conversation_id,
        turn_id=turn_id,
        feedback=feedback,
    )
    if recorded is None:
        raise HTTPException(status_code=404, detail=f"Turn not found: {turn_id}")
    return {
        "conversation_id": conversation_id,
        "turn_id": turn_id,
        "feedback": recorded.model_dump(mode="json"),
    }


def _customer_conversation_payload(record: CustomerConversationRecord) -> dict[str, Any]:
    return {
        "conversation_id": record.conversation_id,
        "agent_id": record.agent_id,
        "customer_id": record.customer_ref,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "turns": [
            {
                "turn_id": snapshot.turn_id,
                "run_id": snapshot.run_id,
                "question": snapshot.question,
                "created_at": snapshot.created_at,
                "response_snapshot": snapshot.response.model_dump(mode="json"),
            }
            for snapshot in record.snapshots
        ],
    }


def _safe_sources(detail: RunDetail) -> tuple[str, ...]:
    labels: list[str] = []
    for chunk in detail.evidence_chunks:
        raw_source = chunk.get("source")
        if raw_source is None:
            continue
        label = Path(str(raw_source)).name or str(raw_source)
        if label and label not in labels:
            labels.append(label)
    return tuple(labels)


def _single_resource_id(values: tuple[str, ...]) -> str | None:
    return values[0] if len(values) == 1 else None


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _require_customer_conversation(
    request: Request,
    conversation_id: str,
) -> CustomerConversationRecord:
    record = _get_customer_store(request).get_conversation(conversation_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Conversation not found: {conversation_id}")
    return record


def _get_customer_store(request: Request) -> CustomerStore:
    return cast(CustomerStore, request.app.state.customer_store)


def _get_run_store(request: Request) -> RunStore:
    return cast(RunStore, request.app.state.store)


def _get_published_agents(request: Request) -> PublishedAgentRegistry:
    return cast(PublishedAgentRegistry, request.app.state.published_agents)
