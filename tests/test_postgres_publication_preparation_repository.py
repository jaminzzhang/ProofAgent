from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from proof_agent.capabilities.knowledge.hybrid.publication_jobs import (
    PublicationPreparationJob,
)
from proof_agent.capabilities.persistence.postgres.bundle import PostgresPersistenceBundle
from proof_agent.capabilities.persistence.postgres.database import upgrade_database
from proof_agent.capabilities.persistence.postgres.publication_preparation_repository import (
    PublicationPreparationClaimRejectedError,
    PostgresPublicationPreparationRepository,
)
from proof_agent.contracts import (
    KnowledgeSource,
    KnowledgeSourceLifecycleState,
    KnowledgeSourceOperation,
)


pytestmark = pytest.mark.postgres_integration
pytest_plugins = ("postgres_fixtures",)


def test_pg_publication_preparation_reclaims_expired_lease_and_fences_stale_owner(
    postgres_dsn: str,
) -> None:
    upgrade_database(postgres_dsn)
    bundle = PostgresPersistenceBundle.create(postgres_dsn)
    now = datetime(2026, 7, 27, 12, tzinfo=UTC)
    current = [now]
    repository = PostgresPublicationPreparationRepository(
        bundle.engine,
        clock=lambda: current[0],
    )
    operation_id = f"ksop_{uuid4().hex}"
    source_id = f"ks_{uuid4().hex}"
    bundle.knowledge.save_source(
        KnowledgeSource(
            source_id=source_id,
            name="Publication preparation",
            provider="hybrid_index",
            lifecycle_state=KnowledgeSourceLifecycleState.ACTIVE,
            params={},
            source_draft_version_id=str(uuid4()),
            created_at="2026-07-27T12:00:00Z",
            updated_at="2026-07-27T12:00:00Z",
        ),
        expected_revision=0,
    )
    bundle.knowledge_source_operations.save(
        KnowledgeSourceOperation(
            operation_id=operation_id,
            source_id=source_id,
            command="prepare_publication",
            status="queued",
            stage="publication_preparation_queued",
            source_revision=9,
            poll_after_ms=1_000,
            created_at="2026-07-27T12:00:00Z",
            updated_at="2026-07-27T12:00:00Z",
        )
    )
    job = PublicationPreparationJob(
        preparation_job_id=str(uuid4()),
        operation_id=operation_id,
        validation_id=f"kspubval_{uuid4().hex}",
        source_id=source_id,
        source_revision=9,
        source_draft_version_id=str(uuid4()),
        smoke_query="What policy term is covered?",
        state="READY",
        fencing_token=0,
        created_by="publisher-1",
        created_at=now,
        updated_at=now,
    )
    try:
        assert repository.enqueue(job) == job
        first = repository.claim_next(worker_id="worker-1", lease_seconds=30)
        assert first is not None
        assert first.fencing_token == 1

        current[0] = now + timedelta(seconds=31)
        second = repository.claim_next(worker_id="worker-2", lease_seconds=30)
        assert second is not None
        assert second.fencing_token == 2
        with pytest.raises(PublicationPreparationClaimRejectedError):
            repository.fail(
                first,
                failure_code="stale",
                safe_reason="stale owner",
            )

        failed = repository.fail(
            second,
            failure_code="publication_preparation_failed",
            safe_reason="Publication preparation failed.",
        )
        assert failed.state == "FAILED"
        assert repository.claim_next(
            worker_id="worker-3",
            lease_seconds=30,
        ) is None
    finally:
        bundle.close()
