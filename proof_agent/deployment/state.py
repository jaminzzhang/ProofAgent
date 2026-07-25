"""Immutable state and audit records for fenced Blue/Green deployments."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from enum import StrEnum
from typing import Self
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator, model_validator

from proof_agent.contracts._base import StrictFrozenModel
from proof_agent.release.digests import canonical_json_bytes, sha256_hex


_SUPPORT_ZONE = ZoneInfo("Asia/Shanghai")


class DeploymentSlot(StrEnum):
    BLUE = "blue"
    GREEN = "green"


class DeploymentOutcome(StrEnum):
    DEPLOYED = "deployed"
    ABORTED = "aborted"
    ABORT_FAILED = "abort_failed"
    ROLLED_BACK = "rolled_back"
    ROLLBACK_FAILED = "rollback_failed"


class DeploymentStepStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class DeploymentStepName(StrEnum):
    VALIDATE_PRECHECKS = "validate_prechecks"
    LOCKED_EXPAND_MIGRATION = "locked_expand_migration"
    START_CANDIDATE_STANDBY = "start_candidate_standby"
    CANDIDATE_READINESS = "candidate_readiness"
    ISOLATED_SMOKE = "isolated_smoke"
    BIDIRECTIONAL_QUEUE_CONTRACT = "bidirectional_queue_contract"
    PAUSE_ADMISSION = "pause_admission"
    OLD_WORKERS_DRAINING = "old_workers_draining"
    OLD_CLAIMS_ZERO = "old_claims_zero"
    GATEWAY_SWITCH = "gateway_switch"
    CANDIDATE_ACTIVATION = "candidate_activation"
    STABLE_ORIGIN_SMOKE = "stable_origin_smoke"
    SOAK = "soak"
    STOP_OLD_COMPUTE = "stop_old_compute"
    RESUME_ADMISSION = "resume_admission"
    ABORT_OLD_WORKERS_ACTIVE = "abort_old_workers_active"
    ABORT_CANDIDATE_STANDBY = "abort_candidate_standby"
    ROLLBACK_OLD_API_READINESS = "rollback_old_api_readiness"
    ROLLBACK_GATEWAY = "rollback_gateway"
    ROLLBACK_CANDIDATE_DRAINING = "rollback_candidate_draining"
    ROLLBACK_CANDIDATE_CLAIMS_ZERO = "rollback_candidate_claims_zero"
    ROLLBACK_CANDIDATE_FENCED = "rollback_candidate_fenced"
    ROLLBACK_OLD_ACTIVATION = "rollback_old_activation"
    ROLLBACK_FAIL_LOST_ATTEMPTS = "rollback_fail_lost_attempts"


class CandidateBinding(StrictFrozenModel):
    """Exact, secret-free identity whose digest binds every deployment step."""

    release_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    image_reference: str = Field(min_length=80, max_length=512)
    deployment_compatibility_manifest_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    migration_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_revision: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    )

    @field_validator("image_reference")
    @classmethod
    def require_immutable_image_digest(cls, value: str) -> str:
        if value.strip() != value or any(ord(char) < 33 for char in value):
            raise ValueError("candidate image reference must be trace-safe")
        marker = "@sha256:"
        if value.count(marker) != 1:
            raise ValueError("candidate image reference must contain one sha256 digest")
        name, digest = value.rsplit(marker, 1)
        if (
            not name
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise ValueError("candidate image reference must be immutable")
        return value

    @property
    def binding_sha256(self) -> str:
        return sha256_hex(canonical_json_bytes(self.model_dump(mode="json")))


class BlueGreenDeploymentRequest(StrictFrozenModel):
    binding: CandidateBinding
    old_slot: DeploymentSlot
    candidate_slot: DeploymentSlot
    old_activation_epoch: int = Field(ge=1)
    active_gateway_generation: int = Field(ge=1)
    drain_timeout_seconds: int = Field(default=150, ge=1, le=150)
    soak_seconds: int = Field(default=1800, ge=1800, le=1800)
    admission_pause_authorized: bool = False

    @model_validator(mode="after")
    def require_distinct_slots(self) -> Self:
        if self.old_slot is self.candidate_slot:
            raise ValueError("old and candidate deployment slots must differ")
        return self


class DeploymentStepRecord(StrictFrozenModel):
    name: DeploymentStepName
    status: DeploymentStepStatus
    deployment_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_release_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    started_at: datetime
    completed_at: datetime
    error_code: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    )

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.started_at.utcoffset() is None or self.completed_at.utcoffset() is None:
            raise ValueError("deployment step timestamps must be timezone-aware")
        if self.completed_at < self.started_at:
            raise ValueError("deployment step completion cannot precede its start")
        if (self.status is DeploymentStepStatus.FAILED) is not (
            self.error_code is not None
        ):
            raise ValueError("only failed deployment steps carry an error code")
        return self


class BlueGreenDeploymentResult(StrictFrozenModel):
    outcome: DeploymentOutcome
    deployment_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    steps: tuple[DeploymentStepRecord, ...] = Field(min_length=1)
    gateway_generation: int | None = Field(default=None, ge=1)
    candidate_activation_epoch: int | None = Field(default=None, ge=1)
    switched_at: datetime | None = None
    retention_until: datetime | None = None

    @model_validator(mode="after")
    def validate_binding_and_retention(self) -> Self:
        if any(
            step.deployment_binding_sha256 != self.deployment_binding_sha256
            for step in self.steps
        ):
            raise ValueError("every deployment step must bind the same candidate")
        for timestamp in (self.switched_at, self.retention_until):
            if timestamp is not None and timestamp.utcoffset() is None:
                raise ValueError("deployment result timestamps must be timezone-aware")
        if (self.switched_at is None) is not (self.retention_until is None):
            raise ValueError("a Gateway switch requires a rollback-asset retention deadline")
        if (
            self.switched_at is not None
            and self.retention_until is not None
            and self.retention_until <= self.switched_at
        ):
            raise ValueError("rollback assets must outlive the Gateway switch")
        return self


def rollback_asset_retention_deadline(switched_at: datetime) -> datetime:
    """Return later of switch+24h and next complete weekday support-window end."""

    if switched_at.utcoffset() is None:
        raise ValueError("Gateway switch time must be timezone-aware")
    local = switched_at.astimezone(_SUPPORT_ZONE)
    candidate_day = local.date()
    window_start = datetime.combine(candidate_day, time(9), tzinfo=_SUPPORT_ZONE)
    if candidate_day.weekday() >= 5 or local >= window_start:
        candidate_day += timedelta(days=1)
    while candidate_day.weekday() >= 5:
        candidate_day += timedelta(days=1)
    support_window_end = datetime.combine(
        candidate_day,
        time(18),
        tzinfo=_SUPPORT_ZONE,
    )
    return max(switched_at + timedelta(hours=24), support_window_end)


__all__ = [
    "BlueGreenDeploymentRequest",
    "BlueGreenDeploymentResult",
    "CandidateBinding",
    "DeploymentOutcome",
    "DeploymentSlot",
    "DeploymentStepName",
    "DeploymentStepRecord",
    "DeploymentStepStatus",
    "rollback_asset_retention_deadline",
]
