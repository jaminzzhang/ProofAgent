"""Customer-facing run API with customer-safe response projection."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import json
from pathlib import Path
import re
from typing import Any, Literal, cast
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.capabilities.memory.local_store import LocalMemoryStore
from proof_agent.capabilities.memory.mem0_store import Mem0MemoryStore

from proof_agent.contracts import (
    AgentManifest,
    CustomerConversationRecord,
    CustomerDisambiguationOption,
    CustomerFeedbackSignal,
    CustomerResponseSnapshot,
    CustomerSafeResponse,
    HandoffReason,
    MemoryAdmission,
    MemoryCandidate,
    MemoryPromotionDecision,
    MemoryPromotionOutcome,
    MemoryQuery,
    MemoryRecallAdmission,
    MemoryRecallWorkingPayload,
    MemoryRecord,
    MemoryScope,
    RunPurpose,
    ValidationStatus,
)
from proof_agent.contracts.dashboard import RunDetail
from proof_agent.control.memory.admission import admit_memory
from proof_agent.control.memory.extractor import (
    candidate_from_customer_turn,
    customer_interest_candidate_from_customer_turn,
)
from proof_agent.control.policy.engine import PolicyEngine
from proof_agent.control.validators.customer_response import validate_customer_safe_response
from proof_agent.control.workflow.harness_helpers import strip_internal_citation_markers
from proof_agent.delivery.api import _execute_published_agent_run
from proof_agent.delivery.customer_adapters import (
    CustomerAdapterRequest,
    CustomerAdapterResult,
    load_customer_run_adapter,
)
from proof_agent.delivery.published_agents import (
    PublishedAgentRegistry,
    published_agent_directory_payload,
)
from proof_agent.observability.storage.customer_store import CustomerStore
from proof_agent.observability.storage.run_store import RunStore


router = APIRouter(tags=["customer"])


_KNOWLEDGE_SOURCE_URI_RE = re.compile(r"knowledge://source/([^/#?]+)")
_NUMBERED_REFERENCE_LABEL_RE = re.compile(r"^\[\d+\]$")


class CustomerConversationCreateRequest(BaseModel):
    """Request body for creating a customer-facing conversation."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1)
    customer_id: str | None = None
    memory_consent: bool = False


