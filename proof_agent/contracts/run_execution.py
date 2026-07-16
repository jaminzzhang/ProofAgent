from __future__ import annotations

from datetime import datetime
from enum import StrEnum
import hashlib
import json
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from proof_agent.contracts._base import StrictFrozenModel
from proof_agent.contracts.dashboard import RunPurpose
from proof_agent.contracts.insurance_authorization import InstitutionAuthorizationContext
from proof_agent.contracts.receipt import ReceiptOutcome


_UUID_PATTERN = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_SHA256_PATTERN = r"^[0-9a-f]{64}$"


class RunLifecycleState(StrEnum):
    """Durable state controlled by the PostgreSQL Run authority."""

    QUEUED = "queued"
    RUNNING = "running"
    FINALIZING = "finalizing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {
            RunLifecycleState.SUCCEEDED,
            RunLifecycleState.FAILED,
            RunLifecycleState.TIMED_OUT,
            RunLifecycleState.CANCELLED,
        }


_ALLOWED_TRANSITIONS = frozenset(
    {
        (RunLifecycleState.QUEUED, RunLifecycleState.RUNNING),
        (RunLifecycleState.QUEUED, RunLifecycleState.CANCELLED),
        (RunLifecycleState.RUNNING, RunLifecycleState.FINALIZING),
        (RunLifecycleState.RUNNING, RunLifecycleState.CANCEL_REQUESTED),
        (RunLifecycleState.RUNNING, RunLifecycleState.FAILED),
        (RunLifecycleState.RUNNING, RunLifecycleState.TIMED_OUT),
        (RunLifecycleState.FINALIZING, RunLifecycleState.SUCCEEDED),
        (RunLifecycleState.FINALIZING, RunLifecycleState.CANCEL_REQUESTED),
        (RunLifecycleState.FINALIZING, RunLifecycleState.FAILED),
        (RunLifecycleState.FINALIZING, RunLifecycleState.TIMED_OUT),
        (RunLifecycleState.CANCEL_REQUESTED, RunLifecycleState.CANCELLED),
        (RunLifecycleState.CANCEL_REQUESTED, RunLifecycleState.FAILED),
        (RunLifecycleState.CANCEL_REQUESTED, RunLifecycleState.TIMED_OUT),
    }
)


def assert_run_transition(source: RunLifecycleState, target: RunLifecycleState) -> None:
    if (source, target) not in _ALLOWED_TRANSITIONS:
        raise ValueError(f"Run transition is not allowed: {source.value} -> {target.value}")


class RunFailureCode(StrEnum):
    EXECUTOR_LOST = "PA_EXECUTOR_LOST"
    SNAPSHOT_INVALID = "PA_SNAPSHOT_INVALID"
    DEADLINE_EXCEEDED = "PA_DEADLINE_EXCEEDED"
    EXECUTION_FAILED = "PA_EXECUTION_FAILED"
    FINALIZATION_FAILED = "PA_FINALIZATION_FAILED"
    ARTIFACT_INTEGRITY = "PA_ARTIFACT_INTEGRITY"
    CANCELLED = "PA_CANCELLED"


class RunFailure(StrictFrozenModel):
    code: RunFailureCode
    safe_detail: str | None = Field(default=None, min_length=1, max_length=256)

    @field_validator("safe_detail")
    @classmethod
    def reject_control_characters(cls, value: str | None) -> str | None:
        if value is not None and (
            value.strip() != value or any(ord(char) < 32 for char in value)
        ):
            raise ValueError("Run failure detail is not trace-safe")
        return value


