from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from proof_agent.contracts._base import StrictFrozenModel
from proof_agent.contracts.run_execution import RoleActivationState


class ProductionWorkerRole(StrEnum):
    """Production worker roles with one database-authoritative active slot."""

    RUN_EXECUTOR = "run_executor"
    KNOWLEDGE_WORKER = "knowledge_worker"


class WorkerRoleActivation(StrictFrozenModel):
    """Fenced ownership lease for one production worker role."""

    role: ProductionWorkerRole
    slot: int = Field(ge=1, le=2)
    state: RoleActivationState
    activation_epoch: int = Field(ge=0)
    owner_id: str | None = Field(default=None, min_length=1, max_length=255)
    heartbeat_at: datetime | None = None
    lease_expires_at: datetime | None = None
    updated_at: datetime

    @model_validator(mode="after")
    def validate_ownership_lease(self) -> Self:
        timestamps = (self.heartbeat_at, self.lease_expires_at, self.updated_at)
        if any(value is not None and value.utcoffset() is None for value in timestamps):
            raise ValueError("Worker role timestamps must be timezone-aware")
        is_owned = self.state in {
            RoleActivationState.ACTIVE,
            RoleActivationState.DRAINING,
        }
        has_complete_lease = (
            self.owner_id is not None
            and self.heartbeat_at is not None
            and self.lease_expires_at is not None
        )
        if is_owned is not has_complete_lease:
            raise ValueError("An owned worker role requires one complete lease")
        if not is_owned and any(
            value is not None
            for value in (self.owner_id, self.heartbeat_at, self.lease_expires_at)
        ):
            raise ValueError("A standby worker role cannot retain an ownership lease")
        if (
            self.heartbeat_at is not None
            and self.lease_expires_at is not None
            and self.lease_expires_at <= self.heartbeat_at
        ):
            raise ValueError("Worker role lease expiry must follow its heartbeat")
        return self

    def is_live(self, *, at: datetime) -> bool:
        if at.utcoffset() is None:
            raise ValueError("Worker role liveness time must be timezone-aware")
        return bool(
            self.state in {RoleActivationState.ACTIVE, RoleActivationState.DRAINING}
            and self.lease_expires_at is not None
            and at < self.lease_expires_at
        )


__all__ = ["ProductionWorkerRole", "WorkerRoleActivation"]
