from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.engine import RowMapping

from proof_agent.capabilities.persistence.postgres._common import (
    ConnectionSource,
    model_json,
    timestamp_value,
    uuid_value,
    write_connection,
)
from proof_agent.capabilities.persistence.postgres.schema import (
    formal_agent_publication_commands,
)
from proof_agent.contracts import FormalProductionAgentPublicationCommandState
from proof_agent.contracts.persistence import (
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
    ) -> FormalProductionAgentPublicationCommandReservation:
        if record.receipt.state is not FormalProductionAgentPublicationCommandState.IN_PROGRESS:
            raise PersistenceInvariantError("formal command reservation must be in progress")
        values = _values(record)
        statement = (
            postgres_insert(formal_agent_publication_commands)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[
                    formal_agent_publication_commands.c.actor_subject,
                    formal_agent_publication_commands.c.idempotency_key,
                ]
            )
            .returning(*formal_agent_publication_commands.c)
        )
        with write_connection(self._connection_source) as connection:
            row = connection.execute(statement).mappings().one_or_none()
            created = row is not None
            if row is None:
                row = (
                    connection.execute(
                        sa.select(formal_agent_publication_commands).where(
                            formal_agent_publication_commands.c.actor_subject
                            == record.actor_subject,
                            formal_agent_publication_commands.c.idempotency_key
                            == record.idempotency_key,
                        )
                    )
                    .mappings()
                    .one()
                )
        persisted = _row_record(row)
        if persisted.receipt.request_sha256 != record.receipt.request_sha256:
            raise PersistenceIdempotencyConflictError(
                "formal publication idempotency key is bound to another request"
            )
        return FormalProductionAgentPublicationCommandReservation(
            record=persisted,
            created=created,
        )

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


def _values(record: FormalProductionAgentPublicationCommandRecord) -> dict[str, object]:
    receipt = record.receipt
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
        "updated_at": started_at,
    }


def _row_record(row: RowMapping) -> FormalProductionAgentPublicationCommandRecord:
    receipt = FormalProductionAgentPublicationCommandRecord.model_validate(
        {
            "actor_subject": row["actor_subject"],
            "idempotency_key": row["idempotency_key"],
            "receipt": row["receipt_json"],
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


__all__ = ["PostgresFormalProductionAgentPublicationCommandRepository"]
