"""In-memory synchronization repository used only by deterministic tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from knowledge_source_service.domain.synchronizations import (
    KnowledgeSourceSynchronizationClaim,
    KnowledgeSourceSynchronizationPersistenceConflict,
    KnowledgeSourceSynchronizationRecord,
    StaleKnowledgeSourceSynchronizationClaim,
)


class InMemoryKnowledgeSourceSynchronizationRepository:
    def __init__(self) -> None:
        self._records: dict[str, KnowledgeSourceSynchronizationRecord] = {}
        self._idempotency: dict[tuple[str, str], str] = {}
        self._claims: dict[str, KnowledgeSourceSynchronizationClaim] = {}
        self._fences: dict[str, int] = {}

    def add(self, record: KnowledgeSourceSynchronizationRecord) -> None:
        synchronization_id = (
            record.synchronization.knowledge_source_synchronization_id
        )
        idempotency_identity = (record.operator_id, record.idempotency_key)
        if synchronization_id in self._records or idempotency_identity in self._idempotency:
            raise KnowledgeSourceSynchronizationPersistenceConflict(
                "synchronization identity already exists"
            )
        persisted = replace(record, state_version=1)
        self._records[synchronization_id] = persisted
        self._idempotency[idempotency_identity] = synchronization_id

    def get(
        self,
        synchronization_id: str,
    ) -> KnowledgeSourceSynchronizationRecord | None:
        return self._records.get(synchronization_id)

    def get_by_idempotency(
        self,
        *,
        operator_id: str,
        idempotency_key: str,
    ) -> KnowledgeSourceSynchronizationRecord | None:
        synchronization_id = self._idempotency.get((operator_id, idempotency_key))
        return None if synchronization_id is None else self._records[synchronization_id]

    def claim_next_queued(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_duration: timedelta,
    ) -> KnowledgeSourceSynchronizationClaim | None:
        if not worker_id.strip() or lease_duration <= timedelta(0):
            raise ValueError("synchronization claim configuration is invalid")
        candidates = sorted(
            (
                record
                for synchronization_id, record in self._records.items()
                if record.synchronization.state in {"queued", "running"}
                and (
                    (claim := self._claims.get(synchronization_id)) is None
                    or claim.lease_expires_at <= now
                )
            ),
            key=lambda record: (
                record.synchronization.submitted_at,
                record.synchronization.knowledge_source_synchronization_id,
            ),
        )
        if not candidates:
            return None
        record = candidates[0]
        synchronization_id = (
            record.synchronization.knowledge_source_synchronization_id
        )
        fencing_token = self._fences.get(synchronization_id, 0) + 1
        claim = KnowledgeSourceSynchronizationClaim(
            record=record,
            worker_id=worker_id,
            fencing_token=fencing_token,
            lease_expires_at=now + lease_duration,
        )
        self._claims[synchronization_id] = claim
        self._fences[synchronization_id] = fencing_token
        return claim

    def renew_claim(
        self,
        claim: KnowledgeSourceSynchronizationClaim,
        *,
        now: datetime,
        lease_duration: timedelta,
    ) -> None:
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        synchronization_id = (
            claim.record.synchronization.knowledge_source_synchronization_id
        )
        current = self._claims.get(synchronization_id)
        record = self._records.get(synchronization_id)
        if (
            current is None
            or record is None
            or record.synchronization.state != "running"
            or current.worker_id != claim.worker_id
            or current.fencing_token != claim.fencing_token
            or current.lease_expires_at <= now
        ):
            raise StaleKnowledgeSourceSynchronizationClaim
        self._claims[synchronization_id] = replace(
            current,
            lease_expires_at=max(current.lease_expires_at, now + lease_duration),
        )

    def save_claim(
        self,
        claim: KnowledgeSourceSynchronizationClaim,
        record: KnowledgeSourceSynchronizationRecord,
    ) -> None:
        synchronization_id = (
            claim.record.synchronization.knowledge_source_synchronization_id
        )
        current = self._claims.get(synchronization_id)
        persisted = self._records.get(synchronization_id)
        if (
            current is None
            or persisted is None
            or current.worker_id != claim.worker_id
            or current.fencing_token != claim.fencing_token
        ):
            raise StaleKnowledgeSourceSynchronizationClaim
        if (
            record.request != persisted.request
            or record.operator_id != persisted.operator_id
            or record.idempotency_key != persisted.idempotency_key
            or record.request_fingerprint != persisted.request_fingerprint
        ):
            raise ValueError("synchronization claim cannot mutate immutable authority")
        updated = replace(record, state_version=persisted.state_version + 1)
        self._records[synchronization_id] = updated
        if updated.synchronization.state in {"succeeded", "failed"}:
            self._claims.pop(synchronization_id, None)
