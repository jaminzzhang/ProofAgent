"""Create and inspect durable Knowledge Source synchronization resources."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json

from knowledge_source_service.contracts.synchronizations import (
    CreateKnowledgeSourceSynchronizationRequest,
    KnowledgeSourceSynchronization,
    KnowledgeSourceSynchronizationLinks,
)
from knowledge_source_service.domain.synchronizations import (
    KnowledgeSourceSynchronizationRecord,
)
from knowledge_source_service.ports.synchronizations import (
    KnowledgeSourceSynchronizationRepository,
)


class KnowledgeSourceSynchronizationIdempotencyConflict(ValueError):
    """One operator-scoped key already names another synchronization request."""


class KnowledgeSnapshotConnectionUnavailable(ValueError):
    """The configured connection is not admitted by this service deployment."""


@dataclass(frozen=True)
class KnowledgeSourceSynchronizationCreation:
    synchronization: KnowledgeSourceSynchronization
    created: bool


class KnowledgeSourceSynchronizationApplication:
    def __init__(
        self,
        *,
        repository: KnowledgeSourceSynchronizationRepository,
        clock: Callable[[], datetime],
        id_factory: Callable[[], str],
        admit_connection: Callable[[str], bool],
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._id_factory = id_factory
        self._admit_connection = admit_connection

    def create(
        self,
        request: CreateKnowledgeSourceSynchronizationRequest,
        *,
        operator_id: str,
        idempotency_key: str,
    ) -> KnowledgeSourceSynchronizationCreation:
        if not operator_id.strip() or not 1 <= len(idempotency_key.strip()) <= 256:
            raise ValueError("synchronization authority identity is invalid")
        fingerprint = _request_fingerprint(request)
        existing = self._repository.get_by_idempotency(
            operator_id=operator_id,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise KnowledgeSourceSynchronizationIdempotencyConflict
            return KnowledgeSourceSynchronizationCreation(
                synchronization=existing.synchronization,
                created=False,
            )
        if not self._admit_connection(request.connection_id):
            raise KnowledgeSnapshotConnectionUnavailable
        synchronization_id = self._id_factory()
        synchronization = KnowledgeSourceSynchronization(
            knowledge_source_synchronization_id=synchronization_id,
            knowledge_space_id=request.knowledge_space_id,
            knowledge_source_id=request.knowledge_source_id,
            connection_id=request.connection_id,
            state="queued",
            submitted_at=self._clock(),
            links=KnowledgeSourceSynchronizationLinks(
                self=(
                    "/v1/knowledge-source-synchronizations/"
                    f"{synchronization_id}"
                )
            ),
        )
        self._repository.add(
            KnowledgeSourceSynchronizationRecord(
                synchronization=synchronization,
                request=request,
                operator_id=operator_id,
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
            )
        )
        return KnowledgeSourceSynchronizationCreation(
            synchronization=synchronization,
            created=True,
        )

    def get(
        self,
        synchronization_id: str,
        *,
        operator_id: str,
    ) -> KnowledgeSourceSynchronization | None:
        record = self._repository.get(synchronization_id)
        if record is None or record.operator_id != operator_id:
            return None
        return record.synchronization


def _request_fingerprint(
    request: CreateKnowledgeSourceSynchronizationRequest,
) -> str:
    canonical_json = json.dumps(
        request.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = sha256(
        f"knowledge-source-synchronization.v1\0{canonical_json}".encode()
    ).hexdigest()
    return f"sha256:{digest}"
