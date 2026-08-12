from __future__ import annotations

from datetime import UTC, datetime, timedelta
import threading
from typing import Any

import pytest

from knowledge_source_service.adapters.memory.synchronizations import (
    InMemoryKnowledgeSourceSynchronizationRepository,
)
from knowledge_source_service.adapters.memory.artifacts import (
    InMemoryImmutableArtifactStore,
)
from knowledge_source_service.adapters.memory.knowledge_catalog import (
    InMemoryKnowledgeCatalog,
)
from knowledge_source_service.application.hybrid_retrieval import (
    HybridKnowledgeRetrievalEngine,
)
from knowledge_source_service.application.knowledge_releases import (
    KnowledgeReleaseApplication,
    PublishKnowledgeReleaseCommand,
)
from knowledge_source_service.application.synchronization_executor import (
    KnowledgeSourceSynchronizationExecutor,
)
from knowledge_source_service.application.synchronizations import (
    KnowledgeSourceSynchronizationApplication,
    KnowledgeSourceSynchronizationIdempotencyConflict,
)
from knowledge_source_service.contracts.synchronizations import (
    CreateKnowledgeSourceSynchronizationRequest,
)
from knowledge_source_service.contracts.knowledge_query import (
    CreateKnowledgeQueryRequest,
)
from knowledge_source_service.domain.identities import sha256_text
from knowledge_source_service.ports.authorization import KnowledgeQueryAdmission
from knowledge_source_service.ports.retrieval import AdmittedKnowledgeQuery
from knowledge_source_service.ports.snapshot_connections import (
    JsonSnapshotConnection,
)
from knowledge_source_service.ports.snapshots import JsonSnapshot


def test_synchronization_create_is_operator_scoped_and_exactly_idempotent() -> None:
    application = KnowledgeSourceSynchronizationApplication(
        repository=InMemoryKnowledgeSourceSynchronizationRepository(),
        clock=lambda: datetime(2026, 8, 12, 11, 0, tzinfo=UTC),
        id_factory=lambda: "source-sync-1",
        admit_connection=lambda connection_id: connection_id == "connection-claims",
    )
    request = CreateKnowledgeSourceSynchronizationRequest.model_validate(
        {
            "knowledge_space_id": "space-claims",
            "knowledge_source_id": "source-claims",
            "connection_id": "connection-claims",
            "display_filename": "claims.snapshot.json",
            "record_path": ["claims"],
            "field_types": {
                "claim_id": "string",
                "claim_total": "decimal",
            },
        }
    )

    created = application.create(
        request,
        operator_id="operator-1",
        idempotency_key="sync-attempt-1",
    )
    replayed = application.create(
        request,
        operator_id="operator-1",
        idempotency_key="sync-attempt-1",
    )

    assert created.created is True
    assert replayed.created is False
    assert replayed.synchronization == created.synchronization
    assert created.synchronization.model_dump(mode="json") == {
        "schema_version": "knowledge-source-synchronization.v1",
        "knowledge_source_synchronization_id": "source-sync-1",
        "knowledge_space_id": "space-claims",
        "knowledge_source_id": "source-claims",
        "connection_id": "connection-claims",
        "state": "queued",
        "submitted_at": "2026-08-12T11:00:00Z",
        "started_at": None,
        "completed_at": None,
        "materialized_knowledge_source_version_id": None,
        "problem": None,
        "links": {
            "self": "/v1/knowledge-source-synchronizations/source-sync-1"
        },
    }

    changed = request.model_copy(update={"record_path": ()})
    with pytest.raises(KnowledgeSourceSynchronizationIdempotencyConflict):
        application.create(
            changed,
            operator_id="operator-1",
            idempotency_key="sync-attempt-1",
        )


class _CountingSnapshotReader:
    def __init__(self) -> None:
        self.calls = 0

    def read(self) -> JsonSnapshot:
        self.calls += 1
        return JsonSnapshot(
            content=(
                b'{"claims":[{"claim_id":"claim-1",'
                b'"claim_total":"12345.67"}]}'
            ),
            source_identity_digest=sha256_text(
                "https://claims.example.test/v1/claims"
            ),
            observed_at=datetime(2026, 8, 12, 11, 1, tzinfo=UTC),
            etag='"claims-v7"',
            last_modified=None,
        )


class _SnapshotRegistry:
    def __init__(self, reader: _CountingSnapshotReader) -> None:
        self._reader = reader

    def contains(self, connection_id: str) -> bool:
        return connection_id == "connection-claims"

    def resolve(self, connection_id: str) -> JsonSnapshotConnection:
        assert self.contains(connection_id)
        return JsonSnapshotConnection(
            connection_id=connection_id,
            connection_kind="http_json",
            reader=self._reader,
        )


class _RenewalObservingSynchronizationRepository(
    InMemoryKnowledgeSourceSynchronizationRepository
):
    def __init__(self) -> None:
        super().__init__()
        self.renewed = threading.Event()
        self.renewal_count = 0

    def renew_claim(
        self,
        claim: Any,
        *,
        now: datetime,
        lease_duration: timedelta,
    ) -> None:
        super().renew_claim(claim, now=now, lease_duration=lease_duration)
        self.renewal_count += 1
        self.renewed.set()


class _LeaseAwareSnapshotReader(_CountingSnapshotReader):
    def __init__(
        self,
        *,
        repository: _RenewalObservingSynchronizationRepository,
        contender_at: datetime,
    ) -> None:
        super().__init__()
        self._repository = repository
        self._contender_at = contender_at
        self.contender_claim: Any = "not-attempted"

    def read(self) -> JsonSnapshot:
        assert self._repository.renewed.wait(timeout=0.5)
        self.contender_claim = self._repository.claim_next_queued(
            worker_id="knowledge-worker-contender",
            now=self._contender_at,
            lease_duration=timedelta(milliseconds=90),
        )
        return super().read()


