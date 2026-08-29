"""Management-only Base Drafts and exact, non-queryable preparation plans."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, ConfigDict, Field, StringConstraints, field_validator

from knowledge_source_service.contracts.base import StrictContract
from knowledge_source_service.contracts.results import Sha256Digest


BaseIdentifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")]


class BasePreparationContract(StrictContract):
    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)


class ExactBaseMember(BasePreparationContract):
    knowledge_source_id: BaseIdentifier
    selection: Literal["exact"]
    knowledge_source_version_id: BaseIdentifier


class LatestReadyBaseMember(BasePreparationContract):
    knowledge_source_id: BaseIdentifier
    selection: Literal["latest_ready_at_preparation"]


BaseDraftMember = Annotated[
    ExactBaseMember | LatestReadyBaseMember, Field(discriminator="selection")
]


class BaseDraftContent(BasePreparationContract):
    knowledge_space_id: BaseIdentifier
    knowledge_base_id: BaseIdentifier
    members: tuple[BaseDraftMember, ...] = Field(min_length=1)

    @field_validator("members")
    @classmethod
    def require_distinct_sources(
        cls, value: tuple[BaseDraftMember, ...]
    ) -> tuple[BaseDraftMember, ...]:
        if len({member.knowledge_source_id for member in value}) != len(value):
            raise ValueError("a Base Draft cannot repeat a Source")
        return value


class SaveKnowledgeBaseDraftRequest(BaseDraftContent):
    expected_revision: int = Field(strict=True, ge=0)


class KnowledgeBaseDraft(BaseDraftContent):
    revision: int = Field(strict=True, ge=1)
    draft_digest: Sha256Digest
    updated_at: AwareDatetime


class StartReleasePreparationRequest(BasePreparationContract):
    knowledge_space_id: BaseIdentifier
    knowledge_base_id: BaseIdentifier
    draft_revision: int = Field(strict=True, ge=1)


class ResolvedBaseMember(BasePreparationContract):
    knowledge_source_id: BaseIdentifier
    knowledge_source_version_id: BaseIdentifier


class KnowledgeBaseVersion(BasePreparationContract):
    knowledge_space_id: BaseIdentifier
    knowledge_base_id: BaseIdentifier
    knowledge_base_version_id: BaseIdentifier
    members: tuple[ResolvedBaseMember, ...] = Field(min_length=1)
    plan_digest: Sha256Digest


class ReleasePreparationIdentity(BasePreparationContract):
    """Immutable admission identity shared by resource states."""

    schema_version: Literal["knowledge-release-preparation.v1"] = "knowledge-release-preparation.v1"
    release_preparation_id: BaseIdentifier
    knowledge_space_id: BaseIdentifier
    knowledge_base_id: BaseIdentifier
    draft_revision: int = Field(strict=True, ge=1)
    draft_digest: Sha256Digest
    base_version: KnowledgeBaseVersion
    submitted_at: AwareDatetime


class QueuedReleasePreparation(ReleasePreparationIdentity):
    state: Literal["queued"] = "queued"


class RunningReleasePreparation(ReleasePreparationIdentity):
    state: Literal["running"] = "running"


class CancelledReleasePreparation(ReleasePreparationIdentity):
    state: Literal["cancelled"] = "cancelled"
    cancelled_at: AwareDatetime


class PreparedReleasePreparation(ReleasePreparationIdentity):
    knowledge_base_release_id: BaseIdentifier
    release_manifest_digest: Sha256Digest
    completed_at: AwareDatetime
    expires_at: AwareDatetime


class ReadyReleasePreparation(PreparedReleasePreparation):
    state: Literal["ready"] = "ready"


class ExpiredReleasePreparation(PreparedReleasePreparation):
    state: Literal["expired"] = "expired"
    expired_at: AwareDatetime


class ConsumedReleasePreparation(PreparedReleasePreparation):
    state: Literal["consumed"] = "consumed"
    consumed_at: AwareDatetime


class FailedReleasePreparation(ReleasePreparationIdentity):
    state: Literal["failed"] = "failed"
    failure_code: BaseIdentifier
    failed_at: AwareDatetime


ReleasePreparationResource = Annotated[
    QueuedReleasePreparation
    | RunningReleasePreparation
    | CancelledReleasePreparation
    | ReadyReleasePreparation
    | ExpiredReleasePreparation
    | ConsumedReleasePreparation
    | FailedReleasePreparation,
    Field(discriminator="state"),
]


class PreparationWorkerAuditEntry(BasePreparationContract):
    action: Literal["claimed", "renewed", "taken_over", "ready", "failed"]
    knowledge_space_id: BaseIdentifier
    knowledge_base_id: BaseIdentifier
    release_preparation_id: BaseIdentifier
    worker_id: BaseIdentifier
    fencing_token: int = Field(strict=True, ge=1)
    lease_expires_at: AwareDatetime
    recorded_at: AwareDatetime


class PreparationPublicationAuditEntry(BasePreparationContract):
    action: Literal["expired", "consumed"]
    operator_id: str
    knowledge_space_id: BaseIdentifier
    knowledge_base_id: BaseIdentifier
    release_preparation_id: BaseIdentifier
    knowledge_base_release_id: BaseIdentifier
    release_manifest_digest: Sha256Digest
    recorded_at: AwareDatetime


class BasePreparationAuditEntry(BasePreparationContract):
    action: Literal["save_draft", "start", "cancel"]
    operator_id: str
    knowledge_space_id: BaseIdentifier
    knowledge_base_id: BaseIdentifier
    draft_revision: int = Field(strict=True, ge=1)
    draft_digest: Sha256Digest
    release_preparation_id: BaseIdentifier | None = None
    knowledge_base_version_id: BaseIdentifier | None = None
    recorded_at: AwareDatetime


class BasePreparationRejectionEntry(BasePreparationContract):
    operator_id: str | None = Field(default=None, max_length=256)
    knowledge_space_id: BaseIdentifier | None = None
    knowledge_base_id: BaseIdentifier | None = None
    release_preparation_id: BaseIdentifier | None = None
    operation: Literal["save_draft", "get_draft", "start", "get_preparation", "audit"]
    code: BaseIdentifier
    recorded_at: AwareDatetime


class BasePreparationAuditCollection(BasePreparationContract):
    events: tuple[BasePreparationAuditEntry, ...]
    rejections: tuple[BasePreparationRejectionEntry, ...]
