"""Agent Configuration API endpoints for the Dashboard workspace."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
import yaml  # type: ignore[import-untyped]

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.bootstrap.skills import (
    SUPPORTED_BUSINESS_FLOW_ADDENDUM_STAGE_IDS,
    load_business_flow_skill_pack_set,
)
from proof_agent.bootstrap.validation import (
    validate_workflow_stage_prompt_config,
)
from proof_agent.capabilities.tools.source_descriptors import (
    get_tool_source_descriptor,
    list_tool_source_descriptors,
)
from proof_agent.configuration.compiler import compile_draft_agent
from proof_agent.configuration.importer import import_agent_package
from proof_agent.configuration.local_store import (
    LocalAgentConfigurationStore,
)
from proof_agent.contracts import (
    AuditActorFacts,
    ContractBundle,
    DraftAgent,
    EnvironmentModelCredentialReference,
    ModelConnectionSmokeTestRecord,
    ModelConnectionValidationRecord,
    SharedModelConnection,
    ToolSource,
    WorkflowStageConfigurationRuntimeSource,
    WorkflowStageConfigurationRuntimeSourceType,
    WorkflowStagePromptConfig,
)
from proof_agent.control.agent_configuration_workspace import (
    AgentConfigurationConflict,
    AgentConfigurationNotFound,
    AgentConfigurationPublicationRejected,
    AgentConfigurationWorkspace,
    SOLE_PRODUCTION_AGENT_ID,
    load_server_owned_agent_template,
)
from proof_agent.control.workflow.stage_context import build_workflow_stage_context_preview
from proof_agent.control.workflow.stage_configuration import (
    resolve_workflow_stage_runtime_configuration,
)
from proof_agent.control.workflow.templates import (
    list_workflow_templates,
    resolve_workflow_template,
)
from proof_agent.delivery.http_errors import proof_agent_http_exception
from proof_agent.errors import ProofAgentError
from proof_agent.observability.api.dependencies import get_operator_identity
from proof_agent.observability.api.operator_identity import (
    OperatorIdentityContext,
    OperatorPermission,
    require_operator_permission,
)
from proof_agent.observability.api.serializers import serialize_agent_version_rollback
from proof_agent.observability.storage.run_store import RunStore


router = APIRouter(tags=["configuration"])

SUPPORTED_SHARED_MODEL_CONNECTION_PROVIDERS = {
    "openai",
    "openai_compatible",
    "deepseek",
}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
_CANONICAL_AGENT_TEMPLATE = {
    "id": SOLE_PRODUCTION_AGENT_ID,
    "name": "Agent Management Insurance Specialist",
    "purpose": (
        "Assist internal insurance staff with governed, evidence-backed insurance "
        "knowledge consultation."
    ),
    "description": (
        "Operator-facing Controlled ReAct V3 consultation with production publication "
        "kept behind candidate gates."
    ),
}
_DEVELOPMENT_DRAFT_CAPABILITIES = {
    "mode": "development",
    "editable_modules": [
        "general",
        "workflow",
        "skills",
        "knowledge",
        "tools",
        "policy",
        "model",
        "memory",
        "response",
    ],
    "lifecycle_tabs": ["validate", "versions", "contract", "monitor"],
    "actions": {
        "can_validate": True,
        "can_publish": True,
        "can_rollback": True,
    },
}


def _require_operator(
    identity: OperatorIdentityContext,
    permission: OperatorPermission,
) -> str:
    """Authorize an operator command and return the audited operator id."""

    require_operator_permission(identity, permission)
    return identity.operator_id


class AgentImportRequest(BaseModel):
    """Request body for importing an existing Agent Package."""

    model_config = ConfigDict(extra="forbid")

    manifest_path: str = Field(min_length=1)


class AgentCreateRequest(BaseModel):
    """Browser-safe command for creating a Draft from the server-owned template."""

    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=200)
    purpose: str = Field(default="", max_length=4_000)


class DraftUpdateRequest(BaseModel):
    """Request body for editable Draft Agent fields."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    purpose: str | None = None


class ContractUpdateRequest(BaseModel):
    """Request body for updating preserved Contract View files."""

    model_config = ConfigDict(extra="forbid")

    agent_yaml: str | None = None
    policy_yaml: str | None = None
    tools_yaml: str | None = None


class BusinessFlowSkillPackCreateRequest(BaseModel):
    """Request body for creating one draft-local Business Flow Skill Pack."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_][A-Za-z0-9_-]*$")
    label: str = Field(min_length=1)
    description: str = Field(min_length=1)
    intent_patterns: list[str] = Field(default_factory=list)
    intent_taxonomy_refs: list[str] = Field(default_factory=list)
    default: bool = False


class WorkflowStagePromptRequest(BaseModel):
    """Request body fragment for stage-level business Prompt settings."""

    model_config = ConfigDict(extra="forbid")

    business_context: str | None = None
    task_instructions: list[str] = Field(default_factory=list)
    output_preferences: list[str] = Field(default_factory=list)


class BusinessFlowSkillPackUpdateRequest(BaseModel):
    """Request body for updating one draft-local Business Flow Skill Pack."""

    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1)
    description: str | None = Field(default=None, min_length=1)
    intent_patterns: list[str] | None = None
    intent_taxonomy_refs: list[str] | None = None
    stage_prompt_addenda: dict[str, WorkflowStagePromptRequest] | None = None
    knowledge_binding_refs: list[str] | None = None
    tool_contract_refs: list[str] | None = None
    policy_rule_refs: list[str] | None = None
    validator_refs: list[str] | None = None
    admission: dict[str, Any] | None = None
    default: bool | None = None


class WorkflowStageUpdateItemRequest(BaseModel):
    """Request body item for one workflow stage configuration."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    prompt: WorkflowStagePromptRequest = Field(default_factory=WorkflowStagePromptRequest)
    context: dict[str, bool] = Field(default_factory=dict)


class WorkflowStagesUpdateRequest(BaseModel):
    """Request body for replacing Draft Agent workflow stage configuration."""

    model_config = ConfigDict(extra="forbid")

    template_descriptor_version: str | None = None
    stages: list[WorkflowStageUpdateItemRequest]


class WorkflowStagePreviewRequest(BaseModel):
    """Request body for rendering one redacted Workflow Stage Context Preview."""

    model_config = ConfigDict(extra="forbid")

    prompt: WorkflowStagePromptRequest = Field(default_factory=WorkflowStagePromptRequest)
    context: dict[str, bool] = Field(default_factory=dict)


class DraftValidationRequest(BaseModel):
    """Request body for triggering a governed validation run."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    full_capture: bool = False
    retain_for_audit: bool = False


class DraftPublishRequest(BaseModel):
    """Request body for publishing a Draft Agent after validation."""

    model_config = ConfigDict(extra="forbid")

    validation_run_id: str | None = None


class RollbackRequest(BaseModel):
    """Request body for switching the Active Agent Version pointer."""

    model_config = ConfigDict(extra="forbid")


class ModelCredentialReferenceRequest(BaseModel):
    """Secret-safe model credential reference."""

    model_config = ConfigDict(extra="forbid")

    type: str = "env"
    name: str = Field(min_length=1)


class ModelConnectionCreateRequest(BaseModel):
    """Request body for creating a Shared Model Connection."""

    model_config = ConfigDict(extra="forbid")

    connection_id: str | None = None
    display_name: str = Field(min_length=1)
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    provider: str = Field(min_length=1)
    model_identifier: str = Field(min_length=1)
    base_url: str | None = None
    credential_ref: ModelCredentialReferenceRequest
    organization_env: str | None = None
    project_env: str | None = None
    timeout_seconds: float | None = None


class ModelConnectionUpdateRequest(BaseModel):
    """Request body for updating a Shared Model Connection."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    provider: str | None = None
    model_identifier: str | None = None
    base_url: str | None = None
    credential_ref: ModelCredentialReferenceRequest | None = None
    organization_env: str | None = None
    project_env: str | None = None
    timeout_seconds: float | None = None
    confirm_impact: bool = False


