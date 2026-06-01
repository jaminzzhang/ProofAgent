"""Agent Configuration API endpoints for the Dashboard workspace."""

from __future__ import annotations

import base64
import binascii
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
import yaml  # type: ignore[import-untyped]

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.configuration.compiler import compile_draft_agent
from proof_agent.configuration.importer import import_agent_package
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import (
    AgentValidationRecord,
    ContractBundle,
    DraftAgent,
    KnowledgeDocument,
    KnowledgeSource,
    RunPurpose,
)
from proof_agent.errors import ProofAgentError
from proof_agent.observability.storage.run_store import RunStore
from proof_agent.runtime.langgraph_runner import run_with_langgraph


router = APIRouter(tags=["configuration"])

SUPPORTED_KNOWLEDGE_SOURCE_PROVIDERS = {
    "local_markdown",
    "local_index",
    "remote_search",
}
MAX_SOURCE_DOCUMENTS = 500
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


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


class KnowledgeSourceCreateRequest(BaseModel):
    """Request body for creating a reusable Knowledge Source."""

    model_config = ConfigDict(extra="forbid")

    source_id: str | None = None
    name: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    actor: str = "local-user"


class KnowledgeDocumentUploadRequest(BaseModel):
    """JSON/base64 upload for Dashboard-managed knowledge documents."""

    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    content_base64: str = Field(min_length=1)
    actor: str = "local-user"


class KnowledgeBindingAttachRequest(BaseModel):
    """Request body for binding a shared Knowledge Source into a Draft Agent."""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1)
    binding_id: str | None = None
    alias: str | None = None
    failure_mode: str = "required"
    fusion_weight: float = 1.0
    top_k: int | None = None
    actor: str = "local-user"


@router.get("/config/knowledge-sources")
def list_knowledge_sources(app_request: Request) -> dict[str, Any]:
    """List reusable Knowledge Sources managed by the local configuration store."""

    store = _get_configuration_store(app_request)
    data = [_knowledge_source_payload(store, source) for source in store.list_knowledge_sources()]
    return {"data": data, "meta": {"total": len(data)}}


@router.post("/config/knowledge-sources")
def create_knowledge_source(
    request: KnowledgeSourceCreateRequest,
    app_request: Request,
) -> dict[str, Any]:
    """Create a reusable Knowledge Source independent of any Agent binding."""

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
            actor=request.actor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _knowledge_source_payload(store, source)


@router.get("/config/knowledge-sources/{source_id}")
def get_knowledge_source(source_id: str, app_request: Request) -> dict[str, Any]:
    """Return one Knowledge Source with document counts."""

    store = _get_configuration_store(app_request)
    source = store.get_knowledge_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail=f"Knowledge Source not found: {source_id}")
    return _knowledge_source_payload(store, source)


@router.get("/config/knowledge-sources/{source_id}/documents")
def list_knowledge_source_documents(source_id: str, app_request: Request) -> dict[str, Any]:
    """List managed documents for one Knowledge Source."""

    store = _get_configuration_store(app_request)
    source = store.get_knowledge_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail=f"Knowledge Source not found: {source_id}")
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
) -> dict[str, Any]:
    """Validate, store, and index one PDF or Markdown document revision."""

    store = _get_configuration_store(app_request)
    source = store.get_knowledge_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail=f"Knowledge Source not found: {source_id}")
    documents = store.list_knowledge_documents(source_id)
    if len(documents) >= MAX_SOURCE_DOCUMENTS:
        raise HTTPException(
            status_code=400,
            detail=f"Knowledge Source document limit reached: {MAX_SOURCE_DOCUMENTS}",
        )
    content = _decode_upload_content(request.content_base64)
    _validate_upload_file(
        filename=request.filename,
        content_type=request.content_type,
        content=content,
    )
    if source.provider != "local_index":
        raise HTTPException(
            status_code=400,
            detail="Dashboard document upload currently supports local_index Knowledge Sources.",
        )

    document = store.add_knowledge_document(
        source_id=source.source_id,
        filename=request.filename,
        content_type=request.content_type,
        content=content,
        state="queued",
        provider_document_id=None,
        error_code=None,
        error_message=None,
        actor=request.actor,
    )
    return _knowledge_document_payload(document)


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


