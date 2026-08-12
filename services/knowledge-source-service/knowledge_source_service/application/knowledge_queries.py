"""Application module for creating and operating Knowledge Queries."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from hashlib import sha256
import json

from knowledge_source_service.contracts.knowledge_query import (
    CreateKnowledgeQueryRequest,
    KnowledgeQuery,
    KnowledgeQueryLinks,
)
from knowledge_source_service.domain.knowledge_queries import KnowledgeQueryRecord
from knowledge_source_service.ports.authorization import KnowledgeQueryAuthorizer
from knowledge_source_service.ports.knowledge_queries import KnowledgeQueryRepository


@dataclass(frozen=True)
class KnowledgeServiceClient:
    """Authenticated service identity supplied by the transport adapter."""

    client_id: str


@dataclass(frozen=True)
class KnowledgeQueryCreation:
    """Outcome needed by HTTP to distinguish creation from exact replay."""

    query: KnowledgeQuery
    replayed: bool


class IdempotencyKeyMismatch(ValueError):
    """One client-scoped key is already bound to another request fingerprint."""


class KnowledgeQueryDeadlineElapsed(ValueError):
    """The requested absolute execution deadline is not after submission."""


class KnowledgeQueryTerminalStateConflict(ValueError):
    """A cancellation command cannot rewrite an immutable terminal state."""


class KnowledgeQueryAccessDenied(PermissionError):
    """The authenticated client has no valid grant for the selected Release."""


class KnowledgeQueryApplication:
    """Create durable Query resources without exposing persistence details."""

    def __init__(
        self,
        *,
        repository: KnowledgeQueryRepository,
        authorizer: KnowledgeQueryAuthorizer,
        clock: Callable[[], datetime],
        id_factory: Callable[[], str],
    ) -> None:
        self._repository = repository
        self._authorizer = authorizer
        self._clock = clock
        self._id_factory = id_factory

    def create(
        self,
        request: CreateKnowledgeQueryRequest,
        *,
        client: KnowledgeServiceClient,
        idempotency_key: str,
    ) -> KnowledgeQueryCreation:
        """Create one queued resource for an already-authenticated client."""

        admission = self._authorizer.authorize(
            client_id=client.client_id,
            request=request,
        )
        if admission is None:
            raise KnowledgeQueryAccessDenied

        request_fingerprint = _fingerprint_request(request)
        existing = self._repository.get_by_idempotency(
            client_id=client.client_id,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            if existing.request_fingerprint != request_fingerprint:
                raise IdempotencyKeyMismatch
            return KnowledgeQueryCreation(
                query=_retention_safe_view(existing.query, now=self._clock()),
                replayed=True,
            )

        submitted_at = self._clock()
        if request.deadline_at <= submitted_at:
            raise KnowledgeQueryDeadlineElapsed

        knowledge_query_id = self._id_factory()
        self_link = f"/v1/knowledge-queries/{knowledge_query_id}"
        query = KnowledgeQuery(
            knowledge_query_id=knowledge_query_id,
            knowledge_base_release_id=request.knowledge_base_release_id,
            state="queued",
            submitted_at=submitted_at,
            deadline_at=request.deadline_at,
            result_availability="pending",
            links=KnowledgeQueryLinks(
                self=self_link,
                cancel=f"{self_link}:cancel",
            ),
        )
        self._repository.add(
            KnowledgeQueryRecord(
                query=query,
                request=request,
                client_id=client.client_id,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
                admission=admission,
            )
        )
        return KnowledgeQueryCreation(query=query, replayed=False)

    def get(
        self,
        knowledge_query_id: str,
        *,
        client: KnowledgeServiceClient,
    ) -> KnowledgeQuery | None:
        """Return one visible Query resource when it exists."""

        record = self._repository.get(knowledge_query_id)
        if record is None or record.client_id != client.client_id:
            return None
        return _retention_safe_view(record.query, now=self._clock())

    def cancel(
        self,
        knowledge_query_id: str,
        *,
        client: KnowledgeServiceClient,
    ) -> KnowledgeQuery | None:
        """Cancel one visible queued or running Query without changing its identity."""

        record = self._repository.get(knowledge_query_id)
        if record is None or record.client_id != client.client_id:
            return None
        if record.query.state == "cancelled":
            return record.query
        if record.query.state in {"succeeded", "failed", "expired"}:
            raise KnowledgeQueryTerminalStateConflict

        now = self._clock()
        payload = record.query.model_dump(mode="python")
        payload.update(
            state="cancelled",
            cancel_requested_at=now,
            completed_at=now,
            result_availability="unavailable",
        )
        cancelled = KnowledgeQuery.model_validate(payload)
        self._repository.add(replace(record, query=cancelled))
        return cancelled


def _fingerprint_request(request: CreateKnowledgeQueryRequest) -> str:
    canonical_json = json.dumps(
        request.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = sha256(f"knowledge-query.v1\0{canonical_json}".encode()).hexdigest()
    return f"sha256:{digest}"


def _retention_safe_view(query: KnowledgeQuery, *, now: datetime) -> KnowledgeQuery:
    if (
        query.state != "succeeded"
        or query.result_availability != "available"
        or query.result_expires_at is None
        or query.result_expires_at > now
    ):
        return query
    payload = query.model_dump(mode="python")
    payload.update(result_availability="expired", result=None)
    return KnowledgeQuery.model_validate(payload)