class ModelConnectionArchiveRequest(BaseModel):
    """Request body for archiving a Shared Model Connection."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)


class ModelConnectionRestoreRequest(BaseModel):
    """Request body for restoring a Shared Model Connection."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = None


class ModelConnectionPhysicalDeleteRequest(BaseModel):
    """Request body for permanently deleting a Shared Model Connection."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)


class ModelConnectionValidationRequest(BaseModel):
    """Request body for validating a Shared Model Connection."""

    model_config = ConfigDict(extra="forbid")


class ToolSourceCreateRequest(BaseModel):
    """Request body for creating a reusable Tool Source connection."""

    model_config = ConfigDict(extra="forbid")

    source_id: str | None = None
    name: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    tool_contract_ids: list[str] = Field(default_factory=list)
    credential_env_ref: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class ToolSourceUpdateRequest(BaseModel):
    """Request body for updating a reusable Tool Source connection."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    source_type: str | None = None
    provider: str | None = None
    tool_contract_ids: list[str] | None = None
    credential_env_ref: str | None = None
    params: dict[str, Any] | None = None


class ToolSourceArchiveRequest(BaseModel):
    """Request body for archiving a reusable Tool Source connection."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)


class ToolSourceRestoreRequest(BaseModel):
    """Request body for restoring a reusable Tool Source connection."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = None


