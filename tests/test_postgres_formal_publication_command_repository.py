from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import Engine

from proof_agent.capabilities.persistence.postgres.configuration_uow import (
    PostgresConfigurationUnitOfWork,
)
from proof_agent.capabilities.persistence.postgres.formal_publication_command_repository import (
    PostgresFormalProductionAgentPublicationCommandRepository,
)
from proof_agent.contracts import (
    FormalProductionAgentPublicationCommandReceipt,
    FormalProductionAgentPublicationCommandState,
)
from proof_agent.contracts.persistence import (
    FormalProductionAgentPublicationCommandRecord,
    PersistenceIdempotencyConflictError,
)


pytestmark = pytest.mark.postgres_integration
pytest_plugins = ("postgres_fixtures",)


def _record(
    *,
    request_sha256: str = "1" * 64,
) -> FormalProductionAgentPublicationCommandRecord:
    return FormalProductionAgentPublicationCommandRecord(
        actor_subject="release-operator",
        idempotency_key="formal-publish-11",
        receipt=FormalProductionAgentPublicationCommandReceipt(
            command_id="019ba001-1111-7000-8000-000000000805",
            state=FormalProductionAgentPublicationCommandState.IN_PROGRESS,
            agent_id="agent_management_insurance_specialist",
            draft_id="019ba001-1111-7000-8000-000000000101",
            draft_revision=11,
            request_sha256=request_sha256,
            started_at="2026-08-30T13:05:00Z",
        ),
    )


def _succeeded(
    record: FormalProductionAgentPublicationCommandRecord,
) -> FormalProductionAgentPublicationCommandRecord:
    return record.model_copy(
        update={
            "receipt": record.receipt.model_copy(
                update={
                    "state": FormalProductionAgentPublicationCommandState.SUCCEEDED,
                    "completed_at": "2026-08-30T13:06:00Z",
                    "published_version_id": "019ba001-1111-7000-8000-000000000901",
                    "validation_run_id": "validation-run-1",
                    "release_reference_id": "release-reference-1",
                    "published_at": "2026-08-30T13:06:00Z",
                }
            )
        }
    )


def _failed(
    record: FormalProductionAgentPublicationCommandRecord,
) -> FormalProductionAgentPublicationCommandRecord:
    return record.model_copy(
        update={
            "receipt": record.receipt.model_copy(
                update={
                    "state": FormalProductionAgentPublicationCommandState.FAILED,
                    "completed_at": "2026-08-30T13:06:00Z",
                    "failure_code": "online_smoke_unavailable",
                }
            )
        }
    )


def test_postgres_formal_command_reserves_replays_and_never_rebinds(
    postgres_engine: Engine,
) -> None:
    repository = PostgresFormalProductionAgentPublicationCommandRepository(postgres_engine)
    record = _record()

    first = repository.reserve(record)
    replay = repository.reserve(record)

    assert first.created is True
    assert first.record == record
    assert replay.created is False
    assert replay.record == record
    with pytest.raises(PersistenceIdempotencyConflictError):
        repository.reserve(_record(request_sha256="2" * 64))

    succeeded = _succeeded(record)
    assert repository.complete(succeeded) == succeeded
    terminal_replay = repository.reserve(record)
    assert terminal_replay.created is False
    assert terminal_replay.record == succeeded
    assert repository.complete(_failed(record)) == succeeded


def test_postgres_formal_command_completion_obeys_configuration_uow_commit(
    postgres_engine: Engine,
) -> None:
    record = _record()
    with PostgresConfigurationUnitOfWork(postgres_engine) as uow:
        reserved = uow.formal_publication_commands.reserve(record)
        assert reserved.created is True
        uow.commit()

    with PostgresConfigurationUnitOfWork(postgres_engine) as uow:
        assert uow.formal_publication_commands.complete(_failed(record)) == _failed(record)

    repository = PostgresFormalProductionAgentPublicationCommandRepository(postgres_engine)
    after_rollback = repository.reserve(record)
    assert after_rollback.record.receipt.state is (
        FormalProductionAgentPublicationCommandState.IN_PROGRESS
    )

    with PostgresConfigurationUnitOfWork(postgres_engine) as uow:
        assert uow.formal_publication_commands.complete(_succeeded(record)) == _succeeded(record)
        uow.commit()
    assert repository.reserve(record).record == _succeeded(record)


def test_postgres_formal_command_concurrent_reservation_has_one_creator(
    postgres_engine: Engine,
) -> None:
    barrier = Barrier(2)

    def reserve_once() -> bool:
        repository = PostgresFormalProductionAgentPublicationCommandRepository(postgres_engine)
        barrier.wait()
        return repository.reserve(_record()).created

    with ThreadPoolExecutor(max_workers=2) as executor:
        created = tuple(executor.map(lambda _: reserve_once(), range(2)))

    assert sorted(created) == [False, True]
