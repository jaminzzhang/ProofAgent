"""PostgreSQL history tests for Hybrid Knowledge ingestion attempts."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from proof_agent.capabilities.knowledge.ingestion.hybrid_worker import (
    HybridArtifactBuildRequest,
    hybrid_build_request_sha256,
)
from proof_agent.capabilities.persistence.postgres.hybrid_ingestion_repository import (
    PostgresHybridIngestionRepository,
)
from proof_agent.capabilities.persistence.postgres.knowledge_ingestion_attempt_repository import (
    KnowledgeIngestionAttemptConflictError,
    PostgresKnowledgeIngestionAttemptRepository,
)
from proof_agent.capabilities.persistence.postgres.knowledge_repository import (
    PostgresKnowledgeAssetRepository,
)
from proof_agent.contracts import (
    KnowledgeIngestionAttempt,
    KnowledgeSource,
    KnowledgeSourceLifecycleState,
)
from proof_agent.contracts.knowledge_index import ExactArtifactRef


pytestmark = pytest.mark.postgres_integration
pytest_plugins = ("postgres_fixtures",)


def _seed_job(postgres_engine) -> str:
    source_id = f"hybrid-{uuid4()}"
    now = datetime(2026, 7, 27, tzinfo=UTC)
    PostgresKnowledgeAssetRepository(postgres_engine).save_source(
        KnowledgeSource(
            source_id=source_id,
            name="Attempt history",
            provider="hybrid_index",
            lifecycle_state=KnowledgeSourceLifecycleState.ACTIVE,
            params={},
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
        ),
        expected_revision=0,
    )
    request = HybridArtifactBuildRequest(
        job_id=str(uuid4()),
        request_identity=f"{source_id}:document:revision",
        source_id=source_id,
        document_id=str(uuid4()),
        revision_id=str(uuid4()),
        original_ref=ExactArtifactRef(
            artifact_uri="s3://proof-agent/hybrid/original.pdf",
            version_id="opaque-s3-version-id",
            sha256="a" * 64,
            size_bytes=1024,
            media_type="application/pdf",
        ),
        page_numbers=(1,),
        parser_revision="parser-v1",
        model_digests=("sha256:model-v1",),
        configuration_sha256="b" * 64,
    )
    request = request.model_copy(
        update={"request_sha256": hybrid_build_request_sha256(request)}
    )
    jobs = PostgresHybridIngestionRepository(postgres_engine, clock=lambda: now)
    jobs.enqueue(request)
    return request.job_id


def test_pg_ingestion_attempt_history_appends_without_overwriting(
    postgres_engine,
) -> None:
    job_id = _seed_job(postgres_engine)
    repository = PostgresKnowledgeIngestionAttemptRepository(postgres_engine)
    attempt = KnowledgeIngestionAttempt(
        attempt_id=str(uuid4()),
        job_id=job_id,
        attempt_number=1,
        initiation="automatic",
        state="running",
        fencing_token=1,
        worker_id="worker-1",
        started_at="2026-07-27T00:00:00Z",
        updated_at="2026-07-27T00:00:00Z",
    )

    assert repository.append(attempt) == attempt
    assert repository.list_for_job(job_id) == (attempt,)
    with pytest.raises(KnowledgeIngestionAttemptConflictError):
        repository.append(
            attempt.model_copy(update={"attempt_id": str(uuid4())})
        )
