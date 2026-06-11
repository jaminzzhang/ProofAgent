"""Agent Configuration API endpoints for the Dashboard workspace."""

from __future__ import annotations

import base64
import binascii
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
from proof_agent.bootstrap.validation import validate_workflow_node_prompt_config
from proof_agent.bootstrap.knowledge_resolution import (
    ConfigurationStoreKnowledgeBindingResolver,
    PackageKnowledgeBindingResolver,
)
from proof_agent.capabilities.tools.source_descriptors import (
    get_tool_source_descriptor,
    list_tool_source_descriptors,
)
from proof_agent.configuration.compiler import compile_draft_agent
from proof_agent.configuration.importer import import_agent_package
from proof_agent.configuration.local_store import (
    KnowledgeUploadStagingInput,
    LocalAgentConfigurationStore,
    MAX_QUARANTINED_UPLOAD_BATCH_FILES,
)
from proof_agent.contracts import (
    AgentValidationRecord,
    ContractBundle,
    DraftAgent,
    EnvironmentModelCredentialReference,
    KnowledgeDocument,
    KnowledgeIngestionJob,
    KnowledgeSource,
    KnowledgeSourceLifecycleState,
    ModelConnectionSmokeTestRecord,
    ModelConnectionValidationRecord,
    QuarantinedKnowledgeUpload,
    ResolvedKnowledgeBindingSet,
    RunPurpose,
    SharedModelConnection,
    ToolSource,
    WorkflowNodePromptConfig,
)
from proof_agent.control.workflow.node_context import build_workflow_node_context_preview
from proof_agent.control.workflow.templates import (
    list_workflow_templates,
    resolve_workflow_template,
)
from proof_agent.errors import ProofAgentError
from proof_agent.observability.api.dependencies import get_operator_identity
from proof_agent.observability.api.operator_identity import (
    OperatorIdentityContext,
    OperatorPermission,
    require_operator_permission,
)
from proof_agent.observability.storage.run_store import RunStore
from proof_agent.runtime.langgraph_runner import run_with_langgraph


router = APIRouter(tags=["configuration"])

SUPPORTED_KNOWLEDGE_SOURCE_PROVIDERS = {
    "http_json",
    "local_markdown",
    "local_index",
    "remote_search",
}
SUPPORTED_SHARED_MODEL_CONNECTION_PROVIDERS = {
    "openai",
    "openai_compatible",
    "deepseek",
}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


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


class WorkflowNodePromptRequest(BaseModel):
    """Request body fragment for node-level business Prompt settings."""

    model_config = ConfigDict(extra="forbid")

    business_context: str | None = None
    task_instructions: list[str] = Field(default_factory=list)
    output_preferences: list[str] = Field(default_factory=list)


class WorkflowNodeUpdateItemRequest(BaseModel):
    """Request body item for one workflow node configuration."""

    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1)
    prompt: WorkflowNodePromptRequest = Field(default_factory=WorkflowNodePromptRequest)
    context: dict[str, bool] = Field(default_factory=dict)


class WorkflowNodesUpdateRequest(BaseModel):
    """Request body for replacing Draft Agent workflow node configuration."""

    model_config = ConfigDict(extra="forbid")

    template_descriptor_version: str | None = None
    nodes: list[WorkflowNodeUpdateItemRequest]


class WorkflowNodePreviewRequest(BaseModel):
    """Request body for rendering one redacted Workflow Node Context Preview."""

    model_config = ConfigDict(extra="forbid")

    prompt: WorkflowNodePromptRequest = Field(default_factory=WorkflowNodePromptRequest)
    context: dict[str, bool] = Field(default_factory=dict)


class DraftValidationRequest(BaseModel):
    """Request body for triggering a governed validation run."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)


class DraftPublishRequest(BaseModel):
    """Request body for publishing a Draft Agent after validation."""

    model_config = ConfigDict(extra="forbid")

    validation_run_id: str | None = None


class RollbackRequest(BaseModel):
    """Request body for switching the Active Agent Version pointer."""

    model_config = ConfigDict(extra="forbid")


class KnowledgeSourceCreateRequest(BaseModel):
    """Request body for creating a reusable Knowledge Source."""

    model_config = ConfigDict(extra="forbid")

    source_id: str | None = None
    name: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


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


class KnowledgeSourceArchiveRequest(BaseModel):
    """Request body for archiving a reusable Knowledge Source."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)


class KnowledgeSourceRestoreRequest(BaseModel):
    """Request body for restoring an archived reusable Knowledge Source."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = None


class KnowledgeSourcePhysicalDeleteRequest(BaseModel):
    """Request body for permanently deleting an eligible archived Knowledge Source."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)


class KnowledgeIngestionRetryRequest(BaseModel):
    """Request body for manually retrying a failed Knowledge Ingestion Job."""

    model_config = ConfigDict(extra="forbid")


class KnowledgeDocumentUploadRequest(BaseModel):
    """JSON/base64 upload for Dashboard-managed knowledge documents."""

    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    content_base64: str = Field(min_length=1)


class KnowledgeDocumentBatchUploadItemRequest(BaseModel):
    """One JSON/base64 upload item inside a Dashboard-managed batch."""

    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    content_base64: str = Field(min_length=1)


class KnowledgeDocumentBatchUploadRequest(BaseModel):
    """JSON/base64 upload batch for Dashboard-managed knowledge documents."""

    model_config = ConfigDict(extra="forbid")

    documents: list[KnowledgeDocumentBatchUploadItemRequest] = Field(
        min_length=1,
        max_length=MAX_QUARANTINED_UPLOAD_BATCH_FILES,
    )