@router.get("/config/model-connections")
def list_model_connections(
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """List Shared Model Connections managed by the local configuration store."""

    _require_operator(identity, OperatorPermission.MODEL_CONNECTION_VIEW)
    store = _get_configuration_store(app_request)
    data = [
        _model_connection_payload(store, connection)
        for connection in store.list_model_connections()
    ]
    return {"data": data, "meta": {"total": len(data)}}


@router.post("/config/model-connections")
def create_model_connection(
    request: ModelConnectionCreateRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Create a Shared Model Connection with environment credential references."""

    _require_supported_shared_model_provider(request.provider)
    store = _get_configuration_store(app_request)
    actor = _require_operator(identity, OperatorPermission.MODEL_CONNECTION_EDIT)
    try:
        connection = store.create_model_connection(
            connection_id=_model_connection_id(request.connection_id)
            if request.connection_id
            else None,
            display_name=request.display_name,
            description=request.description,
            tags=tuple(request.tags),
            provider=request.provider,
            model_identifier=request.model_identifier,
            base_url=request.base_url,
            credential_ref=_credential_ref(request.credential_ref),
            organization_env=request.organization_env,
            project_env=request.project_env,
            timeout_seconds=request.timeout_seconds,
            actor=actor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    return _model_connection_payload(store, connection)


@router.get("/config/model-connections/{connection_id}")
def get_model_connection(
    connection_id: str,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Return one Shared Model Connection."""

    _require_operator(identity, OperatorPermission.MODEL_CONNECTION_VIEW)
    store = _get_configuration_store(app_request)
    connection = _require_model_connection(store, connection_id)
    return _model_connection_payload(store, connection)


@router.patch("/config/model-connections/{connection_id}")
def update_model_connection(
    connection_id: str,
    request: ModelConnectionUpdateRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Update one Shared Model Connection."""

    if request.provider is not None:
        _require_supported_shared_model_provider(request.provider)
    store = _get_configuration_store(app_request)
    _require_model_connection(store, connection_id)
    actor = _require_operator(identity, OperatorPermission.MODEL_CONNECTION_EDIT)
    _require_model_connection_update_impact_confirmation(
        store,
        connection_id=connection_id,
        request=request,
    )
    try:
        connection = store.update_model_connection(
            connection_id=connection_id,
            actor=actor,
            display_name=request.display_name,
            description=request.description,
            tags=tuple(request.tags) if request.tags is not None else None,
            provider=request.provider,
            model_identifier=request.model_identifier,
            base_url=request.base_url,
            credential_ref=(
                _credential_ref(request.credential_ref)
                if request.credential_ref is not None
                else None
            ),
            organization_env=request.organization_env,
            project_env=request.project_env,
            timeout_seconds=request.timeout_seconds,
        )
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    return _model_connection_payload(store, connection)


@router.post("/config/model-connections/{connection_id}/archive")
def archive_model_connection(
    connection_id: str,
    request: ModelConnectionArchiveRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Archive a Shared Model Connection without deleting retained state."""

    store = _get_configuration_store(app_request)
    _require_model_connection(store, connection_id)
    actor = _require_operator(identity, OperatorPermission.MODEL_CONNECTION_ARCHIVE)
    try:
        connection = store.archive_model_connection(
            connection_id=connection_id,
            actor=actor,
            reason=request.reason,
        )
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    return _model_connection_payload(store, connection)


@router.post("/config/model-connections/{connection_id}/restore")
def restore_model_connection(
    connection_id: str,
    request: ModelConnectionRestoreRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Restore an archived Shared Model Connection."""

    store = _get_configuration_store(app_request)
    _require_model_connection(store, connection_id)
    actor = _require_operator(identity, OperatorPermission.MODEL_CONNECTION_ARCHIVE)
    try:
        connection = store.restore_model_connection(
            connection_id=connection_id,
            actor=actor,
            reason=request.reason,
        )
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    return _model_connection_payload(store, connection)


@router.get("/config/model-connections/{connection_id}/references")
def get_model_connection_references(
    connection_id: str,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Return configuration references for one Shared Model Connection."""

    _require_operator(identity, OperatorPermission.MODEL_CONNECTION_VIEW)
    store = _get_configuration_store(app_request)
    _require_model_connection(store, connection_id)
    try:
        summary = store.get_model_connection_reference_summary(connection_id)
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    return summary.model_dump(mode="json")


@router.get("/config/model-connections/{connection_id}/deletion-eligibility")
def get_model_connection_deletion_eligibility(
    connection_id: str,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Return physical-deletion eligibility and blockers for one model connection."""

    _require_operator(identity, OperatorPermission.MODEL_CONNECTION_VIEW)
    store = _get_configuration_store(app_request)
    _require_model_connection(store, connection_id)
    try:
        eligibility = store.get_model_connection_deletion_eligibility(connection_id)
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    return eligibility.model_dump(mode="json")


@router.delete("/config/model-connections/{connection_id}")
def physically_delete_model_connection(
    connection_id: str,
    request: ModelConnectionPhysicalDeleteRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Permanently delete an eligible archived Shared Model Connection."""

    store = _get_configuration_store(app_request)
    _require_model_connection(store, connection_id)
    actor = _require_operator(identity, OperatorPermission.MODEL_CONNECTION_ARCHIVE)
    try:
        eligibility = store.physically_delete_model_connection(
            connection_id=connection_id,
            actor=actor,
            reason=request.reason,
        )
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    return eligibility.model_dump(mode="json")


@router.post("/config/model-connections/{connection_id}/validate")
def validate_model_connection(
    connection_id: str,
    request: ModelConnectionValidationRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Run local secret-safe validation for a Shared Model Connection."""

    store = _get_configuration_store(app_request)
    connection = _require_model_connection(store, connection_id)
    actor = _require_operator(identity, OperatorPermission.MODEL_CONNECTION_VALIDATE)
    record = _model_connection_validation_record(connection, actor=actor)
    store.record_model_connection_validation(record)
    return record.model_dump(mode="json")


@router.post("/config/model-connections/{connection_id}/smoke-test")
def smoke_test_model_connection(
    connection_id: str,
    request: ModelConnectionValidationRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Run a manual smoke test for a Shared Model Connection."""

    store = _get_configuration_store(app_request)
    connection = _require_model_connection(store, connection_id)
    actor = _require_operator(identity, OperatorPermission.MODEL_CONNECTION_VALIDATE)
    record = _model_connection_smoke_test_record(connection, actor=actor)
    store.record_model_connection_smoke_test(record)
    return record.model_dump(mode="json")


@router.get("/config/tool-source-descriptors")
def list_tool_source_descriptor_payloads(
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """List built-in trusted Tool Source descriptors."""

    _require_operator(identity, OperatorPermission.TOOL_SOURCE_VIEW)
    data = [descriptor.model_dump(mode="json") for descriptor in list_tool_source_descriptors()]
    return {"data": data, "meta": {"total": len(data)}}


@router.get("/config/tool-sources")
def list_tool_sources(
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """List reusable Tool Sources managed by the local configuration store."""

    _require_operator(identity, OperatorPermission.TOOL_SOURCE_VIEW)
    store = _get_configuration_store(app_request)
    data = [_tool_source_payload(source) for source in store.list_tool_sources()]
    return {"data": data, "meta": {"total": len(data)}}


@router.post("/config/tool-sources")
def create_tool_source(
    request: ToolSourceCreateRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Create a reusable Tool Source from a trusted built-in descriptor."""

    _require_supported_tool_source_provider(request.provider)
    store = _get_configuration_store(app_request)
    actor = _require_operator(identity, OperatorPermission.TOOL_SOURCE_EDIT)
    try:
        source = store.create_tool_source(
            source_id=_tool_source_id(request.source_id or request.name),
            name=request.name,
            source_type=request.source_type,
            provider=request.provider,
            tool_contract_ids=tuple(request.tool_contract_ids),
            credential_env_ref=request.credential_env_ref,
            params=dict(request.params),
            actor=actor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    return _tool_source_payload(source)


@router.get("/config/tool-sources/{source_id}")
def get_tool_source(
    source_id: str,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Return one reusable Tool Source."""

    _require_operator(identity, OperatorPermission.TOOL_SOURCE_VIEW)
    store = _get_configuration_store(app_request)
    source = _require_tool_source(store, source_id)
    return _tool_source_payload(source)


@router.patch("/config/tool-sources/{source_id}")
def update_tool_source(
    source_id: str,
    request: ToolSourceUpdateRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Update one reusable Tool Source live connection."""

    if request.provider is not None:
        _require_supported_tool_source_provider(request.provider)
    store = _get_configuration_store(app_request)
    _require_tool_source(store, source_id)
    actor = _require_operator(identity, OperatorPermission.TOOL_SOURCE_EDIT)
    try:
        source = store.update_tool_source(
            source_id=source_id,
            actor=actor,
            name=request.name,
            source_type=request.source_type,
            provider=request.provider,
            tool_contract_ids=(
                tuple(request.tool_contract_ids) if request.tool_contract_ids is not None else None
            ),
            credential_env_ref=request.credential_env_ref,
            params=dict(request.params) if request.params is not None else None,
        )
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    return _tool_source_payload(source)


@router.post("/config/tool-sources/{source_id}/archive")
def archive_tool_source(
    source_id: str,
    request: ToolSourceArchiveRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Archive a reusable Tool Source without deleting retained state."""

    store = _get_configuration_store(app_request)
    _require_tool_source(store, source_id)
    actor = _require_operator(identity, OperatorPermission.TOOL_SOURCE_ARCHIVE)
    try:
        source = store.archive_tool_source(
            source_id=source_id,
            actor=actor,
            reason=request.reason,
        )
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    return _tool_source_payload(source)


@router.post("/config/tool-sources/{source_id}/restore")
def restore_tool_source(
    source_id: str,
    request: ToolSourceRestoreRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Restore an archived reusable Tool Source to active state."""

    store = _get_configuration_store(app_request)
    _require_tool_source(store, source_id)
    actor = _require_operator(identity, OperatorPermission.TOOL_SOURCE_ARCHIVE)
    try:
        source = store.restore_tool_source(
            source_id=source_id,
            actor=actor,
            reason=request.reason,
        )
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    return _tool_source_payload(source)


@router.get("/config/agents")
def list_config_agents(
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """List Agent identities through the Agent Configuration Workspace."""

    _require_operator(identity, OperatorPermission.AGENT_VIEW)
    inventory = _get_agent_configuration_workspace(app_request).list_agents()
    data = [
        {
            "agent_id": item.agent_id,
            "display_name": item.display_name,
            "purpose": item.purpose,
            "draft_count": item.draft_count,
            "latest_draft_id": item.latest_draft_id,
            "version_count": item.version_count,
            "active_version_id": item.active_version_id,
            "updated_at": item.updated_at,
        }
        for item in inventory.agents
    ]
    return {
        "data": data,
        "meta": {
            "total": len(data),
            "capabilities": {
                "mode": "development",
                "can_create": (
                    inventory.can_create
                    and OperatorPermission.AGENT_EDIT in identity.permissions
                ),
                "can_import_manifest": (
                    OperatorPermission.AGENT_EDIT in identity.permissions
                ),
                "canonical_template": _CANONICAL_AGENT_TEMPLATE,
            },
        },
    }


@router.post("/config/agents", status_code=201)
def create_config_agent(
    request: AgentCreateRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Create a local Draft from the same server-owned canonical template."""

    actor = _require_operator(identity, OperatorPermission.AGENT_EDIT)
    try:
        draft = _get_configuration_store(app_request).create_draft(
            agent_id=SOLE_PRODUCTION_AGENT_ID,
            display_name=request.display_name.strip(),
            purpose=request.purpose.strip(),
            contract_bundle=load_server_owned_agent_template(),
            actor=actor,
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="server_agent_template_unavailable") from exc
    return _draft_payload(draft)


@router.post("/config/agents/import")
def import_config_agent(
    request: AgentImportRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Import an existing Agent Package into Draft Agent state."""

    actor = _require_operator(identity, OperatorPermission.AGENT_EDIT)
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
            actor=actor,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    return _draft_payload(draft)


@router.get("/config/agents/{agent_id}/drafts/{draft_id}")
def get_config_draft(
    agent_id: str,
    draft_id: str,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Return editable Draft Agent metadata."""

    _require_operator(identity, OperatorPermission.AGENT_VIEW)
    try:
        record = _get_agent_configuration_workspace(app_request).get_draft(
            agent_id=agent_id,
            draft_id=draft_id,
        )
    except (AgentConfigurationConflict, AgentConfigurationNotFound) as exc:
        raise _configuration_workspace_exception(exc) from exc
    return _draft_payload(record.draft)


@router.patch("/config/agents/{agent_id}/drafts/{draft_id}")
def update_config_draft(
    agent_id: str,
    draft_id: str,
    request: DraftUpdateRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Update editable Draft Agent fields."""

    _require_operator(identity, OperatorPermission.AGENT_EDIT)
    workspace = _get_agent_configuration_workspace(app_request)
    try:
        current = workspace.get_draft(agent_id=agent_id, draft_id=draft_id)
        updated = workspace.update_draft(
            agent_id=agent_id,
            draft_id=draft_id,
            expected_revision=current.revision,
            display_name=request.display_name,
            purpose=request.purpose,
            actor=_workspace_audit_actor(identity),
        )
    except (AgentConfigurationConflict, AgentConfigurationNotFound) as exc:
        raise _configuration_workspace_exception(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _draft_payload(updated.draft)


@router.get("/config/workflow-templates")
def list_config_workflow_templates(
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Return backend-owned Workflow Template Descriptors for Dashboard rendering."""

    _require_operator(identity, OperatorPermission.AGENT_VIEW)
    descriptors = list_workflow_templates()
    return {
        "data": [_workflow_template_payload(descriptor) for descriptor in descriptors],
        "meta": {"total": len(descriptors)},
    }


@router.get("/config/workflow-templates/{template_id}")
def get_config_workflow_template(
    template_id: str,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Return one backend-owned Workflow Template Descriptor."""

    _require_operator(identity, OperatorPermission.AGENT_VIEW)
    try:
        descriptor = resolve_workflow_template(template_id)
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    return _workflow_template_payload(descriptor)


@router.get("/config/agents/{agent_id}/drafts/{draft_id}/contract")
def get_config_draft_contract(
    agent_id: str,
    draft_id: str,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Return the preserved Contract View for a Draft Agent."""

    _require_operator(identity, OperatorPermission.AGENT_VIEW)
    draft = _require_draft(_get_configuration_store(app_request), agent_id, draft_id)
    return draft.contract_bundle.model_dump(mode="json")


@router.get("/config/agents/{agent_id}/drafts/{draft_id}/skills")
def fetch_config_draft_skills(
    agent_id: str,
    draft_id: str,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Return structured Business Flow Skill Pack configuration for Dashboard."""

    _require_operator(identity, OperatorPermission.AGENT_VIEW)
    store = _get_configuration_store(app_request)
    draft = _require_draft(store, agent_id, draft_id)
    try:
        return _business_flow_skill_pack_configuration_payload(draft, store)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc


@router.post("/config/agents/{agent_id}/drafts/{draft_id}/skills/business-flows")
def create_config_draft_business_flow_skill_pack(
    agent_id: str,
    draft_id: str,
    request: BusinessFlowSkillPackCreateRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Create a package-local Business Flow Skill Pack in one Draft Agent."""

    actor = _require_operator(identity, OperatorPermission.AGENT_EDIT)
    store = _get_configuration_store(app_request)
    draft = _require_draft(store, agent_id, draft_id)
    try:
        bundle = _create_business_flow_skill_pack_bundle(draft, request)
        candidate = _draft_with_contract_bundle(draft, bundle)
        package_dir = compile_draft_agent(candidate, store.root_dir / "compiled_validation")
        manifest = load_agent_manifest(package_dir / "agent.yaml")
        load_business_flow_skill_pack_set(
            manifest,
            template=resolve_workflow_template(manifest.workflow.template),
            manifest_path=package_dir / "agent.yaml",
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    updated = store.update_draft(
        agent_id=agent_id,
        draft_id=draft_id,
        contract_bundle=bundle,
        actor=actor,
    )
    return _business_flow_skill_pack_configuration_payload(updated, store)


@router.patch("/config/agents/{agent_id}/drafts/{draft_id}/skills/business-flows/{pack_id}")
def update_config_draft_business_flow_skill_pack(
    agent_id: str,
    draft_id: str,
    pack_id: str,
    request: BusinessFlowSkillPackUpdateRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Update one package-local Business Flow Skill Pack in a Draft Agent."""

    actor = _require_operator(identity, OperatorPermission.AGENT_EDIT)
    store = _get_configuration_store(app_request)
    draft = _require_draft(store, agent_id, draft_id)
    try:
        bundle = _update_business_flow_skill_pack_bundle(draft, pack_id, request)
        candidate = _draft_with_contract_bundle(draft, bundle)
        package_dir = compile_draft_agent(candidate, store.root_dir / "compiled_validation")
        manifest = load_agent_manifest(package_dir / "agent.yaml")
        load_business_flow_skill_pack_set(
            manifest,
            template=resolve_workflow_template(manifest.workflow.template),
            manifest_path=package_dir / "agent.yaml",
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    updated = store.update_draft(
        agent_id=agent_id,
        draft_id=draft_id,
        contract_bundle=bundle,
        actor=actor,
    )
    return _business_flow_skill_pack_configuration_payload(updated, store)


@router.delete("/config/agents/{agent_id}/drafts/{draft_id}/skills/business-flows/{pack_id}")
def delete_config_draft_business_flow_skill_pack(
    agent_id: str,
    draft_id: str,
    pack_id: str,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Delete one package-local Business Flow Skill Pack from a Draft Agent."""

    actor = _require_operator(identity, OperatorPermission.AGENT_EDIT)
    store = _get_configuration_store(app_request)
    draft = _require_draft(store, agent_id, draft_id)
    try:
        bundle = _delete_business_flow_skill_pack_bundle(draft, pack_id)
        candidate = _draft_with_contract_bundle(draft, bundle)
        package_dir = compile_draft_agent(candidate, store.root_dir / "compiled_validation")
        manifest = load_agent_manifest(package_dir / "agent.yaml")
        load_business_flow_skill_pack_set(
            manifest,
            template=resolve_workflow_template(manifest.workflow.template),
            manifest_path=package_dir / "agent.yaml",
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    updated = store.update_draft(
        agent_id=agent_id,
        draft_id=draft_id,
        contract_bundle=bundle,
        actor=actor,
    )
    return _business_flow_skill_pack_configuration_payload(updated, store)


@router.patch("/config/agents/{agent_id}/drafts/{draft_id}/contract")
def update_config_draft_contract(
    agent_id: str,
    draft_id: str,
    request: ContractUpdateRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Update the preserved Contract View and validate it as an Agent Package."""

    actor = _require_operator(identity, OperatorPermission.AGENT_EDIT)
    store = _get_configuration_store(app_request)
    draft = _require_draft(store, agent_id, draft_id)
    agent_yaml = (
        request.agent_yaml if request.agent_yaml is not None else draft.contract_bundle.agent_yaml
    )
    bundle = ContractBundle(
        agent_yaml=agent_yaml,
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
        manifest = load_agent_manifest(package_dir / "agent.yaml")
        _validate_business_flow_skill_packs(manifest, package_dir / "agent.yaml")
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc

    updated = store.update_draft(
        agent_id=agent_id,
        draft_id=draft_id,
        contract_bundle=bundle,
        actor=actor,
    )
    return updated.contract_bundle.model_dump(mode="json")


@router.patch("/config/agents/{agent_id}/drafts/{draft_id}/workflow-stages")
def update_config_draft_workflow_stages(
    agent_id: str,
    draft_id: str,
    request: WorkflowStagesUpdateRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Replace Draft Agent workflow.stages[] and validate the Agent Contract."""

    actor = _require_operator(identity, OperatorPermission.AGENT_EDIT)
    store = _get_configuration_store(app_request)
    draft = _require_draft(store, agent_id, draft_id)
    try:
        raw = yaml.safe_load(draft.contract_bundle.agent_yaml)
        if not isinstance(raw, dict):
            raise ValueError("agent_yaml must be a mapping.")
        workflow = raw.get("workflow")
        if not isinstance(workflow, dict):
            raise ValueError("agent_yaml workflow must be a mapping.")
        if request.template_descriptor_version is not None:
            workflow["template_descriptor_version"] = request.template_descriptor_version
        workflow["stages"] = [_workflow_stage_request_payload(item) for item in request.stages]
        workflow.pop("nodes", None)
        raw["workflow"] = workflow
        agent_yaml = _dump_agent_yaml(raw)
        bundle = ContractBundle(
            agent_yaml=agent_yaml,
            policy_yaml=draft.contract_bundle.policy_yaml,
            tools_yaml=draft.contract_bundle.tools_yaml,
            extra_files=draft.contract_bundle.extra_files,
            advanced_fields=draft.contract_bundle.advanced_fields,
        )
        candidate = _draft_with_contract_bundle(draft, bundle)
        package_dir = compile_draft_agent(candidate, store.root_dir / "compiled_validation")
        load_agent_manifest(package_dir / "agent.yaml")
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc

    updated = store.update_draft(
        agent_id=agent_id,
        draft_id=draft_id,
        contract_bundle=bundle,
        actor=actor,
    )
    return updated.contract_bundle.model_dump(mode="json")


@router.post("/config/agents/{agent_id}/drafts/{draft_id}/workflow-stages/{stage_id}/preview")
def preview_config_draft_workflow_stage(
    agent_id: str,
    draft_id: str,
    stage_id: str,
    request: WorkflowStagePreviewRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Render a redacted Workflow Stage Context Preview without executing a run."""

    _require_operator(identity, OperatorPermission.AGENT_VALIDATE)
    store = _get_configuration_store(app_request)
    draft = _require_draft(store, agent_id, draft_id)
    try:
        package_dir = compile_draft_agent(draft, store.root_dir / "compiled_preview")
        manifest = load_agent_manifest(package_dir / "agent.yaml")
        descriptor = resolve_workflow_template(manifest.workflow.template)
        stage_descriptor = descriptor.stage(stage_id)
        prompt = WorkflowStagePromptConfig(**_workflow_stage_prompt_request_payload(request.prompt))
        validate_workflow_stage_prompt_config(
            stage_id=stage_id,
            prompt=prompt,
            stage_descriptor=stage_descriptor,
            manifest_path=package_dir / "agent.yaml",
        )
        return build_workflow_stage_context_preview(
            descriptor=descriptor,
            stage_id=stage_id,
            prompt=prompt,
            context_options=request.context,
            sample_context=_workflow_stage_sample_context(manifest),
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc


@router.post("/config/agents/{agent_id}/drafts/{draft_id}/validate")
def validate_config_draft(
    agent_id: str,
    draft_id: str,
    request: DraftValidationRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Run a Draft Agent through the governed Harness as a validation run."""

    _require_operator(identity, OperatorPermission.AGENT_VALIDATE)
    try:
        result = _get_agent_configuration_workspace(app_request).validate_draft(
            agent_id=agent_id,
            draft_id=draft_id,
            question=request.question,
            full_capture=request.full_capture,
            retain_for_audit=request.retain_for_audit,
            actor=_workspace_audit_actor(identity),
        )
    except (AgentConfigurationConflict, AgentConfigurationNotFound) as exc:
        raise _configuration_workspace_exception(exc) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=500,
            detail="agent_draft_validation_failed",
        ) from exc
    record = result.validation
    execution = result.execution
    validation_capture = (
        None
        if execution.validation_capture is None
        else execution.validation_capture.model_dump(mode="json")
    )
    links = {
        "run_detail": f"/api/runs/{execution.run_id}",
        "trace": f"/api/runs/{execution.run_id}/trace",
        "receipt": f"/api/runs/{execution.run_id}/receipt",
    }
    if validation_capture is not None:
        links["validation_capture"] = (
            f"/api/runs/{execution.run_id}/validation-capture"
        )
    trace_capture = {
        "mode": "full_capture" if request.full_capture else "summary_only",
        "validation_capture": validation_capture,
    }
    if execution.capture_error is not None:
        trace_capture["capture_error"] = {
            "code": execution.capture_error.code,
            "message": execution.capture_error.message,
            "retryable": execution.capture_error.retryable,
        }
    return {
        "validation_id": record.validation_id,
        "run_id": execution.run_id,
        "status": record.status,
        "outcome": execution.outcome,
        "run_purpose": execution.run_purpose,
        "agent_id": execution.agent_id,
        "draft_id": execution.draft_id,
        "warnings": list(record.warnings),
        "publish_blockers": list(record.publish_blockers),
        "trace_capture": trace_capture,
        "links": links,
    }


@router.post("/config/agents/{agent_id}/drafts/{draft_id}/publish")
def publish_config_draft(
    agent_id: str,
    draft_id: str,
    request: DraftPublishRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Publish a validated Draft Agent as an immutable version."""

    _require_operator(identity, OperatorPermission.AGENT_PUBLISH)
    try:
        version = _get_agent_configuration_workspace(app_request).publish_draft(
            agent_id=agent_id,
            draft_id=draft_id,
            validation_run_id=request.validation_run_id,
            actor=_workspace_audit_actor(identity),
        )
    except (AgentConfigurationConflict, AgentConfigurationNotFound) as exc:
        raise _configuration_workspace_exception(exc) from exc
    except AgentConfigurationPublicationRejected as exc:
        raise HTTPException(status_code=400, detail=exc.code) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail="agent_draft_publication_invalid",
        ) from exc
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=500,
            detail="agent_draft_publication_failed",
        ) from exc
    return _version_payload(version)


@router.get("/config/agents/{agent_id}/versions")
def list_config_versions(
    agent_id: str,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """List immutable Published Agent Versions for one Agent identity."""

    _require_operator(identity, OperatorPermission.AGENT_VIEW)
    try:
        history = _get_agent_configuration_workspace(app_request).list_versions(
            agent_id=agent_id
        )
    except (AgentConfigurationConflict, AgentConfigurationNotFound) as exc:
        raise _configuration_workspace_exception(exc) from exc
    return {
        "data": [_version_payload(version) for version in history.versions],
        "meta": {
            "total": len(history.versions),
            "active_version_id": history.active_version_id,
        },
    }


@router.post("/config/agents/{agent_id}/versions/{version_id}/rollback")
def rollback_config_version(
    agent_id: str,
    version_id: str,
    request: RollbackRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Switch the Active Agent Version pointer to a previous version."""

    _require_operator(identity, OperatorPermission.AGENT_PUBLISH)
    del request
    try:
        result = _get_agent_configuration_workspace(app_request).rollback_version(
            agent_id=agent_id,
            version_id=version_id,
            actor=_workspace_audit_actor(identity),
        )
    except (AgentConfigurationConflict, AgentConfigurationNotFound) as exc:
        raise _configuration_workspace_exception(exc) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="agent_version_rollback_invalid",
        ) from exc
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="agent_version_rollback_failed",
        ) from exc
    return serialize_agent_version_rollback(result.activation, result.restored)


def _workflow_template_payload(descriptor: Any) -> dict[str, Any]:
    payload = asdict(descriptor)
    payload["stages"] = [asdict(stage) for stage in descriptor.stages]
    return payload


def _workflow_stage_request_payload(item: WorkflowStageUpdateItemRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {"id": item.id}
    prompt = _workflow_stage_prompt_request_payload(item.prompt)
    if prompt:
        payload["prompt"] = prompt
    if item.context:
        payload["context"] = dict(item.context)
    return payload


def _workflow_stage_prompt_request_payload(
    prompt: WorkflowStagePromptRequest,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if prompt.business_context:
        payload["business_context"] = prompt.business_context
    if prompt.task_instructions:
        payload["task_instructions"] = list(prompt.task_instructions)
    if prompt.output_preferences:
        payload["output_preferences"] = list(prompt.output_preferences)
    return payload


def _workflow_stage_sample_context(manifest: Any) -> dict[str, Any]:
    tool_contract_path = (
        str(manifest.capabilities.tools.file)
        if manifest.capabilities.tools.enabled and manifest.capabilities.tools.file is not None
        else ""
    )
    return {
        "agent_purpose": manifest.purpose,
        "bound_knowledge_sources": [],
        "bound_tools": tool_contract_path,
        "policy_outline": str(manifest.policy.file),
        "response_disclosure_policy": (
            manifest.response.model_dump(mode="json") if manifest.response else {}
        ),
        "memory_scope": {
            "enabled": manifest.capabilities.memory.enabled,
            "provider": manifest.capabilities.memory.provider,
            "scopes": dict(manifest.capabilities.memory.scopes),
        },
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
        "capabilities": _DEVELOPMENT_DRAFT_CAPABILITIES,
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


def _business_flow_skill_pack_configuration_payload(
    draft: DraftAgent,
    store: LocalAgentConfigurationStore,
) -> dict[str, Any]:
    package_dir = compile_draft_agent(draft, store.root_dir / "compiled_projection")
    manifest_path = package_dir / "agent.yaml"
    manifest = load_agent_manifest(manifest_path)
    template = resolve_workflow_template(manifest.workflow.template)
    configuration_issues: list[dict[str, str]] = []
    try:
        skill_packs = load_business_flow_skill_pack_set(
            manifest,
            template=template,
            manifest_path=manifest_path,
        )
    except ProofAgentError as exc:
        if not _is_recoverable_business_flow_skill_pack_ref_error(exc):
            raise
        configuration_issues.append(_configuration_issue_payload(exc))
        skill_packs = load_business_flow_skill_pack_set(
            manifest,
            template=template,
            manifest_path=manifest_path,
            validate_capability_refs=False,
        )
    stage_runtime = resolve_workflow_stage_runtime_configuration(
        manifest_path.read_text(encoding="utf-8"),
        source=WorkflowStageConfigurationRuntimeSource(
            source_type=WorkflowStageConfigurationRuntimeSourceType.PACKAGE_LOCAL_LATEST,
            reference=draft.draft_id,
        ),
    )
    base_prompts: dict[str, WorkflowStagePromptConfig] = {}
    if stage_runtime is not None:
        base_prompts = {
            stage.id: WorkflowStagePromptConfig.model_validate(stage.prompt)
            for stage in stage_runtime.effective_stage_configuration.stages
        }
    bindings_by_id = {
        binding.id: binding for binding in manifest.capabilities.skills.business_flows
    }
    slots: list[dict[str, str]] = []
    for stage_id in SUPPORTED_BUSINESS_FLOW_ADDENDUM_STAGE_IDS:
        try:
            stage = template.stage(stage_id)
        except ProofAgentError:
            continue
        slots.append(
            {
                "stage_id": stage_id,
                "stage_label": stage.label,
            }
        )
    return {
        "enabled": manifest.capabilities.skills.enabled,
        "template_name": template.name,
        "template_descriptor_version": template.descriptor_version,
        "addendum_slots": slots,
        "configuration_issues": configuration_issues,
        "packs": [
            _business_flow_skill_pack_payload(
                skill_pack,
                binding=bindings_by_id[skill_pack.id],
                package_dir=package_dir,
                slots=slots,
                base_prompts=base_prompts,
            )
            for skill_pack in skill_packs
        ],
    }


def _is_recoverable_business_flow_skill_pack_ref_error(exc: ProofAgentError) -> bool:
    return exc.code == "PA_CONFIG_002" and exc.message.startswith(
        "unknown Business Flow Skill Pack "
    )


def _configuration_issue_payload(exc: ProofAgentError) -> dict[str, str]:
    payload = {"code": exc.code, "message": exc.message, "fix": exc.fix}
    if exc.artifact_path is not None:
        payload["artifact_path"] = str(exc.artifact_path)
    return payload


def _create_business_flow_skill_pack_bundle(
    draft: DraftAgent,
    request: BusinessFlowSkillPackCreateRequest,
) -> ContractBundle:
    raw = yaml.safe_load(draft.contract_bundle.agent_yaml)
    if not isinstance(raw, dict):
        raise ValueError("agent_yaml must be a mapping.")
    capabilities = raw.setdefault("capabilities", {})
    if not isinstance(capabilities, dict):
        raise ValueError("agent_yaml capabilities must be a mapping.")
    skills = capabilities.get("skills")
    if skills is None:
        skills = {}
    if not isinstance(skills, dict):
        raise ValueError("agent_yaml capabilities.skills must be a mapping.")
    business_flows = skills.get("business_flows") or []
    if not isinstance(business_flows, list):
        raise ValueError("agent_yaml capabilities.skills.business_flows must be a list.")
    if any(isinstance(item, Mapping) and item.get("id") == request.id for item in business_flows):
        raise ValueError(f"Business Flow Skill Pack already exists: {request.id}")
    if request.default and any(
        isinstance(item, Mapping) and item.get("default") is True for item in business_flows
    ):
        raise ValueError("Only one Business Flow Skill Pack can be marked default.")

    definition_path = f"skills/{request.id}.yaml"
    extra_files = dict(draft.contract_bundle.extra_files)
    if definition_path in extra_files:
        raise ValueError(f"Business Flow Skill Pack definition already exists: {definition_path}")

    flow_binding: dict[str, Any] = {
        "id": request.id,
        "definition": f"./{definition_path}",
    }
    if request.default:
        flow_binding["default"] = True
    business_flows.append(flow_binding)
    skills["enabled"] = True
    skills["business_flows"] = business_flows
    capabilities["skills"] = skills
    raw["capabilities"] = capabilities

    definition = {
        "schema_version": "business_flow_skill_pack.v1",
        "id": request.id,
        "label": request.label,
        "description": request.description,
        "intent_patterns": request.intent_patterns,
        "intent_taxonomy_refs": request.intent_taxonomy_refs,
        "stage_prompt_addenda": {},
        "knowledge_binding_refs": [],
        "tool_contract_refs": [],
        "policy_rule_refs": [],
        "validator_refs": [],
        "admission": {},
    }
    extra_files[definition_path] = yaml.safe_dump(
        definition,
        sort_keys=False,
        allow_unicode=False,
    )
    return ContractBundle(
        agent_yaml=_dump_agent_yaml(raw),
        policy_yaml=draft.contract_bundle.policy_yaml,
        tools_yaml=draft.contract_bundle.tools_yaml,
        extra_files=extra_files,
        advanced_fields=draft.contract_bundle.advanced_fields,
    )


def _update_business_flow_skill_pack_bundle(
    draft: DraftAgent,
    pack_id: str,
    request: BusinessFlowSkillPackUpdateRequest,
) -> ContractBundle:
    raw = yaml.safe_load(draft.contract_bundle.agent_yaml)
    if not isinstance(raw, dict):
        raise ValueError("agent_yaml must be a mapping.")
    binding = _business_flow_binding(raw, pack_id)
    if request.default is True and _has_other_default_business_flow(raw, pack_id):
        raise ValueError("Only one Business Flow Skill Pack can be marked default.")
    if request.default is True:
        binding["default"] = True
    elif request.default is False:
        binding.pop("default", None)

    definition_path = _package_extra_file_path(str(binding.get("definition", "")))
    extra_files = dict(draft.contract_bundle.extra_files)
    raw_definition = yaml.safe_load(extra_files.get(definition_path, ""))
    if not isinstance(raw_definition, dict):
        raise ValueError(f"Business Flow Skill Pack definition is missing: {definition_path}")

    if request.label is not None:
        raw_definition["label"] = request.label
    if request.description is not None:
        raw_definition["description"] = request.description
    if request.intent_patterns is not None:
        raw_definition["intent_patterns"] = request.intent_patterns
    if request.intent_taxonomy_refs is not None:
        raw_definition["intent_taxonomy_refs"] = request.intent_taxonomy_refs
    if request.stage_prompt_addenda is not None:
        raw_definition["stage_prompt_addenda"] = {
            stage_id: prompt.model_dump(mode="json", exclude_none=True)
            for stage_id, prompt in request.stage_prompt_addenda.items()
        }
    if request.knowledge_binding_refs is not None:
        raw_definition["knowledge_binding_refs"] = request.knowledge_binding_refs
    if request.tool_contract_refs is not None:
        raw_definition["tool_contract_refs"] = request.tool_contract_refs
    if request.policy_rule_refs is not None:
        raw_definition["policy_rule_refs"] = request.policy_rule_refs
    if request.validator_refs is not None:
        raw_definition["validator_refs"] = request.validator_refs
    if request.admission is not None:
        raw_definition["admission"] = request.admission

    extra_files[definition_path] = yaml.safe_dump(
        raw_definition,
        sort_keys=False,
        allow_unicode=False,
    )
    return ContractBundle(
        agent_yaml=_dump_agent_yaml(raw),
        policy_yaml=draft.contract_bundle.policy_yaml,
        tools_yaml=draft.contract_bundle.tools_yaml,
        extra_files=extra_files,
        advanced_fields=draft.contract_bundle.advanced_fields,
    )


def _delete_business_flow_skill_pack_bundle(
    draft: DraftAgent,
    pack_id: str,
) -> ContractBundle:
    raw = yaml.safe_load(draft.contract_bundle.agent_yaml)
    if not isinstance(raw, dict):
        raise ValueError("agent_yaml must be a mapping.")
    capabilities = raw.get("capabilities")
    if not isinstance(capabilities, dict):
        raise ValueError("agent_yaml capabilities must be a mapping.")
    skills = capabilities.get("skills")
    if not isinstance(skills, dict):
        raise ValueError("agent_yaml capabilities.skills must be a mapping.")
    business_flows = _business_flow_bindings(raw)
    kept_flows: list[Any] = []
    removed_definition_path: str | None = None
    for item in business_flows:
        if isinstance(item, Mapping) and item.get("id") == pack_id:
            removed_definition_path = _package_extra_file_path(str(item.get("definition", "")))
            continue
        kept_flows.append(item)
    if removed_definition_path is None:
        raise ValueError(f"Business Flow Skill Pack binding not found: {pack_id}")

    skills["business_flows"] = kept_flows
    if not kept_flows:
        skills["enabled"] = False
    capabilities["skills"] = skills
    raw["capabilities"] = capabilities
    extra_files = dict(draft.contract_bundle.extra_files)
    extra_files.pop(removed_definition_path, None)
    return ContractBundle(
        agent_yaml=_dump_agent_yaml(raw),
        policy_yaml=draft.contract_bundle.policy_yaml,
        tools_yaml=draft.contract_bundle.tools_yaml,
        extra_files=extra_files,
        advanced_fields=draft.contract_bundle.advanced_fields,
    )


def _business_flow_binding(raw: dict[str, Any], pack_id: str) -> dict[str, Any]:
    business_flows = _business_flow_bindings(raw)
    for item in business_flows:
        if isinstance(item, dict) and item.get("id") == pack_id:
            return item
    raise ValueError(f"Business Flow Skill Pack binding not found: {pack_id}")


def _business_flow_bindings(raw: dict[str, Any]) -> list[Any]:
    capabilities = raw.get("capabilities")
    if not isinstance(capabilities, Mapping):
        raise ValueError("agent_yaml capabilities must be a mapping.")
    skills = capabilities.get("skills")
    if not isinstance(skills, Mapping):
        raise ValueError("agent_yaml capabilities.skills must be a mapping.")
    business_flows = skills.get("business_flows") or []
    if not isinstance(business_flows, list):
        raise ValueError("agent_yaml capabilities.skills.business_flows must be a list.")
    return business_flows


def _has_other_default_business_flow(raw: dict[str, Any], pack_id: str) -> bool:
    return any(
        isinstance(item, Mapping) and item.get("id") != pack_id and item.get("default") is True
        for item in _business_flow_bindings(raw)
    )


def _package_extra_file_path(reference: str) -> str:
    return reference[2:] if reference.startswith("./") else reference


def _business_flow_skill_pack_payload(
    skill_pack: Any,
    *,
    binding: Any,
    package_dir: Path,
    slots: list[dict[str, str]],
    base_prompts: Mapping[str, WorkflowStagePromptConfig],
) -> dict[str, Any]:
    stage_addenda = [
        _business_flow_stage_addendum_payload(
            stage_id=slot["stage_id"],
            stage_label=slot["stage_label"],
            addendum=skill_pack.stage_prompt_addenda.get(slot["stage_id"]),
            base_prompt=base_prompts.get(slot["stage_id"], WorkflowStagePromptConfig()),
        )
        for slot in slots
    ]
    configured_stage_ids = [item["stage_id"] for item in stage_addenda if item["configured"]]
    missing_stage_ids = [item["stage_id"] for item in stage_addenda if not item["configured"]]
    return {
        "id": skill_pack.id,
        "label": skill_pack.label,
        "description": skill_pack.description,
        "definition": _package_relative_path(binding.definition, package_dir),
        "default": binding.default,
        "routing_admission": {
            "intent_patterns": list(skill_pack.intent_patterns),
            "intent_taxonomy_refs": list(skill_pack.intent_taxonomy_refs),
            "admission": skill_pack.admission.model_dump(mode="json"),
            "routing_safe_summary": {
                "id": skill_pack.id,
                "label": skill_pack.label,
                "description": skill_pack.description,
                "intent_patterns": list(skill_pack.intent_patterns),
                "intent_taxonomy_refs": list(skill_pack.intent_taxonomy_refs),
                "default": binding.default,
                "admission": skill_pack.admission.model_dump(mode="json"),
            },
        },
        "capability_refs": {
            "knowledge_binding_refs": list(skill_pack.knowledge_binding_refs),
            "tool_contract_refs": list(skill_pack.tool_contract_refs),
            "policy_rule_refs": list(skill_pack.policy_rule_refs),
            "validator_refs": list(skill_pack.validator_refs),
        },
        "stage_addenda": stage_addenda,
        "coverage": {
            "configured_stage_ids": configured_stage_ids,
            "missing_stage_ids": missing_stage_ids,
        },
    }


def _business_flow_stage_addendum_payload(
    *,
    stage_id: str,
    stage_label: str,
    addendum: WorkflowStagePromptConfig | None,
    base_prompt: WorkflowStagePromptConfig,
) -> dict[str, Any]:
    prompt = addendum or WorkflowStagePromptConfig()
    merged = _append_workflow_stage_prompt(base_prompt, prompt)
    return {
        "stage_id": stage_id,
        "stage_label": stage_label,
        "configured": addendum is not None,
        "prompt": _workflow_stage_prompt_payload(prompt),
        "preview": {
            "merge_mode": "append",
            **_workflow_stage_prompt_payload(merged),
        },
    }


def _append_workflow_stage_prompt(
    base: WorkflowStagePromptConfig,
    addendum: WorkflowStagePromptConfig,
) -> WorkflowStagePromptConfig:
    return WorkflowStagePromptConfig(
        business_context=_join_prompt_text(
            base.business_context,
            addendum.business_context,
        ),
        task_instructions=(
            *base.task_instructions,
            *addendum.task_instructions,
        ),
        output_preferences=(
            *base.output_preferences,
            *addendum.output_preferences,
        ),
    )


def _workflow_stage_prompt_payload(prompt: WorkflowStagePromptConfig) -> dict[str, Any]:
    return {
        "business_context": prompt.business_context,
        "task_instructions": list(prompt.task_instructions),
        "output_preferences": list(prompt.output_preferences),
    }


def _join_prompt_text(base: str, addendum: str) -> str:
    if not base:
        return addendum
    if not addendum:
        return base
    return f"{base}\n\n{addendum}"


def _package_relative_path(path: Path, package_dir: Path) -> str:
    try:
        return path.resolve().relative_to(package_dir.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _version_payload(version: Any) -> dict[str, Any]:
    return {
        "agent_id": version.agent_id,
        "version_id": version.version_id,
        "source_draft_id": version.source_draft_id,
        "validation_run_id": version.validation_run_id,
        "display_name": version.display_name,
        "purpose": version.purpose,
        "published_at": version.published_at,
        "published_by": version.published_by,
        "resolved_knowledge_bindings": (
            version.resolved_knowledge_bindings.model_dump(mode="json")
            if version.resolved_knowledge_bindings is not None
            else None
        ),
        "knowledge_release_record": (
            version.knowledge_release_record.model_dump(mode="json")
            if version.knowledge_release_record is not None
            else None
        ),
        "effective_workflow_stage_configuration": (
            version.effective_workflow_stage_configuration.model_dump(mode="json")
            if version.effective_workflow_stage_configuration is not None
            else None
        ),
        "operation_audit": [
            operation.model_dump(mode="json") for operation in version.operation_audit
        ],
    }


def _model_connection_payload(
    store: LocalAgentConfigurationStore,
    connection: SharedModelConnection,
) -> dict[str, Any]:
    payload = connection.model_dump(mode="json")
    payload["reference_summary"] = store.get_model_connection_reference_summary(
        connection.connection_id
    ).model_dump(mode="json")
    validations = store.list_model_connection_validation_records(connection.connection_id)
    smoke_tests = store.list_model_connection_smoke_test_records(connection.connection_id)
    payload["last_validation"] = validations[-1].model_dump(mode="json") if validations else None
    payload["last_smoke_test"] = smoke_tests[-1].model_dump(mode="json") if smoke_tests else None
    return payload


def _tool_source_payload(source: ToolSource) -> dict[str, Any]:
    return source.model_dump(mode="json")



def _dump_agent_yaml(raw: dict[str, Any]) -> str:
    return cast(
        str,
        yaml.safe_dump(
            raw,
            sort_keys=False,
            allow_unicode=True,
            width=1000,
        ),
    )


def _validate_business_flow_skill_packs(manifest: Any, manifest_path: Path) -> None:
    load_business_flow_skill_pack_set(
        manifest,
        template=resolve_workflow_template(manifest.workflow.template),
        manifest_path=manifest_path,
    )


def _require_draft(
    store: LocalAgentConfigurationStore,
    agent_id: str,
    draft_id: str,
) -> DraftAgent:
    draft = store.get_draft(agent_id, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail=f"Draft Agent not found: {agent_id}/{draft_id}")
    return draft


def _require_model_connection(
    store: LocalAgentConfigurationStore,
    connection_id: str,
) -> SharedModelConnection:
    try:
        connection = store.get_model_connection(connection_id)
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    if connection is None:
        raise HTTPException(
            status_code=404,
            detail=f"Shared Model Connection not found: {connection_id}",
        )
    return connection


def _require_tool_source(
    store: LocalAgentConfigurationStore,
    source_id: str,
) -> ToolSource:
    try:
        source = store.get_tool_source(source_id)
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    if source is None:
        raise HTTPException(status_code=404, detail=f"Tool Source not found: {source_id}")
    return source


def _get_configuration_store(request: Request) -> LocalAgentConfigurationStore:
    return cast(LocalAgentConfigurationStore, request.app.state.agent_configuration_store)


def _get_agent_configuration_workspace(request: Request) -> AgentConfigurationWorkspace:
    return cast(
        AgentConfigurationWorkspace,
        request.app.state.agent_configuration_workspace,
    )


def _workspace_audit_actor(identity: OperatorIdentityContext) -> AuditActorFacts:
    return AuditActorFacts(
        subject=identity.operator_id,
        identity_provider="local-development",
        session_id="local-dashboard",
        permissions=tuple(sorted(item.value for item in identity.permissions)),
    )


def _configuration_workspace_exception(
    error: AgentConfigurationConflict | AgentConfigurationNotFound,
) -> HTTPException:
    return HTTPException(
        status_code=409 if isinstance(error, AgentConfigurationConflict) else 404,
        detail=error.code,
    )


def _get_run_store(request: Request) -> RunStore:
    return cast(RunStore, request.app.state.store)


def _get_runs_dir(request: Request) -> Path:
    return cast(Path, request.app.state.runs_dir)


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _model_connection_id(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", value.strip().lower().replace("-", "_"))
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized:
        normalized = f"model_{uuid4().hex[:8]}"
    if not normalized.startswith("model_"):
        normalized = f"model_{normalized}"
    return normalized


def _tool_source_id(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", value.strip().lower().replace("-", "_"))
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized:
        normalized = f"tool_{uuid4().hex[:8]}"
    if not normalized.startswith("tool_"):
        normalized = f"tool_{normalized}"
    return normalized


def _credential_ref(
    request: ModelCredentialReferenceRequest,
) -> EnvironmentModelCredentialReference:
    if request.type != "env":
        raise HTTPException(
            status_code=400,
            detail="Only env model credential references are supported.",
        )
    return EnvironmentModelCredentialReference(name=request.name)


def _require_supported_shared_model_provider(provider: str) -> None:
    if provider not in SUPPORTED_SHARED_MODEL_CONNECTION_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported model provider: {provider}",
        )


def _require_supported_tool_source_provider(provider: str) -> None:
    try:
        get_tool_source_descriptor(provider)
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc


def _require_model_connection_update_impact_confirmation(
    store: LocalAgentConfigurationStore,
    *,
    connection_id: str,
    request: ModelConnectionUpdateRequest,
) -> None:
    high_impact_fields = {
        "provider": request.provider,
        "model_identifier": request.model_identifier,
        "base_url": request.base_url,
        "credential_ref": request.credential_ref,
        "organization_env": request.organization_env,
        "project_env": request.project_env,
    }
    changed_high_impact_fields = tuple(
        field for field, value in high_impact_fields.items() if value is not None
    )
    if not changed_high_impact_fields or request.confirm_impact:
        return
    summary = store.get_model_connection_reference_summary(connection_id)
    total_references = (
        summary.draft_agent_reference_count
        + summary.published_agent_version_reference_count
        + summary.knowledge_source_reference_count
    )
    if not total_references:
        return
    raise HTTPException(
        status_code=409,
        detail={
            "requires_impact_review": True,
            "changed_fields": list(changed_high_impact_fields),
            "reference_summary": summary.model_dump(mode="json"),
        },
    )


def _model_connection_validation_record(
    connection: SharedModelConnection,
    *,
    actor: str,
) -> ModelConnectionValidationRecord:
    missing_env_vars = _missing_model_connection_env_vars(connection)
    return ModelConnectionValidationRecord(
        validation_id=f"modelvalidation_{uuid4().hex[:8]}",
        connection_id=connection.connection_id,
        status="failed" if missing_env_vars else "passed",
        created_at=_now(),
        created_by=actor,
        provider=connection.provider,
        model_identifier=connection.model_identifier,
        credential_ref=connection.credential_ref,
        checked_env_vars=_model_connection_env_vars(connection),
        missing_env_vars=missing_env_vars,
        error_code="missing_env_var" if missing_env_vars else None,
        message=(
            "Credential environment variable is missing."
            if missing_env_vars
            else "Model connection validation passed."
        ),
    )


def _model_connection_smoke_test_record(
    connection: SharedModelConnection,
    *,
    actor: str,
) -> ModelConnectionSmokeTestRecord:
    missing_env_vars = _missing_model_connection_env_vars(connection)
    if missing_env_vars:
        return ModelConnectionSmokeTestRecord(
            smoke_test_id=f"modelsmoke_{uuid4().hex[:8]}",
            connection_id=connection.connection_id,
            status="failed",
            created_at=_now(),
            created_by=actor,
            provider=connection.provider,
            model_identifier=connection.model_identifier,
            credential_ref=connection.credential_ref,
            request_sent=False,
            error_code="missing_env_var",
            message="Credential environment variable is missing; remote smoke test was not sent.",
        )
    return ModelConnectionSmokeTestRecord(
        smoke_test_id=f"modelsmoke_{uuid4().hex[:8]}",
        connection_id=connection.connection_id,
        status="skipped",
        created_at=_now(),
        created_by=actor,
        provider=connection.provider,
        model_identifier=connection.model_identifier,
        credential_ref=connection.credential_ref,
        request_sent=False,
        message="Remote smoke test adapter is not enabled in local configuration API.",
    )


def _model_connection_env_vars(connection: SharedModelConnection) -> tuple[str, ...]:
    credential_ref = connection.credential_ref
    if not isinstance(credential_ref, EnvironmentModelCredentialReference):
        raise HTTPException(
            status_code=409,
            detail="Production Secret Handles require the production model connection API.",
        )
    env_vars = [credential_ref.name]
    if connection.organization_env is not None:
        env_vars.append(connection.organization_env)
    if connection.project_env is not None:
        env_vars.append(connection.project_env)
    return tuple(env_vars)


def _missing_model_connection_env_vars(connection: SharedModelConnection) -> tuple[str, ...]:
    return tuple(
        env_var for env_var in _model_connection_env_vars(connection) if not os.getenv(env_var)
    )



def _proof_agent_http_exception(exc: ProofAgentError) -> HTTPException:
    return proof_agent_http_exception(exc)
