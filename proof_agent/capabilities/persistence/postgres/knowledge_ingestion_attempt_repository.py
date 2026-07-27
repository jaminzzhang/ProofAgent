"""PostgreSQL history authority for Knowledge ingestion attempts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

import sqlalchemy as sa

from proof_agent.capabilities.persistence.postgres._common import (
    ConnectionSource,
    model_json,
    read_connection,
    timestamp_text,
    timestamp_value,
    write_connection,
)
from proof_agent.capabilities.persistence.postgres.schema import (
    knowledge_ingestion_attempts,
)
from proof_agent.contracts.knowledge_operations import KnowledgeIngestionAttempt


class KnowledgeIngestionAttemptConflictError(RuntimeError):
    """An attempt identity or ordinal is already bound to different history."""


class PostgresKnowledgeIngestionAttemptRepository:
    """Append and read bounded immutable attempt identities."""

    def __init__(self, connection_source: ConnectionSource) -> None:
        self._connection_source = connection_source

    def append(self, attempt: KnowledgeIngestionAttempt) -> KnowledgeIngestionAttempt:
        attempt_id = UUID(attempt.attempt_id)
        job_id = UUID(attempt.job_id)
        payload = model_json(attempt)
        with write_connection(self._connection_source) as connection:
            connection.execute(
                sa.text(
                    "SELECT pg_advisory_xact_lock(hashtextextended(:job_id, 0))"
                ),
                {"job_id": attempt.job_id},
            )
            existing_payload = connection.execute(
                sa.select(knowledge_ingestion_attempts.c.attempt_json).where(
                    sa.or_(
                        knowledge_ingestion_attempts.c.attempt_id == attempt_id,
                        sa.and_(
                            knowledge_ingestion_attempts.c.job_id == job_id,
                            knowledge_ingestion_attempts.c.attempt_number
                            == attempt.attempt_number,
                        ),
                    )
                )
            ).scalar_one_or_none()
            if existing_payload is not None:
                existing = KnowledgeIngestionAttempt.model_validate(existing_payload)
                if existing == attempt:
                    return existing
                raise KnowledgeIngestionAttemptConflictError(
                    "Ingestion attempt identity or ordinal already exists"
                )
            connection.execute(
                sa.insert(knowledge_ingestion_attempts).values(
                    attempt_id=attempt_id,
                    job_id=job_id,
                    attempt_number=attempt.attempt_number,
                    initiation=attempt.initiation,
                    state=attempt.state,
                    fencing_token=attempt.fencing_token,
                    worker_id=attempt.worker_id,
                    attempt_json=payload,
                    started_at=timestamp_value(attempt.started_at, field="started_at"),
                    updated_at=timestamp_value(attempt.updated_at, field="updated_at"),
                    completed_at=(
                        None
                        if attempt.completed_at is None
                        else timestamp_value(attempt.completed_at, field="completed_at")
                    ),
                )
            )
        return attempt

    def list_for_job(self, job_id: str) -> tuple[KnowledgeIngestionAttempt, ...]:
        with read_connection(self._connection_source) as connection:
            payloads = connection.execute(
                sa.select(knowledge_ingestion_attempts.c.attempt_json)
                .where(knowledge_ingestion_attempts.c.job_id == UUID(job_id))
                .order_by(knowledge_ingestion_attempts.c.attempt_number)
            ).scalars().all()
        return tuple(
            KnowledgeIngestionAttempt.model_validate(payload) for payload in payloads
        )

    def next_attempt_number(self, job_id: str) -> int:
        with read_connection(self._connection_source) as connection:
            current = connection.execute(
                sa.select(
                    sa.func.coalesce(
                        sa.func.max(knowledge_ingestion_attempts.c.attempt_number),
                        0,
                    )
                ).where(knowledge_ingestion_attempts.c.job_id == UUID(job_id))
            ).scalar_one()
        return int(current) + 1

    def transition_running(
        self,
        *,
        job_id: str,
        fencing_token: int,
        state: Literal["succeeded", "failed", "cancelled"],
        completed_at: datetime,
        failure_code: str | None = None,
        failure_classification: Literal[
            "recoverable",
            "recoverable_exhausted",
            "review_required",
            "non_recoverable",
        ]
        | None = None,
        outcome_detail: str | None = None,
    ) -> KnowledgeIngestionAttempt:
        completed_text = timestamp_text(completed_at)
        with write_connection(self._connection_source) as connection:
            row = connection.execute(
                sa.select(
                    knowledge_ingestion_attempts.c.attempt_id,
                    knowledge_ingestion_attempts.c.attempt_json,
                )
                .where(
                    knowledge_ingestion_attempts.c.job_id == UUID(job_id),
                    knowledge_ingestion_attempts.c.fencing_token == fencing_token,
                    knowledge_ingestion_attempts.c.state == "running",
                )
                .with_for_update()
            ).mappings().one_or_none()
            if row is None:
                raise KnowledgeIngestionAttemptConflictError(
                    "Running ingestion attempt was not found for fence"
                )
            current = KnowledgeIngestionAttempt.model_validate(row["attempt_json"])
            terminal = KnowledgeIngestionAttempt.model_validate(
                {
                    **current.model_dump(mode="python"),
                    "state": state,
                    "failure_code": failure_code,
                    "failure_classification": failure_classification,
                    "outcome_detail": outcome_detail,
                    "updated_at": completed_text,
                    "completed_at": completed_text,
                },
                strict=True,
            )
            payload = model_json(terminal)
            changed = connection.execute(
                sa.update(knowledge_ingestion_attempts)
                .where(
                    knowledge_ingestion_attempts.c.attempt_id == row["attempt_id"],
                    knowledge_ingestion_attempts.c.state == "running",
                )
                .values(
                    state=terminal.state,
                    attempt_json=payload,
                    updated_at=completed_at,
                    completed_at=completed_at,
                )
            )
            if changed.rowcount != 1:
                raise KnowledgeIngestionAttemptConflictError(
                    "Ingestion attempt transition raced another owner"
                )
        return terminal

    def touch_running(
        self,
        *,
        job_id: str,
        fencing_token: int,
        updated_at: datetime,
    ) -> KnowledgeIngestionAttempt:
        updated_text = timestamp_text(updated_at)
        with write_connection(self._connection_source) as connection:
            row = connection.execute(
                sa.select(
                    knowledge_ingestion_attempts.c.attempt_id,
                    knowledge_ingestion_attempts.c.attempt_json,
                )
                .where(
                    knowledge_ingestion_attempts.c.job_id == UUID(job_id),
                    knowledge_ingestion_attempts.c.fencing_token == fencing_token,
                    knowledge_ingestion_attempts.c.state == "running",
                )
                .with_for_update()
            ).mappings().one_or_none()
            if row is None:
                raise KnowledgeIngestionAttemptConflictError(
                    "Running ingestion attempt was not found for fence"
                )
            current = KnowledgeIngestionAttempt.model_validate(row["attempt_json"])
            touched = current.model_copy(update={"updated_at": updated_text})
            connection.execute(
                sa.update(knowledge_ingestion_attempts)
                .where(knowledge_ingestion_attempts.c.attempt_id == row["attempt_id"])
                .values(
                    attempt_json=model_json(touched),
                    updated_at=updated_at,
                )
            )
        return touched


__all__ = [
    "KnowledgeIngestionAttemptConflictError",
    "PostgresKnowledgeIngestionAttemptRepository",
]
