"""PostgreSQL one-use authority for prepared Hybrid publications."""

from __future__ import annotations

import json
import sqlalchemy as sa

from proof_agent.capabilities.persistence.postgres._common import (
    ConnectionSource,
    model_json,
    timestamp_text,
    timestamp_value,
    write_connection,
)
from proof_agent.capabilities.persistence.postgres.schema import (
    prepared_knowledge_publications,
)
from proof_agent.contracts.knowledge_operations import (
    PreparedHybridKnowledgePublication,
)


class PreparedKnowledgePublicationConflictError(RuntimeError):
    """A prepared publication identity, fence, or lifecycle no longer matches."""


class PostgresPreparedKnowledgePublicationRepository:
    """Persist and atomically consume one-use preparation authority."""

    def __init__(self, connection_source: ConnectionSource) -> None:
        self._connection_source = connection_source

    def save_prepared(
        self,
        prepared: PreparedHybridKnowledgePublication,
    ) -> PreparedHybridKnowledgePublication:
        with write_connection(self._connection_source) as connection:
            connection.execute(
                sa.text(
                    "SELECT pg_advisory_xact_lock(hashtextextended(:source_id, 0))"
                ),
                {"source_id": prepared.source_id},
            )
            existing_payload = connection.execute(
                sa.select(prepared_knowledge_publications.c.prepared_json).where(
                    sa.or_(
                        prepared_knowledge_publications.c.validation_id
                        == prepared.validation_id,
                        prepared_knowledge_publications.c.attempt_id
                        == prepared.attempt_id,
                        sa.and_(
                            prepared_knowledge_publications.c.source_id
                            == prepared.source_id,
                            prepared_knowledge_publications.c.fencing_token
                            == prepared.fencing_token,
                        ),
                    )
                )
            ).scalar_one_or_none()
            if existing_payload is not None:
                existing = PreparedHybridKnowledgePublication.model_validate(
                    existing_payload
                )
                if existing == prepared:
                    return existing
                raise PreparedKnowledgePublicationConflictError(
                    "Prepared publication identity or fence already exists"
                )
            connection.execute(
                sa.insert(prepared_knowledge_publications).values(
                    validation_id=prepared.validation_id,
                    operation_id=prepared.operation_id,
                    attempt_id=prepared.attempt_id,
                    fencing_token=prepared.fencing_token,
                    source_id=prepared.source_id,
                    source_draft_version_id=prepared.source_draft_version_id,
                    candidate_digest=prepared.candidate_digest,
                    generation_id=prepared.generation_id,
                    manifest_sha256=prepared.manifest_sha256,
                    staged_projection_id=prepared.staged_projection_id,
                    attestation_sha256=prepared.attestation_sha256,
                    smoke_result_sha256=prepared.smoke_result_sha256,
                    state=prepared.state,
                    prepared_json=model_json(prepared),
                    prepared_at=timestamp_value(
                        prepared.prepared_at,
                        field="prepared_at",
                    ),
                    consumed_at=None,
                )
            )
        return prepared

    def get(
        self,
        validation_id: str,
    ) -> PreparedHybridKnowledgePublication | None:
        with write_connection(self._connection_source) as connection:
            payload = connection.execute(
                sa.select(
                    prepared_knowledge_publications.c.prepared_json
                ).where(
                    prepared_knowledge_publications.c.validation_id
                    == validation_id
                )
            ).scalar_one_or_none()
        return (
            None
            if payload is None
            else PreparedHybridKnowledgePublication.model_validate_json(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            )
        )

    def invalidate_source(self, source_id: str) -> int:
        """Invalidate every unconsumed prepared authority for one changed Source."""

        with write_connection(self._connection_source) as connection:
            rows = connection.execute(
                sa.select(prepared_knowledge_publications)
                .where(
                    prepared_knowledge_publications.c.source_id == source_id,
                    prepared_knowledge_publications.c.state == "prepared",
                )
                .with_for_update()
            ).mappings().all()
            for row in rows:
                current = PreparedHybridKnowledgePublication.model_validate(
                    row["prepared_json"]
                )
                invalidated = current.model_copy(update={"state": "invalidated"})
                connection.execute(
                    sa.update(prepared_knowledge_publications)
                    .where(
                        prepared_knowledge_publications.c.validation_id
                        == row["validation_id"],
                        prepared_knowledge_publications.c.state == "prepared",
                    )
                    .values(
                        state="invalidated",
                        prepared_json=model_json(invalidated),
                    )
                )
        return len(rows)

    def consume(
        self,
        validation_id: str,
        *,
        source_id: str,
        expected_fencing_token: int,
        consumed_at: str,
    ) -> PreparedHybridKnowledgePublication:
        consumed_timestamp = timestamp_value(consumed_at, field="consumed_at")
        with write_connection(self._connection_source) as connection:
            row = connection.execute(
                sa.select(prepared_knowledge_publications)
                .where(
                    prepared_knowledge_publications.c.validation_id == validation_id
                )
                .with_for_update()
            ).mappings().one_or_none()
            if (
                row is None
                or row["source_id"] != source_id
                or int(row["fencing_token"]) != expected_fencing_token
                or row["state"] != "prepared"
            ):
                raise PreparedKnowledgePublicationConflictError(
                    "Prepared publication is stale, consumed, or fenced"
                )
            current = PreparedHybridKnowledgePublication.model_validate(
                row["prepared_json"]
            )
            consumed = current.model_copy(
                update={
                    "state": "consumed",
                    "consumed_at": timestamp_text(consumed_timestamp),
                }
            )
            result = connection.execute(
                sa.update(prepared_knowledge_publications)
                .where(
                    prepared_knowledge_publications.c.validation_id == validation_id,
                    prepared_knowledge_publications.c.source_id == source_id,
                    prepared_knowledge_publications.c.fencing_token
                    == expected_fencing_token,
                    prepared_knowledge_publications.c.state == "prepared",
                )
                .values(
                    state="consumed",
                    prepared_json=model_json(consumed),
                    consumed_at=consumed_timestamp,
                )
            )
            if result.rowcount != 1:
                raise PreparedKnowledgePublicationConflictError(
                    "Prepared publication lost its consumption fence"
                )
        return consumed


__all__ = [
    "PreparedKnowledgePublicationConflictError",
    "PostgresPreparedKnowledgePublicationRepository",
]