class RunRequest(StrictFrozenModel):
    contract_version: Literal["proofagent.run-execution.v1"] = (
        "proofagent.run-execution.v1"
    )
    run_id: str = Field(pattern=_UUID_PATTERN)
    operator_subject: str = Field(min_length=1, max_length=255)
    idempotency_key: str = Field(min_length=1, max_length=128)
    run_purpose: RunPurpose = RunPurpose.PRODUCTION
    agent_id: str = Field(min_length=1, max_length=255)
    agent_version_id: str = Field(pattern=_UUID_PATTERN)
    question: str = Field(min_length=1, max_length=32_768)
    allow_untrusted_web_supplement: bool = False
    conversation_id: str | None = Field(default=None, pattern=_UUID_PATTERN)
    conversation_turn_count: int | None = Field(default=None, ge=0)
    permission_mapping_version_id: str = Field(pattern=_UUID_PATTERN)
    permission_epoch: int = Field(ge=1)
    institution_authorization: InstitutionAuthorizationContext = Field(
        default_factory=InstitutionAuthorizationContext
    )
    submitted_at: datetime

    @field_validator(
        "operator_subject", "idempotency_key", "agent_id", "question"
    )
    @classmethod
    def reject_unsafe_text(cls, value: str) -> str:
        if value.strip() != value or "\x00" in value:
            raise ValueError("Run request text is invalid")
        return value

    @field_validator("submitted_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("Run request timestamp must be timezone-aware")
        return value

    def canonical_sha256(self) -> str:
        payload = self.model_dump(
            mode="json",
            exclude={"run_id", "submitted_at"},
        )
        return _canonical_mapping_sha256(payload)

    @property
    def institution_authorization_sha256(self) -> str:
        return _canonical_mapping_sha256(
            self.institution_authorization.model_dump(mode="json")
        )

    @model_validator(mode="after")
    def validate_conversation_snapshot(self) -> Self:
        if self.conversation_id is None and self.conversation_turn_count is not None:
            raise ValueError("Conversation turn count requires a conversation identity")
        return self


class RunExecutionSnapshot(StrictFrozenModel):
    contract_version: Literal["proofagent.run-execution.v1"] = (
        "proofagent.run-execution.v1"
    )
    run_id: str = Field(pattern=_UUID_PATTERN)
    attempt_id: str = Field(pattern=_UUID_PATTERN)
    attempt_number: int = Field(ge=1)
    release_id: str = Field(min_length=1, max_length=128)
    image_digest: str = Field(pattern=_SHA256_PATTERN)
    agent_id: str = Field(min_length=1, max_length=255)
    agent_version_id: str = Field(pattern=_UUID_PATTERN)
    agent_configuration_sha256: str = Field(pattern=_SHA256_PATTERN)
    knowledge_configuration_sha256: str = Field(pattern=_SHA256_PATTERN)
    model_configuration_sha256: str = Field(pattern=_SHA256_PATTERN)
    egress_policy_version_id: str = Field(pattern=_UUID_PATTERN)
    egress_policy_sha256: str = Field(pattern=_SHA256_PATTERN)
    permission_mapping_version_id: str = Field(pattern=_UUID_PATTERN)
    permission_mapping_sha256: str = Field(pattern=_SHA256_PATTERN)
    permission_epoch: int = Field(ge=1)
    institution_authorization_sha256: str = Field(pattern=_SHA256_PATTERN)
    tool_configuration_sha256: str = Field(pattern=_SHA256_PATTERN)
    secret_handle_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=64)
    frozen_at: datetime

    @field_validator("secret_handle_ids")
    @classmethod
    def validate_secret_handles(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)) or value != tuple(sorted(value)):
            raise ValueError("Secret Handles must be unique and sorted")
        if any(
            not handle
            or len(handle) > 255
            or handle.strip() != handle
            or any(ord(char) < 33 for char in handle)
            for handle in value
        ):
            raise ValueError("Secret Handle identifier is invalid")
        return value

    @field_validator("frozen_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("Run snapshot timestamp must be timezone-aware")
        return value

    def canonical_sha256(self) -> str:
        return canonical_contract_sha256(self)


class RunResultAvailability(StrictFrozenModel):
    result_available: bool = False
    artifact_manifest_id: str | None = Field(default=None, pattern=_UUID_PATTERN)
    receipt_outcome: ReceiptOutcome | None = None

    @model_validator(mode="after")
    def require_exact_manifest_visibility(self) -> Self:
        if self.result_available is not (self.artifact_manifest_id is not None):
            raise ValueError("Result visibility requires exactly one artifact manifest")
        if not self.result_available and self.receipt_outcome is not None:
            raise ValueError("Unavailable result cannot expose a receipt outcome")
        return self


class RunQueueRecord(StrictFrozenModel):
    request: RunRequest
    request_sha256: str = Field(pattern=_SHA256_PATTERN)
    state: RunLifecycleState
    state_version: int = Field(ge=1)
    result: RunResultAvailability = Field(default_factory=RunResultAvailability)
    failure: RunFailure | None = None
    enqueued_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime

    @model_validator(mode="after")
    def validate_queue_record(self) -> Self:
        timestamps = (
            self.enqueued_at,
            self.started_at,
            self.completed_at,
            self.updated_at,
        )
        if any(value is not None and value.utcoffset() is None for value in timestamps):
            raise ValueError("Run queue timestamps must be timezone-aware")
        if self.request_sha256 != self.request.canonical_sha256():
            raise ValueError("Run request digest does not match canonical request")
        if self.enqueued_at != self.request.submitted_at:
            raise ValueError("Run enqueue time must match submitted time")
        if self.started_at is not None and self.started_at < self.enqueued_at:
            raise ValueError("Run start time cannot precede enqueue")
        if self.completed_at is not None and self.completed_at < self.enqueued_at:
            raise ValueError("Run completion time cannot precede enqueue")
        if self.state.is_terminal is not (self.completed_at is not None):
            raise ValueError("Terminal Run requires exactly one completion timestamp")
        if self.result.result_available and self.state is not RunLifecycleState.SUCCEEDED:
            raise ValueError("Only a succeeded Run can expose a result")
        if self.state is RunLifecycleState.SUCCEEDED and self.failure is not None:
            raise ValueError("Succeeded Run cannot contain a failure")
        if self.state in {RunLifecycleState.FAILED, RunLifecycleState.TIMED_OUT}:
            if self.failure is None:
                raise ValueError("Failed Run requires a stable failure code")
        return self


class RunAttempt(StrictFrozenModel):
    contract_version: Literal["proofagent.run-execution.v1"] = (
        "proofagent.run-execution.v1"
    )
    attempt_id: str = Field(pattern=_UUID_PATTERN)
    run_id: str = Field(pattern=_UUID_PATTERN)
    attempt_number: int = Field(ge=1)
    state: RunLifecycleState
    state_version: int = Field(ge=1)
    claim_token: str = Field(min_length=32, max_length=128)
    fencing_epoch: int = Field(ge=1)
    activation_epoch: int = Field(ge=1)
    executor_id: str = Field(min_length=1, max_length=255)
    heartbeat_at: datetime
    lease_expires_at: datetime
    deadline_at: datetime
    snapshot: RunExecutionSnapshot
    snapshot_sha256: str = Field(pattern=_SHA256_PATTERN)
    result: RunResultAvailability = Field(default_factory=RunResultAvailability)
    failure: RunFailure | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_attempt(self) -> Self:
        times = (
            self.heartbeat_at,
            self.lease_expires_at,
            self.deadline_at,
            self.created_at,
            self.updated_at,
        )
        if any(value.utcoffset() is None for value in times):
            raise ValueError("Run Attempt timestamps must be timezone-aware")
        if self.lease_expires_at <= self.heartbeat_at:
            raise ValueError("Run Attempt lease must follow heartbeat")
        if self.deadline_at <= self.created_at:
            raise ValueError("Run Attempt deadline must follow creation")
        if (
            self.snapshot.run_id != self.run_id
            or self.snapshot.attempt_id != self.attempt_id
            or self.snapshot.attempt_number != self.attempt_number
        ):
            raise ValueError("Run Attempt snapshot identity does not match")
        if self.snapshot_sha256 != self.snapshot.canonical_sha256():
            raise ValueError("Run Attempt snapshot digest does not match")
        if self.result.result_available and self.state is not RunLifecycleState.SUCCEEDED:
            raise ValueError("Only a succeeded Run Attempt can expose a result")
        if self.state is RunLifecycleState.SUCCEEDED and self.failure is not None:
            raise ValueError("Succeeded Run Attempt cannot contain a failure")
        if self.state in {RunLifecycleState.FAILED, RunLifecycleState.TIMED_OUT}:
            if self.failure is None:
                raise ValueError("Failed Run Attempt requires a stable failure code")
        return self


class RunClaim(StrictFrozenModel):
    run_request: RunRequest
    attempt: RunAttempt

    @model_validator(mode="after")
    def require_matching_run(self) -> Self:
        if self.run_request.run_id != self.attempt.run_id:
            raise ValueError("Run claim identities do not match")
        if self.run_request.agent_id != self.attempt.snapshot.agent_id:
            raise ValueError("Run claim Agent identity does not match")
        if self.run_request.agent_version_id != self.attempt.snapshot.agent_version_id:
            raise ValueError("Run claim Agent version does not match")
        return self


class RoleActivationState(StrEnum):
    STANDBY = "standby"
    ACTIVE = "active"
    DRAINING = "draining"


class RoleActivation(StrictFrozenModel):
    slot: int = Field(ge=1, le=2)
    state: RoleActivationState
    activation_epoch: int = Field(ge=1)
    executor_id: str | None = Field(default=None, min_length=1, max_length=255)
    updated_at: datetime

    @model_validator(mode="after")
    def require_active_owner(self) -> Self:
        if (self.state is RoleActivationState.ACTIVE) is not (
            self.executor_id is not None
        ):
            raise ValueError("Only an active role slot has an Executor owner")
        if self.updated_at.utcoffset() is None:
            raise ValueError("Role activation timestamp must be timezone-aware")
        return self


class RunProgress(StrictFrozenModel):
    contract_version: Literal["proofagent.run-execution.v1"] = (
        "proofagent.run-execution.v1"
    )
    run_id: str = Field(pattern=_UUID_PATTERN)
    state: RunLifecycleState
    state_version: int = Field(ge=1)
    event_kind: Literal["state_snapshot", "state_change", "detail"]
    safe_detail_code: str | None = Field(
        default=None, min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$"
    )
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("Run progress timestamp must be timezone-aware")
        return value


def canonical_contract_sha256(model: StrictFrozenModel) -> str:
    return _canonical_mapping_sha256(model.model_dump(mode="json"))


def _canonical_mapping_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "RoleActivation",
    "RoleActivationState",
    "RunAttempt",
    "RunClaim",
    "RunExecutionSnapshot",
    "RunFailure",
    "RunFailureCode",
    "RunLifecycleState",
    "RunProgress",
    "RunQueueRecord",
    "RunRequest",
    "RunResultAvailability",
    "assert_run_transition",
    "canonical_contract_sha256",
]
