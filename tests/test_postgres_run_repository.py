from __future__ import annotations

import pytest
from sqlalchemy import Engine

from postgres_fixtures import (
    TEST_RUN_ID,
    run_record,
    seed_agent_version,
)
from proof_agent.capabilities.persistence.postgres.run_repository import (
    PostgresRunMetadataRepository,
)
from proof_agent.contracts import (
    PersistenceConflictError,
    PersistenceInvariantError,
    RunAttemptMetadataRecord,
    RunLifecycleState,
    RunMetadataRecord,
)


pytestmark = pytest.mark.postgres_integration
pytest_plugins = ("postgres_fixtures",)


def _run() -> RunMetadataRecord:
    record = run_record()
    assert isinstance(record, RunMetadataRecord)
    return record


def test_postgres_run_repository_conditionally_transitions_immutable_request(
    postgres_engine: Engine,
) -> None:
    seed_agent_version(postgres_engine)
    repository = PostgresRunMetadataRepository(postgres_engine)
    queued = _run()
    repository.append(queued)
    running = queued.model_copy(
        update={
            "state": RunLifecycleState.RUNNING,
            "state_version": 2,
            "updated_at": "2026-07-15T00:01:00Z",
        }
    )

    assert repository.get(queued.run_id) == queued
    assert repository.transition(running, expected_state_version=1) == running
    assert repository.get(queued.run_id) == running
    with pytest.raises(PersistenceConflictError):
        repository.transition(running, expected_state_version=1)
    with pytest.raises(PersistenceInvariantError):
        repository.transition(
            running.model_copy(
                update={
                    "submitted_by": "attacker",
                    "state_version": 3,
                    "updated_at": "2026-07-15T00:02:00Z",
                }
            ),
            expected_state_version=2,
        )


def test_postgres_run_repository_appends_and_fences_attempt_transitions(
    postgres_engine: Engine,
) -> None:
    seed_agent_version(postgres_engine)
    repository = PostgresRunMetadataRepository(postgres_engine)
    repository.append(_run())
    attempt = RunAttemptMetadataRecord(
        attempt_id="019ba001-1111-7000-8000-000000000020",
        run_id=TEST_RUN_ID,
        attempt_number=1,
        state=RunLifecycleState.RUNNING,
        state_version=1,
        fencing_token=41,
        lease_owner="executor-green",
        lease_expires_at="2026-07-15T00:02:00Z",
        created_at="2026-07-15T00:01:00Z",
        updated_at="2026-07-15T00:01:00Z",
    )
    repository.append_attempt(attempt)
    finalizing = attempt.model_copy(
        update={
            "state": RunLifecycleState.FINALIZING,
            "state_version": 2,
            "updated_at": "2026-07-15T00:01:30Z",
        }
    )

    assert repository.get_attempt(attempt.attempt_id) == attempt
    assert repository.transition_attempt(
        finalizing,
        expected_state_version=1,
        expected_fencing_token=41,
    ) == finalizing
    with pytest.raises(PersistenceConflictError):
        repository.transition_attempt(
            finalizing,
            expected_state_version=1,
            expected_fencing_token=41,
        )
    with pytest.raises(PersistenceInvariantError):
        repository.transition_attempt(
            finalizing.model_copy(update={"state_version": 3, "fencing_token": 42}),
            expected_state_version=2,
            expected_fencing_token=41,
        )
