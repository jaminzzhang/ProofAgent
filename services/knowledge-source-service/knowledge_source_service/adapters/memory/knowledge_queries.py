"""In-memory Knowledge Query repository for deterministic tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from knowledge_source_service.contracts.knowledge_query import KnowledgeQuery
from knowledge_source_service.domain.knowledge_queries import (
    KnowledgeQueryClaim,
    KnowledgeQueryPersistenceConflict,
    KnowledgeQueryRecord,
    StaleKnowledgeQueryClaim,
)


class InMemoryKnowledgeQueryRepository:
    """Store Query resources without acting as a production fallback."""

    def __init__(self) -> None:
        self._queries: dict[str, KnowledgeQueryRecord] = {}
        self._idempotency: dict[tuple[str, str], KnowledgeQueryRecord] = {}
        self._claims: dict[str, KnowledgeQueryClaim] = {}
        self._fencing_tokens: dict[str, int] = {}

    def add(self, record: KnowledgeQueryRecord) -> None:
        query_id = record.query.knowledge_query_id
        current = self._queries.get(query_id)
        if current is None:
            persisted = replace(record, state_version=1)
        else:
            if (
                record.state_version != current.state_version
                or record.request != current.request
                or record.client_id != current.client_id
                or record.idempotency_key != current.idempotency_key
                or record.request_fingerprint != current.request_fingerprint
                or record.admission != current.admission
            ):
                raise KnowledgeQueryPersistenceConflict(
                    "Knowledge Query state version or immutable authority changed"
                )
            persisted = replace(record, state_version=current.state_version + 1)
        self._queries[query_id] = persisted
        self._idempotency[(persisted.client_id, persisted.idempotency_key)] = persisted
        if persisted.query.state in {"succeeded", "failed", "cancelled", "expired"}:
            self._claims.pop(record.query.knowledge_query_id, None)

    def get(self, knowledge_query_id: str) -> KnowledgeQueryRecord | None:
        return self._queries.get(knowledge_query_id)

    def get_by_idempotency(
        self,
        *,
        client_id: str,
        idempotency_key: str,
    ) -> KnowledgeQueryRecord | None:
        return self._idempotency.get((client_id, idempotency_key))

    def claim_next_queued(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_duration: timedelta,
    ) -> KnowledgeQueryClaim | None:
        if not worker_id.strip():
            raise ValueError("worker_id must not be blank")
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        candidates = sorted(
            (
                record
                for record in self._queries.values()
                if record.query.state in {"queued", "running"}
                and (
                    (current := self._claims.get(record.query.knowledge_query_id)) is None
                    or current.lease_expires_at <= now
                )
            ),
            key=lambda record: (record.query.submitted_at, record.query.knowledge_query_id),
        )
        if not candidates:
            return None
        record = candidates[0]
        query_id = record.query.knowledge_query_id
        fencing_token = self._fencing_tokens.get(query_id, 0) + 1
        claim = KnowledgeQueryClaim(
            record=record,
            worker_id=worker_id,
            fencing_token=fencing_token,
            lease_expires_at=now + lease_duration,
        )
        self._claims[query_id] = claim
        self._fencing_tokens[query_id] = fencing_token
        return claim

    def save_claim(
        self,
        claim: KnowledgeQueryClaim,
        record: KnowledgeQueryRecord,
    ) -> None:
        query_id = claim.record.query.knowledge_query_id
        current = self._claims.get(query_id)
        if (
            current is None
            or current.worker_id != claim.worker_id
            or current.fencing_token != claim.fencing_token
        ):
            raise StaleKnowledgeQueryClaim(
                "Knowledge Query execution claim is no longer current"
            )
        if (
            record.query.knowledge_query_id != query_id
            or record.request != claim.record.request
            or record.client_id != claim.record.client_id
            or record.idempotency_key != claim.record.idempotency_key
            or record.request_fingerprint != claim.record.request_fingerprint
            or record.admission != claim.record.admission
        ):
            raise ValueError("a claim cannot mutate immutable Knowledge Query authority")
        validated = KnowledgeQuery.model_validate(record.query.model_dump(mode="python"))
        persisted = KnowledgeQueryRecord(
            query=validated,
            request=record.request,
            client_id=record.client_id,
            idempotency_key=record.idempotency_key,
            request_fingerprint=record.request_fingerprint,
            admission=record.admission,
            state_version=self._queries[query_id].state_version + 1,
        )
        self._queries[query_id] = persisted
        self._idempotency[(persisted.client_id, persisted.idempotency_key)] = persisted
        if validated.state in {"succeeded", "failed", "cancelled", "expired"}:
            self._claims.pop(query_id, None)

    def renew_claim(
        self,
        claim: KnowledgeQueryClaim,
        *,
        now: datetime,
        lease_duration: timedelta,
    ) -> None:
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        query_id = claim.record.query.knowledge_query_id
        current = self._claims.get(query_id)
        record = self._queries.get(query_id)
        if (
            current is None
            or record is None
            or record.query.state != "running"
            or current.worker_id != claim.worker_id
            or current.fencing_token != claim.fencing_token
            or current.lease_expires_at <= now
        ):
            raise StaleKnowledgeQueryClaim(
                "Knowledge Query execution claim is no longer current"
            )
        self._claims[query_id] = replace(
            current,
            lease_expires_at=max(
                current.lease_expires_at,
                now + lease_duration,
            ),
        )
