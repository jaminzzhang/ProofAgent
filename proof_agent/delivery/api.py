"""Run Execution API endpoints for application surfaces."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.contracts import AgentManifest, ContextAdmission, ConversationRecord, ConversationTurn
from proof_agent.contracts.conversation import (
    context_admission_payload,
    conversation_record_payload,
)
from proof_agent.control.conversation import admit_conversation_context
from proof_agent.delivery.published_agents import (
    PublishedAgentRegistry,
    published_agent_directory_payload,
)
from proof_agent.errors import ProofAgentError
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.observability.storage.conversation_store import ConversationStore
from proof_agent.observability.storage.run_store import RunStore
from proof_agent.runtime.approval_resume import (
    LangGraphApprovalResumeContext,
    LangGraphApprovalResumeRegistry,
)
from proof_agent.runtime.langgraph_runner import run_with_langgraph


router = APIRouter(tags=["execution"])


class ChatRunRequest(BaseModel):
    """Request body for starting a Published Agent run from chat."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    include_governance_details: bool = False
    allow_untrusted_web_supplement: bool = False


class ConversationCreateRequest(BaseModel):
    """Request body for creating an assisted chat conversation."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1)


class ConversationUpdateRequest(BaseModel):
    """Request body for updating conversation metadata (title, pin state)."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    pinned: bool | None = None


