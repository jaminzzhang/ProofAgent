"""PostgreSQL authority for durable Knowledge Source operations."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as postgres_insert

from proof_agent.capabilities.persistence.postgres._common import (
    ConnectionSource,
    model_json,
    read_connection,
    timestamp_value,
    write_connection,
)
from proof_agent.capabilities.persistence.postgres.schema import (
    knowledge_source_idempotency,
    knowledge_source_operations,
)
from proof_agent.contracts.knowledge_source_api import KnowledgeSourceOperation
from proof_agent.contracts.ports.knowledge_source_operations import (
    KnowledgeSourceIdempotencyConflictError,
)


class PostgresKnowledgeSourceOperationRepository:
    """Persist provider-neutral asynchronous operation projections."""

    def __init__(self, connection_source: ConnectionSource) -> None:
        self._connection_source = connection_source

    def replay(
        self,
        *,
        operator_subject: str,
        source_id: str,
        command: str,
        idempotency_key: str,
        request_sha256: str,
    ) -> KnowledgeSourceOperation | None:
        scope = self._validate_idempotency_scope(
            operator_subject=operator_subject,
            source_id=source_id,
            command=command,
            idempotency_key=idempotency_key,
            request_sha256=request_sha256,
        )
        with write_connection(self._connection_source) as connection:
            connection.execute(
                sa.text(
                    "SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"
                ),
                {"scope": scope},
            )
            existing = connection.execute(
                sa.select(
                    knowledge_source_idempotency.c.request_sha256,
                    knowledge_source_idempotency.c.outcome_json,
                ).where(
                    knowledge_source_idempotency.c.operator_subject
                    == operator_subject,
                    knowledge_source_idempotency.c.source_id == source_id,
                    knowledge_source_idempotency.c.command == command,
                    knowledge_source_idempotency.c.idempotency_key == idempotency_key,
                )
            ).mappings().one_or_none()
        if existing is None:
            return None
        if existing["request_sha256"] != request_sha256:
            raise KnowledgeSourceIdempotencyConflictError(
                "Idempotency key is already bound to another request"
            )
        return KnowledgeSourceOperation.model_validate(existing["outcome_json"])

    def admit(
        self,
        operation: KnowledgeSourceOperation,
        *,
        operator_subject: str,
        idempotency_key: str,
        request_sha256: str,
        expires_at: datetime,
    ) -> tuple[KnowledgeSourceOperation, bool]:
        scope = self._idempotency_scope(
            operation,
            operator_subject=operator_subject,
            idempotency_key=idempotency_key,
            request_sha256=request_sha256,
            expires_at=expires_at,
        )
        with write_connection(self._connection_source) as connection:
            connection.execute(
                sa.text(
                    "SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"
                ),
                {"scope": scope},
            )
            existing = connection.execute(
                sa.select(
                    knowledge_source_idempotency.c.request_sha256,
                    knowledge_source_idempotency.c.outcome_json,
                ).where(
                    knowledge_source_idempotency.c.operator_subject
                    == operator_subject,
                    knowledge_source_idempotency.c.source_id == operation.source_id,
                    knowledge_source_idempotency.c.command == operation.command,
                    knowledge_source_idempotency.c.idempotency_key == idempotency_key,
                )
            ).mappings().one_or_none()
            if existing is not None:
                if existing["request_sha256"] != request_sha256:
                    raise KnowledgeSourceIdempotencyConflictError(
                        "Idempotency key is already bound to another request"
                    )
                return (
                    KnowledgeSourceOperation.model_validate(existing["outcome_json"]),
                    False,
                )
            connection.execute(
                sa.insert(knowledge_source_operations).values(
                    **self._operation_values(operation)
                )
            )
            connection.execute(
                sa.insert(knowledge_source_idempotency).values(
                    operator_subject=operator_subject,
                    source_id=operation.source_id,
                    command=operation.command,
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    operation_id=operation.operation_id,
                    outcome_json=model_json(operation),
                    created_at=timestamp_value(operation.created_at, field="created_at"),
                    expires_at=expires_at,
                )
            )
        return operation, True

    def save(self, operation: KnowledgeSourceOperation) -> KnowledgeSourceOperation:
        values = self._operation_values(operation)
        with write_connection(self._connection_source) as connection:
            connection.execute(
                postgres_insert(knowledge_source_operations)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=(knowledge_source_operations.c.operation_id,),
                    set_={
                        "status": values["status"],
                        "stage": values["stage"],
                        "operation_json": values["operation_json"],
                        "updated_at": values["updated_at"],
                        "completed_at": values["completed_at"],
                    },
                )
            )
        persisted = self.get(operation.operation_id)
        if persisted is None:
            raise RuntimeError("Knowledge Source operation disappeared after persistence")
        return persisted

    def get(self, operation_id: str) -> KnowledgeSourceOperation | None:
        with read_connection(self._connection_source) as connection:
            payload = connection.execute(
                sa.select(knowledge_source_operations.c.operation_json).where(
                    knowledge_source_operations.c.operation_id == operation_id
                )
            ).scalar_one_or_none()
        return None if payload is None else KnowledgeSourceOperation.model_validate(payload)

    @staticmethod
    def _idempotency_scope(
        operation: KnowledgeSourceOperation,
        *,
        operator_subject: str,
        idempotency_key: str,
        request_sha256: str,
        expires_at: datetime,
    ) -> str:
        scope = PostgresKnowledgeSourceOperationRepository._validate_idempotency_scope(
            operator_subject=operator_subject,
            source_id=operation.source_id,
            command=operation.command,
            idempotency_key=idempotency_key,
            request_sha256=request_sha256,
        )
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            raise ValueError("expires_at must be timezone-aware")
        created_at = timestamp_value(operation.created_at, field="created_at")
        if expires_at < created_at:
            raise ValueError("expires_at cannot precede operation creation")
        return scope

    @staticmethod
    def _validate_idempotency_scope(
        *,
        operator_subject: str,
        source_id: str,
        command: str,
        idempotency_key: str,
        request_sha256: str,
    ) -> str:
        if not operator_subject.strip() or len(operator_subject) > 512:
            raise ValueError("operator_subject must be non-empty and at most 512 characters")
        if not source_id.strip() or len(source_id) > 255:
            raise ValueError("source_id must be non-empty and at most 255 characters")
        if not command.strip() or len(command) > 128:
            raise ValueError("command must be non-empty and at most 128 characters")
        if not idempotency_key.strip() or len(idempotency_key) > 255:
            raise ValueError("idempotency_key must be non-empty and at most 255 characters")
        if (
            len(request_sha256) != 64
            or request_sha256.lower() != request_sha256
            or any(character not in "0123456789abcdef" for character in request_sha256)
        ):
            raise ValueError("request_sha256 must be a lowercase SHA-256 digest")
        return "\x1f".join(
            (
                operator_subject,
                source_id,
                command,
                idempotency_key,
            )
        )

    @staticmethod
    def _operation_values(operation: KnowledgeSourceOperation) -> dict[str, object]:
        return {
            "operation_id": operation.operation_id,
            "source_id": operation.source_id,
            "command": operation.command,
            "status": operation.status,
            "stage": operation.stage,
            "source_revision": operation.source_revision,
            "operation_json": model_json(operation),
            "created_at": timestamp_value(operation.created_at, field="created_at"),
            "updated_at": timestamp_value(operation.updated_at, field="updated_at"),
            "completed_at": (
                None
                if operation.completed_at is None
                else timestamp_value(operation.completed_at, field="completed_at")
            ),
        }


__all__ = [
    "KnowledgeSourceIdempotencyConflictError",
    "PostgresKnowledgeSourceOperationRepository",
]
