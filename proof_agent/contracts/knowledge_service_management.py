"""Browser-safe projections for Knowledge Source Service management through the BFF."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal, Self, cast
from urllib.parse import urlsplit

from pydantic import (
    AwareDatetime,
    ConfigDict,
    Field,
    StringConstraints,
    computed_field,
    field_serializer,
    field_validator,
    model_validator,
)

from proof_agent.contracts._base import StrictFrozenModel, freeze_value


KnowledgeServiceIdentifier = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    ),
]
KnowledgeServiceSha256Digest = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^sha256:[0-9a-f]{64}$"),
]
KnowledgeServiceBoundedText = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=512),
]
KnowledgeServiceOperatorIdentifier = Annotated[
    str,
    StringConstraints(
        strict=True,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$",
    ),
]
KnowledgeServiceStructuredValueType = Literal[
    "string",
    "integer",
    "decimal",
    "boolean",
    "date",
    "datetime",
    "null",
]


class _SensitiveManagementInput(StrictFrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class KnowledgeServiceVersionedSecretHandleInput(_SensitiveManagementInput):
    handle_id: KnowledgeServiceIdentifier = Field(repr=False)
    version: int = Field(strict=True, ge=1)


class KnowledgeServiceHttpSnapshotConfigurationInput(_SensitiveManagementInput):
    kind: Literal["http_json"]
    endpoint: str = Field(min_length=1, max_length=2048, repr=False)
    credential: KnowledgeServiceVersionedSecretHandleInput | None = Field(
        default=None,
        repr=False,
    )
    egress_policy_id: KnowledgeServiceIdentifier = Field(repr=False)
    trust_root_id: KnowledgeServiceIdentifier = Field(repr=False)
    max_response_bytes: int = Field(strict=True, ge=1, le=64 * 1024 * 1024)

    @field_validator("endpoint")
    @classmethod
    def require_credential_free_https_endpoint(cls, value: str) -> str:
        try:
            parsed = urlsplit(value)
            port = parsed.port
            valid = (
                parsed.scheme == "https"
                and bool(parsed.hostname)
                and parsed.username is None
                and parsed.password is None
                and parsed.path.startswith("/")
                and parsed.path != "/"
                and not parsed.query
                and not parsed.fragment
                and (port is None or port > 0)
                and "\\" not in value
                and not any(character.isspace() or ord(character) < 32 for character in value)
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("HTTP snapshot endpoint is invalid")
        return value


class KnowledgeServiceConnectionProfileDraft(_SensitiveManagementInput):
    knowledge_space_id: KnowledgeServiceIdentifier
    knowledge_source_id: KnowledgeServiceIdentifier
    configuration: KnowledgeServiceHttpSnapshotConfigurationInput = Field(repr=False)


class KnowledgeServiceConnectionProfileProjection(StrictFrozenModel):
    schema_version: Literal["knowledge-service-connection-profile.v1"] = (
        "knowledge-service-connection-profile.v1"
    )
    connection_profile_id: KnowledgeServiceIdentifier
    revision: int = Field(strict=True, ge=1)
    knowledge_space_id: KnowledgeServiceIdentifier
    knowledge_source_id: KnowledgeServiceIdentifier
    connector_kind: Literal["http_json"]
    configuration_digest: KnowledgeServiceSha256Digest
    state: Literal["draft", "validated", "published"]
    updated_at: AwareDatetime


class KnowledgeServiceConnectionProfileRevisionCommand(_SensitiveManagementInput):
    expected_revision: int = Field(strict=True, ge=1)


class KnowledgeServiceReviseConnectionProfileRequest(
    KnowledgeServiceConnectionProfileRevisionCommand
):
    draft: KnowledgeServiceConnectionProfileDraft = Field(repr=False)


class KnowledgeServiceSynchronizationProfileReferenceInput(_SensitiveManagementInput):
    connection_profile_id: KnowledgeServiceIdentifier
    revision: int = Field(strict=True, ge=1)


class KnowledgeServiceSynchronizationRequest(_SensitiveManagementInput):
    knowledge_space_id: KnowledgeServiceIdentifier
    knowledge_source_id: KnowledgeServiceIdentifier
    connection_profile: KnowledgeServiceSynchronizationProfileReferenceInput
    display_filename: KnowledgeServiceBoundedText
    record_path: tuple[KnowledgeServiceBoundedText, ...] = Field(
        default_factory=tuple,
        max_length=8,
    )
    field_types: Mapping[KnowledgeServiceBoundedText, KnowledgeServiceStructuredValueType] = Field(
        min_length=1,
        max_length=256,
    )

    @field_validator("field_types", mode="after")
    @classmethod
    def freeze_field_types(
        cls,
        value: Mapping[str, KnowledgeServiceStructuredValueType],
    ) -> Mapping[str, KnowledgeServiceStructuredValueType]:
        return cast(
            Mapping[str, KnowledgeServiceStructuredValueType],
            freeze_value(value),
        )

    @field_serializer("field_types")
    def serialize_field_types(
        self,
        value: Mapping[str, KnowledgeServiceStructuredValueType],
    ) -> dict[str, KnowledgeServiceStructuredValueType]:
        return dict(value)


class KnowledgeServicePinnedConnectionProfileProjection(StrictFrozenModel):
    connection_profile_id: KnowledgeServiceIdentifier
    revision: int = Field(strict=True, ge=1)
    configuration_digest: KnowledgeServiceSha256Digest


class KnowledgeServiceSynchronizationProblemProjection(StrictFrozenModel):
    code: KnowledgeServiceBoundedText
    retryable: bool
    blocker_codes: tuple[KnowledgeServiceBoundedText, ...] = Field(
        default_factory=tuple,
        max_length=16,
    )


class KnowledgeServiceSynchronizationLinks(StrictFrozenModel):
    self: str = Field(
        min_length=1,
        max_length=512,
        pattern=r"^/api/config/knowledge-service/synchronizations/[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    )


class KnowledgeServiceSynchronizationProjection(StrictFrozenModel):
    schema_version: Literal["knowledge-service-synchronization.v1"] = (
        "knowledge-service-synchronization.v1"
    )
    knowledge_source_synchronization_id: KnowledgeServiceIdentifier
    knowledge_space_id: KnowledgeServiceIdentifier
    knowledge_source_id: KnowledgeServiceIdentifier
    state: Literal["queued", "running", "succeeded", "failed"]
    submitted_at: AwareDatetime
    started_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    materialized_knowledge_source_version_id: KnowledgeServiceIdentifier | None = None
    problem: KnowledgeServiceSynchronizationProblemProjection | None = None
    connection_profile: KnowledgeServicePinnedConnectionProfileProjection
    links: KnowledgeServiceSynchronizationLinks

    @model_validator(mode="after")
    def require_state_specific_fields(self) -> Self:
        if self.state == "queued" and any(
            value is not None
            for value in (
                self.started_at,
                self.completed_at,
                self.materialized_knowledge_source_version_id,
                self.problem,
            )
        ):
            raise ValueError("queued synchronization cannot expose execution fields")
        if self.state == "running" and (
            self.started_at is None
            or self.completed_at is not None
            or self.materialized_knowledge_source_version_id is not None
            or self.problem is not None
        ):
            raise ValueError("running synchronization fields are inconsistent")
        if self.state == "succeeded" and (
            self.started_at is None
            or self.completed_at is None
            or self.materialized_knowledge_source_version_id is None
            or self.problem is not None
        ):
            raise ValueError("succeeded synchronization requires a materialized version")
        if self.state == "failed" and (
            self.started_at is None
            or self.completed_at is None
            or self.materialized_knowledge_source_version_id is not None
            or self.problem is None
        ):
            raise ValueError("failed synchronization requires one safe problem")
        return self


class KnowledgeServiceSynchronizationOutcome(StrictFrozenModel):
    synchronization: KnowledgeServiceSynchronizationProjection
    created: bool


class KnowledgeServiceReadinessProjection(StrictFrozenModel):
    state: Literal["ready", "unavailable"]
    revision: str | None = Field(default=None, min_length=1, max_length=255)
    blockers: tuple[str, ...] = Field(default_factory=tuple, max_length=16)


class KnowledgeServiceSpaceProjection(StrictFrozenModel):
    knowledge_space_id: KnowledgeServiceIdentifier


class KnowledgeServiceSourceProjection(StrictFrozenModel):
    knowledge_space_id: KnowledgeServiceIdentifier
    knowledge_source_id: KnowledgeServiceIdentifier


class KnowledgeServiceBaseProjection(StrictFrozenModel):
    knowledge_space_id: KnowledgeServiceIdentifier
    knowledge_base_id: KnowledgeServiceIdentifier


class KnowledgeServiceExactBaseDraftMember(StrictFrozenModel):
    knowledge_source_id: KnowledgeServiceIdentifier
    selection: Literal["exact"]
    knowledge_source_version_id: KnowledgeServiceIdentifier


class KnowledgeServiceLatestReadyBaseDraftMember(StrictFrozenModel):
    knowledge_source_id: KnowledgeServiceIdentifier
    selection: Literal["latest_ready_at_preparation"]


KnowledgeServiceBaseDraftMember = Annotated[
    KnowledgeServiceExactBaseDraftMember | KnowledgeServiceLatestReadyBaseDraftMember,
    Field(discriminator="selection"),
]


class KnowledgeServiceSaveBaseDraftRequest(StrictFrozenModel):
    expected_revision: int = Field(strict=True, ge=0)
    members: tuple[KnowledgeServiceBaseDraftMember, ...] = Field(min_length=1)

    @field_validator("members")
    @classmethod
    def require_distinct_sources(
        cls,
        value: tuple[KnowledgeServiceBaseDraftMember, ...],
    ) -> tuple[KnowledgeServiceBaseDraftMember, ...]:
        if len({member.knowledge_source_id for member in value}) != len(value):
            raise ValueError("a Base Draft cannot repeat a Source")
        return value


class KnowledgeServiceBaseDraftProjection(StrictFrozenModel):
    schema_version: Literal["knowledge-service-base-draft.v1"] = "knowledge-service-base-draft.v1"
    knowledge_space_id: KnowledgeServiceIdentifier
    knowledge_base_id: KnowledgeServiceIdentifier
    revision: int = Field(strict=True, ge=1)
    draft_digest: KnowledgeServiceSha256Digest
    updated_at: AwareDatetime
    members: tuple[KnowledgeServiceBaseDraftMember, ...] = Field(min_length=1)

    @field_validator("members")
    @classmethod
    def require_distinct_sources(
        cls,
        value: tuple[KnowledgeServiceBaseDraftMember, ...],
    ) -> tuple[KnowledgeServiceBaseDraftMember, ...]:
        if len({member.knowledge_source_id for member in value}) != len(value):
            raise ValueError("a Base Draft cannot repeat a Source")
        return value


class KnowledgeServiceStartReleasePreparationRequest(StrictFrozenModel):
    draft_revision: int = Field(strict=True, ge=1)


class KnowledgeServiceResolvedBaseMember(StrictFrozenModel):
    knowledge_source_id: KnowledgeServiceIdentifier
    knowledge_source_version_id: KnowledgeServiceIdentifier


class KnowledgeServiceBaseVersionProjection(StrictFrozenModel):
    knowledge_space_id: KnowledgeServiceIdentifier
    knowledge_base_id: KnowledgeServiceIdentifier
    knowledge_base_version_id: KnowledgeServiceIdentifier
    members: tuple[KnowledgeServiceResolvedBaseMember, ...] = Field(min_length=1)
    plan_digest: KnowledgeServiceSha256Digest

    @field_validator("members")
    @classmethod
    def require_distinct_sources(
        cls,
        value: tuple[KnowledgeServiceResolvedBaseMember, ...],
    ) -> tuple[KnowledgeServiceResolvedBaseMember, ...]:
        if len({member.knowledge_source_id for member in value}) != len(value):
            raise ValueError("a Base Version cannot repeat a Source")
        return value


class KnowledgeServiceReleasePreparationLinks(StrictFrozenModel):
    self: str = Field(
        min_length=1,
        max_length=768,
        pattern=(
            r"^/api/config/knowledge-service/spaces/"
            r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}/bases/"
            r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}/release-preparations/"
            r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
        ),
    )


class KnowledgeServiceReleasePreparationIdentityProjection(StrictFrozenModel):
    schema_version: Literal["knowledge-service-release-preparation.v1"] = (
        "knowledge-service-release-preparation.v1"
    )
    release_preparation_id: KnowledgeServiceIdentifier
    knowledge_space_id: KnowledgeServiceIdentifier
    knowledge_base_id: KnowledgeServiceIdentifier
    draft_revision: int = Field(strict=True, ge=1)
    draft_digest: KnowledgeServiceSha256Digest
    base_version: KnowledgeServiceBaseVersionProjection
    submitted_at: AwareDatetime
    links: KnowledgeServiceReleasePreparationLinks

    @model_validator(mode="after")
    def require_exact_base_version_scope(self) -> Self:
        if (
            self.base_version.knowledge_space_id != self.knowledge_space_id
            or self.base_version.knowledge_base_id != self.knowledge_base_id
        ):
            raise ValueError("Release Preparation Base Version scope is inconsistent")
        return self


class KnowledgeServiceQueuedReleasePreparationProjection(
    KnowledgeServiceReleasePreparationIdentityProjection
):
    state: Literal["queued"]


class KnowledgeServiceRunningReleasePreparationProjection(
    KnowledgeServiceReleasePreparationIdentityProjection
):
    state: Literal["running"]


class KnowledgeServiceCancelledReleasePreparationProjection(
    KnowledgeServiceReleasePreparationIdentityProjection
):
    state: Literal["cancelled"]
    cancelled_at: AwareDatetime


class KnowledgeServicePreparedReleasePreparationProjection(
    KnowledgeServiceReleasePreparationIdentityProjection
):
    knowledge_base_release_id: KnowledgeServiceIdentifier
    release_manifest_digest: KnowledgeServiceSha256Digest
    completed_at: AwareDatetime
    expires_at: AwareDatetime


class KnowledgeServiceReadyReleasePreparationProjection(
    KnowledgeServicePreparedReleasePreparationProjection
):
    state: Literal["ready"]


class KnowledgeServiceExpiredReleasePreparationProjection(
    KnowledgeServicePreparedReleasePreparationProjection
):
    state: Literal["expired"]
    expired_at: AwareDatetime


class KnowledgeServiceConsumedReleasePreparationProjection(
    KnowledgeServicePreparedReleasePreparationProjection
):
    state: Literal["consumed"]
    consumed_at: AwareDatetime


class KnowledgeServiceFailedReleasePreparationProjection(
    KnowledgeServiceReleasePreparationIdentityProjection
):
    state: Literal["failed"]
    failure_code: KnowledgeServiceIdentifier
    failed_at: AwareDatetime


KnowledgeServiceReleasePreparationProjection = Annotated[
    KnowledgeServiceQueuedReleasePreparationProjection
    | KnowledgeServiceRunningReleasePreparationProjection
    | KnowledgeServiceCancelledReleasePreparationProjection
    | KnowledgeServiceReadyReleasePreparationProjection
    | KnowledgeServiceExpiredReleasePreparationProjection
    | KnowledgeServiceConsumedReleasePreparationProjection
    | KnowledgeServiceFailedReleasePreparationProjection,
    Field(discriminator="state"),
]


class KnowledgeServicePreparationAuditActorProjection(StrictFrozenModel):
    identity_kind: Literal["kss_service_operator"]
    operator_id: KnowledgeServiceOperatorIdentifier


class KnowledgeServicePreparationAuditSuccessProjection(StrictFrozenModel):
    kind: Literal["success"]
    action: Literal["save_draft", "start", "cancel"]
    actor: KnowledgeServicePreparationAuditActorProjection
    draft_revision: int = Field(strict=True, ge=1)
    draft_digest: KnowledgeServiceSha256Digest
    release_preparation_id: KnowledgeServiceIdentifier | None = None
    knowledge_base_version_id: KnowledgeServiceIdentifier | None = None
    recorded_at: AwareDatetime

    @model_validator(mode="after")
    def require_action_specific_identity(self) -> Self:
        has_preparation_identity = (
            self.release_preparation_id is not None and self.knowledge_base_version_id is not None
        )
        if self.action == "save_draft" and (
            self.release_preparation_id is not None or self.knowledge_base_version_id is not None
        ):
            raise ValueError("Draft audit cannot expose Preparation identity")
        if self.action != "save_draft" and not has_preparation_identity:
            raise ValueError("Preparation audit requires exact Preparation identity")
        return self


class KnowledgeServicePreparationAuditRejectionProjection(StrictFrozenModel):
    kind: Literal["rejection"]
    operation: Literal[
        "save_draft",
        "get_draft",
        "start",
        "get_preparation",
        "cancel",
        "publish",
        "audit",
    ]
    code: KnowledgeServiceIdentifier
    actor: KnowledgeServicePreparationAuditActorProjection | None = None
    release_preparation_id: KnowledgeServiceIdentifier | None = None
    recorded_at: AwareDatetime


KnowledgeServicePreparationAuditEntryProjection = Annotated[
    KnowledgeServicePreparationAuditSuccessProjection
    | KnowledgeServicePreparationAuditRejectionProjection,
    Field(discriminator="kind"),
]


class KnowledgeServicePreparationAuditPageInfo(StrictFrozenModel):
    offset: int = Field(strict=True, ge=0, le=20_000)
    limit: int = Field(strict=True, ge=1, le=100)
    total: int = Field(strict=True, ge=0, le=20_000)
    returned: int = Field(strict=True, ge=0, le=100)
    has_more: bool

    @model_validator(mode="after")
    def require_consistent_page(self) -> Self:
        if self.returned > self.limit:
            raise ValueError("Preparation audit page exceeds its limit")
        expected_returned = min(self.limit, max(self.total - self.offset, 0))
        if self.returned != expected_returned:
            raise ValueError("Preparation audit page is incomplete")
        if self.has_more != (self.offset + self.returned < self.total):
            raise ValueError("Preparation audit continuation state is inconsistent")
        return self


class KnowledgeServicePreparationAuditPage(StrictFrozenModel):
    schema_version: Literal["knowledge-service-preparation-audit.v1"] = (
        "knowledge-service-preparation-audit.v1"
    )
    knowledge_space_id: KnowledgeServiceIdentifier
    knowledge_base_id: KnowledgeServiceIdentifier
    entries: tuple[KnowledgeServicePreparationAuditEntryProjection, ...] = Field(max_length=100)
    page: KnowledgeServicePreparationAuditPageInfo

    @model_validator(mode="after")
    def require_ordered_bounded_entries(self) -> Self:
        if self.page.returned != len(self.entries):
            raise ValueError("Preparation audit page count is inconsistent")
        if tuple(entry.recorded_at for entry in self.entries) != tuple(
            sorted(entry.recorded_at for entry in self.entries)
        ):
            raise ValueError("Preparation audit entries are not chronological")
        return self


class KnowledgeServiceSourceVersionProjection(StrictFrozenModel):
    knowledge_space_id: KnowledgeServiceIdentifier
    knowledge_source_id: KnowledgeServiceIdentifier
    knowledge_source_version_id: KnowledgeServiceIdentifier
    source_kind: Literal["document", "dataset"]
    media_type: str = Field(min_length=1, max_length=255)


class KnowledgeServiceReleaseProjection(StrictFrozenModel):
    knowledge_space_id: KnowledgeServiceIdentifier
    knowledge_base_id: KnowledgeServiceIdentifier
    knowledge_base_version_id: KnowledgeServiceIdentifier
    knowledge_base_release_id: KnowledgeServiceIdentifier
    source_version_count: int = Field(ge=1, le=10_000)
    state: Literal["queryable", "deprecated", "retired", "revoked"]


class KnowledgeServiceReleaseDeletionEligibilityProjection(StrictFrozenModel):
    schema_version: Literal["knowledge-service-release-deletion-eligibility.v1"] = (
        "knowledge-service-release-deletion-eligibility.v1"
    )
    knowledge_space_id: KnowledgeServiceIdentifier
    knowledge_base_id: KnowledgeServiceIdentifier
    knowledge_base_release_id: KnowledgeServiceIdentifier
    release_state: Literal["queryable", "deprecated", "retired", "revoked"]
    eligible: bool
    blockers: tuple[
        Literal[
            "release_not_retired",
            "emergency_revocation_incident_retention",
            "release_retirement_history_unavailable",
            "active_release_references_present",
            "artifact_retention_unverified",
            "artifact_retention_blocked",
        ],
        ...,
    ] = Field(max_length=6)
    active_reference_count: int = Field(ge=0)
    deregistered_reference_count: int = Field(ge=0)
    retired_at: AwareDatetime | None
    revoked_at: AwareDatetime | None
    assessed_at: AwareDatetime
    artifact_retention_state: Literal["not_assessed", "unverified", "blocked", "clear"]


class KnowledgeServiceManagementSummary(StrictFrozenModel):
    spaces: int = Field(ge=0)
    sources: int = Field(ge=0)
    bases: int = Field(ge=0)
    source_versions: int = Field(ge=0)
    releases: int = Field(ge=0)


class KnowledgeServiceManagementWorkspace(StrictFrozenModel):
    schema_version: Literal["knowledge-service-management.v1"] = "knowledge-service-management.v1"
    readiness: KnowledgeServiceReadinessProjection
    spaces: tuple[KnowledgeServiceSpaceProjection, ...] = Field(max_length=1_000)
    sources: tuple[KnowledgeServiceSourceProjection, ...] = Field(max_length=10_000)
    bases: tuple[KnowledgeServiceBaseProjection, ...] = Field(max_length=10_000)
    source_versions: tuple[KnowledgeServiceSourceVersionProjection, ...] = Field(max_length=10_000)
    releases: tuple[KnowledgeServiceReleaseProjection, ...] = Field(max_length=10_000)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def summary(self) -> KnowledgeServiceManagementSummary:
        return KnowledgeServiceManagementSummary(
            spaces=len(self.spaces),
            sources=len(self.sources),
            bases=len(self.bases),
            source_versions=len(self.source_versions),
            releases=len(self.releases),
        )


__all__ = [
    "KnowledgeServiceBaseDraftMember",
    "KnowledgeServiceBaseDraftProjection",
    "KnowledgeServiceBaseProjection",
    "KnowledgeServiceConnectionProfileDraft",
    "KnowledgeServiceConnectionProfileProjection",
    "KnowledgeServiceConnectionProfileRevisionCommand",
    "KnowledgeServiceHttpSnapshotConfigurationInput",
    "KnowledgeServiceIdentifier",
    "KnowledgeServiceManagementSummary",
    "KnowledgeServiceManagementWorkspace",
    "KnowledgeServicePreparationAuditPage",
    "KnowledgeServiceReadinessProjection",
    "KnowledgeServiceReleaseDeletionEligibilityProjection",
    "KnowledgeServiceReleaseProjection",
    "KnowledgeServiceReleasePreparationProjection",
    "KnowledgeServiceReviseConnectionProfileRequest",
    "KnowledgeServiceSaveBaseDraftRequest",
    "KnowledgeServiceSourceProjection",
    "KnowledgeServiceSourceVersionProjection",
    "KnowledgeServiceSpaceProjection",
    "KnowledgeServiceStartReleasePreparationRequest",
    "KnowledgeServiceSynchronizationOutcome",
    "KnowledgeServiceSynchronizationProblemProjection",
    "KnowledgeServiceSynchronizationProfileReferenceInput",
    "KnowledgeServiceSynchronizationProjection",
    "KnowledgeServiceSynchronizationRequest",
    "KnowledgeServiceVersionedSecretHandleInput",
]
