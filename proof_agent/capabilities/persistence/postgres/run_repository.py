from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as postgres_insert

from proof_agent.capabilities.persistence.postgres._common import (
    ConnectionSource,
    model_json,
    read_connection,
    timestamp_value,
    uuid_value,
    write_connection,
)
from proof_agent.capabilities.persistence.postgres.schema import run_attempts, runs
from proof_agent.contracts.persistence import (
    PersistenceConflictError,
    PersistenceInvariantError,
    RunAttemptMetadataRecord,
    RunMetadataRecord,
)
from proof_agent.contracts.run_execution import RunLifecycleState


class PostgresRunMetadataRepository:
    """Minimal S4-ready Run and Attempt conditional persistence primitives."""

    def __init__(self, connection_source: ConnectionSource) -> None:
        self._connection_source = connection_source

    def append(self, record: RunMetadataRecord) -> None:
        if record.state_version != 1:
            raise PersistenceInvariantError("new Run state_version must be 1")
        statement = (
            postgres_insert(runs)
            .values(**_run_values(record))
            .on_conflict_do_nothing(index_elements=[runs.c.run_id])
            .returning(runs.c.state_version)
        )
        with write_connection(self._connection_source) as connection:
            inserted = connection.execute(statement).scalar_one_or_none()
            if inserted is None:
                actual = connection.execute(
                    sa.select(runs.c.state_version).where(
                        runs.c.run_id == uuid_value(record.run_id, field="run_id")
                    )
                ).scalar_one_or_none()
                raise PersistenceConflictError(
                    resource_type="run",
                    resource_id=record.run_id,
                    expected_revision=0,
                    actual_revision=actual,
                )

    def get(self, run_id: str) -> RunMetadataRecord | None:
        statement = sa.select(runs.c.run_metadata_json).where(
            runs.c.run_id == uuid_value(run_id, field="run_id")
        )
        with read_connection(self._connection_source) as connection:
            payload = connection.execute(statement).scalar_one_or_none()
        return None if payload is None else RunMetadataRecord.model_validate(payload)

    def transition(
        self,
        record: RunMetadataRecord,
        *,
        expected_state_version: int,
    ) -> RunMetadataRecord:
        if record.state_version != expected_state_version + 1:
            raise PersistenceInvariantError(
                "Run transition must increment state_version exactly once"
            )
        run_id = uuid_value(record.run_id, field="run_id")
        immutable = (
            runs.c.run_purpose == record.run_purpose.value,
            runs.c.agent_id == record.agent_id,
            runs.c.agent_version_id
            == uuid_value(record.agent_version_id, field="agent_version_id"),
            runs.c.submitted_by == record.submitted_by,
            runs.c.created_at == timestamp_value(record.created_at, field="created_at"),
        )
        statement = (
            sa.update(runs)
            .where(
                runs.c.run_id == run_id,
                runs.c.state_version == expected_state_version,
                *immutable,
            )
            .values(
                state=record.state.value,
                state_version=record.state_version,
                run_metadata_json=model_json(record),
                updated_at=timestamp_value(record.updated_at, field="updated_at"),
            )
            .returning(runs.c.state_version)
        )
        with write_connection(self._connection_source) as connection:
            updated = connection.execute(statement).scalar_one_or_none()
            if updated is None:
                self._raise_run_transition_failure(
                    connection,
                    record,
                    expected_state_version=expected_state_version,
                )
        return record

    def append_attempt(self, record: RunAttemptMetadataRecord) -> None:
        if record.state_version != 1:
            raise PersistenceInvariantError("new Attempt state_version must be 1")
        statement = (
            postgres_insert(run_attempts)
            .values(**_attempt_values(record))
            .on_conflict_do_nothing(index_elements=[run_attempts.c.attempt_id])
            .returning(run_attempts.c.state_version)
        )
        with write_connection(self._connection_source) as connection:
            inserted = connection.execute(statement).scalar_one_or_none()
            if inserted is None:
                actual = connection.execute(
                    sa.select(run_attempts.c.state_version).where(
                        run_attempts.c.attempt_id
                        == uuid_value(record.attempt_id, field="attempt_id")
                    )
                ).scalar_one_or_none()
                raise PersistenceConflictError(
                    resource_type="run_attempt",
                    resource_id=record.attempt_id,
                    expected_revision=0,
                    actual_revision=actual,
                )

    def get_attempt(self, attempt_id: str) -> RunAttemptMetadataRecord | None:
        statement = sa.select(run_attempts.c.attempt_json).where(
            run_attempts.c.attempt_id == uuid_value(attempt_id, field="attempt_id")
        )
        with read_connection(self._connection_source) as connection:
            payload = connection.execute(statement).scalar_one_or_none()
        return None if payload is None else RunAttemptMetadataRecord.model_validate(payload)

    def transition_attempt(
        self,
        record: RunAttemptMetadataRecord,
        *,
        expected_state_version: int,
        expected_fencing_token: int,
    ) -> RunAttemptMetadataRecord:
        if record.state_version != expected_state_version + 1:
            raise PersistenceInvariantError(
                "Attempt transition must increment state_version exactly once"
            )
        if record.fencing_token != expected_fencing_token:
            raise PersistenceInvariantError(
                "Attempt transition cannot change its fencing token"
            )
        attempt_id = uuid_value(record.attempt_id, field="attempt_id")
        statement = (
            sa.update(run_attempts)
            .where(
                run_attempts.c.attempt_id == attempt_id,
                run_attempts.c.run_id == uuid_value(record.run_id, field="run_id"),
                run_attempts.c.attempt_number == record.attempt_number,
                run_attempts.c.created_at
                == timestamp_value(record.created_at, field="created_at"),
                run_attempts.c.state_version == expected_state_version,
                run_attempts.c.fencing_token == expected_fencing_token,
            )
            .values(
                state=record.state.value,
                state_version=record.state_version,
                lease_owner=record.lease_owner,
                lease_expires_at=(
                    None
                    if record.lease_expires_at is None
                    else timestamp_value(record.lease_expires_at, field="lease_expires_at")
                ),
                attempt_json=model_json(record),
                updated_at=timestamp_value(record.updated_at, field="updated_at"),
            )
            .returning(run_attempts.c.state_version)
        )
        with write_connection(self._connection_source) as connection:
            updated = connection.execute(statement).scalar_one_or_none()
            if updated is None:
                row = connection.execute(
                    sa.select(
                        run_attempts.c.state_version,
                        run_attempts.c.fencing_token,
                        run_attempts.c.attempt_json,
                    ).where(run_attempts.c.attempt_id == attempt_id)
                ).mappings().one_or_none()
                if row is None:
                    actual = None
                else:
                    current = RunAttemptMetadataRecord.model_validate(row["attempt_json"])
                    if _attempt_identity(current) != _attempt_identity(record):
                        raise PersistenceInvariantError(
                            "Attempt transition cannot change immutable request metadata"
                        )
                    actual = int(row["state_version"])
                raise PersistenceConflictError(
                    resource_type="run_attempt",
                    resource_id=record.attempt_id,
                    expected_revision=expected_state_version,
                    actual_revision=actual,
                )
        return record

    @staticmethod
    def _raise_run_transition_failure(
        connection: sa.Connection,
        record: RunMetadataRecord,
        *,
        expected_state_version: int,
    ) -> None:
        row = connection.execute(
            sa.select(runs.c.state_version, runs.c.run_metadata_json).where(
                runs.c.run_id == uuid_value(record.run_id, field="run_id")
            )
        ).mappings().one_or_none()
        if row is None:
            actual = None
        else:
            current = RunMetadataRecord.model_validate(row["run_metadata_json"])
            if _run_identity(current) != _run_identity(record):
                raise PersistenceInvariantError(
                    "Run transition cannot change immutable request metadata"
                )
            actual = int(row["state_version"])
        raise PersistenceConflictError(
            resource_type="run",
            resource_id=record.run_id,
            expected_revision=expected_state_version,
            actual_revision=actual,
        )


