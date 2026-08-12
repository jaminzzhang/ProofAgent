"""Persistence interface for Knowledge Query resources."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from knowledge_source_service.domain.knowledge_queries import (
    KnowledgeQueryClaim,
    KnowledgeQueryRecord,
)


class KnowledgeQueryRepository(Protocol):
    """Persist public Query state behind one application seam."""

    def add(self, record: KnowledgeQueryRecord) -> None: ...

    def get(self, knowledge_query_id: str) -> KnowledgeQueryRecord | None: ...

    def get_by_idempotency(
        self,
        *,
        client_id: str,
        idempotency_key: str,
    ) -> KnowledgeQueryRecord | None: ...

    def claim_next_queued(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_duration: timedelta,
    ) -> KnowledgeQueryClaim | None: ...

    def renew_claim(
        self,
        claim: KnowledgeQueryClaim,
        *,
        now: datetime,
        lease_duration: timedelta,
    ) -> None: ...

    def save_claim(
        self,
        claim: KnowledgeQueryClaim,
        record: KnowledgeQueryRecord,
    ) -> None: ...
