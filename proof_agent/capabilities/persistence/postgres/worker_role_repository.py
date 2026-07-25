from __future__ import annotations

from datetime import datetime, timedelta

import sqlalchemy as sa

from proof_agent.capabilities.persistence.postgres._common import (
    ConnectionSource,
    read_connection,
    write_connection,
)
from proof_agent.capabilities.persistence.postgres.schema import (
    production_worker_role_activations,
)
from proof_agent.contracts.ports.worker_roles import (
    WorkerRoleLeaseConflictError,
    WorkerRoleLeaseLostError,
)
from proof_agent.contracts.run_execution import RoleActivationState
from proof_agent.contracts.worker_roles import (
    ProductionWorkerRole,
    WorkerRoleActivation,
)


_ROLE_LOCK_NAMESPACE = 0x5052574C00000000
_ROLE_LOCK_IDS = {
    ProductionWorkerRole.RUN_EXECUTOR: _ROLE_LOCK_NAMESPACE + 1,
    ProductionWorkerRole.KNOWLEDGE_WORKER: _ROLE_LOCK_NAMESPACE + 2,
}
_MAX_LEASE_SECONDS = 300


class PostgresWorkerRoleRepository:
    """PostgreSQL authority for one fenced ownership lease per worker role."""

    def __init__(self, connection_source: ConnectionSource) -> None:
        self._connection_source = connection_source

    def get(self, role: ProductionWorkerRole) -> WorkerRoleActivation:
        with read_connection(self._connection_source) as connection:
            row = connection.execute(
                sa.select(production_worker_role_activations).where(
                    production_worker_role_activations.c.role == role.value
                )
            ).mappings().one_or_none()
        if row is None:
            raise RuntimeError(f"Worker role authority is not initialized: {role.value}")
        return self._from_row(row)

    def activate(
        self,
        *,
        role: ProductionWorkerRole,
        slot: int,
        owner_id: str,
        expected_epoch: int,
        now: datetime,
        lease_seconds: int,
    ) -> WorkerRoleActivation:
        self._validate_identity(slot=slot, owner_id=owner_id)
        self._validate_time_and_lease(now=now, lease_seconds=lease_seconds)
        if expected_epoch < 0:
            raise ValueError("Expected worker role epoch cannot be negative")
        with write_connection(self._connection_source) as connection:
            self._lock_role(connection, role)
            current = self._locked_current(connection, role)
            if current.activation_epoch != expected_epoch:
                raise WorkerRoleLeaseConflictError(
                    "Worker role activation epoch changed before promotion"
                )
            if current.is_live(at=now):
                raise WorkerRoleLeaseConflictError(
                    "A live worker role lease must drain or expire before promotion"
                )
            activation = WorkerRoleActivation(
                role=role,
                slot=slot,
                state=RoleActivationState.ACTIVE,
                activation_epoch=current.activation_epoch + 1,
                owner_id=owner_id,
                heartbeat_at=now,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                updated_at=now,
            )
            self._write(connection, activation, expected_epoch=current.activation_epoch)
        return activation

    def heartbeat(
        self,
        activation: WorkerRoleActivation,
        *,
        now: datetime,
        lease_seconds: int,
    ) -> WorkerRoleActivation:
        self._validate_time_and_lease(now=now, lease_seconds=lease_seconds)
        if activation.state not in {
            RoleActivationState.ACTIVE,
            RoleActivationState.DRAINING,
        }:
            raise WorkerRoleLeaseLostError("A standby worker role has no lease to renew")
        if activation.heartbeat_at is None or now < activation.heartbeat_at:
            raise ValueError("Worker role heartbeat time cannot move backwards")
        renewed = activation.model_copy(
            update={
                "heartbeat_at": now,
                "lease_expires_at": now + timedelta(seconds=lease_seconds),
                "updated_at": now,
            }
        )
        with write_connection(self._connection_source) as connection:
            updated = connection.execute(
                sa.update(production_worker_role_activations)
                .where(
                    production_worker_role_activations.c.role == activation.role.value,
                    production_worker_role_activations.c.slot == activation.slot,
                    production_worker_role_activations.c.state == activation.state.value,
                    production_worker_role_activations.c.activation_epoch
                    == activation.activation_epoch,
                    production_worker_role_activations.c.owner_id
                    == activation.owner_id,
                    production_worker_role_activations.c.heartbeat_at
                    == activation.heartbeat_at,
                    production_worker_role_activations.c.lease_expires_at
                    == activation.lease_expires_at,
                    production_worker_role_activations.c.lease_expires_at > now,
                )
                .values(
                    heartbeat_at=renewed.heartbeat_at,
                    lease_expires_at=renewed.lease_expires_at,
                    updated_at=now,
                )
            ).rowcount
        if updated != 1:
            raise WorkerRoleLeaseLostError("Worker role lease is expired or fenced")
        return renewed

    def begin_draining(
        self,
        activation: WorkerRoleActivation,
        *,
        now: datetime,
    ) -> WorkerRoleActivation:
        self._require_aware(now)
        if activation.state is not RoleActivationState.ACTIVE:
            raise WorkerRoleLeaseLostError("Only an active worker role can begin draining")
        draining = activation.model_copy(
            update={"state": RoleActivationState.DRAINING, "updated_at": now}
        )
        with write_connection(self._connection_source) as connection:
            updated = connection.execute(
                sa.update(production_worker_role_activations)
                .where(
                    production_worker_role_activations.c.role == activation.role.value,
                    production_worker_role_activations.c.slot == activation.slot,
                    production_worker_role_activations.c.state
                    == RoleActivationState.ACTIVE.value,
                    production_worker_role_activations.c.activation_epoch
                    == activation.activation_epoch,
                    production_worker_role_activations.c.owner_id
                    == activation.owner_id,
                    production_worker_role_activations.c.heartbeat_at
                    == activation.heartbeat_at,
                    production_worker_role_activations.c.lease_expires_at
                    == activation.lease_expires_at,
                    production_worker_role_activations.c.lease_expires_at > now,
                )
                .values(state=RoleActivationState.DRAINING.value, updated_at=now)
            ).rowcount
        if updated != 1:
            raise WorkerRoleLeaseLostError("Worker role lease is expired or fenced")
        return draining

    def resume_active(
        self,
        activation: WorkerRoleActivation,
        *,
        now: datetime,
    ) -> WorkerRoleActivation:
        """Cancel a drain without changing the live owner's fencing epoch."""

        self._require_aware(now)
        if activation.state is not RoleActivationState.DRAINING:
            raise WorkerRoleLeaseLostError("Only a draining worker role can resume")
        active = activation.model_copy(
            update={"state": RoleActivationState.ACTIVE, "updated_at": now}
        )
        with write_connection(self._connection_source) as connection:
            updated = connection.execute(
                sa.update(production_worker_role_activations)
                .where(
                    production_worker_role_activations.c.role == activation.role.value,
                    production_worker_role_activations.c.slot == activation.slot,
                    production_worker_role_activations.c.state
                    == RoleActivationState.DRAINING.value,
                    production_worker_role_activations.c.activation_epoch
                    == activation.activation_epoch,
                    production_worker_role_activations.c.owner_id
                    == activation.owner_id,
                    production_worker_role_activations.c.heartbeat_at
                    == activation.heartbeat_at,
                    production_worker_role_activations.c.lease_expires_at
                    == activation.lease_expires_at,
                    production_worker_role_activations.c.lease_expires_at > now,
                )
                .values(state=RoleActivationState.ACTIVE.value, updated_at=now)
            ).rowcount
        if updated != 1:
            raise WorkerRoleLeaseLostError("Worker role lease is expired or fenced")
        return active

    def release(
        self,
        activation: WorkerRoleActivation,
        *,
        now: datetime,
    ) -> WorkerRoleActivation:
        self._require_aware(now)
        if activation.state not in {
            RoleActivationState.ACTIVE,
            RoleActivationState.DRAINING,
        }:
            raise WorkerRoleLeaseLostError("A standby worker role has no lease to release")
        standby = activation.model_copy(
            update={
                "state": RoleActivationState.STANDBY,
                "owner_id": None,
                "heartbeat_at": None,
                "lease_expires_at": None,
                "updated_at": now,
            }
        )
        with write_connection(self._connection_source) as connection:
            updated = connection.execute(
                sa.update(production_worker_role_activations)
                .where(
                    production_worker_role_activations.c.role == activation.role.value,
                    production_worker_role_activations.c.slot == activation.slot,
                    production_worker_role_activations.c.state == activation.state.value,
                    production_worker_role_activations.c.activation_epoch
                    == activation.activation_epoch,
                    production_worker_role_activations.c.owner_id
                    == activation.owner_id,
                    production_worker_role_activations.c.heartbeat_at
                    == activation.heartbeat_at,
                    production_worker_role_activations.c.lease_expires_at
                    == activation.lease_expires_at,
                )
                .values(
                    state=RoleActivationState.STANDBY.value,
                    owner_id=None,
                    heartbeat_at=None,
                    lease_expires_at=None,
                    updated_at=now,
                )
            ).rowcount
        if updated != 1:
            raise WorkerRoleLeaseLostError("Worker role lease is fenced")
        return standby

    @staticmethod
    def _from_row(row: sa.RowMapping) -> WorkerRoleActivation:
        return WorkerRoleActivation(
            role=ProductionWorkerRole(row["role"]),
            slot=int(row["slot"]),
            state=RoleActivationState(row["state"]),
            activation_epoch=int(row["activation_epoch"]),
            owner_id=row["owner_id"],
            heartbeat_at=row["heartbeat_at"],
            lease_expires_at=row["lease_expires_at"],
            updated_at=row["updated_at"],
        )

    def _locked_current(
        self, connection: sa.Connection, role: ProductionWorkerRole
    ) -> WorkerRoleActivation:
        row = connection.execute(
            sa.select(production_worker_role_activations)
            .where(production_worker_role_activations.c.role == role.value)
            .with_for_update()
        ).mappings().one_or_none()
        if row is None:
            raise RuntimeError(f"Worker role authority is not initialized: {role.value}")
        return self._from_row(row)

    @staticmethod
    def _write(
        connection: sa.Connection,
        activation: WorkerRoleActivation,
        *,
        expected_epoch: int,
    ) -> None:
        updated = connection.execute(
            sa.update(production_worker_role_activations)
            .where(
                production_worker_role_activations.c.role == activation.role.value,
                production_worker_role_activations.c.activation_epoch == expected_epoch,
            )
            .values(
                slot=activation.slot,
                state=activation.state.value,
                activation_epoch=activation.activation_epoch,
                owner_id=activation.owner_id,
                heartbeat_at=activation.heartbeat_at,
                lease_expires_at=activation.lease_expires_at,
                updated_at=activation.updated_at,
            )
        ).rowcount
        if updated != 1:
            raise WorkerRoleLeaseConflictError("Worker role activation CAS failed")

    @staticmethod
    def _lock_role(
        connection: sa.Connection, role: ProductionWorkerRole
    ) -> None:
        connection.execute(
            sa.select(sa.func.pg_advisory_xact_lock(_ROLE_LOCK_IDS[role]))
        )

    @staticmethod
    def _validate_identity(*, slot: int, owner_id: str) -> None:
        if slot not in {1, 2}:
            raise ValueError("Worker role slot must be 1 or 2")
        if not owner_id or owner_id.strip() != owner_id or len(owner_id) > 255:
            raise ValueError("Worker role owner id is invalid")

    @classmethod
    def _validate_time_and_lease(cls, *, now: datetime, lease_seconds: int) -> None:
        cls._require_aware(now)
        if not 1 <= lease_seconds <= _MAX_LEASE_SECONDS:
            raise ValueError("Worker role lease is outside the supported envelope")

    @staticmethod
    def _require_aware(value: datetime) -> None:
        if value.utcoffset() is None:
            raise ValueError("Worker role time must be timezone-aware")


__all__ = ["PostgresWorkerRoleRepository"]
