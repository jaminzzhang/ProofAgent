"""Agent Configuration API endpoints for the Dashboard workspace."""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from proof_agent.capabilities.tools.source_descriptors import (
    get_tool_source_descriptor,
    list_tool_source_descriptors,
)
from proof_agent.configuration.importer import import_agent_package
from proof_agent.configuration.local_store import (
    LocalAgentConfigurationStore,
)
from proof_agent.contracts import (
    AuditActorFacts,
    DraftAgent,
    EnvironmentModelCredentialReference,
    ModelConnectionSmokeTestRecord,
    ModelConnectionValidationRecord,
    SharedModelConnection,
    ToolSource,
)
from proof_agent.control.agent_configuration_workspace import (
    AgentConfigurationConflict,
    AgentConfigurationNotFound,
    AgentConfigurationPublicationRejected,
    AgentConfigurationWorkspace,
    SOLE_PRODUCTION_AGENT_ID,
    load_server_owned_agent_template,
)
from proof_agent.control.workflow.templates import (
    list_workflow_templates,
    resolve_workflow_template,
)
from proof_agent.delivery.http_errors import proof_agent_http_exception
from proof_agent.delivery.agent_configuration_workflow_http import (
    WorkflowStagePreviewRequest,
    WorkflowStageUpdateItemRequest,
    workflow_stage_config_request,
    workflow_stage_prompt_config,
    workflow_template_payload,
)
from proof_agent.delivery.agent_configuration_skill_pack_http import (
    BusinessFlowSkillPackCreateFields,
    BusinessFlowSkillPackUpdateFields,
    business_flow_skill_pack_create_command,
    business_flow_skill_pack_result_payload,
    business_flow_skill_pack_update_command,
)
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
    "visible_modules": [
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
    "editable_modules": [
        "knowledge",
        "general",
        "workflow",
        "skills",
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
    expected_revision: int | None = Field(default=None, ge=1)


class ContractUpdateRequest(BaseModel):
    """Request body for updating preserved Contract View files."""

    model_config = ConfigDict(extra="forbid")

    agent_yaml: str | None = None
    policy_yaml: str | None = None
    tools_yaml: str | None = None
    expected_revision: int | None = Field(default=None, ge=1)


class BusinessFlowSkillPackCreateRequest(BusinessFlowSkillPackCreateFields):
    """Request body for creating one draft-local Business Flow Skill Pack."""

    expected_revision: int | None = Field(default=None, ge=1)


class BusinessFlowSkillPackUpdateRequest(BusinessFlowSkillPackUpdateFields):
    """Request body for updating one draft-local Business Flow Skill Pack."""

    expected_revision: int | None = Field(default=None, ge=1)


class WorkflowStagesUpdateRequest(BaseModel):
    """Request body for replacing Draft Agent workflow stage configuration."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: int | None = Field(default=None, ge=1)
    template: str | None = Field(default=None, min_length=1, max_length=255)
    template_descriptor_version: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
    )
    stages: list[WorkflowStageUpdateItemRequest]


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

    expected_active_version_id: str | None


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
    return _draft_payload(record.draft, revision=record.revision)


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
        expected_revision = request.expected_revision
        if expected_revision is None:
            expected_revision = workspace.get_draft(
                agent_id=agent_id,
                draft_id=draft_id,
            ).revision
        updated = workspace.update_draft(
            agent_id=agent_id,
            draft_id=draft_id,
            expected_revision=expected_revision,
            display_name=request.display_name,
            purpose=request.purpose,
            actor=_workspace_audit_actor(identity),
        )
    except (AgentConfigurationConflict, AgentConfigurationNotFound) as exc:
        raise _configuration_workspace_exception(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _draft_payload(updated.draft, revision=updated.revision)


@router.get("/config/workflow-templates")
def list_config_workflow_templates(
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Return backend-owned Workflow Template Descriptors for Dashboard rendering."""

    _require_operator(identity, OperatorPermission.AGENT_VIEW)
    descriptors = list_workflow_templates()
    return {
        "data": [workflow_template_payload(descriptor) for descriptor in descriptors],
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
    return workflow_template_payload(descriptor)


@router.get("/config/agents/{agent_id}/drafts/{draft_id}/contract")
def get_config_draft_contract(
    agent_id: str,
    draft_id: str,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Return the preserved Contract View for a Draft Agent."""

    _require_operator(identity, OperatorPermission.AGENT_VIEW)
    try:
        record = _get_agent_configuration_workspace(app_request).get_draft(
            agent_id=agent_id,
            draft_id=draft_id,
        )
    except (AgentConfigurationConflict, AgentConfigurationNotFound) as exc:
        raise _configuration_workspace_exception(exc) from exc
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="agent_contract_read_failed",
        ) from exc
    return record.draft.contract_bundle.model_dump(mode="json")


@router.get("/config/agents/{agent_id}/drafts/{draft_id}/skills")
def fetch_config_draft_skills(
    agent_id: str,
    draft_id: str,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Return structured Business Flow Skill Pack configuration for Dashboard."""

    _require_operator(identity, OperatorPermission.AGENT_VIEW)
    workspace = _get_agent_configuration_workspace(app_request)
    try:
        result = workspace.get_business_flow_skill_packs(
            agent_id=agent_id,
            draft_id=draft_id,
        )
    except (AgentConfigurationConflict, AgentConfigurationNotFound) as exc:
        raise _configuration_workspace_exception(exc) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail="agent_skill_pack_configuration_invalid",
        ) from exc
    except ProofAgentError as exc:
        raise HTTPException(
            status_code=400,
            detail="agent_skill_pack_configuration_invalid",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="agent_skill_pack_read_failed",
        ) from exc
    return business_flow_skill_pack_result_payload(result)


@router.post("/config/agents/{agent_id}/drafts/{draft_id}/skills/business-flows")
def create_config_draft_business_flow_skill_pack(
    agent_id: str,
    draft_id: str,
    request: BusinessFlowSkillPackCreateRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Create a package-local Business Flow Skill Pack in one Draft Agent."""

    _require_operator(identity, OperatorPermission.AGENT_EDIT)
    workspace = _get_agent_configuration_workspace(app_request)
    try:
        expected_revision = request.expected_revision
        if expected_revision is None:
            expected_revision = workspace.get_draft(
                agent_id=agent_id,
                draft_id=draft_id,
            ).revision
        result = workspace.create_business_flow_skill_pack(
            agent_id=agent_id,
            draft_id=draft_id,
            expected_revision=expected_revision,
            command=business_flow_skill_pack_create_command(request),
            actor=_workspace_audit_actor(identity),
        )
    except (AgentConfigurationConflict, AgentConfigurationNotFound) as exc:
        raise _configuration_workspace_exception(exc) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail="agent_skill_pack_configuration_invalid",
        ) from exc
    except ProofAgentError as exc:
        raise HTTPException(
            status_code=400,
            detail="agent_skill_pack_configuration_invalid",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="agent_skill_pack_update_failed",
        ) from exc
    return business_flow_skill_pack_result_payload(result)


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

    _require_operator(identity, OperatorPermission.AGENT_EDIT)
    workspace = _get_agent_configuration_workspace(app_request)
    try:
        expected_revision = request.expected_revision
        if expected_revision is None:
            expected_revision = workspace.get_draft(
                agent_id=agent_id,
                draft_id=draft_id,
            ).revision
        result = workspace.update_business_flow_skill_pack(
            agent_id=agent_id,
            draft_id=draft_id,
            pack_id=pack_id,
            expected_revision=expected_revision,
            command=business_flow_skill_pack_update_command(request),
            actor=_workspace_audit_actor(identity),
        )
    except (AgentConfigurationConflict, AgentConfigurationNotFound) as exc:
        raise _configuration_workspace_exception(exc) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail="agent_skill_pack_configuration_invalid",
        ) from exc
    except ProofAgentError as exc:
        raise HTTPException(
            status_code=400,
            detail="agent_skill_pack_configuration_invalid",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="agent_skill_pack_update_failed",
        ) from exc
    return business_flow_skill_pack_result_payload(result)


@router.delete("/config/agents/{agent_id}/drafts/{draft_id}/skills/business-flows/{pack_id}")
def delete_config_draft_business_flow_skill_pack(
    agent_id: str,
    draft_id: str,
    pack_id: str,
    app_request: Request,
    expected_revision: int | None = Query(default=None, ge=1),
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Delete one package-local Business Flow Skill Pack from a Draft Agent."""

    _require_operator(identity, OperatorPermission.AGENT_EDIT)
    workspace = _get_agent_configuration_workspace(app_request)
    try:
        if expected_revision is None:
            expected_revision = workspace.get_draft(
                agent_id=agent_id,
                draft_id=draft_id,
            ).revision
        result = workspace.delete_business_flow_skill_pack(
            agent_id=agent_id,
            draft_id=draft_id,
            pack_id=pack_id,
            expected_revision=expected_revision,
            actor=_workspace_audit_actor(identity),
        )
    except (AgentConfigurationConflict, AgentConfigurationNotFound) as exc:
        raise _configuration_workspace_exception(exc) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail="agent_skill_pack_configuration_invalid",
        ) from exc
    except ProofAgentError as exc:
        raise HTTPException(
            status_code=400,
            detail="agent_skill_pack_configuration_invalid",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="agent_skill_pack_update_failed",
        ) from exc
    return business_flow_skill_pack_result_payload(result)


@router.patch("/config/agents/{agent_id}/drafts/{draft_id}/contract")
def update_config_draft_contract(
    agent_id: str,
    draft_id: str,
    request: ContractUpdateRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Validate and update the preserved Contract View through the Workspace."""

    _require_operator(identity, OperatorPermission.AGENT_EDIT)
    workspace = _get_agent_configuration_workspace(app_request)
    try:
        expected_revision = request.expected_revision
        if expected_revision is None:
            expected_revision = workspace.get_draft(
                agent_id=agent_id,
                draft_id=draft_id,
            ).revision
        updated = workspace.update_contract(
            agent_id=agent_id,
            draft_id=draft_id,
            expected_revision=expected_revision,
            agent_yaml=request.agent_yaml,
            policy_yaml=request.policy_yaml,
            tools_yaml=request.tools_yaml,
            actor=_workspace_audit_actor(identity),
        )
    except (AgentConfigurationConflict, AgentConfigurationNotFound) as exc:
        raise _configuration_workspace_exception(exc) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="agent_contract_invalid") from exc
    except ProofAgentError as exc:
        raise HTTPException(status_code=400, detail="agent_contract_invalid") from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="agent_contract_update_failed",
        ) from exc
    return updated.draft.contract_bundle.model_dump(mode="json")


@router.patch("/config/agents/{agent_id}/drafts/{draft_id}/workflow-stages")
def update_config_draft_workflow_stages(
    agent_id: str,
    draft_id: str,
    request: WorkflowStagesUpdateRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Replace Draft Agent workflow.stages[] and validate the Agent Contract."""

    _require_operator(identity, OperatorPermission.AGENT_EDIT)
    workspace = _get_agent_configuration_workspace(app_request)
    try:
        expected_revision = request.expected_revision
        if expected_revision is None:
            expected_revision = workspace.get_draft(
                agent_id=agent_id,
                draft_id=draft_id,
            ).revision
        updated = workspace.update_workflow_stages(
            agent_id=agent_id,
            draft_id=draft_id,
            expected_revision=expected_revision,
            template=request.template,
            template_descriptor_version=request.template_descriptor_version,
            stages=tuple(
                workflow_stage_config_request(item) for item in request.stages
            ),
            actor=_workspace_audit_actor(identity),
        )
    except (AgentConfigurationConflict, AgentConfigurationNotFound) as exc:
        raise _configuration_workspace_exception(exc) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="agent_workflow_stage_configuration_invalid",
        ) from exc
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="agent_workflow_stage_configuration_failed",
        ) from exc
    return updated.draft.contract_bundle.model_dump(mode="json")


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
    try:
        return _get_agent_configuration_workspace(app_request).preview_workflow_stage(
            agent_id=agent_id,
            draft_id=draft_id,
            stage_id=stage_id,
            prompt=workflow_stage_prompt_config(request.prompt),
            context_options=request.context,
        )
    except (AgentConfigurationConflict, AgentConfigurationNotFound) as exc:
        raise _configuration_workspace_exception(exc) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="agent_workflow_stage_preview_invalid",
        ) from exc
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="agent_workflow_stage_preview_failed",
        ) from exc


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
    try:
        result = _get_agent_configuration_workspace(app_request).rollback_version(
            agent_id=agent_id,
            version_id=version_id,
            expected_active_version_id=request.expected_active_version_id,
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


def _draft_payload(
    draft: DraftAgent,
    *,
    revision: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
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
    if revision is not None:
        payload["revision"] = revision
    return payload


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
