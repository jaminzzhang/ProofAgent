from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from knowledge_source_service.adapters.opensearch.hybrid_projection import (
    OpenSearchHybridProjection,
)
from knowledge_source_service.adapters.postgres.knowledge_catalog import (
    PostgresKnowledgeCatalog,
)
from knowledge_source_service.adapters.postgres.migrations import (
    apply_knowledge_service_migrations,
)
from knowledge_source_service.adapters.s3.artifacts import S3ImmutableArtifactStore
from knowledge_source_service.application.document_intake import (
    DocumentIntakeApplication,
    DocumentIntakeCommand,
)
from knowledge_source_service.application.indexed_retrieval import (
    IndexedHybridKnowledgeRetrievalEngine,
)
from knowledge_source_service.application.integrity_worker import (
    KnowledgeReleaseIntegrityWorker,
)
from knowledge_source_service.application.knowledge_releases import (
    KnowledgeReleaseApplication,
    PublishKnowledgeReleaseCommand,
)
from knowledge_source_service.application.projection_encoding import (
    DeterministicHashProjectionEncoder,
)
from knowledge_source_service.contracts.knowledge_query import CreateKnowledgeQueryRequest
from knowledge_source_service.ports.authorization import KnowledgeQueryAdmission
from knowledge_source_service.ports.retrieval import AdmittedKnowledgeQuery


pytestmark = [
    pytest.mark.postgres_integration,
    pytest.mark.s3_integration,
    pytest.mark.search_integration,
]


def test_release_pins_real_hybrid_index_and_retrieval_verifies_exact_artifacts(
    kss_postgres_dsn: str,
    kss_s3_bucket: tuple[Any, str],
    kss_search_endpoint: str,
) -> None:
    apply_knowledge_service_migrations(kss_postgres_dsn)
    s3_client, bucket = kss_s3_bucket
    artifacts = S3ImmutableArtifactStore(
        client=s3_client,
        bucket=bucket,
        key_prefix="knowledge-source-service/",
    )
    projection = OpenSearchHybridProjection(endpoint=kss_search_endpoint)
    encoder = DeterministicHashProjectionEncoder(dense_dimension=32)
    catalog = PostgresKnowledgeCatalog.from_dsn(
        kss_postgres_dsn,
        artifacts=artifacts,
    )
    catalog.create_space("space-indexed")
    catalog.create_source(
        knowledge_space_id="space-indexed",
        knowledge_source_id="source-indexed",
    )
    catalog.create_base(
        knowledge_space_id="space-indexed",
        knowledge_base_id="base-indexed",
    )
    source = DocumentIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision="document-pipeline-v1",
        max_content_bytes=1024,
    ).create_source_version(
        DocumentIntakeCommand(
            knowledge_space_id="space-indexed",
            knowledge_source_id="source-indexed",
            display_filename="travel.md",
            media_type="text/markdown",
            content=(
                "# Travel\n"
                "Flight delay benefit is 300 CNY after four hours.\n"
                "Medical waiting period is thirty days.\n"
            ).encode(),
        )
    )
    release_application = KnowledgeReleaseApplication(
        artifacts=artifacts,
        catalog=catalog,
        projection=projection,
        encoder=encoder,
    )
    release_command = PublishKnowledgeReleaseCommand(
        knowledge_space_id="space-indexed",
        knowledge_base_id="base-indexed",
        knowledge_source_version_ids=(source.version.knowledge_source_version_id,),
    )
    published = release_application.publish(release_command)
    replayed = release_application.publish(release_command)
    binding = published.release.retrieval_projection
    assert binding is not None
    assert replayed == published

    integrity = KnowledgeReleaseIntegrityWorker(
        catalog=catalog,
        projection=projection,
    ).run_batch(after_release_id=None, limit=1000)
    assert integrity.verified_releases >= 1
    assert integrity.next_release_id is not None
    assert published.release.knowledge_base_release_id <= integrity.next_release_id
    catalog.close()

    try:
        rebuilt_catalog = PostgresKnowledgeCatalog.from_dsn(
            kss_postgres_dsn,
            artifacts=artifacts,
        )
        result = IndexedHybridKnowledgeRetrievalEngine(
            catalog=rebuilt_catalog,
            projection=projection,
            encoder=encoder,
        ).retrieve(
            AdmittedKnowledgeQuery(
                request=CreateKnowledgeQueryRequest.model_validate(
                    {
                        "knowledge_base_release_id": (
                            published.release.knowledge_base_release_id
                        ),
                        "question": "flight delay four hours benefit",
                        "execution_budget": {
                            "max_rounds": 1,
                            "max_model_calls": 1,
                            "max_candidates": 10,
                            "max_model_tokens": 1000,
                            "max_duration_ms": 2000,
                        },
                        "deadline_at": datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
                    }
                ),
                admission=KnowledgeQueryAdmission(
                    knowledge_space_id="space-indexed",
                    client_grant_id="grant-indexed",
                    effective_access_scope_digest=f"sha256:{'d' * 64}",
                ),
            )
        )
        rebuilt_catalog.close()
    finally:
        projection.delete_generation(binding.index_identity)
        projection.close()

    candidate = result.evidence_groups[0].candidate_evidence[0]
    assert candidate.content.text == "Flight delay benefit is 300 CNY after four hours."
    assert candidate.retrieval_lineage.index_identity == binding.index_identity
    assert {item.lane for item in candidate.ranking.lane_contributions} == {
        "lexical",
        "sparse",
        "dense",
    }
    assert result.retrieval_lineage.release_manifest_digest == (
        published.release.release_manifest_digest
    )
