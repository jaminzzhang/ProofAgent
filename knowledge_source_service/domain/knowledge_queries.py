"""Internal authority records for Knowledge Query persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from knowledge_source_service.contracts.knowledge_query import (
    CreateKnowledgeQueryRequest,
    KnowledgeQuery,
)
from knowledge_source_service.ports.authorization import KnowledgeQueryAdmission


@dataclass(frozen=True)
class KnowledgeQueryRecord:
    """Public resource plus service-only ownership and idempotency facts."""

    query: KnowledgeQuery
    request: CreateKnowledgeQueryRequest
    client_id: str
    idempotency_key: str
    request_fingerprint: str
    admission: KnowledgeQueryAdmission
    state_version: int = 1


@dataclass(frozen=True)
class KnowledgeQueryClaim:
    """One leased execution right protected by a monotonically increasing fence."""

    record: KnowledgeQueryRecord
    worker_id: str
    fencing_token: int
    lease_expires_at: datetime


class KnowledgeQueryPersistenceConflict(RuntimeError):
    """A durable uniqueness, version, or immutable-record invariant was violated."""


class StaleKnowledgeQueryClaim(RuntimeError):
    """The worker no longer owns the fenced execution right."""
