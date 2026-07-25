from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from proof_agent.capabilities.persistence.postgres.worker_role_repository import (
    PostgresWorkerRoleRepository,
)
from proof_agent.contracts.worker_roles import (
    ProductionWorkerRole,
    WorkerRoleActivation,
)
from proof_agent.contracts.run_execution import RoleActivationState
from proof_agent.contracts.ports.worker_roles import (
    WorkerRoleLeaseConflictError,
    WorkerRoleLeaseLostError,
)


pytest_plugins = ("postgres_fixtures",)
NOW = datetime(2026, 7, 25, 8, tzinfo=UTC)


def test_worker_role_contract_distinguishes_standby_from_owned_lease() -> None:
    standby = WorkerRoleActivation(
        role=ProductionWorkerRole.RUN_EXECUTOR,
        slot=1,
        state=RoleActivationState.STANDBY,
        activation_epoch=3,
        owner_id=None,
        heartbeat_at=None,
        lease_expires_at=None,
        updated_at=NOW,
    )
    active = standby.model_copy(
        update={
            "state": RoleActivationState.ACTIVE,
            "owner_id": "executor-blue",
            "heartbeat_at": NOW,
            "lease_expires_at": NOW + timedelta(seconds=15),
        }
    )

    assert standby.is_live(at=NOW) is False
    assert active.is_live(at=NOW + timedelta(seconds=14)) is True
    assert active.is_live(at=NOW + timedelta(seconds=15)) is False

    with pytest.raises(ValidationError, match="owned worker role"):
        WorkerRoleActivation(
            **{
                **active.model_dump(mode="python"),
                "owner_id": None,
            }
        )


@pytest.mark.postgres_integration
def test_worker_role_lease_cas_heartbeat_drain_and_release(postgres_engine) -> None:
    repository = PostgresWorkerRoleRepository(postgres_engine)

    active = repository.activate(
        role=ProductionWorkerRole.RUN_EXECUTOR,
        slot=1,
        owner_id="executor-blue",
        expected_epoch=0,
        now=NOW,
        lease_seconds=15,
    )
    renewed = repository.heartbeat(
        active,
        now=NOW + timedelta(seconds=5),
        lease_seconds=15,
    )
    draining = repository.begin_draining(
        renewed,
        now=NOW + timedelta(seconds=6),
    )
    resumed = repository.resume_active(
        draining,
        now=NOW + timedelta(seconds=7),
    )
    draining_again = repository.begin_draining(
        resumed,
        now=NOW + timedelta(seconds=8),
    )
    standby = repository.release(
        draining_again,
        now=NOW + timedelta(seconds=9),
    )

    assert active.activation_epoch == 1
    assert renewed.lease_expires_at == NOW + timedelta(seconds=20)
    assert draining.state is RoleActivationState.DRAINING
    assert draining.owner_id == "executor-blue"
    assert resumed.state is RoleActivationState.ACTIVE
    assert resumed.activation_epoch == active.activation_epoch
    assert standby.state is RoleActivationState.STANDBY
    assert standby.owner_id is None
    assert repository.get(ProductionWorkerRole.RUN_EXECUTOR) == standby


@pytest.mark.postgres_integration
def test_worker_role_activation_is_epoch_cas_and_fences_expired_owner(
    postgres_engine,
) -> None:
    repository = PostgresWorkerRoleRepository(postgres_engine)
    first = repository.activate(
        role=ProductionWorkerRole.KNOWLEDGE_WORKER,
        slot=1,
        owner_id="knowledge-blue",
        expected_epoch=0,
        now=NOW,
        lease_seconds=15,
    )

    with pytest.raises(WorkerRoleLeaseConflictError):
        repository.activate(
            role=ProductionWorkerRole.KNOWLEDGE_WORKER,
            slot=2,
            owner_id="knowledge-green",
            expected_epoch=0,
            now=NOW + timedelta(seconds=1),
            lease_seconds=15,
        )
    with pytest.raises(WorkerRoleLeaseLostError):
        repository.heartbeat(
            first,
            now=NOW + timedelta(seconds=15),
            lease_seconds=15,
        )

    replacement = repository.activate(
        role=ProductionWorkerRole.KNOWLEDGE_WORKER,
        slot=2,
        owner_id="knowledge-green",
        expected_epoch=first.activation_epoch,
        now=NOW + timedelta(seconds=16),
        lease_seconds=15,
    )
    assert replacement.activation_epoch == first.activation_epoch + 1


@pytest.mark.postgres_integration
def test_concurrent_worker_role_activation_has_one_epoch_winner(postgres_engine) -> None:
    def activate(owner: str) -> WorkerRoleActivation | None:
        try:
            return PostgresWorkerRoleRepository(postgres_engine).activate(
                role=ProductionWorkerRole.RUN_EXECUTOR,
                slot=1 if owner.endswith("blue") else 2,
                owner_id=owner,
                expected_epoch=0,
                now=NOW,
                lease_seconds=15,
            )
        except WorkerRoleLeaseConflictError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(activate, ("executor-blue", "executor-green")))

    winners = tuple(result for result in results if result is not None)
    assert len(winners) == 1
    assert winners[0].activation_epoch == 1
