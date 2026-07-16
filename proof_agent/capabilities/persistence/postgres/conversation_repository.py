from __future__ import annotations

from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as postgres_insert

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
    conversation_turns,
    conversations,
)
from proof_agent.contracts.conversation import ConversationRecord, ConversationTurn
from proof_agent.contracts.persistence import (
    PersistenceConflictError,
    PersistenceInvariantError,
    PersistenceNotFoundError,
)


class PostgresConversationRepository:
    """Ordered Operator Chat persistence with optimistic append semantics."""

    _RAW_TEXT_RETENTION = timedelta(days=90)

    def __init__(self, connection_source: ConnectionSource) -> None:
        self._connection_source = connection_source

    def create(self, record: ConversationRecord) -> None:
        if record.turns:
            raise PersistenceInvariantError(
                "new conversations must append turns through append_turn"
            )
        statement = (
            postgres_insert(conversations)
            .values(
                conversation_id=uuid_value(
                    record.conversation_id, field="conversation_id"
                ),
                agent_id=record.agent_id,
                title=record.title,
                pinned=record.pinned,
                created_at=timestamp_value(record.created_at, field="created_at"),
                updated_at=timestamp_value(record.updated_at, field="updated_at"),
            )
            .on_conflict_do_nothing(index_elements=[conversations.c.conversation_id])
            .returning(conversations.c.conversation_id)
        )
        with write_connection(self._connection_source) as connection:
            inserted = connection.execute(statement).scalar_one_or_none()
        if inserted is None:
            raise PersistenceConflictError(
                resource_type="conversation",
                resource_id=record.conversation_id,
                expected_revision=0,
                actual_revision=0,
            )

    def get(self, conversation_id: str) -> ConversationRecord | None:
        conversation_uuid = uuid_value(conversation_id, field="conversation_id")
        header_statement = sa.select(conversations).where(
            conversations.c.conversation_id == conversation_uuid
        )
        turns_statement = (
            sa.select(conversation_turns.c.turn_json)
            .where(conversation_turns.c.conversation_id == conversation_uuid)
            .order_by(conversation_turns.c.ordinal)
        )
        with read_connection(self._connection_source) as connection:
            header = connection.execute(header_statement).mappings().one_or_none()
            if header is None:
                return None
            turn_payloads = connection.execute(turns_statement).scalars().all()
        return ConversationRecord(
            conversation_id=str(header["conversation_id"]),
            agent_id=str(header["agent_id"]),
            title=header["title"],
            pinned=bool(header["pinned"]),
            created_at=timestamp_text(header["created_at"]),
            updated_at=timestamp_text(header["updated_at"]),
            turns=tuple(ConversationTurn.model_validate(item) for item in turn_payloads),
        )

    def list(self, *, limit: int = 200) -> tuple[ConversationRecord, ...]:
        if not 1 <= limit <= 500:
            raise ValueError("conversation list limit must be between 1 and 500")
        with read_connection(self._connection_source) as connection:
            identities = connection.execute(
                sa.select(conversations.c.conversation_id)
                .order_by(
                    conversations.c.pinned.desc(),
                    conversations.c.updated_at.desc(),
                    conversations.c.conversation_id.desc(),
                )
                .limit(limit)
            ).scalars().all()
            records = tuple(
                record
                for identity in identities
                if (record := PostgresConversationRepository(connection).get(str(identity)))
                is not None
                and record.turns
            )
        return records

    def update(self, record: ConversationRecord) -> None:
        with write_connection(self._connection_source) as connection:
            updated = connection.execute(
                sa.update(conversations)
                .where(
                    conversations.c.conversation_id
                    == uuid_value(record.conversation_id, field="conversation_id"),
                    conversations.c.agent_id == record.agent_id,
                    conversations.c.created_at
                    == timestamp_value(record.created_at, field="created_at"),
                )
                .values(
                    title=record.title,
                    pinned=record.pinned,
                    updated_at=timestamp_value(record.updated_at, field="updated_at"),
                )
            )
        if updated.rowcount != 1:
            raise PersistenceNotFoundError(
                resource_type="conversation", resource_id=record.conversation_id
            )

    def delete(self, conversation_id: str) -> bool:
        with write_connection(self._connection_source) as connection:
            deleted = connection.execute(
                sa.delete(conversations).where(
                    conversations.c.conversation_id
                    == uuid_value(conversation_id, field="conversation_id")
                )
            )
        return deleted.rowcount == 1

    def append_turn(
        self,
        conversation_id: str,
        turn: ConversationTurn,
        *,
        expected_turn_count: int,
    ) -> ConversationRecord:
        conversation_uuid = uuid_value(conversation_id, field="conversation_id")
        if expected_turn_count < 0:
            raise ValueError("expected_turn_count cannot be negative")
        created_at = timestamp_value(turn.created_at, field="created_at")
        with write_connection(self._connection_source) as connection:
            header = connection.execute(
                sa.select(
                    conversations.c.agent_id,
                    conversations.c.updated_at,
                )
                .where(conversations.c.conversation_id == conversation_uuid)
                .with_for_update()
            ).mappings().one_or_none()
            if header is None:
                raise PersistenceNotFoundError(
                    resource_type="conversation", resource_id=conversation_id
                )
            if str(header["agent_id"]) != turn.agent_id:
                raise PersistenceInvariantError(
                    "conversation turn agent_id must match its conversation"
                )
            actual = int(
                connection.execute(
                    sa.select(sa.func.count())
                    .select_from(conversation_turns)
                    .where(conversation_turns.c.conversation_id == conversation_uuid)
                ).scalar_one()
            )
            if actual != expected_turn_count:
                raise PersistenceConflictError(
                    resource_type="conversation",
                    resource_id=conversation_id,
                    expected_revision=expected_turn_count,
                    actual_revision=actual,
                )
            inserted = connection.execute(
                postgres_insert(conversation_turns)
                .values(
                    turn_id=uuid_value(turn.turn_id, field="turn_id"),
                    conversation_id=conversation_uuid,
                    ordinal=expected_turn_count + 1,
                    run_id=uuid_value(turn.run_id, field="run_id"),
                    turn_json=model_json(turn),
                    created_at=created_at,
                    raw_text_expires_at=created_at + self._RAW_TEXT_RETENTION,
                )
                .on_conflict_do_nothing(index_elements=[conversation_turns.c.turn_id])
                .returning(conversation_turns.c.turn_id)
            ).scalar_one_or_none()
            if inserted is None:
                raise PersistenceConflictError(
                    resource_type="conversation_turn",
                    resource_id=turn.turn_id,
                    expected_revision=0,
                    actual_revision=1,
                )
            connection.execute(
                sa.update(conversations)
                .where(conversations.c.conversation_id == conversation_uuid)
                .values(updated_at=created_at)
            )
        updated = self.get(conversation_id)
        if updated is None:
            raise PersistenceInvariantError("committed conversation disappeared")
        return updated