class KnowledgeDocumentRoutingMetadataUpdateRequest(BaseModel):
    """Request body for operator-managed routing metadata edits."""

    model_config = ConfigDict(extra="forbid")

    routing_metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeSourceFoundationValidationRequest(BaseModel):
    """Request body for validating one derived Local Index candidate snapshot."""

    model_config = ConfigDict(extra="forbid")


class KnowledgeSourceSnapshotFreezeRequest(BaseModel):
    """Request body for freezing one validated Local Index candidate snapshot."""

    model_config = ConfigDict(extra="forbid")

    validation_id: str = Field(min_length=1)


class KnowledgeSourcePublicationValidationRequest(BaseModel):
    """Request body for Source-level publication smoke validation."""

    model_config = ConfigDict(extra="forbid")

    smoke_query: str = Field(min_length=1)


class KnowledgeSourcePublicationRequest(BaseModel):
    """Request body for publishing one validated Knowledge Source snapshot."""

    model_config = ConfigDict(extra="forbid")

    validation_id: str = Field(min_length=1)
    change_note: str = Field(min_length=1)


class KnowledgeBindingAttachRequest(BaseModel):
    """Request body for binding a shared Knowledge Source into a Draft Agent."""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1)
    binding_id: str | None = None
    alias: str | None = None
    failure_mode: str = "required"
    fusion_weight: float = 1.0
    top_k: int | None = None


class KnowledgeBindingDetachRequest(BaseModel):
    """Request body for removing a Knowledge Source binding from a Draft Agent."""

    model_config = ConfigDict(extra="forbid")


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
    data = [
        descriptor.model_dump(mode="json") for descriptor in list_tool_source_descriptors()
    ]
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
                tuple(request.tool_contract_ids)
                if request.tool_contract_ids is not None
                else None
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