def test_worker_materializes_snapshot_before_any_release_query() -> None:
    repository = InMemoryKnowledgeSourceSynchronizationRepository()
    artifacts = InMemoryImmutableArtifactStore()
    catalog = InMemoryKnowledgeCatalog()
    reader = _CountingSnapshotReader()
    registry = _SnapshotRegistry(reader)
    application = KnowledgeSourceSynchronizationApplication(
        repository=repository,
        clock=lambda: datetime(2026, 8, 12, 11, 0, tzinfo=UTC),
        id_factory=lambda: "source-sync-worker-1",
        admit_connection=registry.contains,
    )
    application.create(
        CreateKnowledgeSourceSynchronizationRequest.model_validate(
            {
                "knowledge_space_id": "space-sync-worker",
                "knowledge_source_id": "source-sync-worker",
                "connection_id": "connection-claims",
                "display_filename": "claims.snapshot.json",
                "record_path": ["claims"],
                "field_types": {
                    "claim_id": "string",
                    "claim_total": "decimal",
                },
            }
        ),
        operator_id="operator-1",
        idempotency_key="sync-worker-attempt-1",
    )
    clock_values = iter(
        (
            datetime(2026, 8, 12, 11, 0, 1, tzinfo=UTC),
            datetime(2026, 8, 12, 11, 0, 2, tzinfo=UTC),
        )
    )
    executor = KnowledgeSourceSynchronizationExecutor(
        repository=repository,
        connections=registry,
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision="dataset-pipeline-v1",
        max_content_bytes=4096,
        max_records=10,
        clock=lambda: next(clock_values),
        trace_id_factory=lambda: "trace-source-sync-1",
        worker_id="knowledge-worker-1",
        lease_duration=timedelta(seconds=30),
    )

    worked = executor.run_once()
    completed = application.get(
        "source-sync-worker-1",
        operator_id="operator-1",
    )

    assert worked is True
    assert completed is not None
    assert completed.state == "succeeded"
    assert completed.materialized_knowledge_source_version_id is not None
    assert reader.calls == 1

    release = KnowledgeReleaseApplication(
        artifacts=artifacts,
        catalog=catalog,
    ).publish(
        PublishKnowledgeReleaseCommand(
            knowledge_space_id="space-sync-worker",
            knowledge_base_id="base-sync-worker",
            knowledge_source_version_ids=(
                completed.materialized_knowledge_source_version_id,
            ),
        )
    ).release
    result = HybridKnowledgeRetrievalEngine(catalog=catalog).retrieve(
        AdmittedKnowledgeQuery(
            request=CreateKnowledgeQueryRequest.model_validate(
                {
                    "knowledge_base_release_id": release.knowledge_base_release_id,
                    "question": "claim totals",
                    "execution_budget": {
                        "max_rounds": 1,
                        "max_model_calls": 1,
                        "max_candidates": 10,
                        "max_model_tokens": 100,
                        "max_duration_ms": 1000,
                    },
                    "deadline_at": "2026-08-12T12:00:00Z",
                }
            ),
            admission=KnowledgeQueryAdmission(
                knowledge_space_id="space-sync-worker",
                client_grant_id="grant-sync-worker",
                effective_access_scope_digest=f"sha256:{'a' * 64}",
            ),
        )
    )

    assert reader.calls == 1
    assert (
        result.evidence_groups[0]
        .candidate_evidence[0]
        .content.structured_data.fields[1]
        .value
        == "12345.67"
    )


def test_synchronization_worker_renews_its_fenced_lease_during_capture() -> None:
    base = datetime(2026, 8, 12, 11, 30, tzinfo=UTC)
    repository = _RenewalObservingSynchronizationRepository()
    artifacts = InMemoryImmutableArtifactStore()
    catalog = InMemoryKnowledgeCatalog()
    reader = _LeaseAwareSnapshotReader(
        repository=repository,
        contender_at=base + timedelta(milliseconds=100),
    )
    registry = _SnapshotRegistry(reader)
    application = KnowledgeSourceSynchronizationApplication(
        repository=repository,
        clock=lambda: base - timedelta(seconds=1),
        id_factory=lambda: "source-sync-renewal-1",
        admit_connection=registry.contains,
    )
    application.create(
        CreateKnowledgeSourceSynchronizationRequest.model_validate(
            {
                "knowledge_space_id": "space-sync-renewal",
                "knowledge_source_id": "source-sync-renewal",
                "connection_id": "connection-claims",
                "display_filename": "claims.snapshot.json",
                "record_path": ["claims"],
                "field_types": {
                    "claim_id": "string",
                    "claim_total": "decimal",
                },
            }
        ),
        operator_id="operator-1",
        idempotency_key="sync-renewal-attempt-1",
    )
    clock_values = iter(
        (
            base,
            base + timedelta(milliseconds=60),
            base + timedelta(milliseconds=70),
        )
    )
    executor = KnowledgeSourceSynchronizationExecutor(
        repository=repository,
        connections=registry,
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision="dataset-pipeline-v1",
        max_content_bytes=4096,
        max_records=10,
        clock=lambda: next(clock_values),
        trace_id_factory=lambda: "trace-source-sync-renewal-1",
        worker_id="knowledge-worker-1",
        lease_duration=timedelta(milliseconds=90),
    )

    executor.run_once()
    completed = application.get(
        "source-sync-renewal-1",
        operator_id="operator-1",
    )

    assert repository.renewal_count == 1
    assert reader.contender_claim is None
    assert completed is not None
    assert completed.state == "succeeded"