class ConversationRunRequest(BaseModel):
    """Request body for adding one governed run to a conversation."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    include_governance_details: bool = False
    allow_untrusted_web_supplement: bool = False


@router.get("/chat/agents")
def list_chat_agents(app_request: Request) -> dict[str, Any]:
    """Return Published Agents available to operator-facing chat."""

    registry = _get_published_agents(app_request)
    return published_agent_directory_payload(registry.list_agents())


@router.post("/chat/runs")
def create_chat_run(request: ChatRunRequest, app_request: Request) -> dict[str, Any]:
    """Start one governed Harness run for a Published Agent."""

    registry = _get_published_agents(app_request)
    published_agent = registry.resolve(request.agent_id)
    if published_agent is None:
        raise HTTPException(
            status_code=404,
            detail={
                "message": f"Published Agent not found: {request.agent_id}",
                "available_agent_ids": registry.list_agent_ids(),
            },
        )

    _, detail, manifest = _execute_published_agent_run(
        app_request=app_request,
        manifest_path=published_agent.manifest_path,
        question=request.question,
        agent_id=published_agent.agent_id,
        agent_version_id=published_agent.agent_version_id,
        draft_id=published_agent.source_draft_id,
        resolved_knowledge_bindings=published_agent.resolved_knowledge_bindings,
        allow_untrusted_web_supplement=request.allow_untrusted_web_supplement,
    )

    return _run_response(
        agent_id=published_agent.agent_id,
        detail=detail,
        manifest=manifest,
        include_governance_details=request.include_governance_details,
    )


@router.post("/chat/conversations")
def create_conversation(
    request: ConversationCreateRequest, app_request: Request
) -> dict[str, Any]:
    """Create an assisted chat conversation for a Published Agent."""

    registry = _get_published_agents(app_request)
    if registry.resolve(request.agent_id) is None:
        raise HTTPException(
            status_code=404,
            detail={
                "message": f"Published Agent not found: {request.agent_id}",
                "available_agent_ids": registry.list_agent_ids(),
            },
        )
    record = _get_conversation_store(app_request).create_conversation(agent_id=request.agent_id)
    return conversation_record_payload(record)


@router.get("/chat/conversations")
def list_conversations(app_request: Request) -> list[dict[str, Any]]:
    """Return a list of all assisted chat conversations."""
    records = _get_conversation_store(app_request).list_conversations()
    return [conversation_record_payload(r) for r in records]


@router.get("/chat/conversations/{conversation_id}")
def get_conversation(conversation_id: str, app_request: Request) -> dict[str, Any]:
    """Return the operator-facing conversation timeline."""

    record = _require_conversation(app_request, conversation_id)
    return conversation_record_payload(record)


@router.patch("/chat/conversations/{conversation_id}")
def update_conversation(
    conversation_id: str,
    request: ConversationUpdateRequest,
    app_request: Request,
) -> dict[str, Any]:
    """Update conversation title and/or pin state."""

    store = _get_conversation_store(app_request)
    updated = store.update_conversation(
        conversation_id,
        title=request.title,
        pinned=request.pinned,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Conversation not found: {conversation_id}")
    return conversation_record_payload(updated)


@router.delete("/chat/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str, app_request: Request) -> None:
    """Delete a conversation and all its data."""

    store = _get_conversation_store(app_request)
    if not store.delete_conversation(conversation_id):
        raise HTTPException(status_code=404, detail=f"Conversation not found: {conversation_id}")


@router.post("/chat/conversations/{conversation_id}/runs")
def create_conversation_run(
    conversation_id: str,
    request: ConversationRunRequest,
    app_request: Request,
) -> dict[str, Any]:
    """Start a governed Harness run with admitted conversation context."""

    conversation = _require_conversation(app_request, conversation_id)
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

    context_admission = admit_conversation_context(conversation)
    result, detail, manifest = _execute_published_agent_run(
        app_request=app_request,
        manifest_path=published_agent.manifest_path,
        question=request.question,
        conversation_context=context_admission,
        agent_id=published_agent.agent_id,
        agent_version_id=published_agent.agent_version_id,
        draft_id=published_agent.source_draft_id,
        resolved_knowledge_bindings=published_agent.resolved_knowledge_bindings,
        allow_untrusted_web_supplement=request.allow_untrusted_web_supplement,
    )
    governance_details = _governance_projection(
        detail,
        manifest,
        request.include_governance_details,
    )
    turn = ConversationTurn(
        turn_id=f"turn_{uuid4().hex[:8]}",
        run_id=detail.run_id,
        agent_id=conversation.agent_id,
        question=request.question,
        final_output=result.final_output,
        outcome=detail.outcome,
        created_at=_now(),
        context_admission=context_admission,
        evidence=tuple(detail.evidence_chunks),
        approval_state=detail.approval_state,
        governance_details=governance_details,
    )
    updated = _get_conversation_store(app_request).append_turn(
        conversation_id=conversation.conversation_id,
        turn=turn,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Conversation not found: {conversation_id}")

    return _run_response(
        agent_id=conversation.agent_id,
        detail=detail,
        manifest=manifest,
        final_output=result.final_output,
        conversation_id=conversation.conversation_id,
        turn_id=turn.turn_id,
        context_admission=context_admission,
        include_governance_details=request.include_governance_details,
    )


def _execute_published_agent_run(
    *,
    app_request: Request,
    manifest_path: Path,
    question: str,
    conversation_context: ContextAdmission | None = None,
    agent_id: str | None = None,
    agent_version_id: str | None = None,
    draft_id: str | None = None,
    resolved_knowledge_bindings: Any | None = None,
    allow_untrusted_web_supplement: bool = False,
) -> tuple[Any, Any, AgentManifest]:
    store = _get_store(app_request)
    run_id = f"run_{uuid4().hex[:8]}"
    resume_registry = _get_approval_resume_registry(app_request)
    checkpointer = resume_registry.checkpointer_for(run_id)
    try:
        manifest = load_agent_manifest(manifest_path)
        result = run_with_langgraph(
            manifest_path,
            question=question,
            runs_dir=_get_runs_dir(app_request),
            conversation_context=conversation_context,
            run_id=run_id,
            store=store,
            checkpointer=checkpointer,
            manifest=manifest,
            resolved_knowledge_bindings=resolved_knowledge_bindings,
            configuration_store=_get_configuration_store(app_request),
            agent_id=agent_id,
            agent_version_id=agent_version_id,
            draft_id=draft_id,
            allow_untrusted_web_supplement=allow_untrusted_web_supplement,
        )
    except ProofAgentError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": exc.message, "fix": exc.fix},
        ) from exc

    detail = store.get_run_detail(run_id)
    if detail is None:
        raise HTTPException(status_code=500, detail="Run artifacts were not persisted.")
    if detail.pending_approvals:
        resume_registry.put(
            LangGraphApprovalResumeContext(
                agent_yaml=manifest_path,
                runs_dir=store.history_dir / run_id,
                run_id=run_id,
                question=question,
                checkpointer=checkpointer,
                manifest=manifest,
                conversation_context=conversation_context,
                resolved_knowledge_bindings=resolved_knowledge_bindings,
                configuration_store=_get_configuration_store(app_request),
                run_purpose=detail.run_purpose,
                agent_id=agent_id,
                agent_version_id=agent_version_id,
                draft_id=draft_id,
                allow_untrusted_web_supplement=allow_untrusted_web_supplement,
            )
        )
    return result, detail, manifest


def _run_response(
    *,
    agent_id: str,
    detail: Any,
    manifest: AgentManifest,
    final_output: str | None = None,
    conversation_id: str | None = None,
    turn_id: str | None = None,
    context_admission: ContextAdmission | None = None,
    include_governance_details: bool = False,
) -> dict[str, Any]:
    response = {
        "agent_id": agent_id,
        "agent_version_id": detail.agent_version_id,
        "run_id": detail.run_id,
        "outcome": detail.outcome.value,
        "final_output": final_output or _final_output_from_trace(detail),
        "evidence": list(detail.evidence_chunks),
        "approval_state": detail.approval_state,
        "pending_approvals": list(detail.pending_approvals),
        "links": {
            "run_detail": f"/api/runs/{detail.run_id}",
            "trace": f"/api/runs/{detail.run_id}/trace",
            "receipt": f"/api/runs/{detail.run_id}/receipt",
        },
    }
    if conversation_id is not None:
        response["conversation_id"] = conversation_id
    if turn_id is not None:
        response["turn_id"] = turn_id
    if context_admission is not None:
        response["context_admission"] = context_admission_payload(context_admission)
    governance_details = _governance_projection(
        detail,
        manifest,
        include_governance_details,
    )
    if governance_details is not None:
        response["governance_details"] = governance_details
    return response


def _governance_projection(
    detail: Any,
    manifest: AgentManifest,
    requested: bool,
) -> dict[str, Any] | None:
    if not requested or manifest.response is None:
        return None

    allowed: dict[str, Any] = {}
    details = detail.governance_details or {}
    if manifest.response.include_reasoning_summary:
        allowed["intent_resolution"] = details.get("intent_resolution")
        allowed["reasoning_summary"] = details.get("reasoning_summary")
    if manifest.response.include_review_results:
        allowed["review_results"] = details.get("review_results", [])
    return allowed or None


def _final_output_from_trace(detail: Any) -> str:
    final = next(
        (event for event in reversed(detail.trace_events) if event.get("event_type") == "final_output"),
        None,
    )
    if final is None:
        return ""
    return str(final.get("payload", {}).get("message") or "")


def _get_store(request: Request) -> RunStore:
    return cast(RunStore, request.app.state.store)


def _get_runs_dir(request: Request) -> Path:
    return cast(Path, request.app.state.runs_dir)


def _get_published_agents(request: Request) -> PublishedAgentRegistry:
    return cast(PublishedAgentRegistry, request.app.state.published_agents)


def _get_conversation_store(request: Request) -> ConversationStore:
    return cast(ConversationStore, request.app.state.conversation_store)


def _get_configuration_store(request: Request) -> LocalAgentConfigurationStore:
    return cast(LocalAgentConfigurationStore, request.app.state.agent_configuration_store)


def _get_approval_resume_registry(request: Request) -> LangGraphApprovalResumeRegistry:
    return cast(LangGraphApprovalResumeRegistry, request.app.state.approval_resume_registry)


def _require_conversation(request: Request, conversation_id: str) -> ConversationRecord:
    conversation = _get_conversation_store(request).get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail=f"Conversation not found: {conversation_id}")
    return conversation


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