@router.get("/config/knowledge-sources")
def list_knowledge_sources(
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """List reusable Knowledge Sources managed by the local configuration store."""

    _require_operator(identity, OperatorPermission.KNOWLEDGE_SOURCE_VIEW)
    store = _get_configuration_store(app_request)
    data = [_knowledge_source_payload(store, source) for source in store.list_knowledge_sources()]
    return {"data": data, "meta": {"total": len(data)}}


@router.post("/config/knowledge-sources")
def create_knowledge_source(
    request: KnowledgeSourceCreateRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Create a reusable Knowledge Source independent of any Agent binding."""

    actor = _require_operator(identity, OperatorPermission.KNOWLEDGE_SOURCE_EDIT)
    if request.provider not in SUPPORTED_KNOWLEDGE_SOURCE_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported knowledge provider: {request.provider}",
        )
    store = _get_configuration_store(app_request)
    source_id = _source_id(request.source_id or request.name)
    params = dict(request.params)
    try:
        source = store.create_knowledge_source(
            source_id=source_id,
            name=request.name,
            provider=request.provider,
            params=params,
            actor=actor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    return _knowledge_source_payload(store, source)


@router.get("/config/knowledge-sources/{source_id}")
def get_knowledge_source(
    source_id: str,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Return one Knowledge Source with document counts."""

    _require_operator(identity, OperatorPermission.KNOWLEDGE_SOURCE_VIEW)
    store = _get_configuration_store(app_request)
    source = _require_knowledge_source(store, source_id)
    return _knowledge_source_payload(store, source)


@router.post("/config/knowledge-sources/{source_id}/archive")
def archive_knowledge_source(
    source_id: str,
    request: KnowledgeSourceArchiveRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Archive a reusable Knowledge Source without deleting retained state."""

    actor = _require_operator(identity, OperatorPermission.KNOWLEDGE_SOURCE_ARCHIVE)
    store = _get_configuration_store(app_request)
    _require_knowledge_source(store, source_id)
    try:
        source = store.archive_knowledge_source(
            source_id=source_id,
            actor=actor,
            reason=request.reason,
        )
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    return _knowledge_source_payload(store, source)


@router.post("/config/knowledge-sources/{source_id}/restore")
def restore_knowledge_source(
    source_id: str,
    request: KnowledgeSourceRestoreRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Restore an archived reusable Knowledge Source to active state."""

    actor = _require_operator(identity, OperatorPermission.KNOWLEDGE_SOURCE_EDIT)
    store = _get_configuration_store(app_request)
    _require_knowledge_source(store, source_id)
    try:
        source = store.restore_knowledge_source(
            source_id=source_id,
            actor=actor,
            reason=request.reason,
        )
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    return _knowledge_source_payload(store, source)


@router.get("/config/knowledge-sources/{source_id}/deletion-eligibility")
def get_knowledge_source_deletion_eligibility(
    source_id: str,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Return physical-deletion eligibility and blockers for one Knowledge Source."""

    _require_operator(identity, OperatorPermission.KNOWLEDGE_SOURCE_VIEW)
    store = _get_configuration_store(app_request)
    _require_knowledge_source(store, source_id)
    try:
        eligibility = store.get_knowledge_source_deletion_eligibility(source_id)
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    return eligibility.model_dump(mode="json")


@router.delete("/config/knowledge-sources/{source_id}")
def physically_delete_knowledge_source(
    source_id: str,
    request: KnowledgeSourcePhysicalDeleteRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Permanently delete an eligible empty archived Knowledge Source."""

    actor = _require_operator(identity, OperatorPermission.KNOWLEDGE_SOURCE_ARCHIVE)
    store = _get_configuration_store(app_request)
    _require_knowledge_source(store, source_id)
    try:
        eligibility = store.physically_delete_knowledge_source(
            source_id=source_id,
            actor=actor,
            reason=request.reason,
        )
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    return eligibility.model_dump(mode="json")


@router.get("/config/knowledge-sources/{source_id}/documents")
def list_knowledge_source_documents(
    source_id: str,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """List managed documents for one Knowledge Source."""

    _require_operator(identity, OperatorPermission.KNOWLEDGE_SOURCE_VIEW)
    store = _get_configuration_store(app_request)
    _require_knowledge_source(store, source_id)
    documents = store.list_knowledge_documents(source_id)
    return {
        "data": [_knowledge_document_payload(document) for document in documents],
        "meta": {"total": len(documents)},
    }


@router.post("/config/knowledge-sources/{source_id}/documents")
def upload_knowledge_source_document(
    source_id: str,
    request: KnowledgeDocumentUploadRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Stage one upload for asynchronous validation and Local Index ingestion."""

    actor = _require_operator(identity, OperatorPermission.KNOWLEDGE_SOURCE_EDIT)
    store = _get_configuration_store(app_request)
    source = _require_active_knowledge_source(store, source_id)
    if source.provider != "local_index":
        raise HTTPException(
            status_code=400,
            detail="Dashboard document upload currently supports local_index Knowledge Sources.",
        )
    content = _decode_upload_content(request.content_base64)

    try:
        upload = store.stage_quarantined_knowledge_upload(
            source_id=source.source_id,
            filename=request.filename,
            content_type=request.content_type,
            content=content,
            actor=actor,
        )
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    return _quarantined_upload_payload(upload)


@router.patch("/config/knowledge-sources/{source_id}/documents/{document_id}/routing-metadata")
def update_knowledge_source_document_routing_metadata(
    source_id: str,
    document_id: str,
    request: KnowledgeDocumentRoutingMetadataUpdateRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Update routing-only metadata for one managed Knowledge Document."""

    actor = _require_operator(identity, OperatorPermission.KNOWLEDGE_SOURCE_EDIT)
    store = _get_configuration_store(app_request)
    _require_active_knowledge_source(store, source_id)
    try:
        document = store.update_knowledge_document_routing_metadata(
            source_id=source_id,
            document_id=document_id,
            routing_metadata=request.routing_metadata,
            actor=actor,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Knowledge Document not found: {source_id}/{document_id}",
        ) from exc
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    return _knowledge_document_payload(document)


@router.post("/config/knowledge-sources/{source_id}/documents/batch")
def upload_knowledge_source_document_batch(
    source_id: str,
    request: KnowledgeDocumentBatchUploadRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Stage one upload batch for asynchronous validation and Local Index ingestion."""

    actor = _require_operator(identity, OperatorPermission.KNOWLEDGE_SOURCE_EDIT)
    store = _get_configuration_store(app_request)
    source = _require_active_knowledge_source(store, source_id)
    if source.provider != "local_index":
        raise HTTPException(
            status_code=400,
            detail="Dashboard document upload currently supports local_index Knowledge Sources.",
        )
    staging_inputs = tuple(
        KnowledgeUploadStagingInput(
            filename=document.filename,
            content_type=document.content_type,
            content=_decode_upload_content(document.content_base64),
        )
        for document in request.documents
    )

    try:
        uploads = store.stage_quarantined_knowledge_upload_batch(
            source_id=source.source_id,
            uploads=staging_inputs,
            actor=actor,
        )
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    return {
        "data": [_quarantined_upload_payload(upload) for upload in uploads],
        "meta": {"total": len(uploads)},
    }


@router.get("/config/knowledge-sources/{source_id}/quarantined-uploads")
def list_quarantined_knowledge_uploads(
    source_id: str,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """List asynchronous upload-validation records for one Knowledge Source."""

    _require_operator(identity, OperatorPermission.KNOWLEDGE_SOURCE_VIEW)
    store = _get_configuration_store(app_request)
    _require_knowledge_source(store, source_id)
    uploads = store.list_quarantined_knowledge_uploads(source_id)
    return {
        "data": [_quarantined_upload_payload(upload) for upload in uploads],
        "meta": {"total": len(uploads)},
    }


@router.get("/config/knowledge-sources/{source_id}/quarantined-uploads/{upload_id}")
def get_quarantined_knowledge_upload(
    source_id: str,
    upload_id: str,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Return one asynchronous upload-validation record."""

    _require_operator(identity, OperatorPermission.KNOWLEDGE_SOURCE_VIEW)
    store = _get_configuration_store(app_request)
    _require_knowledge_source(store, source_id)
    upload = store.get_quarantined_knowledge_upload(
        source_id=source_id,
        upload_id=upload_id,
    )
    if upload is None:
        raise HTTPException(
            status_code=404,
            detail=f"Quarantined Knowledge Upload not found: {source_id}/{upload_id}",
        )
    return _quarantined_upload_payload(upload)


@router.get("/config/knowledge-sources/{source_id}/ingestion-jobs")
def list_knowledge_ingestion_jobs(
    source_id: str,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """List persisted artifact-build jobs for one Knowledge Source."""

    _require_operator(identity, OperatorPermission.KNOWLEDGE_SOURCE_VIEW)
    store = _get_configuration_store(app_request)
    _require_knowledge_source(store, source_id)
    jobs = store.list_knowledge_ingestion_jobs(source_id)
    return {
        "data": [_knowledge_ingestion_job_payload(job) for job in jobs],
        "meta": {"total": len(jobs)},
    }


@router.get("/config/knowledge-sources/{source_id}/ingestion-jobs/{job_id}")
def get_knowledge_ingestion_job(
    source_id: str,
    job_id: str,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Return one persisted artifact-build job."""

    _require_operator(identity, OperatorPermission.KNOWLEDGE_SOURCE_VIEW)
    store = _get_configuration_store(app_request)
    _require_knowledge_source(store, source_id)
    job = store.get_knowledge_ingestion_job(source_id=source_id, job_id=job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail=f"Knowledge Ingestion Job not found: {source_id}/{job_id}",
        )
    return _knowledge_ingestion_job_payload(job)


@router.post("/config/knowledge-sources/{source_id}/ingestion-jobs/{job_id}/retry")
def retry_knowledge_ingestion_job(
    source_id: str,
    job_id: str,
    request: KnowledgeIngestionRetryRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Return one failed artifact-build job to the worker queue."""

    _require_operator(identity, OperatorPermission.KNOWLEDGE_SOURCE_EDIT)
    store = _get_configuration_store(app_request)
    _require_active_knowledge_source(store, source_id)
    if store.get_knowledge_ingestion_job(source_id=source_id, job_id=job_id) is None:
        raise HTTPException(
            status_code=404,
            detail=f"Knowledge Ingestion Job not found: {source_id}/{job_id}",
        )
    try:
        job = store.retry_failed_knowledge_ingestion_job(source_id=source_id, job_id=job_id)
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    return _knowledge_ingestion_job_payload(job)


@router.get("/config/knowledge-sources/{source_id}/candidate-snapshot")
def get_candidate_knowledge_source_snapshot(
    source_id: str,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Return the current derived Local Index candidate snapshot."""

    _require_operator(identity, OperatorPermission.KNOWLEDGE_SOURCE_VIEW)
    store = _get_configuration_store(app_request)
    _require_active_knowledge_source(store, source_id)
    try:
        candidate = store.get_candidate_knowledge_source_snapshot(source_id)
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    return candidate.model_dump(mode="json")


@router.post("/config/knowledge-sources/{source_id}/candidate-snapshot/validate-foundation")
def validate_candidate_knowledge_source_snapshot_foundation(
    source_id: str,
    request: KnowledgeSourceFoundationValidationRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Persist a minimal freeze-readiness validation for the current candidate."""

    actor = _require_operator(identity, OperatorPermission.KNOWLEDGE_SOURCE_EDIT)
    store = _get_configuration_store(app_request)
    _require_active_knowledge_source(store, source_id)
    try:
        validation = store.validate_candidate_knowledge_source_snapshot_foundation(
            source_id=source_id,
            actor=actor,
        )
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    return validation.model_dump(mode="json")


@router.post("/config/knowledge-sources/{source_id}/candidate-snapshot/freeze")
def freeze_candidate_knowledge_source_snapshot(
    source_id: str,
    request: KnowledgeSourceSnapshotFreezeRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Freeze one foundation-validated Local Index snapshot manifest."""

    actor = _require_operator(identity, OperatorPermission.KNOWLEDGE_SOURCE_EDIT)
    store = _get_configuration_store(app_request)
    _require_active_knowledge_source(store, source_id)
    try:
        snapshot = store.freeze_candidate_knowledge_source_snapshot(
            source_id=source_id,
            validation_id=request.validation_id,
            actor=actor,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=(
                "Foundation Knowledge Source Validation not found: "
                f"{source_id}/{request.validation_id}"
            ),
        ) from exc
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    return snapshot.model_dump(mode="json")


@router.get("/config/knowledge-sources/{source_id}/snapshots")
def list_knowledge_source_snapshots(
    source_id: str,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """List immutable Local Index snapshot manifests for one source."""

    _require_operator(identity, OperatorPermission.KNOWLEDGE_SOURCE_VIEW)
    store = _get_configuration_store(app_request)
    _require_knowledge_source(store, source_id)
    try:
        snapshots = store.list_knowledge_source_snapshots(source_id)
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    return {
        "data": [snapshot.model_dump(mode="json") for snapshot in snapshots],
        "meta": {"total": len(snapshots)},
    }


@router.get("/config/knowledge-sources/{source_id}/snapshots/{snapshot_id}")
def get_knowledge_source_snapshot(
    source_id: str,
    snapshot_id: str,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Return one immutable Local Index snapshot manifest."""

    _require_operator(identity, OperatorPermission.KNOWLEDGE_SOURCE_VIEW)
    store = _get_configuration_store(app_request)
    _require_knowledge_source(store, source_id)
    try:
        snapshot = store.get_knowledge_source_snapshot(
            source_id=source_id,
            snapshot_id=snapshot_id,
        )
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail=f"Knowledge Source Snapshot not found: {source_id}/{snapshot_id}",
        )
    return snapshot.model_dump(mode="json")


@router.post("/config/knowledge-sources/{source_id}/publication/validate")
def validate_knowledge_source_publication(
    source_id: str,
    request: KnowledgeSourcePublicationValidationRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Run Source-level smoke retrieval and persist a passed publication validation."""

    actor = _require_operator(identity, OperatorPermission.KNOWLEDGE_SOURCE_PUBLISH)
    store = _get_configuration_store(app_request)
    source = _require_active_knowledge_source(store, source_id)
    try:
        if source.provider == "local_index":
            validation = store.validate_local_index_source_publication(
                source_id=source_id,
                smoke_query=request.smoke_query,
                actor=actor,
            )
        elif source.provider == "http_json":
            validation = store.validate_http_json_source_publication(
                source_id=source_id,
                smoke_query=request.smoke_query,
                actor=actor,
            )
        else:
            raise ProofAgentError(
                "PA_CONFIG_001",
                f"Knowledge Source provider cannot be publication-validated: {source.provider}",
                "Use a publishable Knowledge Source provider such as local_index or http_json.",
            )
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    return validation.model_dump(mode="json")


@router.post("/config/knowledge-sources/{source_id}/publication/publish")
def publish_knowledge_source(
    source_id: str,
    request: KnowledgeSourcePublicationRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Publish one validation-passed Knowledge Source resource."""

    actor = _require_operator(identity, OperatorPermission.KNOWLEDGE_SOURCE_PUBLISH)
    store = _get_configuration_store(app_request)
    _require_active_knowledge_source(store, source_id)
    try:
        publication = store.publish_knowledge_source(
            source_id=source_id,
            validation_id=request.validation_id,
            change_note=request.change_note,
            actor=actor,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=(
                "Knowledge Source Publication Validation not found: "
                f"{source_id}/{request.validation_id}"
            ),
        ) from exc
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    return publication.model_dump(mode="json")


@router.get("/config/knowledge-sources/{source_id}/publication-validations")
def list_knowledge_source_publication_validations(
    source_id: str,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """List Source-level publication smoke validations."""

    _require_operator(identity, OperatorPermission.KNOWLEDGE_SOURCE_VIEW)
    store = _get_configuration_store(app_request)
    _require_knowledge_source(store, source_id)
    try:
        validations = store.list_knowledge_source_publication_validations(source_id)
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    return {
        "data": [validation.model_dump(mode="json") for validation in validations],
        "meta": {"total": len(validations)},
    }


@router.get("/config/knowledge-sources/{source_id}/publications")
def list_knowledge_source_publications(
    source_id: str,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """List immutable Knowledge Source publication records."""

    _require_operator(identity, OperatorPermission.KNOWLEDGE_SOURCE_VIEW)
    store = _get_configuration_store(app_request)
    _require_knowledge_source(store, source_id)
    try:
        publications = store.list_knowledge_source_publications(source_id)
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    return {
        "data": [publication.model_dump(mode="json") for publication in publications],
        "meta": {"total": len(publications)},
    }


@router.get("/config/agents")
def list_config_agents(
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """List Agent identities managed by the local configuration store."""

    _require_operator(identity, OperatorPermission.AGENT_VIEW)
    store = _get_configuration_store(app_request)
    agent_ids = _configuration_agent_ids(store)
    data = [_agent_summary_payload(store, agent_id) for agent_id in agent_ids]
    return {"data": data, "meta": {"total": len(data)}}


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
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": exc.message, "fix": exc.fix},
        ) from exc
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
    draft = _require_draft(_get_configuration_store(app_request), agent_id, draft_id)
    return _draft_payload(draft)


@router.patch("/config/agents/{agent_id}/drafts/{draft_id}")
def update_config_draft(
    agent_id: str,
    draft_id: str,
    request: DraftUpdateRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Update editable Draft Agent fields."""

    actor = _require_operator(identity, OperatorPermission.AGENT_EDIT)
    store = _get_configuration_store(app_request)
    _require_draft(store, agent_id, draft_id)
    draft = store.update_draft(
        agent_id=agent_id,
        draft_id=draft_id,
        display_name=request.display_name,
        purpose=request.purpose,
        actor=actor,
    )
    return _draft_payload(draft)


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
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": exc.message, "fix": exc.fix},
        ) from exc
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


@router.post("/config/agents/{agent_id}/drafts/{draft_id}/knowledge-bindings")
def bind_knowledge_source_to_draft(
    agent_id: str,
    draft_id: str,
    request: KnowledgeBindingAttachRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Bind a shared Knowledge Source into a Draft Agent contract."""

    actor = _require_operator(identity, OperatorPermission.AGENT_EDIT)
    store = _get_configuration_store(app_request)
    draft = _require_draft(store, agent_id, draft_id)
    source = _require_active_knowledge_source(store, request.source_id)
    if source.published_snapshot_id is None:
        raise HTTPException(
            status_code=400,
            detail="Knowledge Source must be published before binding.",
        )
    if request.failure_mode not in {"required", "advisory"}:
        raise HTTPException(status_code=400, detail="failure_mode must be required or advisory.")
    if request.fusion_weight <= 0:
        raise HTTPException(status_code=400, detail="fusion_weight must be greater than 0.")
    if request.top_k is not None and request.top_k <= 0:
        raise HTTPException(status_code=400, detail="top_k must be greater than 0.")

    agent_yaml = _bind_source_in_agent_yaml(
        draft.contract_bundle.agent_yaml,
        source=source,
        request=request,
    )
    bundle = ContractBundle(
        agent_yaml=agent_yaml,
        policy_yaml=draft.contract_bundle.policy_yaml,
        tools_yaml=draft.contract_bundle.tools_yaml,
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
        actor=actor,
    )
    return updated.contract_bundle.model_dump(mode="json")


@router.delete("/config/agents/{agent_id}/drafts/{draft_id}/knowledge-bindings/{binding_id}")
def unbind_knowledge_source_from_draft(
    agent_id: str,
    draft_id: str,
    binding_id: str,
    request: KnowledgeBindingDetachRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Remove a shared Knowledge Source binding from a Draft Agent contract."""

    actor = _require_operator(identity, OperatorPermission.AGENT_EDIT)
    store = _get_configuration_store(app_request)
    draft = _require_draft(store, agent_id, draft_id)

    agent_yaml = _unbind_source_in_agent_yaml(
        draft.contract_bundle.agent_yaml,
        binding_id=binding_id,
    )
    bundle = ContractBundle(
        agent_yaml=agent_yaml,
        policy_yaml=draft.contract_bundle.policy_yaml,
        tools_yaml=draft.contract_bundle.tools_yaml,
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
        actor=actor,
    )
    return updated.contract_bundle.model_dump(mode="json")


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
        manifest = load_agent_manifest(package_dir / "agent.yaml")
        _resolve_draft_knowledge_bindings(store, manifest)
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
        actor=actor,
    )
    return updated.contract_bundle.model_dump(mode="json")


@router.patch("/config/agents/{agent_id}/drafts/{draft_id}/workflow-nodes")
def update_config_draft_workflow_nodes(
    agent_id: str,
    draft_id: str,
    request: WorkflowNodesUpdateRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Replace Draft Agent workflow.nodes[] and validate the Agent Contract."""

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
        workflow["nodes"] = [_workflow_node_request_payload(item) for item in request.nodes]
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
        manifest = load_agent_manifest(package_dir / "agent.yaml")
        _resolve_draft_knowledge_bindings(store, manifest)
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
        actor=actor,
    )
    return updated.contract_bundle.model_dump(mode="json")


@router.post("/config/agents/{agent_id}/drafts/{draft_id}/workflow-nodes/{node_id}/preview")
def preview_config_draft_workflow_node(
    agent_id: str,
    draft_id: str,
    node_id: str,
    request: WorkflowNodePreviewRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Render a redacted Workflow Node Context Preview without executing a run."""

    _require_operator(identity, OperatorPermission.AGENT_VALIDATE)
    store = _get_configuration_store(app_request)
    draft = _require_draft(store, agent_id, draft_id)
    try:
        package_dir = compile_draft_agent(draft, store.root_dir / "compiled_preview")
        manifest = load_agent_manifest(package_dir / "agent.yaml")
        descriptor = resolve_workflow_template(manifest.workflow.template)
        node_descriptor = descriptor.node(node_id)
        prompt = WorkflowNodePromptConfig(
            **_workflow_node_prompt_request_payload(request.prompt)
        )
        validate_workflow_node_prompt_config(
            node_id=node_id,
            prompt=prompt,
            node_descriptor=node_descriptor,
            manifest_path=package_dir / "agent.yaml",
        )
        return build_workflow_node_context_preview(
            descriptor=descriptor,
            node_id=node_id,
            prompt=prompt,
            context_options=request.context,
            sample_context=_workflow_node_sample_context(manifest),
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProofAgentError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": exc.message, "fix": exc.fix},
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

    actor = _require_operator(identity, OperatorPermission.AGENT_VALIDATE)
    config_store = _get_configuration_store(app_request)
    draft = _require_draft(config_store, agent_id, draft_id)
    try:
        package_dir = compile_draft_agent(draft, config_store.root_dir / "compiled")
        manifest = load_agent_manifest(package_dir / "agent.yaml")
        resolved_knowledge_bindings = _resolve_draft_knowledge_bindings(
            config_store,
            manifest,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProofAgentError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": exc.message, "fix": exc.fix},
        ) from exc
    run_store = _get_run_store(app_request)
    run_id = f"run_{uuid4().hex[:8]}"
    try:
        result = run_with_langgraph(
            package_dir / "agent.yaml",
            question=request.question,
            runs_dir=_get_runs_dir(app_request),
            run_id=run_id,
            store=run_store,
            manifest=manifest,
            resolved_knowledge_bindings=resolved_knowledge_bindings,
            configuration_store=config_store,
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
    warnings, publish_blockers = _validation_model_connection_warnings(detail.trace_events)
    record = AgentValidationRecord(
        validation_id=f"validation_{uuid4().hex[:8]}",
        draft_id=draft_id,
        run_id=run_id,
        status=detail.outcome.value,
        created_at=_now(),
        summary=result.final_output[:500],
        warnings=warnings,
        publish_blockers=publish_blockers,
        resolved_knowledge_bindings=resolved_knowledge_bindings,
    )
    config_store.record_validation(
        agent_id=agent_id,
        draft_id=draft_id,
        record=record,
        actor=actor,
    )
    return {
        "validation_id": record.validation_id,
        "run_id": detail.run_id,
        "status": record.status,
        "outcome": detail.outcome.value,
        "run_purpose": detail.run_purpose.value,
        "agent_id": detail.agent_id,
        "draft_id": detail.draft_id,
        "warnings": list(warnings),
        "publish_blockers": list(publish_blockers),
        "links": {
            "run_detail": f"/api/runs/{detail.run_id}",
            "trace": f"/api/runs/{detail.run_id}/trace",
            "receipt": f"/api/runs/{detail.run_id}/receipt",
        },
    }


def _validation_model_connection_warnings(
    trace_events: tuple[dict[str, Any], ...],
) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
    warnings: list[dict[str, Any]] = []
    publish_blockers: list[dict[str, Any]] = []
    seen_connections: set[tuple[str | None, str | None]] = set()
    for event in trace_events:
        if event.get("event_type") != "model_connection_resolution":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        event_warnings = payload.get("warnings")
        if not isinstance(event_warnings, list | tuple):
            continue
        if "connection_archived" not in event_warnings:
            continue
        connection_id = payload.get("connection_id")
        role = payload.get("role")
        key = (
            connection_id if isinstance(connection_id, str) else None,
            role if isinstance(role, str) else None,
        )
        if key in seen_connections:
            continue
        seen_connections.add(key)
        if not isinstance(connection_id, str) or not isinstance(role, str):
            continue
        warnings.append(
            {
                "code": "model_connection_archived",
                "connection_id": connection_id,
                "role": role,
                "message": f"Shared Model Connection is archived: {connection_id}.",
            }
        )
        publish_blockers.append(
            {
                "code": "archived_model_connection",
                "connection_id": connection_id,
                "role": role,
                "message": (
                    "Publish is blocked while Shared Model Connection "
                    f"{connection_id} is archived."
                ),
            }
        )
    return tuple(warnings), tuple(publish_blockers)


@router.post("/config/agents/{agent_id}/drafts/{draft_id}/publish")
def publish_config_draft(
    agent_id: str,
    draft_id: str,
    request: DraftPublishRequest,
    app_request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Publish a validated Draft Agent as an immutable version."""

    actor = _require_operator(identity, OperatorPermission.AGENT_PUBLISH)
    store = _get_configuration_store(app_request)
    draft = _require_draft(store, agent_id, draft_id)
    validation_run_id = request.validation_run_id or _latest_validation_run_id(draft)
    if validation_run_id is None:
        raise HTTPException(status_code=400, detail="A validation run is required before publish.")
    validation_record = next(
        (record for record in draft.validation_records if record.run_id == validation_run_id),
        None,
    )
    if validation_record is None:
        raise HTTPException(
            status_code=400,
            detail=f"Validation run is not recorded for this draft: {validation_run_id}",
        )
    try:
        package_dir = compile_draft_agent(draft, store.root_dir / "compiled_publication")
        manifest = load_agent_manifest(package_dir / "agent.yaml")
        _resolve_draft_knowledge_bindings(store, manifest)
        version = store.publish_version(
            agent_id=agent_id,
            draft_id=draft_id,
            validation_run_id=validation_run_id,
            actor=actor,
            resolved_knowledge_bindings=validation_record.resolved_knowledge_bindings,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProofAgentError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": exc.message, "fix": exc.fix},
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
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    """Switch the Active Agent Version pointer to a previous version."""

    actor = _require_operator(identity, OperatorPermission.AGENT_PUBLISH)
    store = _get_configuration_store(app_request)
    try:
        active = store.rollback_active_version(
            agent_id=agent_id,
            version_id=version_id,
            actor=actor,
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


def _workflow_template_payload(descriptor: Any) -> dict[str, Any]:
    payload = asdict(descriptor)
    payload["nodes"] = [asdict(node) for node in descriptor.nodes]
    return payload


def _workflow_node_request_payload(item: WorkflowNodeUpdateItemRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {"node_id": item.node_id}
    prompt = _workflow_node_prompt_request_payload(item.prompt)
    if prompt:
        payload["prompt"] = prompt
    if item.context:
        payload["context"] = dict(item.context)
    return payload


def _workflow_node_prompt_request_payload(
    prompt: WorkflowNodePromptRequest,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if prompt.business_context:
        payload["business_context"] = prompt.business_context
    if prompt.task_instructions:
        payload["task_instructions"] = list(prompt.task_instructions)
    if prompt.output_preferences:
        payload["output_preferences"] = list(prompt.output_preferences)
    return payload


def _workflow_node_sample_context(manifest: Any) -> dict[str, Any]:
    return {
        "agent_purpose": manifest.purpose,
        "bound_knowledge_sources": [
            binding.source_ref.source_id for binding in manifest.knowledge_bindings
        ],
        "bound_tools": str(manifest.tools.file),
        "policy_outline": str(manifest.policy.file),
        "response_disclosure_policy": (
            manifest.response.model_dump(mode="json") if manifest.response else {}
        ),
        "memory_scope": manifest.memory.model_dump(mode="json"),
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
        "display_name": version.display_name,
        "purpose": version.purpose,
        "published_at": version.published_at,
        "published_by": version.published_by,
        "resolved_knowledge_bindings": (
            version.resolved_knowledge_bindings.model_dump(mode="json")
            if version.resolved_knowledge_bindings is not None
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


def _knowledge_source_payload(
    store: LocalAgentConfigurationStore,
    source: KnowledgeSource,
) -> dict[str, Any]:
    documents = store.list_knowledge_documents(source.source_id)
    payload = source.model_dump(mode="json")
    payload["document_count"] = len(documents)
    payload["ready_document_count"] = sum(1 for document in documents if document.state == "ready")
    payload["publication_count"] = len(store.list_knowledge_source_publications(source.source_id))
    return payload


def _knowledge_document_payload(document: KnowledgeDocument) -> dict[str, Any]:
    return document.model_dump(mode="json")


def _quarantined_upload_payload(upload: QuarantinedKnowledgeUpload) -> dict[str, Any]:
    return upload.model_dump(mode="json")


def _knowledge_ingestion_job_payload(job: KnowledgeIngestionJob) -> dict[str, Any]:
    return job.model_dump(mode="json")


def _bind_source_in_agent_yaml(
    agent_yaml: str,
    *,
    source: KnowledgeSource,
    request: KnowledgeBindingAttachRequest,
) -> str:
    raw = yaml.safe_load(agent_yaml)
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="agent_yaml must be a mapping.")

    # Shared Source bindings reference Configuration Store state. They do not
    # copy provider params into the Agent Contract.
    raw.pop("knowledge", None)
    raw.pop("knowledge_sources", None)

    package_knowledge_sources = raw.setdefault("package_knowledge_sources", [])
    if not isinstance(package_knowledge_sources, list):
        raise HTTPException(status_code=400, detail="package_knowledge_sources must be a list.")

    knowledge_bindings = raw.setdefault("knowledge_bindings", [])
    if not isinstance(knowledge_bindings, list):
        raise HTTPException(status_code=400, detail="knowledge_bindings must be a list.")
    binding_id = request.binding_id or f"{source.source_id}_binding"
    binding_entry: dict[str, Any] = {
        "binding_id": binding_id,
        "source_ref": {"scope": "shared", "source_id": source.source_id},
        "failure_mode": request.failure_mode,
        "fusion_weight": request.fusion_weight,
    }
    if request.alias:
        binding_entry["alias"] = request.alias
    if request.top_k is not None:
        binding_entry["top_k"] = request.top_k
    _upsert_by_key(knowledge_bindings, "binding_id", binding_id, binding_entry)

    return _dump_agent_yaml(raw)


def _unbind_source_in_agent_yaml(
    agent_yaml: str,
    *,
    binding_id: str,
) -> str:
    raw = yaml.safe_load(agent_yaml)
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="agent_yaml must be a mapping.")

    raw.pop("knowledge", None)
    raw.pop("knowledge_sources", None)
    package_knowledge_sources = raw.setdefault("package_knowledge_sources", [])
    if not isinstance(package_knowledge_sources, list):
        raise HTTPException(status_code=400, detail="package_knowledge_sources must be a list.")

    knowledge_bindings = raw.get("knowledge_bindings", [])
    if not isinstance(knowledge_bindings, list):
        raise HTTPException(status_code=400, detail="knowledge_bindings must be a list.")

    for binding in list(knowledge_bindings):
        if isinstance(binding, dict) and binding.get("binding_id") == binding_id:
            knowledge_bindings.remove(binding)
            break

    return _dump_agent_yaml(raw)


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


def _upsert_by_key(
    items: list[Any],
    key: str,
    value: str,
    replacement: dict[str, Any],
) -> None:
    for index, item in enumerate(items):
        if isinstance(item, dict) and item.get(key) == value:
            items[index] = replacement
            return
    items.append(replacement)


def _configuration_agent_ids(store: LocalAgentConfigurationStore) -> tuple[str, ...]:
    agents_root = store.root_dir / "agents"
    if not agents_root.exists():
        return ()
    return tuple(sorted(entry.name for entry in agents_root.iterdir() if entry.is_dir()))


def _latest_validation_run_id(draft: DraftAgent) -> str | None:
    if not draft.validation_records:
        return None
    return draft.validation_records[-1].run_id


def _resolve_draft_knowledge_bindings(
    store: LocalAgentConfigurationStore,
    manifest: Any,
) -> ResolvedKnowledgeBindingSet:
    has_shared_binding = any(
        binding.source_ref.scope == "shared" for binding in manifest.knowledge_bindings
    )
    if has_shared_binding:
        return ConfigurationStoreKnowledgeBindingResolver(store).resolve(manifest)
    return PackageKnowledgeBindingResolver().resolve(manifest)


def _require_draft(
    store: LocalAgentConfigurationStore,
    agent_id: str,
    draft_id: str,
) -> DraftAgent:
    draft = store.get_draft(agent_id, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail=f"Draft Agent not found: {agent_id}/{draft_id}")
    return draft


def _require_knowledge_source(
    store: LocalAgentConfigurationStore,
    source_id: str,
) -> KnowledgeSource:
    try:
        source = store.get_knowledge_source(source_id)
    except ProofAgentError as exc:
        raise _proof_agent_http_exception(exc) from exc
    if source is None:
        raise HTTPException(status_code=404, detail=f"Knowledge Source not found: {source_id}")
    return source


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


def _require_active_knowledge_source(
    store: LocalAgentConfigurationStore,
    source_id: str,
) -> KnowledgeSource:
    source = _require_knowledge_source(store, source_id)
    if source.lifecycle_state is not KnowledgeSourceLifecycleState.ACTIVE:
        raise HTTPException(status_code=400, detail="Knowledge Source is archived.")
    return source


def _get_configuration_store(request: Request) -> LocalAgentConfigurationStore:
    return cast(LocalAgentConfigurationStore, request.app.state.agent_configuration_store)


def _get_run_store(request: Request) -> RunStore:
    return cast(RunStore, request.app.state.store)


def _get_runs_dir(request: Request) -> Path:
    return cast(Path, request.app.state.runs_dir)


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _source_id(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", value.strip().lower().replace("-", "_"))
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized:
        normalized = f"ks_{uuid4().hex[:8]}"
    if not normalized.startswith("ks_"):
        normalized = f"ks_{normalized}"
    return normalized


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
    env_vars = [connection.credential_ref.name]
    if connection.organization_env is not None:
        env_vars.append(connection.organization_env)
    if connection.project_env is not None:
        env_vars.append(connection.project_env)
    return tuple(env_vars)


def _missing_model_connection_env_vars(connection: SharedModelConnection) -> tuple[str, ...]:
    return tuple(
        env_var for env_var in _model_connection_env_vars(connection) if not os.getenv(env_var)
    )


def _decode_upload_content(content_base64: str) -> bytes:
    maximum_encoded_chars = ((MAX_UPLOAD_BYTES + 2) // 3) * 4
    if len(content_base64) > maximum_encoded_chars:
        raise HTTPException(
            status_code=400,
            detail=f"Uploaded encoded upload envelope exceeds {maximum_encoded_chars} characters.",
        )
    try:
        content = base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="content_base64 is not valid base64") from exc
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded document is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"Uploaded document exceeds {MAX_UPLOAD_BYTES} bytes.",
        )
    return content


def _proof_agent_http_exception(exc: ProofAgentError) -> HTTPException:
    status_code = {
        "PA_INGESTION_004": 503,
        "PA_INGESTION_005": 409,
    }.get(exc.code, 400)
    return HTTPException(
        status_code=status_code,
        detail={"code": exc.code, "message": exc.message, "fix": exc.fix},
    )
