from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from sqlalchemy import Engine, text

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
    FormalProductionAgentPublicationExecutionClaim,
    FormalProductionAgentPublicationCommandRecord,
    FormalProductionAgentPublicationCommandReservation,
    PersistenceIdempotencyConflictError,
    PersistenceInvariantError,
)


pytestmark = pytest.mark.postgres_integration
pytest_plugins = ("postgres_fixtures",)


def _record(
    *,
    request_sha256: str = "1" * 64,
    owner_id: str = "formal-publisher-process-1",
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
        execution_claim=FormalProductionAgentPublicationExecutionClaim(
            fencing_token=1,
            owner_id=owner_id,
            lease_expires_at="2026-08-30T13:05:30Z",
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

    first = repository.reserve(record, lease_duration=timedelta(seconds=30))
    replay = repository.reserve(record, lease_duration=timedelta(seconds=30))

    assert first.created is True
    assert first.acquired is True
    assert first.record.receipt == record.receipt
    assert first.record.execution_claim is not None
    assert first.record.execution_claim.owner_id == "formal-publisher-process-1"
    assert replay.created is False
    assert replay.acquired is False
    assert replay.record == first.record
    with pytest.raises(PersistenceIdempotencyConflictError):
        repository.reserve(
            _record(request_sha256="2" * 64),
            lease_duration=timedelta(seconds=30),
        )

    succeeded = _succeeded(first.record)
    assert repository.complete(succeeded) == succeeded
    terminal_replay = repository.reserve(record, lease_duration=timedelta(seconds=30))
    assert terminal_replay.created is False
    assert terminal_replay.acquired is False
    assert terminal_replay.record == succeeded
    assert repository.complete(_failed(first.record)) == succeeded


def test_postgres_formal_command_find_owned_is_exact_and_read_only(
    postgres_engine: Engine,
) -> None:
    repository = PostgresFormalProductionAgentPublicationCommandRepository(postgres_engine)
    reserved = repository.reserve(
        _record(),
        lease_duration=timedelta(seconds=30),
    )

    found = repository.find_owned(
        command_id=reserved.record.receipt.command_id,
        actor_subject=reserved.record.actor_subject,
    )

    assert found == reserved.record
    assert (
        repository.find_owned(
            command_id=reserved.record.receipt.command_id,
            actor_subject="another-operator",
        )
        is None
    )
    assert (
        repository.find_owned(
            command_id="019ba001-1111-7000-8000-000000000899",
            actor_subject=reserved.record.actor_subject,
        )
        is None
    )
    replay = repository.reserve(
        _record(),
        lease_duration=timedelta(seconds=30),
    )
    assert replay.acquired is False
    assert replay.record == reserved.record


def test_postgres_formal_command_completion_obeys_configuration_uow_commit(
    postgres_engine: Engine,
) -> None:
    record = _record()
    with PostgresConfigurationUnitOfWork(postgres_engine) as uow:
        reserved = uow.formal_publication_commands.reserve(
            record,
            lease_duration=timedelta(seconds=30),
        )
        assert reserved.created is True
        assert reserved.acquired is True
        uow.commit()

    with PostgresConfigurationUnitOfWork(postgres_engine) as uow:
        assert uow.formal_publication_commands.complete(_failed(reserved.record)) == _failed(
            reserved.record
        )

    repository = PostgresFormalProductionAgentPublicationCommandRepository(postgres_engine)
    after_rollback = repository.reserve(record, lease_duration=timedelta(seconds=30))
    assert after_rollback.record.receipt.state is (
        FormalProductionAgentPublicationCommandState.IN_PROGRESS
    )

    with PostgresConfigurationUnitOfWork(postgres_engine) as uow:
        assert uow.formal_publication_commands.complete(
            _succeeded(after_rollback.record)
        ) == _succeeded(after_rollback.record)
        uow.commit()
    assert repository.reserve(
        record,
        lease_duration=timedelta(seconds=30),
    ).record == _succeeded(after_rollback.record)


def test_postgres_formal_command_concurrent_reservation_has_one_creator(
    postgres_engine: Engine,
) -> None:
    barrier = Barrier(2)

    def reserve_once() -> bool:
        repository = PostgresFormalProductionAgentPublicationCommandRepository(postgres_engine)
        barrier.wait()
        return repository.reserve(
            _record(),
            lease_duration=timedelta(seconds=30),
        ).created

    with ThreadPoolExecutor(max_workers=2) as executor:
        created = tuple(executor.map(lambda _: reserve_once(), range(2)))

    assert sorted(created) == [False, True]


def test_postgres_formal_command_expired_claim_has_one_takeover_and_fences_stale_completion(
    postgres_engine: Engine,
) -> None:
    repository = PostgresFormalProductionAgentPublicationCommandRepository(postgres_engine)
    initial = repository.reserve(
        _record(),
        lease_duration=timedelta(seconds=30),
    )
    assert initial.acquired is True
    checkpointed = repository.checkpoint_candidate(
        initial.record,
        formal_candidate_sha256="2" * 64,
        knowledge_release_candidate_sha256="3" * 64,
    )
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE formal_agent_publication_commands "
                "SET lease_expires_at = clock_timestamp() - interval '1 second' "
                "WHERE command_id = CAST(:command_id AS uuid)"
            ),
            {"command_id": initial.record.receipt.command_id},
        )

    barrier = Barrier(2)

    def take_over(owner_id: str) -> FormalProductionAgentPublicationCommandReservation:
        contender = PostgresFormalProductionAgentPublicationCommandRepository(postgres_engine)
        barrier.wait()
        return contender.reserve(
            _record(owner_id=owner_id),
            lease_duration=timedelta(seconds=30),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        attempts = tuple(
            executor.map(
                take_over,
                ("formal-publisher-process-2", "formal-publisher-process-3"),
            )
        )

    acquired = tuple(item for item in attempts if item.acquired)
    assert len(acquired) == 1
    assert acquired[0].created is False
    assert acquired[0].record.execution_claim is not None
    assert acquired[0].record.execution_claim.fencing_token == 2
    assert acquired[0].record.candidate_checkpoint == checkpointed.candidate_checkpoint
    with pytest.raises(PersistenceInvariantError):
        repository.checkpoint_candidate(
            checkpointed,
            formal_candidate_sha256="2" * 64,
            knowledge_release_candidate_sha256="3" * 64,
        )
    with pytest.raises(PersistenceInvariantError):
        repository.complete(_failed(checkpointed))
    terminal = _succeeded(acquired[0].record)
    assert repository.complete(terminal) == terminal


def test_postgres_formal_command_claims_legacy_in_progress_row_without_execution_claim(
    postgres_engine: Engine,
) -> None:
    repository = PostgresFormalProductionAgentPublicationCommandRepository(postgres_engine)
    initial = repository.reserve(
        _record(),
        lease_duration=timedelta(seconds=30),
    )
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE formal_agent_publication_commands "
                "SET execution_fencing_token = NULL, lease_owner = NULL, "
                "lease_expires_at = NULL "
                "WHERE command_id = CAST(:command_id AS uuid)"
            ),
            {"command_id": initial.record.receipt.command_id},
        )

    recovered = repository.reserve(
        _record(owner_id="formal-publisher-process-2"),
        lease_duration=timedelta(seconds=30),
    )

    assert recovered.created is False
    assert recovered.acquired is True
    assert recovered.record.execution_claim is not None
    assert recovered.record.execution_claim.fencing_token == 1
    assert recovered.record.execution_claim.owner_id == "formal-publisher-process-2"


