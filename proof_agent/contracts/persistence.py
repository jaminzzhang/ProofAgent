from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, cast

from pydantic import Field, field_serializer, field_validator, model_validator

from proof_agent.contracts._base import FrozenDict, FrozenModel, freeze_value
from proof_agent.contracts.agent_configuration import (
    ActiveAgentVersion,
    DraftAgent,
    FormalProductionAgentPublicationCommandReceipt,
    FormalProductionAgentPublicationCommandState,
    KnowledgeSource,
    PublishedAgentVersion,
)
from proof_agent.contracts.dashboard import RunPurpose
from proof_agent.contracts.memory import MemoryCandidate, MemoryScope
from proof_agent.contracts.receipt import ReceiptOutcome
from proof_agent.contracts.run_execution import RunLifecycleState as RunLifecycleState


class PersistenceConflictError(RuntimeError):
    """Optimistic-concurrency conflict reported without leaking adapter details."""

    def __init__(
        self,
        *,
        resource_type: str,
        resource_id: str,
        expected_revision: int,
        actual_revision: int | None,
    ) -> None:
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision
        super().__init__(
            f"{resource_type} {resource_id!r} revision conflict: "
            f"expected {expected_revision}, actual {actual_revision}"
        )


class PersistencePointerConflictError(RuntimeError):
    """A conditional active-pointer update observed a different exact version."""

    def __init__(
        self,
        *,
        resource_type: str,
        resource_id: str,
        expected_pointer: str | None,
        actual_pointer: str | None,
    ) -> None:
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.expected_pointer = expected_pointer
        self.actual_pointer = actual_pointer
        super().__init__(
            f"{resource_type} {resource_id!r} pointer conflict: "
            f"expected {expected_pointer!r}, actual {actual_pointer!r}"
        )


class PersistenceNotFoundError(LookupError):
    """Required authoritative state was not found."""

    def __init__(self, *, resource_type: str, resource_id: str) -> None:
        self.resource_type = resource_type
        self.resource_id = resource_id
        super().__init__(f"{resource_type} {resource_id!r} was not found")


class PersistenceInvariantError(RuntimeError):
    """An adapter returned state that violates a persistence contract."""


class PersistenceIdempotencyConflictError(RuntimeError):
    """One idempotency scope was reused for a different canonical request."""


class AgentDraftRecord(FrozenModel):
    """A Draft Agent plus its adapter-neutral optimistic revision."""

    draft: DraftAgent
    revision: int = Field(ge=1)


class KnowledgeSourceRecord(FrozenModel):
    """A Knowledge Source plus its adapter-neutral optimistic revision."""

    source: KnowledgeSource
    revision: int = Field(ge=1)


class ActiveAgentPointerExpectation(FrozenModel):
    """Optional exact CAS precondition for replacing an Agent activation pointer."""

    version_id: str | None


class AgentActivationRecord(FrozenModel):
    """An existing Published Agent Version activation guarded by exact pointer CAS."""

    activation: ActiveAgentVersion
    active_pointer_expectation: ActiveAgentPointerExpectation

    @model_validator(mode="after")
    def require_matching_rollback_origin(self) -> "AgentActivationRecord":
        if self.activation.rollback_from_version_id != self.active_pointer_expectation.version_id:
            raise ValueError("activation rollback origin must match active pointer expectation")
        return self


class AgentPublicationRecord(FrozenModel):
    """The immutable version and active pointer committed in one transaction."""

    version: PublishedAgentVersion
    activation: ActiveAgentVersion
    draft_revision: int = Field(ge=1)
    active_pointer_expectation: ActiveAgentPointerExpectation | None = None

    @model_validator(mode="after")
    def require_matching_identities(self) -> "AgentPublicationRecord":
        if self.activation.agent_id != self.version.agent_id:
            raise ValueError("activation agent_id must match published version")
        if self.activation.version_id != self.version.version_id:
            raise ValueError("activation version_id must match published version")
        formal_evidence = self.version.formal_production_evidence
        if formal_evidence is not None:
            if formal_evidence.source_draft_revision != self.draft_revision:
                raise ValueError("formal evidence Draft revision must match publication")
            if self.active_pointer_expectation is None:
                raise ValueError("formal publication requires an Active pointer expectation")
            if (
                self.activation.activated_at != self.version.published_at
                or self.activation.activated_by != self.version.published_by
                or self.activation.rollback_from_version_id is not None
            ):
                raise ValueError("formal publication activation must match publication facts")
        return self


class FormalProductionAgentPublicationCommandRecord(FrozenModel):
    """Internal idempotency identity paired with its trace-safe public receipt."""

    actor_subject: str = Field(min_length=1, max_length=255)
    idempotency_key: str = Field(min_length=1, max_length=128)
    receipt: FormalProductionAgentPublicationCommandReceipt
    execution_claim: FormalProductionAgentPublicationExecutionClaim | None = None
    candidate_checkpoint: FormalProductionAgentPublicationCandidateCheckpoint | None = None


class FormalProductionAgentPublicationExecutionClaim(FrozenModel):
    """Internal fenced lease for one formal-publication execution attempt."""

    fencing_token: int = Field(strict=True, ge=1)
    owner_id: str = Field(min_length=1, max_length=128)
    lease_expires_at: str = Field(min_length=1)


class FormalProductionAgentPublicationCandidateCheckpoint(FrozenModel):
    """Immutable candidate identity frozen before publication side effects."""

    formal_candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    knowledge_release_candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    checkpointed_at: str = Field(min_length=1)


