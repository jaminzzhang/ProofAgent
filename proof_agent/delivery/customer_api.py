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
from proof_agent.capabilities.memory.local_store import LocalMemoryStore
from proof_agent.contracts import (
    AgentManifest,
    ContextAdmission,
    CustomerConversationRecord,
    CustomerDisambiguationOption,
    CustomerFeedbackSignal,
    CustomerResponseSnapshot,
    CustomerSafeResponse,
    HandoffReason,
    MemoryAdmission,
    MemoryQuery,
    MemoryScope,
    ValidationStatus,
)
from proof_agent.contracts.dashboard import RunDetail
from proof_agent.control.memory.admission import admit_memory
from proof_agent.control.memory.extractor import candidate_from_customer_turn
from proof_agent.control.policy.engine import PolicyEngine
from proof_agent.control.validators.customer_response import validate_customer_safe_response
from proof_agent.delivery.api import _execute_published_agent_run
from proof_agent.delivery.customer_adapters import (
    CustomerAdapterRequest,
    CustomerAdapterResult,
    load_customer_run_adapter,
)
from proof_agent.delivery.published_agents import PublishedAgentRegistry
from proof_agent.observability.storage.customer_store import CustomerStore
from proof_agent.observability.storage.run_store import RunStore


router = APIRouter(tags=["customer"])


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
    manifest = _load_manifest(manifest_path)
    adapter_response = load_customer_run_adapter(
        manifest.customer.adapter if manifest.customer is not None else None
    )(
        CustomerAdapterRequest(
            manifest=manifest,
            manifest_path=manifest_path,
            question=request.question,
            conversation=conversation,
        )
    )
    if adapter_response is not None:
        _result, detail, _manifest = _execute_published_agent_run(
            app_request=app_request,
            manifest_path=manifest_path,
            question=request.question,
            approved=None,
        )
        if adapter_response.handoff_reason is not None:
            _append_customer_handoff_event(
                app_request=app_request,
                detail=cast(RunDetail, detail),
                conversation=conversation,
                reason=adapter_response.handoff_reason,
                question=request.question,
                summary=adapter_response.handoff_summary,
            )
        payload = _store_customer_response(
            app_request=app_request,
            conversation=conversation,
            safe_response=adapter_response.safe_response,
            run_id=str(detail.run_id),
            created_at=str(detail.updated_at),
            question=request.question,
        )
        payload.update(dict(adapter_response.response_metadata))
        _update_customer_disambiguation_options(
            app_request=app_request,
            conversation_id=conversation.conversation_id,
            options=adapter_response.disambiguation_options,
            clear=adapter_response.clear_disambiguation_options,
            run_id=str(detail.run_id),
            turn_id=str(payload["turn_id"]),
        )
        _append_adapter_trace_events(
            app_request=app_request,
            run_id=str(detail.run_id),
            turn_id=str(payload["turn_id"]),
            adapter_response=adapter_response,
        )
        return payload

    memory_enabled = _case_memory_enabled(manifest)
    memory_admission = (
        _admit_customer_case_memory(app_request, conversation, manifest)
        if memory_enabled
        else MemoryAdmission(admitted=False)
    )
    result, detail, _ = _execute_published_agent_run(
        app_request=app_request,
        manifest_path=manifest_path,
        question=request.question,
        approved=None,
        conversation_context=_memory_context(memory_admission),
    )
    if memory_enabled:
        _append_memory_admission_event(
            app_request=app_request,
            detail=cast(RunDetail, detail),
            admission=memory_admission,
            conversation=conversation,
        )
    safe_response = CustomerSafeResponse(
        message=str(result.final_output),
        safe_sources=_safe_sources(cast(RunDetail, detail)),
    )
    payload = _store_customer_response(
        app_request=app_request,
        conversation=conversation,
        safe_response=safe_response,
        run_id=str(detail.run_id),
        created_at=str(detail.updated_at),
        question=request.question,
    )
    if memory_enabled:
        _write_case_memory(
            app_request=app_request,
            conversation=conversation,
            safe_response=safe_response,
            question=request.question,
            run_id=str(detail.run_id),
            turn_id=str(payload["turn_id"]),
            manifest=manifest,
        )
    return payload


def _load_manifest(manifest_path: Path) -> AgentManifest:
    return load_agent_manifest(manifest_path)


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


def _update_customer_disambiguation_options(
    *,
    app_request: Request,
    conversation_id: str,
    options: tuple[CustomerDisambiguationOption, ...],
    clear: bool,
    run_id: str,
    turn_id: str,
) -> None:
    if not options and not clear:
        return
    stored_options = tuple(
        CustomerDisambiguationOption(
            option_id=option.option_id,
            resource_type=option.resource_type,
            resource_id=option.resource_id,
            label=option.label,
            origin_run_id=run_id,
            origin_turn_id=turn_id,
        )
        for option in options
    )
    _get_customer_store(app_request).set_disambiguation_options(
        conversation_id=conversation_id,
        options=stored_options,
    )


def _append_adapter_trace_events(
    *,
    app_request: Request,
    run_id: str,
    turn_id: str,
    adapter_response: CustomerAdapterResult,
) -> None:
    for event in adapter_response.trace_events:
        payload = dict(event.payload)
        for field_name in event.run_id_fields:
            payload[field_name] = run_id
        for field_name in event.turn_id_fields:
            payload[field_name] = turn_id
        _append_run_trace_event(
            app_request=app_request,
            run_id=run_id,
            event_type=event.event_type,
            status=event.status,
            payload=payload,
        )