def test_postgres_formal_command_checkpoints_candidate_once_before_completion(
    postgres_engine: Engine,
) -> None:
    repository = PostgresFormalProductionAgentPublicationCommandRepository(postgres_engine)
    reserved = repository.reserve(
        _record(),
        lease_duration=timedelta(seconds=30),
    )

    first = repository.checkpoint_candidate(
        reserved.record,
        formal_candidate_sha256="2" * 64,
        knowledge_release_candidate_sha256="3" * 64,
    )
    replay = repository.checkpoint_candidate(
        first,
        formal_candidate_sha256="2" * 64,
        knowledge_release_candidate_sha256="3" * 64,
    )
    drift = repository.checkpoint_candidate(
        first,
        formal_candidate_sha256="4" * 64,
        knowledge_release_candidate_sha256="5" * 64,
    )

    assert first.candidate_checkpoint is not None
    assert first.candidate_checkpoint.formal_candidate_sha256 == "2" * 64
    assert first.candidate_checkpoint.knowledge_release_candidate_sha256 == "3" * 64
    assert first.candidate_checkpoint.checkpointed_at.endswith("Z")
    assert replay == first
    assert drift == first
    with pytest.raises(PersistenceInvariantError):
        repository.complete(_failed(reserved.record))
    assert repository.complete(_succeeded(first)) == _succeeded(first)


def test_postgres_formal_command_concurrent_candidate_checkpoint_is_immutable(
    postgres_engine: Engine,
) -> None:
    repository = PostgresFormalProductionAgentPublicationCommandRepository(postgres_engine)
    reserved = repository.reserve(
        _record(),
        lease_duration=timedelta(seconds=30),
    )
    barrier = Barrier(2)

    def checkpoint_once(digit: str) -> FormalProductionAgentPublicationCommandRecord:
        contender = PostgresFormalProductionAgentPublicationCommandRepository(postgres_engine)
        barrier.wait()
        return contender.checkpoint_candidate(
            reserved.record,
            formal_candidate_sha256=digit * 64,
            knowledge_release_candidate_sha256=str(int(digit) + 2) * 64,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(checkpoint_once, ("2", "3")))

    assert results[0].candidate_checkpoint == results[1].candidate_checkpoint
    assert results[0].candidate_checkpoint is not None
    assert results[0].candidate_checkpoint.formal_candidate_sha256 in {"2" * 64, "3" * 64}
