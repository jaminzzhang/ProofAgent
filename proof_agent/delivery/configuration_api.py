"""Agent Configuration API endpoints for the Dashboard workspace."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.configuration.compiler import compile_draft_agent
from proof_agent.configuration.importer import import_agent_package
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import AgentValidationRecord, ContractBundle, DraftAgent, RunPurpose
from proof_agent.errors import ProofAgentError
from proof_agent.observability.storage.run_store import RunStore
from proof_agent.runtime.langgraph_runner import run_with_langgraph


router = APIRouter(tags=["configuration"])


class AgentImportRequest(BaseModel):
    """Request body for importing an existing Agent Package."""

    model_config = ConfigDict(extra="forbid")

    manifest_path: str = Field(min_length=1)
    actor: str = "local-user"


class DraftUpdateRequest(BaseModel):
    """Request body for editable Draft Agent fields."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    purpose: str | None = None
    actor: str = "local-user"


class ContractUpdateRequest(BaseModel):
    """Request body for updating preserved Contract View files."""

    model_config = ConfigDict(extra="forbid")

    agent_yaml: str | None = None
    policy_yaml: str | None = None
    tools_yaml: str | None = None
    actor: str = "local-user"


class DraftValidationRequest(BaseModel):
    """Request body for triggering a governed validation run."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    approved: bool | None = None
    actor: str = "local-user"


class DraftPublishRequest(BaseModel):
    """Request body for publishing a Draft Agent after validation."""

    model_config = ConfigDict(extra="forbid")

    validation_run_id: str | None = None
    actor: str = "local-user"


class RollbackRequest(BaseModel):
    """Request body for switching the Active Agent Version pointer."""

    model_config = ConfigDict(extra="forbid")

    actor: str = "local-user"


@router.get("/config/agents")
def list_config_agents(app_request: Request) -> dict[str, Any]:
    """List Agent identities managed by the local configuration store."""

    store = _get_configuration_store(app_request)
    agent_ids = _configuration_agent_ids(store)
    data = [_agent_summary_payload(store, agent_id) for agent_id in agent_ids]
    return {"data": data, "meta": {"total": len(data)}}


@router.post("/config/agents/import")
def import_config_agent(
    request: AgentImportRequest,
    app_request: Request,
) -> dict[str, Any]:
    """Import an existing Agent Package into Draft Agent state."""

    manifest_path = Path(request.manifest_path)
    if not manifest_path.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Agent manifest not found: {request.manifest_path}",
        )
    try:
        draft = import_agent_package(
            manifest_path,
            store=_get_configuration_store(app_request),
            actor=request.actor,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProofAgentError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": exc.message, "fix": exc.fix},
        ) from exc
    return _draft_payload(draft)


@router.get("/config/agents/{agent_id}/drafts/{draft_id}")
def get_config_draft(agent_id: str, draft_id: str, app_request: Request) -> dict[str, Any]:
    """Return editable Draft Agent metadata."""

    draft = _require_draft(_get_configuration_store(app_request), agent_id, draft_id)
    return _draft_payload(draft)


@router.patch("/config/agents/{agent_id}/drafts/{draft_id}")
def update_config_draft(
    agent_id: str,
    draft_id: str,
    request: DraftUpdateRequest,
    app_request: Request,
) -> dict[str, Any]:
    """Update editable Draft Agent fields."""

    store = _get_configuration_store(app_request)
    _require_draft(store, agent_id, draft_id)
    draft = store.update_draft(
        agent_id=agent_id,
        draft_id=draft_id,
        display_name=request.display_name,
        purpose=request.purpose,
        actor=request.actor,
    )
    return _draft_payload(draft)


@router.get("/config/agents/{agent_id}/drafts/{draft_id}/contract")
def get_config_draft_contract(
    agent_id: str,
    draft_id: str,
    app_request: Request,
) -> dict[str, Any]:
    """Return the preserved Contract View for a Draft Agent."""

    draft = _require_draft(_get_configuration_store(app_request), agent_id, draft_id)
    return draft.contract_bundle.model_dump(mode="json")


@router.patch("/config/agents/{agent_id}/drafts/{draft_id}/contract")
def update_config_draft_contract(
    agent_id: str,
    draft_id: str,
    request: ContractUpdateRequest,
    app_request: Request,
) -> dict[str, Any]:
    """Update the preserved Contract View and validate it as an Agent Package."""

    store = _get_configuration_store(app_request)
    draft = _require_draft(store, agent_id, draft_id)
    bundle = ContractBundle(
        agent_yaml=request.agent_yaml
        if request.agent_yaml is not None
        else draft.contract_bundle.agent_yaml,
        policy_yaml=request.policy_yaml
        if request.policy_yaml is not None
        else draft.contract_bundle.policy_yaml,
        tools_yaml=request.tools_yaml
        if request.tools_yaml is not None
        else draft.contract_bundle.tools_yaml,
        extra_files=draft.contract_bundle.extra_files,
        advanced_fields=draft.contract_bundle.advanced_fields,
    )
    candidate = _draft_with_contract_bundle(draft, bundle)
    try:
        package_dir = compile_draft_agent(candidate, store.root_dir / "compiled_validation")
        load_agent_manifest(package_dir / "agent.yaml")
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProofAgentError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": exc.message, "fix": exc.fix},
        ) from exc

    updated = store.update_draft(
        agent_id=agent_id,
        draft_id=draft_id,
        contract_bundle=bundle,
        actor=request.actor,
    )
    return updated.contract_bundle.model_dump(mode="json")


@router.post("/config/agents/{agent_id}/drafts/{draft_id}/validate")
def validate_config_draft(
    agent_id: str,
    draft_id: str,
    request: DraftValidationRequest,
    app_request: Request,
) -> dict[str, Any]:
    """Run a Draft Agent through the governed Harness as a validation run."""

    config_store = _get_configuration_store(app_request)
    draft = _require_draft(config_store, agent_id, draft_id)
    package_dir = compile_draft_agent(draft, config_store.root_dir / "compiled")
    run_store = _get_run_store(app_request)
    run_id = f"run_{uuid4().hex[:8]}"
    try:
        result = run_with_langgraph(
            package_dir / "agent.yaml",
            question=request.question,
            runs_dir=_get_runs_dir(app_request),
            approved=request.approved,
            run_id=run_id,
            store=run_store,
            run_purpose=RunPurpose.VALIDATION,
            agent_id=agent_id,
            draft_id=draft_id,
        )
    except ProofAgentError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": exc.message, "fix": exc.fix},
        ) from exc
    detail = run_store.get_run_detail(run_id)
    if detail is None:
        raise HTTPException(status_code=500, detail="Validation run artifacts were not persisted.")
    record = AgentValidationRecord(
        validation_id=f"validation_{uuid4().hex[:8]}",
        draft_id=draft_id,
        run_id=run_id,
        status=detail.outcome.value,
        created_at=_now(),
        summary=result.final_output[:500],
    )
    config_store.record_validation(
        agent_id=agent_id,
        draft_id=draft_id,
        record=record,
        actor=request.actor,
    )
    return {
        "validation_id": record.validation_id,
        "run_id": detail.run_id,
        "status": record.status,
        "outcome": detail.outcome.value,
        "run_purpose": detail.run_purpose.value,
        "agent_id": detail.agent_id,
        "draft_id": detail.draft_id,
        "links": {
            "run_detail": f"/api/runs/{detail.run_id}",
            "trace": f"/api/runs/{detail.run_id}/trace",
            "receipt": f"/api/runs/{detail.run_id}/receipt",
        },
    }


@router.post("/config/agents/{agent_id}/drafts/{draft_id}/publish")
def publish_config_draft(
    agent_id: str,
    draft_id: str,
    request: DraftPublishRequest,
    app_request: Request,
) -> dict[str, Any]:
    """Publish a validated Draft Agent as an immutable version."""

    store = _get_configuration_store(app_request)
    draft = _require_draft(store, agent_id, draft_id)
    validation_run_id = request.validation_run_id or _latest_validation_run_id(draft)
    if validation_run_id is None:
        raise HTTPException(status_code=400, detail="A validation run is required before publish.")
    if validation_run_id not in {record.run_id for record in draft.validation_records}:
        raise HTTPException(
            status_code=400,
            detail=f"Validation run is not recorded for this draft: {validation_run_id}",
        )
    version = store.publish_version(
        agent_id=agent_id,
        draft_id=draft_id,
        validation_run_id=validation_run_id,
        actor=request.actor,
    )
    return _version_payload(version)


@router.get("/config/agents/{agent_id}/versions")
def list_config_versions(agent_id: str, app_request: Request) -> dict[str, Any]:
    """List immutable Published Agent Versions for one Agent identity."""

    store = _get_configuration_store(app_request)
    versions = store.list_versions(agent_id)
    active = store.get_active_version(agent_id)
    return {
        "data": [_version_payload(version) for version in versions],
        "meta": {
            "total": len(versions),
            "active_version_id": active.version_id if active else None,
        },
    }


@router.post("/config/agents/{agent_id}/versions/{version_id}/rollback")
def rollback_config_version(
    agent_id: str,
    version_id: str,
    request: RollbackRequest,
    app_request: Request,
) -> dict[str, Any]:
    """Switch the Active Agent Version pointer to a previous version."""

    store = _get_configuration_store(app_request)
    try:
        active = store.rollback_active_version(
            agent_id=agent_id,
            version_id=version_id,
            actor=request.actor,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return active.model_dump(mode="json")


def _agent_summary_payload(
    store: LocalAgentConfigurationStore,
    agent_id: str,
) -> dict[str, Any]:
    drafts = store.list_drafts(agent_id)
    versions = store.list_versions(agent_id)
    active = store.get_active_version(agent_id)
    latest_draft = max(drafts, key=lambda draft: draft.updated_at) if drafts else None
    return {
        "agent_id": agent_id,
        "display_name": latest_draft.display_name if latest_draft else agent_id,
        "purpose": latest_draft.purpose if latest_draft else "",
        "draft_count": len(drafts),
        "latest_draft_id": latest_draft.draft_id if latest_draft else None,
        "version_count": len(versions),
        "active_version_id": active.version_id if active else None,
        "updated_at": latest_draft.updated_at if latest_draft else None,
    }


def _draft_payload(draft: DraftAgent) -> dict[str, Any]:
    return {
        "agent_id": draft.agent_id,
        "draft_id": draft.draft_id,
        "display_name": draft.display_name,
        "purpose": draft.purpose,
        "created_at": draft.created_at,
        "updated_at": draft.updated_at,
        "created_by": draft.created_by,
        "updated_by": draft.updated_by,
        "version_id": draft.version_id,
        "validation_records": [
            record.model_dump(mode="json") for record in draft.validation_records
        ],
        "operation_audit": [
            operation.model_dump(mode="json") for operation in draft.operation_audit
        ],
    }


def _draft_with_contract_bundle(draft: DraftAgent, bundle: ContractBundle) -> DraftAgent:
    return DraftAgent(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        display_name=draft.display_name,
        purpose=draft.purpose,
        contract_bundle=bundle,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
        created_by=draft.created_by,
        updated_by=draft.updated_by,
        version_id=draft.version_id,
        validation_records=draft.validation_records,
        operation_audit=draft.operation_audit,
    )


def _version_payload(version: Any) -> dict[str, Any]:
    return {
        "agent_id": version.agent_id,
        "version_id": version.version_id,
        "source_draft_id": version.source_draft_id,
        "validation_run_id": version.validation_run_id,
        "published_at": version.published_at,
        "published_by": version.published_by,
        "operation_audit": [
            operation.model_dump(mode="json") for operation in version.operation_audit
        ],
    }


def _configuration_agent_ids(store: LocalAgentConfigurationStore) -> tuple[str, ...]:
    agents_root = store.root_dir / "agents"
    if not agents_root.exists():
        return ()
    return tuple(sorted(entry.name for entry in agents_root.iterdir() if entry.is_dir()))


def _latest_validation_run_id(draft: DraftAgent) -> str | None:
    if not draft.validation_records:
        return None
    return draft.validation_records[-1].run_id


def _require_draft(
    store: LocalAgentConfigurationStore,
    agent_id: str,
    draft_id: str,
) -> DraftAgent:
    draft = store.get_draft(agent_id, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail=f"Draft Agent not found: {agent_id}/{draft_id}")
    return draft


def _get_configuration_store(request: Request) -> LocalAgentConfigurationStore:
    return cast(LocalAgentConfigurationStore, request.app.state.agent_configuration_store)


def _get_run_store(request: Request) -> RunStore:
    return cast(RunStore, request.app.state.store)


def _get_runs_dir(request: Request) -> Path:
    return cast(Path, request.app.state.runs_dir)


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