@router.post("/config/agents/{agent_id}/drafts/{draft_id}/knowledge-bindings")
def bind_knowledge_source_to_draft(
    agent_id: str,
    draft_id: str,
    request: KnowledgeBindingAttachRequest,
    app_request: Request,
) -> dict[str, Any]:
    """Bind a shared Knowledge Source into a Draft Agent contract."""

    store = _get_configuration_store(app_request)
    draft = _require_draft(store, agent_id, draft_id)
    source = store.get_knowledge_source(request.source_id)
    if source is None:
        raise HTTPException(
            status_code=404,
            detail=f"Knowledge Source not found: {request.source_id}",
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
        actor=request.actor,
    )
    return updated.contract_bundle.model_dump(mode="json")


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
        "display_name": version.display_name,
        "purpose": version.purpose,
        "published_at": version.published_at,
        "published_by": version.published_by,
        "operation_audit": [
            operation.model_dump(mode="json") for operation in version.operation_audit
        ],
    }


def _knowledge_source_payload(
    store: LocalAgentConfigurationStore,
    source: KnowledgeSource,
) -> dict[str, Any]:
    documents = store.list_knowledge_documents(source.source_id)
    payload = source.model_dump(mode="json")
    payload["document_count"] = len(documents)
    payload["ready_document_count"] = sum(
        1 for document in documents if document.state == "ready"
    )
    return payload


def _knowledge_document_payload(document: KnowledgeDocument) -> dict[str, Any]:
    return document.model_dump(mode="json")


def _bind_source_in_agent_yaml(
    agent_yaml: str,
    *,
    source: KnowledgeSource,
    request: KnowledgeBindingAttachRequest,
) -> str:
    raw = yaml.safe_load(agent_yaml)
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="agent_yaml must be a mapping.")

    # Remove legacy inline knowledge section when migrating to
    # knowledge_sources + knowledge_bindings.
    raw.pop("knowledge", None)

    knowledge_sources = raw.setdefault("knowledge_sources", [])
    if not isinstance(knowledge_sources, list):
        raise HTTPException(status_code=400, detail="knowledge_sources must be a list.")
    source_entry = {
        "source_id": source.source_id,
        "name": source.name,
        "provider": source.provider,
        "params": dict(source.params),
    }
    _upsert_by_key(knowledge_sources, "source_id", source.source_id, source_entry)

    knowledge_bindings = raw.setdefault("knowledge_bindings", [])
    if not isinstance(knowledge_bindings, list):
        raise HTTPException(status_code=400, detail="knowledge_bindings must be a list.")
    binding_id = request.binding_id or f"{source.source_id}_binding"
    binding_entry: dict[str, Any] = {
        "binding_id": binding_id,
        "source_id": source.source_id,
        "failure_mode": request.failure_mode,
        "fusion_weight": request.fusion_weight,
    }
    if request.alias:
        binding_entry["alias"] = request.alias
    if request.top_k is not None:
        binding_entry["top_k"] = request.top_k
    _upsert_by_key(knowledge_bindings, "binding_id", binding_id, binding_entry)

    return cast(str, yaml.safe_dump(raw, sort_keys=False))


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


def _source_id(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", value.strip().lower().replace("-", "_"))
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized:
        normalized = f"ks_{uuid4().hex[:8]}"
    if not normalized.startswith("ks_"):
        normalized = f"ks_{normalized}"
    return normalized


def _decode_upload_content(content_base64: str) -> bytes:
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


def _validate_upload_file(*, filename: str, content_type: str, content: bytes) -> None:
    suffix = Path(filename).suffix.lower()
    normalized_content_type = content_type.lower()
    if suffix == ".pdf" or normalized_content_type == "application/pdf":
        if not content.startswith(b"%PDF-"):
            raise HTTPException(status_code=400, detail="PDF upload is missing a PDF signature.")
        return
    if suffix in {".md", ".markdown"} or normalized_content_type in {
        "text/markdown",
        "text/plain",
    }:
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(
                status_code=400,
                detail="Markdown upload must be UTF-8 text.",
            ) from exc
        return
    raise HTTPException(
        status_code=400,
        detail="Unsupported knowledge document type. Upload PDF or Markdown.",
    )
