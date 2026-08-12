"""Persistence seam for durable Knowledge Source synchronization work."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from knowledge_source_service.domain.synchronizations import (
    KnowledgeSourceSynchronizationClaim,
    KnowledgeSourceSynchronizationRecord,
)


class KnowledgeSourceSynchronizationRepository(Protocol):
    def add(self, record: KnowledgeSourceSynchronizationRecord) -> None: ...

    def get(
        self,
        synchronization_id: str,
    ) -> KnowledgeSourceSynchronizationRecord | None: ...

    def get_by_idempotency(
        self,
        *,
        operator_id: str,
        idempotency_key: str,
    ) -> KnowledgeSourceSynchronizationRecord | None: ...

    def claim_next_queued(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_duration: timedelta,
    ) -> KnowledgeSourceSynchronizationClaim | None: ...

    def renew_claim(
        self,
        claim: KnowledgeSourceSynchronizationClaim,
        *,
        now: datetime,
        lease_duration: timedelta,
    ) -> None: ...

    def save_claim(
        self,
        claim: KnowledgeSourceSynchronizationClaim,
        record: KnowledgeSourceSynchronizationRecord,
    ) -> None: ...
