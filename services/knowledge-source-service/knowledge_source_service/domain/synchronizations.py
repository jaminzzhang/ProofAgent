"""Internal durable authority records for Knowledge Source synchronization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from knowledge_source_service.contracts.synchronizations import (
    CreateKnowledgeSourceSynchronizationRequest,
    KnowledgeSourceSynchronization,
)


@dataclass(frozen=True)
class KnowledgeSourceSynchronizationRecord:
    synchronization: KnowledgeSourceSynchronization
    request: CreateKnowledgeSourceSynchronizationRequest
    operator_id: str
    idempotency_key: str
    request_fingerprint: str
    state_version: int = 1


@dataclass(frozen=True)
class KnowledgeSourceSynchronizationClaim:
    record: KnowledgeSourceSynchronizationRecord
    worker_id: str
    fencing_token: int
    lease_expires_at: datetime


class KnowledgeSourceSynchronizationPersistenceConflict(RuntimeError):
    """A durable synchronization uniqueness or CAS invariant was violated."""


class StaleKnowledgeSourceSynchronizationClaim(RuntimeError):
    """A worker no longer owns the fenced synchronization execution right."""