class CustomerRunRequest(BaseModel):
    """Request body for adding one customer-facing run."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    memory_consent: bool | None = None
    allow_untrusted_web_supplement: bool = False


class CustomerFeedbackRequest(BaseModel):
    """Request body for customer feedback on a safe response turn."""

    model_config = ConfigDict(extra="forbid")

    rating: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=1000)


@router.get("/customer/agents")
def list_customer_agents(app_request: Request) -> dict[str, Any]:
    """Return Customer-Facing Published Agents available to customer chat."""

    registry = _get_published_agents(app_request)
    return published_agent_directory_payload(registry.list_agents(customer_facing_only=True))


@router.post("/customer/conversations")
def create_customer_conversation(
    request: CustomerConversationCreateRequest,
    app_request: Request,
) -> dict[str, Any]:
    """Create a customer-facing conversation for a Published Agent."""

    registry = _get_published_agents(app_request)
    if registry.resolve_customer_facing(request.agent_id) is None:
        raise _customer_agent_not_found(registry, request.agent_id)

    record = _get_customer_store(app_request).create_conversation(
        agent_id=request.agent_id,
        customer_ref=request.customer_id,
        memory_consent=request.memory_consent,
    )
    return {
        "conversation_id": record.conversation_id,
        "agent_id": record.agent_id,
        "customer_id": record.customer_ref,
        "memory_consent": record.memory_consent,
    }


@router.get("/customer/conversations/{conversation_id}")
def get_customer_conversation(conversation_id: str, app_request: Request) -> dict[str, Any]:
    """Return customer-safe conversation metadata and snapshots."""

    record = _require_customer_conversation(app_request, conversation_id)
    return _customer_conversation_payload(record)


@router.get("/customer/memory/{subject_ref}")
def export_customer_user_memory(
    subject_ref: str,
    agent_id: str,
    app_request: Request,
) -> dict[str, Any]:
    """Export trace-safe Customer Persistent User Memory for one customer reference."""

    manifest = _require_published_agent_manifest(app_request, agent_id)
    audit_run_id = _get_customer_store(app_request).latest_run_id_for_customer(
        agent_id=agent_id,
        customer_ref=subject_ref,
    )
    if not _user_memory_enabled(manifest):
        memories: tuple[MemoryRecord, ...] = ()
    else:
        memories = _get_case_memory_store(app_request, manifest).export_subject(
            agent_id=agent_id,
            subject_ref=subject_ref,
        )
    _append_customer_user_memory_export_event(
        app_request=app_request,
        run_id=audit_run_id,
        manifest=manifest,
        agent_id=agent_id,
        subject_ref=subject_ref,
        exported_count=len(memories),
    )
    return {
        "agent_id": agent_id,
        "subject_ref": subject_ref,
        "audit_run_id": audit_run_id,
        "memories": [_customer_user_memory_payload(record) for record in memories],
    }


@router.delete("/customer/memory/{subject_ref}")
def delete_customer_user_memory(
    subject_ref: str,
    agent_id: str,
    app_request: Request,
) -> dict[str, Any]:
    """Delete Customer Persistent User Memory for one customer reference."""

    manifest = _require_published_agent_manifest(app_request, agent_id)
    audit_run_id = _get_customer_store(app_request).latest_run_id_for_customer(
        agent_id=agent_id,
        customer_ref=subject_ref,
    )
    deleted_count = (
        _get_case_memory_store(app_request, manifest).soft_delete_subject(
            agent_id=agent_id,
            subject_ref=subject_ref,
        )
        if _user_memory_enabled(manifest)
        else 0
    )
    _append_customer_user_memory_delete_event(
        app_request=app_request,
        run_id=audit_run_id,
        manifest=manifest,
        agent_id=agent_id,
        subject_ref=subject_ref,
        deleted_count=deleted_count,
    )
    return {
        "agent_id": agent_id,
        "subject_ref": subject_ref,
        "audit_run_id": audit_run_id,
        "deleted_count": deleted_count,
    }


@router.delete("/customer/conversations/{conversation_id}/memory")
def delete_customer_case_memory(conversation_id: str, app_request: Request) -> dict[str, Any]:
    """Delete Case Memory for a customer conversation without exposing memory contents."""

    conversation = _require_customer_conversation(app_request, conversation_id)
    registry = _get_published_agents(app_request)
    published_agent = registry.resolve_customer_facing(conversation.agent_id)
    if published_agent is None:
        raise _customer_agent_not_found(registry, conversation.agent_id)
    manifest = _load_manifest(published_agent.manifest_path)
    audit_run_id = _latest_customer_run_id(conversation)
    if not _case_memory_enabled(manifest):
        _append_case_memory_delete_event(
            app_request=app_request,
            run_id=audit_run_id,
            conversation=conversation,
            manifest=manifest,
            deleted_count=0,
        )
        return {
            "conversation_id": conversation.conversation_id,
            "agent_id": conversation.agent_id,
            "deleted_count": 0,
            "audit_run_id": audit_run_id,
        }
    deleted_count = _get_case_memory_store(app_request, manifest).soft_delete_case(
        agent_id=conversation.agent_id,
        case_id=conversation.conversation_id,
    )
    _append_case_memory_delete_event(
        app_request=app_request,
        run_id=audit_run_id,
        conversation=conversation,
        manifest=manifest,
        deleted_count=deleted_count,
    )
    return {
        "conversation_id": conversation.conversation_id,
        "agent_id": conversation.agent_id,
        "deleted_count": deleted_count,
        "audit_run_id": audit_run_id,
    }


@router.post("/customer/conversations/{conversation_id}/runs")
def create_customer_run(
    conversation_id: str,
    request: CustomerRunRequest,
    app_request: Request,
) -> dict[str, Any]:
    """Start a governed run and return only the customer-safe response projection."""

    return execute_customer_run_for_conversation(
        conversation_id=conversation_id,
        request=request,
        app_request=app_request,
    )


def execute_customer_run_for_conversation(
    *,
    conversation_id: str,
    request: CustomerRunRequest,
    app_request: Request,
    run_purpose: RunPurpose = RunPurpose.PRODUCTION,
) -> dict[str, Any]:
    """Execute one Customer Run API turn for an existing customer conversation."""

    conversation = _require_customer_conversation(app_request, conversation_id)
    registry = _get_published_agents(app_request)
    published_agent = registry.resolve_customer_facing(conversation.agent_id)
    if published_agent is None:
        raise _customer_agent_not_found(registry, conversation.agent_id)

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
            published_agent=published_agent,
            question=request.question,
            allow_untrusted_web_supplement=request.allow_untrusted_web_supplement,
            run_purpose=run_purpose,
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

    manifest = _load_manifest(manifest_path)
    case_memory_enabled = _case_memory_enabled(manifest)
    user_memory_enabled = _user_memory_enabled(manifest)
    case_memory_recall_enabled = _memory_recall_scope_enabled(
        manifest,
        "case",
        default=True,
    )
    user_memory_recall_enabled = _memory_recall_scope_enabled(
        manifest,
        "user",
        default=True,
    )
    user_memory_consent = _customer_memory_consent(conversation, request)
    case_memory_admission = (
        _admit_customer_case_memory(app_request, conversation, manifest)
        if case_memory_enabled and case_memory_recall_enabled
        else MemoryAdmission(admitted=False)
    )
    user_memory_admission = (
        _admit_customer_user_memory(app_request, conversation, manifest)
        if (
            user_memory_enabled
            and user_memory_recall_enabled
            and user_memory_consent
            and conversation.customer_ref is not None
        )
        else MemoryAdmission(admitted=False)
    )
    result, detail, _ = _execute_published_agent_run(
        app_request=app_request,
        published_agent=published_agent,
        question=request.question,
        memory_recall_admissions=_memory_recall_admissions(
            (
                MemoryScope.CASE,
                case_memory_admission,
                conversation.conversation_id,
                "",
                conversation.agent_id,
            ),
            (
                MemoryScope.USER,
                user_memory_admission,
                "",
                conversation.customer_ref or "",
                conversation.agent_id,
            ),
        ),
        run_purpose=run_purpose,
    )
    if case_memory_enabled and case_memory_recall_enabled:
        _append_memory_admission_event(
            app_request=app_request,
            detail=cast(RunDetail, detail),
            admission=case_memory_admission,
            conversation=conversation,
            scope=MemoryScope.CASE,
        )
    if (
        user_memory_enabled
        and user_memory_recall_enabled
        and user_memory_consent
        and conversation.customer_ref is not None
    ):
        _append_memory_admission_event(
            app_request=app_request,
            detail=cast(RunDetail, detail),
            admission=user_memory_admission,
            conversation=conversation,
            scope=MemoryScope.USER,
        )
    safe_response = CustomerSafeResponse(
        message=str(result.final_output),
        safe_sources=_safe_sources(
            cast(RunDetail, detail),
            knowledge_source_store=getattr(
                app_request.app.state,
                "agent_configuration_store",
                None,
            ),
        ),
    )
    payload = _store_customer_response(
        app_request=app_request,
        conversation=conversation,
        safe_response=safe_response,
        run_id=str(detail.run_id),
        created_at=str(detail.updated_at),
        question=request.question,
    )
    if case_memory_enabled:
        _write_case_memory(
            app_request=app_request,
            conversation=conversation,
            safe_response=safe_response,
            question=request.question,
            run_id=str(detail.run_id),
            turn_id=str(payload["turn_id"]),
            manifest=manifest,
        )
    if user_memory_enabled:
        if not user_memory_consent:
            _append_memory_promotion_decision_event(
                app_request=app_request,
                run_id=str(detail.run_id),
                decision=MemoryPromotionDecision(
                    outcome=MemoryPromotionOutcome.NO_MEMORY,
                    source_turn_id=str(payload["turn_id"]),
                    reasons=("user_memory_consent_not_granted",),
                ),
            )
        elif conversation.customer_ref is None:
            _append_memory_promotion_decision_event(
                app_request=app_request,
                run_id=str(detail.run_id),
                decision=MemoryPromotionDecision(
                    outcome=MemoryPromotionOutcome.NO_MEMORY,
                    source_turn_id=str(payload["turn_id"]),
                    reasons=("user_memory_subject_ref_missing",),
                ),
            )
        else:
            _write_user_memory(
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


def _require_published_agent_manifest(request: Request, agent_id: str) -> AgentManifest:
    registry = _get_published_agents(request)
    published_agent = registry.resolve_customer_facing(agent_id)
    if published_agent is None:
        raise _customer_agent_not_found(registry, agent_id)
    return _load_manifest(published_agent.manifest_path)


def _customer_agent_not_found(registry: PublishedAgentRegistry, agent_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "message": f"Customer-facing Published Agent not found: {agent_id}",
            "available_agent_ids": list(registry.list_agent_ids(customer_facing_only=True)),
        },
    )


def _store_customer_response(
    *,
    app_request: Request,
    conversation: CustomerConversationRecord,
    safe_response: CustomerSafeResponse,
    run_id: str,
    created_at: str,
    question: str,
) -> dict[str, Any]:
    safe_response = safe_response.model_copy(
        update={"message": _customer_safe_message(safe_response.message)}
    )
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
    case_config = _memory_scope_config(manifest, "case")
    query = MemoryQuery(
        scope=MemoryScope.CASE,
        case_id=conversation.conversation_id,
        agent_id=conversation.agent_id,
        max_records=case_config["max_records"],
        allow_restricted=case_config["allow_restricted"],
    )
    records = _get_case_memory_store(app_request, manifest).read(query)
    return admit_memory(records, query=query)


def _admit_customer_user_memory(
    app_request: Request,
    conversation: CustomerConversationRecord,
    manifest: AgentManifest,
) -> MemoryAdmission:
    user_config = _memory_scope_config(manifest, "user")
    if conversation.customer_ref is None:
        return MemoryAdmission(admitted=False)
    query = MemoryQuery(
        scope=MemoryScope.USER,
        subject_ref=conversation.customer_ref,
        agent_id=conversation.agent_id,
        max_records=user_config["max_records"],
        allow_restricted=user_config["allow_restricted"],
        consent_granted=True,
    )
    records = _get_case_memory_store(app_request, manifest).read(query)
    return admit_memory(records, query=query)


def _memory_recall_admissions(
    *admissions: tuple[MemoryScope, MemoryAdmission, str, str, str],
) -> tuple[MemoryRecallAdmission, ...]:
    recall_admissions: list[MemoryRecallAdmission] = []
    for scope, admission, case_id, subject_ref, agent_id in admissions:
        if not admission.admitted and not admission.rejected_memory_ids:
            continue
        fact_keys = tuple(sorted(str(key) for key in admission.facts))
        working_payload = (
            MemoryRecallWorkingPayload(
                scope=scope,
                source_refs=admission.included_memory_ids,
                summary=admission.summary,
                facts=admission.facts,
            )
            if admission.admitted
            else None
        )
        recall_admissions.append(
            MemoryRecallAdmission(
                admitted=admission.admitted,
                scope=scope,
                case_id=case_id,
                subject_ref=subject_ref,
                agent_id=agent_id,
                included_memory_ids=admission.included_memory_ids,
                rejected_memory_ids=admission.rejected_memory_ids,
                summary=admission.summary,
                fact_keys=fact_keys,
                fact_count=len(fact_keys),
                rejection_reasons=admission.rejection_reasons,
                working_payload=working_payload,
            )
        )
    return tuple(recall_admissions)


def _customer_memory_consent(
    conversation: CustomerConversationRecord,
    request: CustomerRunRequest,
) -> bool:
    return (
        request.memory_consent
        if request.memory_consent is not None
        else conversation.memory_consent
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
        retention_days=_memory_scope_config(manifest, "case")["retention_days"],
    )
    if candidate is None:
        _append_memory_promotion_decision_event(
            app_request=app_request,
            run_id=run_id,
            decision=MemoryPromotionDecision(
                outcome=MemoryPromotionOutcome.NO_MEMORY,
                source_turn_id=turn_id,
                reasons=("case_memory_candidate_not_generated",),
            ),
        )
        return
    _append_memory_promotion_decision_event(
        app_request=app_request,
        run_id=run_id,
        decision=MemoryPromotionDecision(
            outcome=MemoryPromotionOutcome.CASE_MEMORY,
            source_turn_id=turn_id,
            target_scope=MemoryScope.CASE,
            reasons=("case_memory_candidate_generated",),
        ),
    )
    _write_memory_candidate(
        app_request=app_request,
        run_id=run_id,
        manifest=manifest,
        candidate=candidate,
    )


def _write_user_memory(
    *,
    app_request: Request,
    conversation: CustomerConversationRecord,
    safe_response: CustomerSafeResponse,
    question: str,
    run_id: str,
    turn_id: str,
    manifest: AgentManifest,
) -> None:
    if conversation.customer_ref is None:
        return
    candidate = customer_interest_candidate_from_customer_turn(
        subject_ref=conversation.customer_ref,
        agent_id=conversation.agent_id,
        question=question,
        safe_response=safe_response,
        source_run_id=run_id,
        source_turn_id=turn_id,
        retention_days=_memory_scope_config(manifest, "user")["retention_days"],
    )
    if candidate is None:
        _append_memory_promotion_decision_event(
            app_request=app_request,
            run_id=run_id,
            decision=MemoryPromotionDecision(
                outcome=MemoryPromotionOutcome.NO_MEMORY,
                source_turn_id=turn_id,
                reasons=("persistent_user_memory_candidate_not_generated",),
            ),
        )
        return
    _append_memory_promotion_decision_event(
        app_request=app_request,
        run_id=run_id,
        decision=MemoryPromotionDecision(
            outcome=MemoryPromotionOutcome.PERSISTENT_USER_MEMORY,
            source_turn_id=turn_id,
            target_scope=MemoryScope.USER,
            reasons=("persistent_user_memory_candidate_generated",),
        ),
    )
    _write_memory_candidate(
        app_request=app_request,
        run_id=run_id,
        manifest=manifest,
        candidate=candidate,
    )


def _write_memory_candidate(
    *,
    app_request: Request,
    run_id: str,
    manifest: AgentManifest,
    candidate: MemoryCandidate,
) -> None:
    _append_run_trace_event(
        app_request=app_request,
        run_id=run_id,
        event_type="memory_candidate_generated",
        status="ok",
        payload={
            "scope": candidate.scope.value,
            "case_id": candidate.case_id,
            "subject_ref": candidate.subject_ref,
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
            "subject_ref": candidate.subject_ref,
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
                "subject_ref": candidate.subject_ref,
            },
        )
        return

    record = _get_case_memory_store(app_request, manifest).append(candidate)
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
            "subject_ref": record.subject_ref,
        },
    )


def _append_memory_promotion_decision_event(
    *,
    app_request: Request,
    run_id: str,
    decision: MemoryPromotionDecision,
) -> None:
    _append_run_trace_event(
        app_request=app_request,
        run_id=run_id,
        event_type="memory_promotion_decision",
        status="ok" if decision.outcome is not MemoryPromotionOutcome.NO_MEMORY else "blocked",
        payload=decision.model_dump(mode="json"),
    )


def _case_memory_enabled(manifest: AgentManifest) -> bool:
    return (
        _memory_provider(manifest) in {"local", "mem0"}
        and _memory_scope_config(manifest, "case")["enabled"]
    )


def _user_memory_enabled(manifest: AgentManifest) -> bool:
    return (
        _memory_provider(manifest) in {"local", "mem0"}
        and _memory_scope_config(manifest, "user")["enabled"]
    )


def _memory_provider(manifest: AgentManifest) -> str:
    return str(manifest.capabilities.memory.provider or "")


def _memory_recall_scope_enabled(
    manifest: AgentManifest,
    scope: str,
    *,
    default: bool,
) -> bool:
    if manifest.context is None:
        return default
    source_policies = manifest.context.source_policies
    memory_recall = source_policies.get("memory_recall")
    if not isinstance(memory_recall, Mapping):
        return default
    scopes = memory_recall.get("scopes")
    if not isinstance(scopes, Mapping):
        return default
    scope_policy = scopes.get(scope)
    if not isinstance(scope_policy, Mapping) or "enabled" not in scope_policy:
        return default
    return scope_policy.get("enabled") is True


def _memory_scope_config(manifest: AgentManifest, scope: str) -> dict[str, Any]:
    scopes = manifest.capabilities.memory.scopes
    raw_scope = scopes.get(scope, {}) if isinstance(scopes, Mapping) else {}
    scope_config = raw_scope if isinstance(raw_scope, Mapping) else {}
    return {
        "enabled": bool(scope_config.get("enabled", False)),
        "retention_days": int(scope_config.get("retention_days", 30) or 30),
        "max_records": int(scope_config.get("max_records", 5) or 5),
        "allow_restricted": bool(scope_config.get("allow_restricted", False)),
    }


def _append_memory_admission_event(
    *,
    app_request: Request,
    detail: RunDetail,
    admission: MemoryAdmission,
    conversation: CustomerConversationRecord,
    scope: MemoryScope,
) -> None:
    subject_ref = conversation.customer_ref if scope == MemoryScope.USER else ""
    _append_run_trace_event(
        app_request=app_request,
        run_id=detail.run_id,
        event_type="memory_admission",
        status="ok" if admission.admitted else "blocked",
        payload={
            "admitted": admission.admitted,
            "scope": scope.value,
            "case_id": conversation.conversation_id,
            "subject_ref": subject_ref,
            "agent_id": conversation.agent_id,
            "included_memory_ids": list(admission.included_memory_ids),
            "summary": admission.summary,
            "facts": dict(admission.facts),
            "rejected_memory_ids": list(admission.rejected_memory_ids),
            "rejection_reasons": dict(admission.rejection_reasons),
        },
    )


def _append_case_memory_delete_event(
    *,
    app_request: Request,
    run_id: str | None,
    conversation: CustomerConversationRecord,
    manifest: AgentManifest,
    deleted_count: int,
) -> None:
    if run_id is None:
        return
    _append_run_trace_event(
        app_request=app_request,
        run_id=run_id,
        event_type="memory_delete_decision",
        status="ok",
        payload={
            "scope": MemoryScope.CASE.value,
            "case_id": conversation.conversation_id,
            "agent_id": conversation.agent_id,
            "provider": _memory_provider(manifest),
            "deleted_count": deleted_count,
        },
    )


def _append_customer_user_memory_export_event(
    *,
    app_request: Request,
    run_id: str | None,
    manifest: AgentManifest,
    agent_id: str,
    subject_ref: str,
    exported_count: int,
) -> None:
    if run_id is None:
        return
    _append_run_trace_event(
        app_request=app_request,
        run_id=run_id,
        event_type="memory_export_decision",
        status="ok",
        payload={
            "scope": MemoryScope.USER.value,
            "subject_ref": subject_ref,
            "agent_id": agent_id,
            "provider": _memory_provider(manifest),
            "exported_count": exported_count,
        },
    )


def _append_customer_user_memory_delete_event(
    *,
    app_request: Request,
    run_id: str | None,
    manifest: AgentManifest,
    agent_id: str,
    subject_ref: str,
    deleted_count: int,
) -> None:
    if run_id is None:
        return
    _append_run_trace_event(
        app_request=app_request,
        run_id=run_id,
        event_type="memory_delete_decision",
        status="ok",
        payload={
            "scope": MemoryScope.USER.value,
            "subject_ref": subject_ref,
            "agent_id": agent_id,
            "provider": _memory_provider(manifest),
            "deleted_count": deleted_count,
        },
    )


def _latest_customer_run_id(conversation: CustomerConversationRecord) -> str | None:
    if not conversation.snapshots:
        return None
    return conversation.snapshots[-1].run_id


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
        "memory_consent": record.memory_consent,
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


def _customer_user_memory_payload(record: MemoryRecord) -> dict[str, Any]:
    return {
        "memory_id": record.memory_id,
        "scope": record.scope.value,
        "subject_ref": record.subject_ref,
        "agent_id": record.agent_id,
        "summary": record.summary,
        "facts": _plain_payload(record.facts),
        "source_run_id": record.source_run_id,
        "source_turn_id": record.source_turn_id,
        "created_at": record.created_at,
        "expires_at": record.expires_at,
        "sensitivity": record.sensitivity.value,
        "status": record.status.value,
    }


def _plain_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _plain_payload(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain_payload(item) for item in value]
    if hasattr(value, "items"):
        return {str(key): _plain_payload(item) for key, item in value.items()}
    return value


def _customer_safe_message(message: str) -> str:
    return strip_internal_citation_markers(message)


def _safe_sources(
    detail: RunDetail,
    *,
    knowledge_source_store: object | None = None,
) -> tuple[str, ...]:
    labels: list[str] = []
    for chunk in detail.evidence_chunks:
        label = _safe_source_label(chunk, knowledge_source_store=knowledge_source_store)
        if label is None:
            continue
        if label and label not in labels:
            labels.append(label)
    return tuple(labels)


def _safe_source_label(
    chunk: Mapping[str, Any],
    *,
    knowledge_source_store: object | None,
) -> str | None:
    source_id = _knowledge_source_id_from_chunk(chunk)
    if source_id is not None:
        source_name = _knowledge_source_name(knowledge_source_store, source_id)
        if source_name is not None:
            return source_name
        raw_source = str(chunk.get("source") or "").strip()
        if not raw_source or _NUMBERED_REFERENCE_LABEL_RE.match(raw_source):
            return f"Knowledge Source {source_id}"

    source_value = chunk.get("source")
    if source_value is None:
        return None
    label = Path(str(source_value)).name or str(source_value)
    return label.strip() or None


def _knowledge_source_id_from_chunk(chunk: Mapping[str, Any]) -> str | None:
    for value in (chunk.get("source_id"), chunk.get("citation"), chunk.get("source")):
        if not isinstance(value, str):
            continue
        match = _KNOWLEDGE_SOURCE_URI_RE.search(value)
        if match is not None:
            return match.group(1)
        if value.startswith("ks_"):
            return value
    return None


def _knowledge_source_name(
    knowledge_source_store: object | None,
    source_id: str,
) -> str | None:
    if knowledge_source_store is None:
        return None
    get_knowledge_source = getattr(knowledge_source_store, "get_knowledge_source", None)
    if not callable(get_knowledge_source):
        return None
    try:
        source = get_knowledge_source(source_id)
    except Exception:
        return None
    name = getattr(source, "name", None)
    if not isinstance(name, str):
        return None
    name = name.strip()
    return name or None


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


def _get_case_memory_store(
    request: Request,
    manifest: AgentManifest,
) -> LocalMemoryStore | Mem0MemoryStore:
    if _memory_provider(manifest) == "mem0":
        store = getattr(request.app.state, "mem0_memory_store", None)
        if store is None:
            store = Mem0MemoryStore()
            request.app.state.mem0_memory_store = store
        return cast(Mem0MemoryStore, store)
    return _get_memory_store(request)


def _get_run_store(request: Request) -> RunStore:
    return cast(RunStore, request.app.state.store)


def _get_published_agents(request: Request) -> PublishedAgentRegistry:
    return cast(PublishedAgentRegistry, request.app.state.published_agents)
