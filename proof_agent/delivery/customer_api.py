"""Customer-facing run API with customer-safe response projection."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from proof_agent.contracts import CustomerResponseSnapshot, CustomerSafeResponse
from proof_agent.contracts.dashboard import RunDetail
from proof_agent.control.validators.customer_response import validate_customer_safe_response
from proof_agent.delivery.api import _execute_published_agent_run
from proof_agent.delivery.published_agents import PublishedAgentRegistry
from proof_agent.observability.storage.customer_store import CustomerStore


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
    return record.model_dump(mode="json")


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

    result, detail, _ = _execute_published_agent_run(
        app_request=app_request,
        manifest_path=published_agent.manifest_path,
        question=request.question,
        approved=None,
    )
    safe_response = CustomerSafeResponse(
        message=str(result.final_output),
        safe_sources=_safe_sources(cast(RunDetail, detail)),
    )
    validation = validate_customer_safe_response(safe_response)
    if validation.status == "failed":
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
        run_id=str(detail.run_id),
        created_at=str(detail.updated_at),
        customer_ref=conversation.customer_ref,
        response=safe_response,
    )
    updated = _get_customer_store(app_request).append_snapshot(
        conversation_id=conversation.conversation_id,
        snapshot=snapshot,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Conversation not found: {conversation_id}")

    payload = safe_response.model_dump(mode="json")
    payload["conversation_id"] = conversation.conversation_id
    payload["turn_id"] = turn_id
    return payload


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


def _require_customer_conversation(
    request: Request,
    conversation_id: str,
) -> Any:
    record = _get_customer_store(request).get_conversation(conversation_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Conversation not found: {conversation_id}")
    return record


def _get_customer_store(request: Request) -> CustomerStore:
    return cast(CustomerStore, request.app.state.customer_store)


def _get_published_agents(request: Request) -> PublishedAgentRegistry:
    return cast(PublishedAgentRegistry, request.app.state.published_agents)
