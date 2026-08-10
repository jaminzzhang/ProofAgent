"""Provider-neutral public contracts for Knowledge Source API V1."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Generic, Literal, Self, TypeVar, cast

from pydantic import Field, field_serializer, field_validator, model_validator

from proof_agent.contracts._base import FrozenDict, StrictFrozenModel, freeze_value
from proof_agent.contracts.agent_configuration import KnowledgeSource


_CursorItem = TypeVar("_CursorItem")


class KnowledgeSourceCursorError(ValueError):
    """A cursor is invalid, expired, or bound to another collection."""


class KnowledgeSourceIntakeCapability(StrictFrozenModel):
    """Deployment-advertised bounded file intake envelope."""

    content_types: tuple[str, ...] = Field(min_length=1)
    max_file_bytes: int = Field(ge=1)
    max_batch_files: int = Field(ge=1)
    max_source_documents: int = Field(ge=1)

    @field_validator("content_types")
    @classmethod
    def require_unique_content_types(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("knowledge intake content types must be unique")
        return values


class KnowledgeSourceProviderReadiness(StrictFrozenModel):
    """Sanitized readiness facts for one deployment-owned provider graph."""

    state: Literal["ready", "degraded", "unavailable"]
    revision: str | None = Field(default=None, min_length=1, max_length=255)
    blockers: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("blockers")
    @classmethod
    def require_unique_blockers(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("knowledge provider readiness blockers must be unique")
        return values


class KnowledgeSourceProviderCapability(StrictFrozenModel):
    """Creation and lifecycle features for one registered Knowledge provider."""

    provider: str = Field(min_length=1, pattern=r"^[a-z0-9_]+$")
    creation_supported: bool
    intake: KnowledgeSourceIntakeCapability
    features: tuple[str, ...] = Field(default_factory=tuple)
    readiness: KnowledgeSourceProviderReadiness

    @field_validator("features")
    @classmethod
    def require_unique_features(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("knowledge provider features must be unique")
        if any(not value or not value.replace("_", "").isalnum() for value in values):
            raise ValueError("knowledge provider features must be stable identifiers")
        return values


class KnowledgeSourceCapabilityProjection(StrictFrozenModel):
    """Deployment-level provider projection consumed by Dashboard."""

    schema_version: Literal["knowledge-source-api.v1"] = "knowledge-source-api.v1"
    providers: tuple[KnowledgeSourceProviderCapability, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def require_unique_providers(self) -> Self:
        providers = tuple(item.provider for item in self.providers)
        if len(providers) != len(set(providers)):
            raise ValueError("knowledge source capability providers must be unique")
        return self


class KnowledgeSourceActionBlocker(StrictFrozenModel):
    """Stable safe explanation for one unavailable Source command."""

    code: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9_]+$")
    detail: str = Field(min_length=1, max_length=1_000)


class KnowledgeSourceActionCapability(StrictFrozenModel):
    """One permission- and state-aware Source action projection."""

    action: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9_]+$")
    allowed: bool
    blockers: tuple[KnowledgeSourceActionBlocker, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def require_consistent_blockers(self) -> Self:
        blocker_codes = tuple(item.code for item in self.blockers)
        if len(blocker_codes) != len(set(blocker_codes)):
            raise ValueError("knowledge source action blocker codes must be unique")
        if self.allowed and self.blockers:
            raise ValueError("allowed knowledge source action cannot contain blockers")
        if not self.allowed and not self.blockers:
            raise ValueError("blocked knowledge source action requires at least one blocker")
        return self


class KnowledgeSourceActionCapabilityProjection(StrictFrozenModel):
    """Source-specific actions rendered by Dashboard and rechecked by commands."""

    source_id: str = Field(min_length=1, max_length=255)
    source_revision: int = Field(ge=1)
    actions: tuple[KnowledgeSourceActionCapability, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def require_unique_actions(self) -> Self:
        actions = tuple(item.action for item in self.actions)
        if len(actions) != len(set(actions)):
            raise ValueError("knowledge source capability actions must be unique")
        return self


class KnowledgeSourceOperationProgress(StrictFrozenModel):
    """Bounded progress facts for a durable asynchronous Source command."""

    current: int = Field(ge=0)
    total: int = Field(ge=1)
    unit: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")

    @model_validator(mode="after")
    def require_current_within_total(self) -> Self:
        if self.current > self.total:
            raise ValueError("knowledge source operation progress exceeds total")
        return self


class KnowledgeSourceOperation(StrictFrozenModel):
    """Trace-safe durable state used by Dashboard polling."""

    operation_id: str = Field(min_length=1, max_length=255)
    source_id: str = Field(min_length=1, max_length=255)
    command: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9_]+$")
    status: Literal[
        "queued",
        "running",
        "cancel_requested",
        "succeeded",
        "failed",
        "cancelled",
    ]
    stage: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9_]+$")
    source_revision: int = Field(ge=1)
    poll_after_ms: int = Field(ge=250, le=60_000)
    progress: KnowledgeSourceOperationProgress | None = None
    outcome_code: str | None = Field(
        default=None,
        max_length=128,
        pattern=r"^[a-z0-9_]+$",
    )
    outcome_detail: str | None = Field(default=None, max_length=1_000)
    created_at: str
    updated_at: str
    completed_at: str | None = None


class KnowledgeSourceRevisionCommand(StrictFrozenModel):
    """JSON precondition envelope for non-binary Source mutations."""

    expected_revision: int = Field(ge=1)


class KnowledgeSourceApiFieldError(StrictFrozenModel):
    """Safe field-level validation failure inside a Problem Details response."""

    location: tuple[str, ...] = Field(min_length=1)
    code: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9_]+$")
    detail: str = Field(min_length=1, max_length=1_000)


class KnowledgeSourceApiProblem(StrictFrozenModel):
    """Stable trace-safe application/problem+json contract."""

    type: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=255)
    status: int = Field(ge=400, le=599)
    code: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9_]+$")
    detail: str = Field(min_length=1, max_length=2_000)
    trace_id: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_.:-]+$")
    retryable: bool
    current_revision: int | None = Field(default=None, ge=1)
    field_errors: tuple[KnowledgeSourceApiFieldError, ...] = Field(default_factory=tuple)
    blockers: tuple[KnowledgeSourceActionBlocker, ...] = Field(default_factory=tuple)

    @field_validator("type")
    @classmethod
    def require_proof_agent_problem_type(cls, value: str) -> str:
        if not value.startswith("urn:proof-agent:problem:"):
            raise ValueError("knowledge source problem type must use Proof Agent URN")
        return value


class KnowledgeSourceCursorPageInfo(StrictFrozenModel):
    """Opaque keyset continuation facts for one bounded collection page."""

    limit: int = Field(ge=1, le=100)
    next_cursor: str | None = Field(default=None, min_length=1, max_length=4_096)
    has_more: bool

    @model_validator(mode="after")
    def require_cursor_when_more_exists(self) -> Self:
        if self.has_more != (self.next_cursor is not None):
            raise ValueError("knowledge source page cursor and has_more diverge")
        return self


class KnowledgeSourceCursorPage(StrictFrozenModel, Generic[_CursorItem]):
    """Common bounded collection envelope for Knowledge Source resources."""

    data: tuple[_CursorItem, ...] = Field(default_factory=tuple)
    page: KnowledgeSourceCursorPageInfo
    summary: Mapping[str, int] = Field(default_factory=FrozenDict)

    @field_validator("summary", mode="after")
    @classmethod
    def freeze_summary(cls, value: Mapping[str, int]) -> Mapping[str, int]:
        if any(item < 0 for item in value.values()):
            raise ValueError("knowledge source page summary values must be non-negative")
        return cast(Mapping[str, int], freeze_value(value))

    @field_serializer("summary")
    def serialize_summary(self, value: Mapping[str, int]) -> dict[str, int]:
        return dict(value)


class KnowledgeSourceListItemProjection(StrictFrozenModel):
    """One Source list item with its authoritative optimistic revision."""

    source: KnowledgeSource
    revision: int = Field(ge=1)


class KnowledgeSourceDocumentProjection(StrictFrozenModel):
    """Trace-safe document revision state without storage or provider locators."""

    document_id: str = Field(min_length=1, max_length=255)
    revision_id: str = Field(min_length=1, max_length=255)
    filename: str = Field(min_length=1, max_length=1_000)
    content_type: str = Field(min_length=1, max_length=255)
    state: str = Field(min_length=1, max_length=128)
    candidate_state: Literal["candidate", "pending", "superseded", "unselected"]
    safe_reason: str | None = Field(default=None, max_length=1_000)
    created_at: str
    updated_at: str


class KnowledgeSourceMetadataReviewProjection(StrictFrozenModel):
    """Current Metadata Review V2 task projection without artifact references."""

    review_id: str = Field(min_length=1, max_length=512)
    review_identity: str = Field(min_length=64, max_length=64)
    review_version: int = Field(ge=1)
    document_id: str = Field(min_length=1, max_length=255)
    revision_id: str = Field(min_length=1, max_length=255)
    structured_build_id: str = Field(min_length=1, max_length=512)
    profile_revision_id: str = Field(min_length=1, max_length=512)
    scope: Literal["document_default", "rule_unit_override"]
    state: Literal["needs_input", "ready_for_approval", "approved", "rejected"]
    current: bool
    canonical_anchor: str | None = Field(default=None, max_length=1_000)
    approved_metadata_revision_id: str | None = Field(default=None, max_length=512)
    parser_proposal: "KnowledgeSourceMetadataValuesProjection"
    current_draft: "KnowledgeSourceMetadataValuesProjection"


class KnowledgeSourceMetadataValuesProjection(StrictFrozenModel):
    """Safe structured business metadata shown and edited by Dashboard."""

    authority: str | None = Field(default=None, max_length=255)
    effective_from: str | None = Field(default=None, max_length=10)
    effective_to: str | None = Field(default=None, max_length=10)
    taxonomy_id: str | None = Field(default=None, max_length=255)
    taxonomy_revision_id: str | None = Field(default=None, max_length=255)
    precedence_policy_revision_id: str | None = Field(default=None, max_length=255)
    precedence_authority_tier: str | None = Field(default=None, max_length=255)
    precedence_order: int | None = Field(default=None, ge=0)


class KnowledgeSourceMetadataProfileValueProjection(StrictFrozenModel):
    code: str = Field(min_length=1, max_length=255)
    label: str = Field(min_length=1, max_length=255)


class KnowledgeSourceMetadataProfileProjection(StrictFrozenModel):
    metadata_scheme: Literal["insurance_rule.v2"] = "insurance_rule.v2"
    profile_id: str = Field(min_length=1, max_length=255)
    profile_revision_id: str = Field(min_length=1, max_length=512)
    reference_only: bool
    authority_values: tuple[KnowledgeSourceMetadataProfileValueProjection, ...]
    taxonomy_id: str = Field(min_length=1, max_length=255)
    taxonomy_revision_id: str = Field(min_length=1, max_length=255)
    precedence_policy_revision_id: str = Field(min_length=1, max_length=255)
    precedence_authority_tier_values: tuple[
        KnowledgeSourceMetadataProfileValueProjection, ...
    ]


class KnowledgeSourceMetadataWorkbookFieldMergeProjection(StrictFrozenModel):
    scope: Literal["document_default", "rule_unit_override"]
    canonical_anchor: str | None = Field(default=None, max_length=4_096)
    field: str = Field(min_length=1, max_length=128)
    classification: Literal[
        "unchanged",
        "workbook_only",
        "server_only",
        "matching_change",
        "conflict",
    ]
    base_value: str | int | None = None
    server_value: str | int | None = None
    workbook_value: str | int | None = None
    proposed_value: str | int | None = None


class KnowledgeSourceMetadataWorkbookOverrideMergeProjection(StrictFrozenModel):
    canonical_anchor: str = Field(min_length=1, max_length=4_096)
    base_mode: Literal["inherit", "override"]
    server_mode: Literal["inherit", "override"]
    workbook_mode: Literal["inherit", "override"]
    classification: Literal[
        "unchanged",
        "workbook_only",
        "server_only",
        "matching_change",
        "conflict",
    ]
    proposed_mode: Literal["inherit", "override"] | None = None
    override_reason: str | None = Field(default=None, max_length=2_000)


class KnowledgeSourceMetadataWorkbookValidationIssueProjection(StrictFrozenModel):
    sheet: str | None = Field(default=None, max_length=255)
    row: int | None = Field(default=None, ge=1)
    field: str | None = Field(default=None, max_length=255)
    code: str = Field(min_length=1, max_length=128)
    suggested_action_key: str = Field(min_length=1, max_length=255)


class KnowledgeSourceMetadataWorkbookValidationReportProjection(StrictFrozenModel):
    total_error_count: int = Field(ge=1)
    errors: tuple[KnowledgeSourceMetadataWorkbookValidationIssueProjection, ...] = (
        Field(min_length=1, max_length=100)
    )


class KnowledgeSourceMetadataWorkbookPreviewProjection(StrictFrozenModel):
    preview_id: str = Field(min_length=1, max_length=512)
    export_id: str = Field(min_length=1, max_length=512)
    state: Literal[
        "validation_failed",
        "conflicts",
        "ready_to_apply",
        "applied",
        "expired",
        "stale",
    ]
    preview_identity: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    conflict_count: int = Field(ge=0)
    field_merges: tuple[KnowledgeSourceMetadataWorkbookFieldMergeProjection, ...]
    override_modes: tuple[KnowledgeSourceMetadataWorkbookOverrideMergeProjection, ...]
    validation_report: KnowledgeSourceMetadataWorkbookValidationReportProjection | None
    created_at: str
    expires_at: str


class KnowledgeSourcePublicationValidationProjection(StrictFrozenModel):
    """Prepared publication authority required by the final short CAS."""

    validation_id: str = Field(min_length=1, max_length=512)
    state: Literal["queued", "running", "prepared", "failed", "consumed"]
    source_revision: int = Field(ge=1)
    fencing_token: int = Field(ge=0)
    source_draft_version_id: str = Field(min_length=1, max_length=512)
    generation_id: str | None = Field(default=None, min_length=1, max_length=512)
    safe_reason: str | None = Field(default=None, max_length=1_000)
    created_at: str
    updated_at: str


class KnowledgeSourcePublicationProjection(StrictFrozenModel):
    """Immutable Source publication history without artifact locators."""

    publication_id: str = Field(min_length=1, max_length=512)
    source_publication_seq: int = Field(ge=1)
    source_draft_version_id: str = Field(min_length=1, max_length=512)
    source_snapshot_id: str = Field(min_length=1, max_length=512)
    generation_id: str = Field(min_length=1, max_length=512)
    validation_id: str = Field(min_length=1, max_length=512)
    published_at: str
    published_by: str = Field(min_length=1, max_length=512)


class KnowledgeSourceAuditProjection(StrictFrozenModel):
    """Retained trace-safe audit metadata for one Source workspace."""

    audit_id: str = Field(min_length=1, max_length=255)
    event_type: str = Field(min_length=1, max_length=255)
    outcome: str = Field(min_length=1, max_length=128)
    actor_subject: str = Field(min_length=1, max_length=512)
    occurred_at: str
    target_type: str = Field(min_length=1, max_length=255)
    target_id: str = Field(min_length=1, max_length=512)
    metadata: Mapping[str, object] = Field(default_factory=FrozenDict)

    @field_validator("metadata", mode="after")
    @classmethod
    def freeze_metadata(cls, value: Mapping[str, object]) -> Mapping[str, object]:
        return cast(Mapping[str, object], freeze_value(value))

    @field_serializer("metadata")
    def serialize_metadata(self, value: Mapping[str, object]) -> dict[str, object]:
        return dict(value)


class KnowledgeSourceDetailProjection(StrictFrozenModel):
    """One authoritative Source detail plus its current actionable projection."""

    schema_version: Literal["knowledge-source-api.v1"] = "knowledge-source-api.v1"
    source: KnowledgeSource
    revision: int = Field(ge=1)
    summary: Mapping[str, int] = Field(default_factory=FrozenDict)
    action_capabilities: KnowledgeSourceActionCapabilityProjection

    @field_validator("summary", mode="after")
    @classmethod
    def freeze_summary(cls, value: Mapping[str, int]) -> Mapping[str, int]:
        if any(item < 0 for item in value.values()):
            raise ValueError("knowledge source detail summary values must be non-negative")
        return cast(Mapping[str, int], freeze_value(value))

    @field_serializer("summary")
    def serialize_summary(self, value: Mapping[str, int]) -> dict[str, int]:
        return dict(value)

    @model_validator(mode="after")
    def require_matching_action_authority(self) -> Self:
        if self.source.source_id != self.action_capabilities.source_id:
            raise ValueError("knowledge source detail action source identity diverges")
        if self.revision != self.action_capabilities.source_revision:
            raise ValueError("knowledge source detail action revision diverges")
        return self


__all__ = [
    "KnowledgeSourceActionBlocker",
    "KnowledgeSourceActionCapability",
    "KnowledgeSourceActionCapabilityProjection",
    "KnowledgeSourceApiFieldError",
    "KnowledgeSourceApiProblem",
    "KnowledgeSourceCapabilityProjection",
    "KnowledgeSourceCursorPage",
    "KnowledgeSourceCursorPageInfo",
    "KnowledgeSourceCursorError",
    "KnowledgeSourceDetailProjection",
    "KnowledgeSourceDocumentProjection",
    "KnowledgeSourceIntakeCapability",
    "KnowledgeSourceListItemProjection",
    "KnowledgeSourceMetadataReviewProjection",
    "KnowledgeSourceMetadataProfileProjection",
    "KnowledgeSourceMetadataProfileValueProjection",
    "KnowledgeSourceMetadataWorkbookFieldMergeProjection",
    "KnowledgeSourceMetadataWorkbookOverrideMergeProjection",
    "KnowledgeSourceMetadataWorkbookPreviewProjection",
    "KnowledgeSourceMetadataWorkbookValidationIssueProjection",
    "KnowledgeSourceMetadataWorkbookValidationReportProjection",
    "KnowledgeSourceMetadataValuesProjection",
    "KnowledgeSourceOperation",
    "KnowledgeSourceOperationProgress",
    "KnowledgeSourcePublicationProjection",
    "KnowledgeSourcePublicationValidationProjection",
    "KnowledgeSourceProviderCapability",
    "KnowledgeSourceProviderReadiness",
    "KnowledgeSourceRevisionCommand",
    "KnowledgeSourceAuditProjection",
]