class FormalProductionAgentPublicationCommandReservation(FrozenModel):
    """Result of atomically reserving an actor-scoped idempotency key."""

    record: FormalProductionAgentPublicationCommandRecord
    created: bool
    acquired: bool


def complete_formal_publication_command_success(
    record: FormalProductionAgentPublicationCommandRecord,
    publication: AgentPublicationRecord,
) -> FormalProductionAgentPublicationCommandRecord:
    """Build the exact terminal command record for one committed publication."""

    evidence = publication.version.formal_production_evidence
    if evidence is None:
        raise ValueError("formal command success requires formal publication evidence")
    receipt = record.receipt
    if (
        receipt.state is not FormalProductionAgentPublicationCommandState.IN_PROGRESS
        or receipt.agent_id != publication.version.agent_id
        or receipt.draft_id != publication.version.source_draft_id
        or receipt.draft_revision != publication.draft_revision
    ):
        raise ValueError("formal command identity must match publication")
    return record.model_copy(
        update={
            "receipt": receipt.model_copy(
                update={
                    "state": FormalProductionAgentPublicationCommandState.SUCCEEDED,
                    "completed_at": publication.version.published_at,
                    "published_version_id": publication.version.version_id,
                    "validation_run_id": publication.version.validation_run_id,
                    "release_reference_id": evidence.release_reference.release_reference_id,
                    "published_at": publication.version.published_at,
                }
            )
        }
    )


class RunMetadataRecord(FrozenModel):
    """Trace-safe transactional Run metadata with no raw request or artifact bytes."""

    run_id: str
    state: RunLifecycleState
    state_version: int = Field(ge=1)
    run_purpose: RunPurpose = RunPurpose.PRODUCTION
    agent_id: str
    agent_version_id: str
    submitted_by: str
    created_at: str
    updated_at: str
    outcome: ReceiptOutcome | None = None
    error_code: str | None = None


class RunAttemptMetadataRecord(FrozenModel):
    """Trace-safe Attempt metadata for transaction-scoped conditional transitions."""

    attempt_id: str
    run_id: str
    attempt_number: int = Field(ge=1)
    state: RunLifecycleState
    state_version: int = Field(ge=1)
    fencing_token: int = Field(ge=1)
    lease_owner: str | None = None
    lease_expires_at: str | None = None
    created_at: str
    updated_at: str

    @model_validator(mode="after")
    def require_complete_lease(self) -> "RunAttemptMetadataRecord":
        if (self.lease_owner is None) is not (self.lease_expires_at is None):
            raise ValueError("Attempt lease owner and expiry must be set together")
        return self


class CaseMemoryAdmission(FrozenModel):
    """Initial-production admission command for bounded PostgreSQL Case Memory."""

    candidate: MemoryCandidate
    admitted_at: str

    @model_validator(mode="after")
    def enforce_initial_production_boundary(self) -> "CaseMemoryAdmission":
        if self.candidate.scope is not MemoryScope.CASE:
            raise ValueError("initial production admits Case Memory only")
        if not self.candidate.case_id.strip():
            raise ValueError("Case Memory requires a case_id")
        if self.candidate.subject_ref.strip():
            raise ValueError("Case Memory cannot bind an operator or customer subject")
        admitted_at = _parse_utc_timestamp(self.admitted_at)
        expires_at = _parse_utc_timestamp(self.candidate.expires_at)
        if expires_at <= admitted_at:
            raise ValueError("Case Memory expiry must be later than admission")
        if expires_at > admitted_at + timedelta(days=30):
            raise ValueError("Case Memory retention cannot exceed 30 days")
        return self


def _parse_utc_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")
    return parsed


class AuditCategory(str, Enum):
    """Retention-compatible audit event families."""

    CONFIGURATION = "configuration"
    SECURITY = "security"
    RUN = "run"
    OPERATIONS = "operations"


class AuditOutcome(str, Enum):
    """Trace-safe result of the audited operation."""

    SUCCEEDED = "succeeded"
    DENIED = "denied"
    FAILED = "failed"


class AuditActorFacts(FrozenModel):
    """Trusted identity projection captured at an audited backend boundary."""

    subject: str
    identity_provider: str
    session_id: str
    permissions: tuple[str, ...] = Field(default_factory=tuple)
    matched_groups: tuple[str, ...] = Field(default_factory=tuple)


class AuditMetadataRecord(FrozenModel):
    """Append-only trace-safe audit metadata; raw payloads and secrets are forbidden."""

    audit_id: str
    category: AuditCategory
    event_type: str
    outcome: AuditOutcome
    actor: AuditActorFacts
    occurred_at: str
    target_type: str
    target_id: str
    metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("metadata", mode="after")
    @classmethod
    def validate_and_freeze_metadata(cls, value: Any) -> Mapping[str, Any]:
        forbidden = _find_forbidden_audit_key(value)
        if forbidden is not None:
            raise ValueError(f"audit metadata cannot contain {forbidden!r}")
        return cast(Mapping[str, Any], freeze_value(value))

    @field_serializer("metadata")
    def serialize_metadata(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], _plain_value(value))


_FORBIDDEN_AUDIT_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "chain_of_thought",
        "password",
        "provider_response",
        "raw_context",
        "raw_payload",
        "raw_prompt",
        "refresh_token",
        "secret",
    }
)


def _find_forbidden_audit_key(value: Any) -> str | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in _FORBIDDEN_AUDIT_KEYS:
                return normalized
            nested = _find_forbidden_audit_key(item)
            if nested is not None:
                return nested
    elif isinstance(value, list | tuple):
        for item in value:
            nested = _find_forbidden_audit_key(item)
            if nested is not None:
                return nested
    return None


def _plain_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain_value(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value
