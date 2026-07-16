from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from proof_agent.capabilities.knowledge.ingestion.hybrid_worker import (
    HybridArtifactBuildRequest,
    hybrid_build_request_sha256,
)
from proof_agent.capabilities.persistence.postgres.bundle import PostgresPersistenceBundle
from proof_agent.capabilities.persistence.postgres.database import upgrade_database
from proof_agent.capabilities.persistence.postgres.hybrid_ingestion_repository import (
    HybridIngestionClaimRejectedError,
    PostgresHybridIngestionRepository,
)
from proof_agent.contracts import KnowledgeSource, KnowledgeSourceLifecycleState
from proof_agent.contracts.knowledge_index import ExactArtifactRef


pytestmark = pytest.mark.postgres_integration
pytest_plugins = ("postgres_fixtures",)


def _request(source_id: str) -> HybridArtifactBuildRequest:
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
        page_numbers=(1, 2),
        parser_revision="parser-v1",
        model_digests=("sha256:model-v1",),
        configuration_sha256="b" * 64,
    )
    return request.model_copy(
        update={"request_sha256": hybrid_build_request_sha256(request)}
    )


def test_pg_hybrid_ingestion_claim_retry_and_fencing(postgres_dsn: str) -> None:
    upgrade_database(postgres_dsn)
    bundle = PostgresPersistenceBundle.create(postgres_dsn)
    source_id = f"hybrid-{uuid4()}"
    now = datetime(2026, 7, 15, tzinfo=UTC)
    current = [now]
    repository = PostgresHybridIngestionRepository(
        bundle.engine,
        clock=lambda: current[0],
    )
    try:
        bundle.knowledge.save_source(
            KnowledgeSource(
                source_id=source_id,
                name="Insurance clauses",
                provider="hybrid_index",
                lifecycle_state=KnowledgeSourceLifecycleState.ACTIVE,
                params={},
                source_draft_version_id=str(uuid4()),
                created_at=now.isoformat(),
                updated_at=now.isoformat(),
            ),
            expected_revision=0,
        )
        request = _request(source_id)
        admitted = repository.enqueue(request)
        assert admitted.state == "READY"

        first = repository.claim_next(worker_id="worker-1", lease_seconds=30)
        assert first is not None
        assert first.fencing_token == 1
        renewed = repository.renew_claim(first, lease_seconds=30)
        assert renewed.lease_expires_at == now + timedelta(seconds=30)
        retried = repository.schedule_retry(
            renewed,
            auto_retry_count=1,
            safe_error="Temporary parser failure.",
        )
        assert retried.state == "RETRY_SCHEDULED"

        current[0] = now + timedelta(seconds=6)
        second = repository.claim_next(worker_id="worker-2", lease_seconds=30)
        assert second is not None
        assert second.fencing_token == 2
        assert repository.load_build_request(second).auto_retry_count == 1
        with pytest.raises(HybridIngestionClaimRejectedError):
            repository.require_review(first, safe_reason="stale owner")
        reviewed = repository.require_review(
            second,
            safe_reason="Structured document requires operator review.",
        )
        assert reviewed.state == "REVIEW_REQUIRED"
    finally:
        bundle.close()
