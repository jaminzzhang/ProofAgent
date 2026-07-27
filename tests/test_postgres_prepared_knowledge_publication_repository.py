"""PostgreSQL fencing tests for prepared Hybrid publications."""

from __future__ import annotations

from proof_agent.capabilities.persistence.postgres.knowledge_repository import (
    PostgresKnowledgeAssetRepository,
)
from proof_agent.capabilities.persistence.postgres.knowledge_source_operation_repository import (
    PostgresKnowledgeSourceOperationRepository,
)
from proof_agent.capabilities.persistence.postgres.prepared_knowledge_publication_repository import (
    PreparedKnowledgePublicationConflictError,
    PostgresPreparedKnowledgePublicationRepository,
)
from proof_agent.contracts import (
    KnowledgeSource,
    KnowledgeSourceLifecycleState,
    KnowledgeSourceOperation,
    PreparedHybridKnowledgePublication,
)

import pytest


pytestmark = pytest.mark.postgres_integration
pytest_plugins = ("postgres_fixtures",)


def test_pg_prepared_publication_is_consumed_once_by_exact_fence(
    postgres_engine,
) -> None:
    PostgresKnowledgeAssetRepository(postgres_engine).save_source(
        KnowledgeSource(
            source_id="ks_hybrid",
            name="Prepared publication",
            provider="hybrid_index",
            lifecycle_state=KnowledgeSourceLifecycleState.ACTIVE,
            params={},
            source_draft_version_id="draft-17",
            created_at="2026-07-27T00:00:00Z",
            updated_at="2026-07-27T00:00:00Z",
        ),
        expected_revision=0,
    )
    PostgresKnowledgeSourceOperationRepository(postgres_engine).save(
        KnowledgeSourceOperation(
            operation_id="ksop_prepare_001",
            source_id="ks_hybrid",
            command="prepare_publication",
            status="succeeded",
            stage="prepared",
            source_revision=1,
            poll_after_ms=1_000,
            outcome_code="publication_prepared",
            outcome_detail="Publication validation completed.",
            created_at="2026-07-27T00:00:00Z",
            updated_at="2026-07-27T00:01:00Z",
            completed_at="2026-07-27T00:01:00Z",
        )
    )
    repository = PostgresPreparedKnowledgePublicationRepository(postgres_engine)
    prepared = PreparedHybridKnowledgePublication(
        validation_id="kspubval_001",
        operation_id="ksop_prepare_001",
        attempt_id="publication-attempt-001",
        fencing_token=7,
        source_id="ks_hybrid",
        source_draft_version_id="draft-17",
        candidate_digest="a" * 64,
        generation_id="generation-17",
        manifest_sha256="b" * 64,
        staged_projection_id="projection-attempt-001",
        attestation_sha256="c" * 64,
        smoke_result_sha256="d" * 64,
        state="prepared",
        prepared_at="2026-07-27T00:01:00Z",
    )

    assert repository.save_prepared(prepared) == prepared
    consumed = repository.consume(
        prepared.validation_id,
        source_id=prepared.source_id,
        expected_fencing_token=prepared.fencing_token,
        consumed_at="2026-07-27T00:02:00Z",
    )

    assert consumed.state == "consumed"
    assert consumed.consumed_at == "2026-07-27T00:02:00Z"
    with pytest.raises(PreparedKnowledgePublicationConflictError):
        repository.consume(
            prepared.validation_id,
            source_id=prepared.source_id,
            expected_fencing_token=prepared.fencing_token,
            consumed_at="2026-07-27T00:03:00Z",
        )
