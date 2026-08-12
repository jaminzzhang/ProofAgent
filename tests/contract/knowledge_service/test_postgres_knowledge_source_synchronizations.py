from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from knowledge_source_service.adapters.memory.artifacts import (
    InMemoryImmutableArtifactStore,
)
from knowledge_source_service.adapters.postgres.knowledge_catalog import (
    PostgresKnowledgeCatalog,
)
from knowledge_source_service.adapters.postgres.migrations import (
    apply_knowledge_service_migrations,
)
from knowledge_source_service.adapters.postgres.synchronizations import (
    PostgresKnowledgeSourceSynchronizationRepository,
)
from knowledge_source_service.application.synchronizations import (
    KnowledgeSourceSynchronizationApplication,
)
from knowledge_source_service.contracts.synchronizations import (
    CreateKnowledgeSourceSynchronizationRequest,
)
from knowledge_source_service.domain.synchronizations import (
    StaleKnowledgeSourceSynchronizationClaim,
)


pytestmark = pytest.mark.postgres_integration


def test_postgres_synchronization_queue_renews_and_fences_claims(
    kss_postgres_dsn: str,
) -> None:
    apply_knowledge_service_migrations(kss_postgres_dsn)
    catalog = PostgresKnowledgeCatalog.from_dsn(
        kss_postgres_dsn,
        artifacts=InMemoryImmutableArtifactStore(),
    )
    catalog.create_space("space-sync-queue")
    catalog.create_source(
        knowledge_space_id="space-sync-queue",
        knowledge_source_id="source-sync-queue",
    )
    repository = PostgresKnowledgeSourceSynchronizationRepository.from_dsn(
        kss_postgres_dsn
    )
    created = KnowledgeSourceSynchronizationApplication(
        repository=repository,
        clock=lambda: datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
        id_factory=lambda: "source-sync-queue-1",
        admit_connection=lambda connection_id: connection_id == "connection-queue",
    ).create(
        CreateKnowledgeSourceSynchronizationRequest.model_validate(
            {
                "knowledge_space_id": "space-sync-queue",
                "knowledge_source_id": "source-sync-queue",
                "connection_id": "connection-queue",
                "display_filename": "claims.json",
                "record_path": ["records"],
                "field_types": {"claim_id": "string"},
            }
        ),
        operator_id="operator-sync",
        idempotency_key="sync-queue-attempt-1",
    )

    claim = repository.claim_next_queued(
        worker_id="knowledge-worker-a",
        now=datetime(2026, 8, 12, 12, 0, 1, tzinfo=UTC),
        lease_duration=timedelta(seconds=30),
    )
    assert claim is not None
    running = claim.record.synchronization.model_copy(
        update={
            "state": "running",
            "started_at": datetime(2026, 8, 12, 12, 0, 1, tzinfo=UTC),
        }
    )
    repository.save_claim(claim, replace(claim.record, synchronization=running))
    repository.renew_claim(
        claim,
        now=datetime(2026, 8, 12, 12, 0, 20, tzinfo=UTC),
        lease_duration=timedelta(seconds=30),
    )

    blocked = repository.claim_next_queued(
        worker_id="knowledge-worker-b",
        now=datetime(2026, 8, 12, 12, 0, 32, tzinfo=UTC),
        lease_duration=timedelta(seconds=30),
    )
    takeover = repository.claim_next_queued(
        worker_id="knowledge-worker-b",
        now=datetime(2026, 8, 12, 12, 0, 51, tzinfo=UTC),
        lease_duration=timedelta(seconds=30),
    )

    assert created.synchronization.state == "queued"
    assert repository.get("source-sync-queue-1") is not None
    assert blocked is None
    assert takeover is not None
    assert takeover.fencing_token == claim.fencing_token + 1
    with pytest.raises(StaleKnowledgeSourceSynchronizationClaim):
        repository.save_claim(claim, replace(claim.record, synchronization=running))
    repository.close()
    catalog.close()
