from __future__ import annotations

from datetime import timedelta
from typing import Any

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
from proof_agent.capabilities.persistence.postgres.schema import audit_events
from proof_agent.contracts.persistence import AuditMetadataRecord, PersistenceConflictError


class PostgresAuditRepository:
    """Append-only trace-safe audit metadata with initial 365-day visibility."""

    _RETENTION = timedelta(days=365)

    def __init__(self, connection_source: ConnectionSource) -> None:
        self._connection_source = connection_source

    def append(self, event: AuditMetadataRecord) -> None:
        occurred_at = timestamp_value(event.occurred_at, field="occurred_at")
        statement = (
            postgres_insert(audit_events)
            .values(
                audit_id=uuid_value(event.audit_id, field="audit_id"),
                category=event.category.value,
                event_type=event.event_type,
                outcome=event.outcome.value,
                actor_json=model_json(event.actor),
                target_type=event.target_type,
                target_id=event.target_id,
                metadata_json=model_json(event)["metadata"],
                occurred_at=occurred_at,
                expires_at=occurred_at + self._RETENTION,
            )
            .on_conflict_do_nothing(index_elements=[audit_events.c.audit_id])
            .returning(audit_events.c.audit_id)
        )
        with write_connection(self._connection_source) as connection:
            inserted = connection.execute(statement).scalar_one_or_none()
        if inserted is None:
            raise PersistenceConflictError(
                resource_type="audit_event",
                resource_id=event.audit_id,
                expected_revision=0,
                actual_revision=1,
            )

    def get(self, audit_id: str) -> AuditMetadataRecord | None:
        statement = self._projection().where(
            audit_events.c.audit_id == uuid_value(audit_id, field="audit_id")
        )
        with read_connection(self._connection_source) as connection:
            row = connection.execute(statement).mappings().one_or_none()
        return None if row is None else self._hydrate(row)

    def list_for_target(
        self,
        *,
        target_type: str,
        target_id: str,
    ) -> tuple[AuditMetadataRecord, ...]:
        """Return retained audit metadata for one exact target in event order."""

        statement = (
            self._projection()
            .where(
                audit_events.c.target_type == target_type,
                audit_events.c.target_id == target_id,
            )
            .order_by(audit_events.c.occurred_at, audit_events.c.audit_id)
        )
        with read_connection(self._connection_source) as connection:
            rows = connection.execute(statement).mappings().all()
        return tuple(self._hydrate(row) for row in rows)

    @staticmethod
    def _projection() -> sa.Select[Any]:
        return sa.select(
            audit_events.c.audit_id,
            audit_events.c.category,
            audit_events.c.event_type,
            audit_events.c.outcome,
            audit_events.c.actor_json,
            audit_events.c.target_type,
            audit_events.c.target_id,
            audit_events.c.metadata_json,
            audit_events.c.occurred_at,
        )

    @staticmethod
    def _hydrate(row: RowMapping) -> AuditMetadataRecord:
        return AuditMetadataRecord.model_validate(
            {
                "audit_id": str(row["audit_id"]),
                "category": str(row["category"]),
                "event_type": str(row["event_type"]),
                "outcome": str(row["outcome"]),
                "actor": row["actor_json"],
                "occurred_at": timestamp_text(row["occurred_at"]),
                "target_type": str(row["target_type"]),
                "target_id": str(row["target_id"]),
                "metadata": row["metadata_json"],
            }
        )
