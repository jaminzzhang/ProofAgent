"""Ports for durable Knowledge Source command admission and operations."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from proof_agent.contracts.knowledge_source_api import KnowledgeSourceOperation


class KnowledgeSourceIdempotencyConflictError(RuntimeError):
    """An idempotency scope was reused with a different canonical request."""


class KnowledgeSourceOperationRepository(Protocol):
    def replay(
        self,
        *,
        operator_subject: str,
        source_id: str,
        command: str,
        idempotency_key: str,
        request_sha256: str,
    ) -> KnowledgeSourceOperation | None: ...

    def admit(
        self,
        operation: KnowledgeSourceOperation,
        *,
        operator_subject: str,
        idempotency_key: str,
        request_sha256: str,
        expires_at: datetime,
    ) -> tuple[KnowledgeSourceOperation, bool]: ...

    def save(self, operation: KnowledgeSourceOperation) -> KnowledgeSourceOperation: ...

    def get(self, operation_id: str) -> KnowledgeSourceOperation | None: ...


__all__ = [
    "KnowledgeSourceIdempotencyConflictError",
    "KnowledgeSourceOperationRepository",
]