def _run_values(record: RunMetadataRecord) -> dict[str, object]:
    return {
        "run_id": uuid_value(record.run_id, field="run_id"),
        "state": record.state.value,
        "state_version": record.state_version,
        "run_purpose": record.run_purpose.value,
        "agent_id": record.agent_id,
        "agent_version_id": uuid_value(
            record.agent_version_id, field="agent_version_id"
        ),
        "submitted_by": record.submitted_by,
        "request_sha256": "0" * 64,
        "idempotency_key": f"legacy-{record.run_id}",
        "request_json": {"legacy_run_id": record.run_id},
        "enqueued_at": timestamp_value(record.created_at, field="created_at"),
        "started_at": (
            None
            if record.state is RunLifecycleState.QUEUED
            else timestamp_value(record.created_at, field="created_at")
        ),
        "completed_at": (
            timestamp_value(record.updated_at, field="updated_at")
            if record.state.is_terminal
            else None
        ),
        "result_available": False,
        "artifact_manifest_id": None,
        "terminal_failure_json": None,
        "run_metadata_json": model_json(record),
        "created_at": timestamp_value(record.created_at, field="created_at"),
        "updated_at": timestamp_value(record.updated_at, field="updated_at"),
    }


def _attempt_values(record: RunAttemptMetadataRecord) -> dict[str, object]:
    return {
        "attempt_id": uuid_value(record.attempt_id, field="attempt_id"),
        "run_id": uuid_value(record.run_id, field="run_id"),
        "attempt_number": record.attempt_number,
        "state": record.state.value,
        "state_version": record.state_version,
        "fencing_token": record.fencing_token,
        "claim_token": None,
        "activation_epoch": 1,
        "executor_id": record.lease_owner,
        "lease_owner": record.lease_owner,
        "heartbeat_at": (
            timestamp_value(record.updated_at, field="updated_at")
            if record.lease_owner is not None
            else None
        ),
        "lease_expires_at": (
            None
            if record.lease_expires_at is None
            else timestamp_value(record.lease_expires_at, field="lease_expires_at")
        ),
        "deadline_at": None,
        "snapshot_json": None,
        "snapshot_sha256": None,
        "result_available": False,
        "artifact_manifest_id": None,
        "terminal_failure_json": None,
        "attempt_json": model_json(record),
        "created_at": timestamp_value(record.created_at, field="created_at"),
        "updated_at": timestamp_value(record.updated_at, field="updated_at"),
    }


def _run_identity(record: RunMetadataRecord) -> tuple[object, ...]:
    return (
        record.run_id,
        record.run_purpose,
        record.agent_id,
        record.agent_version_id,
        record.submitted_by,
        record.created_at,
    )


def _attempt_identity(record: RunAttemptMetadataRecord) -> tuple[object, ...]:
    return (
        record.attempt_id,
        record.run_id,
        record.attempt_number,
        record.fencing_token,
        record.created_at,
    )
