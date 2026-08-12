from __future__ import annotations

from datetime import UTC, datetime

from knowledge_source_service.adapters.memory.artifacts import (
    InMemoryImmutableArtifactStore,
)
from knowledge_source_service.adapters.memory.knowledge_catalog import (
    InMemoryKnowledgeCatalog,
)
from knowledge_source_service.application.dataset_intake import (
    ParquetDatasetIntakeApplication,
    ParquetDatasetIntakeCommand,
)
from knowledge_source_service.application.hybrid_retrieval import (
    HybridKnowledgeRetrievalEngine,
)
from knowledge_source_service.application.knowledge_releases import (
    KnowledgeReleaseApplication,
    PublishKnowledgeReleaseCommand,
)
from knowledge_source_service.contracts.knowledge_query import CreateKnowledgeQueryRequest
from knowledge_source_service.ports.authorization import KnowledgeQueryAdmission
from knowledge_source_service.ports.retrieval import AdmittedKnowledgeQuery
from parquet_fixture import claims_parquet


def test_parquet_columns_keep_declared_types_and_are_structurally_queryable() -> None:
    artifacts = InMemoryImmutableArtifactStore()
    catalog = InMemoryKnowledgeCatalog()
    published = ParquetDatasetIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision="dataset-pipeline-v1",
        max_content_bytes=1024 * 1024,
        max_records=100,
    ).create_source_version(
        ParquetDatasetIntakeCommand(
            knowledge_space_id="space-insurance",
            knowledge_source_id="source-parquet-claims",
            display_filename="claims.parquet",
            content=claims_parquet(),
            field_types={
                "claim_year": "integer",
                "claim_total": "decimal",
                "active": "boolean",
            },
        )
    )
    release = KnowledgeReleaseApplication(
        artifacts=artifacts,
        catalog=catalog,
    ).publish(
        PublishKnowledgeReleaseCommand(
            knowledge_space_id="space-insurance",
            knowledge_base_id="base-insurance",
            knowledge_source_version_ids=(
                published.version.knowledge_source_version_id,
            ),
        )
    )
    result = HybridKnowledgeRetrievalEngine(catalog=catalog).retrieve(
        AdmittedKnowledgeQuery(
            request=CreateKnowledgeQueryRequest.model_validate(
                {
                    "knowledge_base_release_id": (
                        release.release.knowledge_base_release_id
                    ),
                    "question": "2025 claims",
                    "query_constraints": {
                        "filters": [
                            {
                                "field": "claim_year",
                                "operator": "eq",
                                "value": 2025,
                            }
                        ]
                    },
                    "execution_budget": {
                        "max_rounds": 1,
                        "max_model_calls": 1,
                        "max_candidates": 10,
                        "max_model_tokens": 1000,
                        "max_duration_ms": 1000,
                    },
                    "deadline_at": datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
                }
            ),
            admission=KnowledgeQueryAdmission(
                knowledge_space_id="space-insurance",
                client_grant_id="grant-proof-agent",
                effective_access_scope_digest=f"sha256:{'e' * 64}",
            ),
        )
    )

    candidate = result.evidence_groups[0].candidate_evidence[0]
    assert candidate.content.structured_data.fields[0].value == 2025
    assert candidate.content.structured_data.fields[1].value == "12345.67"
    assert candidate.content.structured_data.fields[2].value is True
    assert published.original_artifact.media_type == "application/vnd.apache.parquet"
