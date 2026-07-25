from __future__ import annotations

from datetime import datetime
from typing import Protocol

from proof_agent.contracts.worker_roles import (
    ProductionWorkerRole,
    WorkerRoleActivation,
)


class WorkerRoleLeaseConflictError(RuntimeError):
    """The expected activation epoch no longer identifies current authority."""


class WorkerRoleLeaseLostError(RuntimeError):
    """The caller no longer owns a live role lease."""


class WorkerRoleRepository(Protocol):
    def get(self, role: ProductionWorkerRole) -> WorkerRoleActivation: ...

    def activate(
        self,
        *,
        role: ProductionWorkerRole,
        slot: int,
        owner_id: str,
        expected_epoch: int,
        now: datetime,
        lease_seconds: int,
    ) -> WorkerRoleActivation: ...

    def heartbeat(
        self,
        activation: WorkerRoleActivation,
        *,
        now: datetime,
        lease_seconds: int,
    ) -> WorkerRoleActivation: ...

    def begin_draining(
        self,
        activation: WorkerRoleActivation,
        *,
        now: datetime,
    ) -> WorkerRoleActivation: ...

    def resume_active(
        self,
        activation: WorkerRoleActivation,
        *,
        now: datetime,
    ) -> WorkerRoleActivation: ...

    def release(
        self,
        activation: WorkerRoleActivation,
        *,
        now: datetime,
    ) -> WorkerRoleActivation: ...


__all__ = [
    "WorkerRoleLeaseConflictError",
    "WorkerRoleLeaseLostError",
    "WorkerRoleRepository",
]
