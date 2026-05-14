"""Run Execution API endpoints for application surfaces."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from proof_agent.contracts import ContextAdmission, ConversationRecord, ConversationTurn
from proof_agent.contracts.conversation import (
    context_admission_payload,
    conversation_record_payload,
)
from proof_agent.control.conversation import admit_conversation_context
from proof_agent.delivery.published_agents import PublishedAgentRegistry
from proof_agent.errors import ProofAgentError
from proof_agent.observability.storage.conversation_store import ConversationStore
from proof_agent.observability.storage.run_store import RunStore
from proof_agent.runtime.langgraph_runner import run_with_langgraph


router = APIRouter(tags=["execution"])


class ChatRunRequest(BaseModel):
    """Request body for starting a Published Agent run from chat."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    approved: bool | None = None


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
    approved: bool | None = None


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

    _, detail = _execute_published_agent_run(
        app_request=app_request,
        manifest_path=published_agent.manifest_path,
        question=request.question,
        approved=request.approved,
    )

    return _run_response(agent_id=published_agent.agent_id, detail=detail)


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
    result, detail = _execute_published_agent_run(
        app_request=app_request,
        manifest_path=published_agent.manifest_path,
        question=request.question,
        approved=request.approved,
        conversation_context=context_admission,
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
        final_output=result.final_output,
        conversation_id=conversation.conversation_id,
        turn_id=turn.turn_id,
        context_admission=context_admission,
    )


def _execute_published_agent_run(
    *,
    app_request: Request,
    manifest_path: Path,
    question: str,
    approved: bool | None,
    conversation_context: ContextAdmission | None = None,
) -> tuple[Any, Any]:
    store = _get_store(app_request)
    run_id = f"run_{uuid4().hex[:8]}"
    try:
        result = run_with_langgraph(
            manifest_path,
            question=question,
            runs_dir=_get_runs_dir(app_request),
            approved=approved,
            conversation_context=conversation_context,
            run_id=run_id,
            store=store,
        )
    except ProofAgentError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": exc.message, "fix": exc.fix},
        ) from exc

    detail = store.get_run_detail(run_id)
    if detail is None:
        raise HTTPException(status_code=500, detail="Run artifacts were not persisted.")
    return result, detail


def _run_response(
    *,
    agent_id: str,
    detail: Any,
    final_output: str | None = None,
    conversation_id: str | None = None,
    turn_id: str | None = None,
    context_admission: ContextAdmission | None = None,
) -> dict[str, Any]:
    response = {
        "agent_id": agent_id,
        "run_id": detail.run_id,
        "outcome": detail.outcome.value,
        "final_output": final_output or _final_output_from_trace(detail),
        "evidence": list(detail.evidence_chunks),
        "approval_state": detail.approval_state,
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
    return response


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


def _require_conversation(request: Request, conversation_id: str) -> ConversationRecord:
    conversation = _get_conversation_store(request).get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail=f"Conversation not found: {conversation_id}")
    return conversation


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
