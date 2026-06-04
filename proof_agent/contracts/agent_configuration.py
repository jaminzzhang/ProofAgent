from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any, Literal, cast

from pydantic import Field, field_serializer, field_validator

from proof_agent.contracts._base import FrozenDict, FrozenModel, freeze_value


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value


class ConfigurationOperation(str, Enum):
    IMPORTED = "imported"
    UPDATED = "updated"
    VALIDATED = "validated"
    PUBLISHED = "published"
    ROLLED_BACK = "rolled_back"


class ContractBundle(FrozenModel):
    """Reviewable Agent Package contract files preserved for Contract View."""

    agent_yaml: str
    policy_yaml: str
    tools_yaml: str
    extra_files: Mapping[str, str] = Field(default_factory=FrozenDict)
    advanced_fields: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("extra_files", "advanced_fields", mode="after")
    @classmethod
    def freeze_mappings(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_serializer("extra_files", "advanced_fields")
    def serialize_mappings(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(value))


class AgentValidationRecord(FrozenModel):
    """Validation metadata linking a Draft Agent to a governed validation run."""

    validation_id: str
    draft_id: str
    run_id: str
    status: str
    created_at: str
    summary: str = ""
    errors: tuple[str, ...] = Field(default_factory=tuple)


class ConfigurationOperationAudit(FrozenModel):
    """Audit metadata for configuration lifecycle operations."""

    operation_id: str
    operation: ConfigurationOperation
    actor: str
    created_at: str
    summary: str = ""
    metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("metadata", mode="after")
    @classmethod
    def freeze_metadata(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_serializer("metadata")
    def serialize_metadata(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(value))


class DraftAgent(FrozenModel):
    """Editable Agent configuration state before publication."""

    agent_id: str
    draft_id: str
    display_name: str
    purpose: str
    contract_bundle: ContractBundle
    created_at: str
    updated_at: str
    created_by: str
    updated_by: str
    version_id: str | None = None
    validation_records: tuple[AgentValidationRecord, ...] = Field(default_factory=tuple)
    operation_audit: tuple[ConfigurationOperationAudit, ...] = Field(default_factory=tuple)


class PublishedAgentVersion(FrozenModel):
    """Immutable published snapshot available to execution surfaces."""

    agent_id: str
    version_id: str
    source_draft_id: str
    validation_run_id: str
    display_name: str = ""
    purpose: str = ""
    contract_bundle: ContractBundle
    published_at: str
    published_by: str
    operation_audit: tuple[ConfigurationOperationAudit, ...] = Field(default_factory=tuple)

    @field_validator("validation_run_id")
    @classmethod
    def require_validation_run_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("validation_run_id is required")
        return value


class ActiveAgentVersion(FrozenModel):
    """Pointer to the default Published Agent Version for one Agent identity."""

    agent_id: str
    version_id: str
    activated_at: str
    activated_by: str
    rollback_from_version_id: str | None = None


class KnowledgeSource(FrozenModel):
    """Reusable knowledge asset or connection."""

    source_id: str
    name: str
    provider: str
    params: Mapping[str, Any] = Field(default_factory=FrozenDict)
    created_at: str
    updated_at: str
    source_draft_version_id: str | None = None
    latest_snapshot_id: str | None = None
    published_snapshot_id: str | None = None

    @field_validator("params", mode="after")
    @classmethod
    def freeze_params(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_serializer("params")
    def serialize_params(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(value))


class KnowledgeSourceSnapshotDocument(FrozenModel):
    """Immutable document-revision reference inside one Local Index snapshot."""

    document_id: str
    revision_id: str
    filename: str
    content_type: str
    content_hash: str
    artifact_path: str
    routing_metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("routing_metadata", mode="after")
    @classmethod
    def freeze_routing_metadata(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_serializer("routing_metadata")
    def serialize_routing_metadata(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(value))


class CandidateKnowledgeSourceSnapshot(FrozenModel):
    """Derived mutable Source Draft projection eligible for snapshot freeze."""

    source_id: str
    source_draft_version_id: str
    candidate_digest: str
    included_documents: tuple[KnowledgeSourceSnapshotDocument, ...]
    queued_document_count: int
    processing_document_count: int
    failed_document_count: int
    archived_document_count: int
    required_reingestion_count: int


class FoundationKnowledgeSourceValidation(FrozenModel):
    """Passed minimum validation record required before preview snapshot freeze."""

    validation_id: str
    source_id: str
    source_draft_version_id: str
    candidate_digest: str
    validation_level: Literal["foundation"]
    status: Literal["passed"]
    document_count: int
    required_reingestion_count: int
    created_at: str
    created_by: str


class KnowledgeSourcePublicationValidation(FrozenModel):
    """Passed Source-level retrieval smoke validation eligible for publication."""

    validation_id: str
    source_id: str
    snapshot_id: str
    source_draft_version_id: str
    candidate_digest: str
    status: Literal["passed"]
    smoke_query: str
    candidate_count: int
    citation_count: int
    created_at: str
    created_by: str


class KnowledgeSourcePublicationRecord(FrozenModel):
    """Immutable record for one published Knowledge Source snapshot."""

    publication_id: str
    source_id: str
    snapshot_id: str
    source_draft_version_id: str
    validation_id: str
    change_note: str
    published_at: str
    published_by: str
    document_count: int
    smoke_query: str
    smoke_result_summary: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("smoke_result_summary", mode="after")
    @classmethod
    def freeze_smoke_result_summary(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_serializer("smoke_result_summary")
    def serialize_smoke_result_summary(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(value))


class KnowledgeSourceSnapshotManifest(FrozenModel):
    """Immutable multi-document preview manifest for later routing development."""

    schema_version: Literal["local_index.snapshot.v2"]
    snapshot_id: str
    source_id: str
    state: Literal["READY"]
    validation_level: Literal["foundation"]
    source_draft_version_id: str
    candidate_digest: str
    foundation_validation_id: str
    documents: tuple[KnowledgeSourceSnapshotDocument, ...]
    created_at: str
    created_by: str


class KnowledgeDocument(FrozenModel):
    """Managed document revision inside a reusable Knowledge Source."""

    document_id: str
    source_id: str
    revision_id: str
    filename: str
    content_type: str
    content_hash: str
    size_bytes: int
    state: str
    storage_path: str
    provider_document_id: str | None = None
    ingestion_job_id: str | None = None
    artifact_path: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: str
    updated_at: str


class KnowledgeArtifactBuildSpec(FrozenModel):
    """Immutable artifact-affecting inputs frozen when one ingestion job is created."""

    provider: str
    engine_name: str
    engine_version: str
    parser_fingerprint_identity: str
    content_hash: str
    parsed_text_sha256: str
    declared_ingestion_model: Mapping[str, Any] | None = None

    @field_validator("declared_ingestion_model", mode="after")
    @classmethod
    def freeze_declared_ingestion_model(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_serializer("declared_ingestion_model")
    def serialize_declared_ingestion_model(
        self, value: Mapping[str, Any] | None
    ) -> dict[str, Any] | None:
        return cast(dict[str, Any] | None, _jsonable(value))


class QuarantinedKnowledgeUpload(FrozenModel):
    """Persisted operator-upload intake record awaiting asynchronous validation."""

    upload_id: str
    source_id: str
    filename: str
    content_type: str
    size_bytes: int
    storage_path: str
    state: str
    attempt_count: int = 0
    claimed_at: str | None = None
    claim_token: str | None = None
    lease_expires_at: str | None = None
    completed_at: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    promoted_document_id: str | None = None
    promoted_revision_id: str | None = None
    ingestion_job_id: str | None = None
    expires_at: str | None = None
    purged_at: str | None = None
    created_at: str
    updated_at: str


class KnowledgeIngestionJob(FrozenModel):
    """Persisted single-revision Local Index artifact-build task."""

    job_id: str
    source_id: str
    document_id: str
    revision_id: str
    state: str
    attempt_count: int = 0
    auto_retry_count: int = 0
    max_auto_retries: int = 2
    ingestion_config_fingerprint: str
    artifact_build_spec: KnowledgeArtifactBuildSpec
    artifact_path: str | None = None
    claimed_at: str | None = None
    claim_token: str | None = None
    lease_expires_at: str | None = None
    completed_at: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    last_failure_classification: str | None = None
    next_attempt_at: str | None = None
    created_at: str
    updated_at: str


class ToolSource(FrozenModel):
    """Reusable tool connection or local tool package."""

    source_id: str
    name: str
    source_type: str
    tool_contract_ids: tuple[str, ...] = Field(default_factory=tuple)
    params: Mapping[str, Any] = Field(default_factory=FrozenDict)
    created_at: str
    updated_at: str

    @field_validator("params", mode="after")
    @classmethod
    def freeze_params(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_serializer("params")
    def serialize_params(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(value))
