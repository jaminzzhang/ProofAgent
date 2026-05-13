"""Run Execution API endpoints for application surfaces."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from proof_agent.delivery.published_agents import PublishedAgentRegistry
from proof_agent.errors import ProofAgentError
from proof_agent.observability.storage.run_store import RunStore
from proof_agent.runtime.langgraph_runner import run_with_langgraph


router = APIRouter(tags=["execution"])


class ChatRunRequest(BaseModel):
    """Request body for starting a Published Agent run from chat."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1)
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

    store = _get_store(app_request)
    runs_dir = _get_runs_dir(app_request)
    run_id = f"run_{uuid4().hex[:8]}"
    try:
        result = run_with_langgraph(
            published_agent.manifest_path,
            question=request.question,
            runs_dir=runs_dir,
            approved=request.approved,
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

    return {
        "agent_id": published_agent.agent_id,
        "run_id": detail.run_id,
        "outcome": detail.outcome.value,
        "final_output": result.final_output,
        "evidence": list(detail.evidence_chunks),
        "approval_state": detail.approval_state,
        "links": {
            "run_detail": f"/api/runs/{detail.run_id}",
            "trace": f"/api/runs/{detail.run_id}/trace",
            "receipt": f"/api/runs/{detail.run_id}/receipt",
        },
    }


def _get_store(request: Request) -> RunStore:
    return cast(RunStore, request.app.state.store)


def _get_runs_dir(request: Request) -> Path:
    return cast(Path, request.app.state.runs_dir)


def _get_published_agents(request: Request) -> PublishedAgentRegistry:
    return cast(PublishedAgentRegistry, request.app.state.published_agents)