def _admit_customer_case_memory(
    app_request: Request,
    conversation: CustomerConversationRecord,
    manifest: AgentManifest,
) -> MemoryAdmission:
    case_config = manifest.memory.scopes.case
    query = MemoryQuery(
        scope=MemoryScope.CASE,
        case_id=conversation.conversation_id,
        agent_id=conversation.agent_id,
        max_records=case_config.max_records,
        allow_restricted=case_config.allow_restricted,
    )
    records = _get_memory_store(app_request).read(query)
    return admit_memory(records, query=query)


def _memory_context(admission: MemoryAdmission) -> ContextAdmission | None:
    if not admission.admitted:
        return None
    return ContextAdmission(
        admitted=True,
        turn_count=len(admission.included_memory_ids),
        included_turn_ids=admission.included_memory_ids,
        summary=f"Admitted Case Memory: {admission.summary}",
        char_count=len(admission.summary),
        max_turns=5,
    )


def _write_case_memory(
    *,
    app_request: Request,
    conversation: CustomerConversationRecord,
    safe_response: CustomerSafeResponse,
    question: str,
    run_id: str,
    turn_id: str,
    manifest: AgentManifest,
) -> None:
    candidate = candidate_from_customer_turn(
        case_id=conversation.conversation_id,
        agent_id=conversation.agent_id,
        question=question,
        safe_response=safe_response,
        source_run_id=run_id,
        source_turn_id=turn_id,
        retention_days=manifest.memory.scopes.case.retention_days,
    )
    if candidate is None:
        return
    _append_run_trace_event(
        app_request=app_request,
        run_id=run_id,
        event_type="memory_candidate_generated",
        status="ok",
        payload={
            "scope": candidate.scope.value,
            "case_id": candidate.case_id,
            "agent_id": candidate.agent_id,
            "source_run_id": candidate.source_run_id,
            "source_turn_id": candidate.source_turn_id,
            "summary": candidate.summary,
        },
    )

    _append_run_trace_event(
        app_request=app_request,
        run_id=run_id,
        event_type="memory_write_requested",
        status="ok",
        payload={
            "scope": candidate.scope.value,
            "case_id": candidate.case_id,
            "field_names": sorted(candidate.facts.keys()),
            "sensitivity": candidate.sensitivity.value,
            "expires_at": candidate.expires_at,
        },
    )
    policy_decision = PolicyEngine.from_file(manifest.policy.file).evaluate(
        "before_memory_write",
        {"write": {"summary": candidate.summary, **dict(candidate.facts)}},
    )
    if policy_decision.decision.value != "allow":
        _append_run_trace_event(
            app_request=app_request,
            run_id=run_id,
            event_type="memory_write_decision",
            status="blocked",
            payload={
                "decision": policy_decision.decision.value,
                "policy_rule_id": policy_decision.policy_rule_id,
                "reason": policy_decision.reason,
                "scope": candidate.scope.value,
                "case_id": candidate.case_id,
            },
        )
        return

    record = _get_memory_store(app_request).append(candidate)
    _append_run_trace_event(
        app_request=app_request,
        run_id=run_id,
        event_type="memory_write_decision",
        status="ok",
        payload={
            "decision": "allow",
            "policy_rule_id": policy_decision.policy_rule_id,
            "memory_id": record.memory_id,
            "scope": record.scope.value,
            "case_id": record.case_id,
        },
    )


def _case_memory_enabled(manifest: AgentManifest) -> bool:
    return manifest.memory.provider == "local" and manifest.memory.scopes.case.enabled


def _append_memory_admission_event(
    *,
    app_request: Request,
    detail: RunDetail,
    admission: MemoryAdmission,
    conversation: CustomerConversationRecord,
) -> None:
    _append_run_trace_event(
        app_request=app_request,
        run_id=detail.run_id,
        event_type="memory_admission",
        status="ok" if admission.admitted else "blocked",
        payload={
            "admitted": admission.admitted,
            "case_id": conversation.conversation_id,
            "agent_id": conversation.agent_id,
            "included_memory_ids": list(admission.included_memory_ids),
            "summary": admission.summary,
            "facts": dict(admission.facts),
            "rejected_memory_ids": list(admission.rejected_memory_ids),
            "rejection_reasons": dict(admission.rejection_reasons),
        },
    )


def _append_run_trace_event(
    *,
    app_request: Request,
    run_id: str,
    event_type: str,
    status: Literal["ok", "blocked", "waiting", "error"],
    payload: dict[str, Any],
) -> None:
    if not run_id:
        return
    trace_path = _get_run_store(app_request).history_dir / run_id / "trace.jsonl"
    if not trace_path.exists():
        return
    event = {
        "schema_version": "trace.v1",
        "run_id": run_id,
        "event_id": f"evt_{event_type}_{uuid4().hex[:8]}",
        "sequence": _next_trace_sequence(trace_path),
        "timestamp": _now(),
        "event_type": event_type,
        "span_id": f"span_{event_type}",
        "status": status,
        "payload": payload,
        "redaction": {"applied": False, "fields": []},
    }
    with trace_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True))
        handle.write("\n")


def _append_customer_handoff_event(
    *,
    app_request: Request,
    detail: RunDetail,
    conversation: CustomerConversationRecord,
    reason: HandoffReason,
    question: str,
    summary: str | None = None,
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
            "summary": summary or "Customer request requires internal follow-up.",
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


def _get_memory_store(request: Request) -> LocalMemoryStore:
    return cast(LocalMemoryStore, request.app.state.memory_store)


def _get_run_store(request: Request) -> RunStore:
    return cast(RunStore, request.app.state.store)


def _get_published_agents(request: Request) -> PublishedAgentRegistry:
    return cast(PublishedAgentRegistry, request.app.state.published_agents)
