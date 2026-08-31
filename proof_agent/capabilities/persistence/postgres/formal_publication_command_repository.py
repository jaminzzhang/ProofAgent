from __future__ import annotations

from datetime import timedelta
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.engine import RowMapping

from proof_agent.capabilities.persistence.postgres._common import (
    ConnectionSource,
    model_json,
    read_connection,
    timestamp_text,
    timestamp_value,
    uuid_value,
    write_connection,
)
from proof_agent.capabilities.persistence.postgres.schema import (
    formal_agent_publication_commands,
)
from proof_agent.contracts import FormalProductionAgentPublicationCommandState
from proof_agent.contracts.persistence import (
    FormalProductionAgentPublicationCandidateCheckpoint,
    FormalProductionAgentPublicationExecutionClaim,
    FormalProductionAgentPublicationCommandRecord,
    FormalProductionAgentPublicationCommandReservation,
    PersistenceIdempotencyConflictError,
    PersistenceInvariantError,
)


class PostgresFormalProductionAgentPublicationCommandRepository:
    """PostgreSQL reservation and terminal-state adapter for formal publication."""

    def __init__(self, connection_source: ConnectionSource) -> None:
        self._connection_source = connection_source

    def reserve(
        self,
        record: FormalProductionAgentPublicationCommandRecord,
        *,
        lease_duration: timedelta,
    ) -> FormalProductionAgentPublicationCommandReservation:
        if record.receipt.state is not FormalProductionAgentPublicationCommandState.IN_PROGRESS:
            raise PersistenceInvariantError("formal command reservation must be in progress")
        proposed_claim = _require_execution_claim(record)
        _require_lease_duration(lease_duration)
        with write_connection(self._connection_source) as connection:
            database_now = connection.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
            claimed = record.model_copy(
                update={
                    "execution_claim": FormalProductionAgentPublicationExecutionClaim(
                        fencing_token=1,
                        owner_id=proposed_claim.owner_id,
                        lease_expires_at=timestamp_text(database_now + lease_duration),
                    )
                }
            )
            statement = (
                postgres_insert(formal_agent_publication_commands)
                .values(**_values(claimed, updated_at=database_now))
                .on_conflict_do_nothing(
                    index_elements=[
                        formal_agent_publication_commands.c.actor_subject,
                        formal_agent_publication_commands.c.idempotency_key,
                    ]
                )
                .returning(*formal_agent_publication_commands.c)
            )
            row = connection.execute(statement).mappings().one_or_none()
            created = row is not None
            if row is None:
                row = (
                    connection.execute(
                        sa.select(formal_agent_publication_commands)
                        .where(
                            formal_agent_publication_commands.c.actor_subject
                            == record.actor_subject,
                            formal_agent_publication_commands.c.idempotency_key
                            == record.idempotency_key,
                        )
                        .with_for_update()
                    )
                    .mappings()
                    .one()
                )
                persisted = _row_record(row)
                _require_request_identity(persisted, record)
                if (
                    persisted.receipt.state
                    is not FormalProductionAgentPublicationCommandState.IN_PROGRESS
                ):
                    return FormalProductionAgentPublicationCommandReservation(
                        record=persisted,
                        created=False,
                        acquired=False,
                    )
                current_claim = persisted.execution_claim
                database_now = connection.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
                if (
                    current_claim is not None
                    and timestamp_value(
                        current_claim.lease_expires_at,
                        field="lease_expires_at",
                    )
                    > database_now
                ):
                    return FormalProductionAgentPublicationCommandReservation(
                        record=persisted,
                        created=False,
                        acquired=False,
                    )
                next_fencing_token = 1 if current_claim is None else current_claim.fencing_token + 1
                next_claim = FormalProductionAgentPublicationExecutionClaim(
                    fencing_token=next_fencing_token,
                    owner_id=proposed_claim.owner_id,
                    lease_expires_at=timestamp_text(database_now + lease_duration),
                )
                updated_row = (
                    connection.execute(
                        sa.update(formal_agent_publication_commands)
                        .where(
                            formal_agent_publication_commands.c.command_id
                            == uuid_value(
                                persisted.receipt.command_id,
                                field="command_id",
                            ),
                            formal_agent_publication_commands.c.state
                            == FormalProductionAgentPublicationCommandState.IN_PROGRESS.value,
                        )
                        .values(
                            execution_fencing_token=next_claim.fencing_token,
                            lease_owner=next_claim.owner_id,
                            lease_expires_at=timestamp_value(
                                next_claim.lease_expires_at,
                                field="lease_expires_at",
                            ),
                            updated_at=database_now,
                        )
                        .returning(*formal_agent_publication_commands.c)
                    )
                    .mappings()
                    .one_or_none()
                )
                if updated_row is None:
                    raise PersistenceInvariantError("formal command takeover lost its lock")
                taken_over = _row_record(updated_row)
                if taken_over.execution_claim != next_claim:
                    raise PersistenceInvariantError(
                        "formal command takeover result is inconsistent"
                    )
                return FormalProductionAgentPublicationCommandReservation(
                    record=taken_over,
                    created=False,
                    acquired=True,
                )
        persisted = _row_record(row)
        _require_request_identity(persisted, record)
        return FormalProductionAgentPublicationCommandReservation(
            record=persisted,
            created=created,
            acquired=True,
        )

    def find_owned(
        self,
        *,
        command_id: str,
        actor_subject: str,
    ) -> FormalProductionAgentPublicationCommandRecord | None:
        """Return one exact actor-owned command without acquiring its lease."""

        with read_connection(self._connection_source) as connection:
            row = (
                connection.execute(
                    sa.select(formal_agent_publication_commands).where(
                        formal_agent_publication_commands.c.command_id
                        == uuid_value(command_id, field="command_id"),
                        formal_agent_publication_commands.c.actor_subject == actor_subject,
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else _row_record(row)

    def checkpoint_candidate(
        self,
        record: FormalProductionAgentPublicationCommandRecord,
        *,
        formal_candidate_sha256: str,
        knowledge_release_candidate_sha256: str,
    ) -> FormalProductionAgentPublicationCommandRecord:
        if record.receipt.state is not FormalProductionAgentPublicationCommandState.IN_PROGRESS:
            raise PersistenceInvariantError("formal command checkpoint must be in progress")
        execution_claim = _require_execution_claim(record)
        with write_connection(self._connection_source) as connection:
            current_row = (
                connection.execute(
                    sa.select(formal_agent_publication_commands)
                    .where(
                        formal_agent_publication_commands.c.actor_subject == record.actor_subject,
                        formal_agent_publication_commands.c.idempotency_key
                        == record.idempotency_key,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if current_row is None:
                raise PersistenceInvariantError("formal command reservation was not found")
            current = _row_record(current_row)
            _require_same_identity(current, record)
            _require_same_execution_claim(current, record)
            if (
                current.receipt.state
                is not FormalProductionAgentPublicationCommandState.IN_PROGRESS
            ):
                raise PersistenceInvariantError("formal command checkpoint is terminal")
            if current.candidate_checkpoint is not None:
                return current

            database_now = connection.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
            checkpoint = FormalProductionAgentPublicationCandidateCheckpoint(
                formal_candidate_sha256=formal_candidate_sha256,
                knowledge_release_candidate_sha256=knowledge_release_candidate_sha256,
                checkpointed_at=timestamp_text(database_now),
            )
            updated_row = (
                connection.execute(
                    sa.update(formal_agent_publication_commands)
                    .where(
                        formal_agent_publication_commands.c.command_id
                        == uuid_value(record.receipt.command_id, field="command_id"),
                        formal_agent_publication_commands.c.state
                        == FormalProductionAgentPublicationCommandState.IN_PROGRESS.value,
                        formal_agent_publication_commands.c.execution_fencing_token
                        == execution_claim.fencing_token,
                        formal_agent_publication_commands.c.lease_owner == execution_claim.owner_id,
                        formal_agent_publication_commands.c.formal_candidate_sha256.is_(None),
                        formal_agent_publication_commands.c.knowledge_release_candidate_sha256.is_(
                            None
                        ),
                        formal_agent_publication_commands.c.candidate_checkpointed_at.is_(None),
                    )
                    .values(
                        formal_candidate_sha256=checkpoint.formal_candidate_sha256,
                        knowledge_release_candidate_sha256=(
                            checkpoint.knowledge_release_candidate_sha256
                        ),
                        candidate_checkpointed_at=timestamp_value(
                            checkpoint.checkpointed_at,
                            field="candidate_checkpointed_at",
                        ),
                        updated_at=database_now,
                    )
                    .returning(*formal_agent_publication_commands.c)
                )
                .mappings()
                .one_or_none()
            )
            if updated_row is None:
                raise PersistenceInvariantError("formal command checkpoint lost its lock")
        checkpointed = _row_record(updated_row)
        if checkpointed.candidate_checkpoint != checkpoint:
            raise PersistenceInvariantError("formal command checkpoint result is inconsistent")
        return checkpointed

    def complete(
        self,
        record: FormalProductionAgentPublicationCommandRecord,
    ) -> FormalProductionAgentPublicationCommandRecord:
        if record.receipt.state is FormalProductionAgentPublicationCommandState.IN_PROGRESS:
            raise PersistenceInvariantError("formal command completion must be terminal")
        with write_connection(self._connection_source) as connection:
            current_row = (
                connection.execute(
                    sa.select(formal_agent_publication_commands)
                    .where(
                        formal_agent_publication_commands.c.actor_subject == record.actor_subject,
                        formal_agent_publication_commands.c.idempotency_key
                        == record.idempotency_key,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if current_row is None:
                raise PersistenceInvariantError("formal command reservation was not found")
            current = _row_record(current_row)
            _require_same_identity(current, record)
            _require_same_execution_claim(current, record)
            _require_same_candidate_checkpoint(current, record)
            execution_claim = _require_execution_claim(record)
            if (
                current.receipt.state
                is not FormalProductionAgentPublicationCommandState.IN_PROGRESS
            ):
                return current
            completed_at = record.receipt.completed_at
            assert completed_at is not None
            updated_row = (
                connection.execute(
                    sa.update(formal_agent_publication_commands)
                    .where(
                        formal_agent_publication_commands.c.command_id
                        == uuid_value(record.receipt.command_id, field="command_id"),
                        formal_agent_publication_commands.c.state
                        == FormalProductionAgentPublicationCommandState.IN_PROGRESS.value,
                        formal_agent_publication_commands.c.execution_fencing_token
                        == execution_claim.fencing_token,
                        formal_agent_publication_commands.c.lease_owner == execution_claim.owner_id,
                    )
                    .values(
                        state=record.receipt.state.value,
                        receipt_json=model_json(record.receipt),
                        completed_at=timestamp_value(completed_at, field="completed_at"),
                        updated_at=timestamp_value(completed_at, field="completed_at"),
                    )
                    .returning(*formal_agent_publication_commands.c)
                )
                .mappings()
                .one_or_none()
            )
            if updated_row is None:
                raise PersistenceInvariantError("formal command completion lost its lock")
        persisted = _row_record(updated_row)
        if persisted != record:
            raise PersistenceInvariantError("formal command completion result is inconsistent")
        return persisted


def _values(
    record: FormalProductionAgentPublicationCommandRecord,
    *,
    updated_at: object,
) -> dict[str, object]:
    receipt = record.receipt
    claim = _require_execution_claim(record)
    started_at = timestamp_value(receipt.started_at, field="started_at")
    return {
        "command_id": uuid_value(receipt.command_id, field="command_id"),
        "actor_subject": record.actor_subject,
        "idempotency_key": record.idempotency_key,
        "request_sha256": receipt.request_sha256,
        "state": receipt.state.value,
        "agent_id": receipt.agent_id,
        "draft_id": uuid_value(receipt.draft_id, field="draft_id"),
        "draft_revision": receipt.draft_revision,
        "receipt_json": model_json(receipt),
        "started_at": started_at,
        "completed_at": None,
        "updated_at": updated_at,
        "execution_fencing_token": claim.fencing_token,
        "lease_owner": claim.owner_id,
        "lease_expires_at": timestamp_value(
            claim.lease_expires_at,
            field="lease_expires_at",
        ),
        "formal_candidate_sha256": None,
        "knowledge_release_candidate_sha256": None,
        "candidate_checkpointed_at": None,
    }


def _row_record(row: RowMapping) -> FormalProductionAgentPublicationCommandRecord:
    claim_values = (
        row["execution_fencing_token"],
        row["lease_owner"],
        row["lease_expires_at"],
    )
    if all(value is None for value in claim_values):
        execution_claim = None
    elif any(value is None for value in claim_values):
        raise PersistenceInvariantError("formal command execution claim is incomplete")
    else:
        execution_claim = FormalProductionAgentPublicationExecutionClaim(
            fencing_token=row["execution_fencing_token"],
            owner_id=row["lease_owner"],
            lease_expires_at=timestamp_text(row["lease_expires_at"]),
        )
    checkpoint_values = (
        row["formal_candidate_sha256"],
        row["knowledge_release_candidate_sha256"],
        row["candidate_checkpointed_at"],
    )
    if all(value is None for value in checkpoint_values):
        candidate_checkpoint = None
    elif any(value is None for value in checkpoint_values):
        raise PersistenceInvariantError("formal command candidate checkpoint is incomplete")
    else:
        candidate_checkpoint = FormalProductionAgentPublicationCandidateCheckpoint(
            formal_candidate_sha256=row["formal_candidate_sha256"],
            knowledge_release_candidate_sha256=row["knowledge_release_candidate_sha256"],
            checkpointed_at=timestamp_text(row["candidate_checkpointed_at"]),
        )
    receipt = FormalProductionAgentPublicationCommandRecord.model_validate(
        {
            "actor_subject": row["actor_subject"],
            "idempotency_key": row["idempotency_key"],
            "receipt": row["receipt_json"],
            "execution_claim": execution_claim,
            "candidate_checkpoint": candidate_checkpoint,
        }
    )
    public = receipt.receipt
    if (
        str(row["command_id"]) != public.command_id
        or row["request_sha256"] != public.request_sha256
        or row["state"] != public.state.value
        or row["agent_id"] != public.agent_id
        or str(row["draft_id"]) != public.draft_id
        or row["draft_revision"] != public.draft_revision
    ):
        raise PersistenceInvariantError("formal command columns and receipt disagree")
    return receipt


def _require_request_identity(
    persisted: FormalProductionAgentPublicationCommandRecord,
    proposed: FormalProductionAgentPublicationCommandRecord,
) -> None:
    if persisted.receipt.request_sha256 != proposed.receipt.request_sha256:
        raise PersistenceIdempotencyConflictError(
            "formal publication idempotency key is bound to another request"
        )


def _require_execution_claim(
    record: FormalProductionAgentPublicationCommandRecord,
) -> FormalProductionAgentPublicationExecutionClaim:
    claim = record.execution_claim
    if claim is None:
        raise PersistenceInvariantError("formal command execution claim is required")
    return claim


def _require_lease_duration(value: timedelta) -> None:
    if value <= timedelta(0) or value > timedelta(hours=1):
        raise PersistenceInvariantError("formal command lease duration is invalid")


def _require_same_identity(
    current: FormalProductionAgentPublicationCommandRecord,
    desired: FormalProductionAgentPublicationCommandRecord,
) -> None:
    current_receipt = current.receipt
    desired_receipt = desired.receipt
    if (
        current.actor_subject != desired.actor_subject
        or current.idempotency_key != desired.idempotency_key
        or current_receipt.command_id != desired_receipt.command_id
        or current_receipt.request_sha256 != desired_receipt.request_sha256
        or current_receipt.agent_id != desired_receipt.agent_id
        or current_receipt.draft_id != desired_receipt.draft_id
        or current_receipt.draft_revision != desired_receipt.draft_revision
    ):
        raise PersistenceInvariantError("formal command completion identity mismatch")


def _require_same_execution_claim(
    current: FormalProductionAgentPublicationCommandRecord,
    desired: FormalProductionAgentPublicationCommandRecord,
) -> None:
    current_claim = current.execution_claim
    desired_claim = desired.execution_claim
    if current_claim is None or desired_claim is None or current_claim != desired_claim:
        raise PersistenceInvariantError("formal command completion execution claim mismatch")


def _require_same_candidate_checkpoint(
    current: FormalProductionAgentPublicationCommandRecord,
    desired: FormalProductionAgentPublicationCommandRecord,
) -> None:
    if current.candidate_checkpoint != desired.candidate_checkpoint:
        raise PersistenceInvariantError("formal command candidate checkpoint mismatch")


__all__ = ["PostgresFormalProductionAgentPublicationCommandRepository"]
