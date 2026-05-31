from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any, cast

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

    @field_validator("params", mode="after")
    @classmethod
    def freeze_params(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_serializer("params")
    def serialize_params(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(value))


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
    error_code: str | None = None
    error_message: str | None = None
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
