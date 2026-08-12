from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from knowledge_source_service.adapters.memory.artifacts import (
    InMemoryImmutableArtifactStore,
)
from knowledge_source_service.adapters.memory.knowledge_catalog import (
    InMemoryKnowledgeCatalog,
)
from knowledge_source_service.adapters.postgres.knowledge_catalog import (
    PostgresKnowledgeCatalog,
)
from knowledge_source_service.adapters.postgres.migrations import (
    apply_knowledge_service_migrations,
)
from knowledge_source_service.adapters.s3.artifacts import S3ImmutableArtifactStore
from knowledge_source_service.application.hybrid_retrieval import (
    HybridKnowledgeRetrievalEngine,
)
from knowledge_source_service.application.json_dataset_intake import (
    JsonDatasetIntakeApplication,
    JsonDatasetIntakeCommand,
)
from knowledge_source_service.application.knowledge_releases import (
    KnowledgeReleaseApplication,
    PublishKnowledgeReleaseCommand,
)
from knowledge_source_service.contracts.knowledge_query import CreateKnowledgeQueryRequest
from knowledge_source_service.ports.authorization import KnowledgeQueryAdmission
from knowledge_source_service.ports.retrieval import AdmittedKnowledgeQuery


def test_mapped_json_becomes_typed_queryable_dataset_with_exact_original() -> None:
    artifacts = InMemoryImmutableArtifactStore()
    catalog = InMemoryKnowledgeCatalog()
    published = JsonDatasetIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision="dataset-pipeline-v1",
        max_content_bytes=1024 * 1024,
        max_records=1000,
    ).create_source_version(
        JsonDatasetIntakeCommand(
            knowledge_space_id="space-insurance",
            knowledge_source_id="source-json-claims",
            display_filename="claims.json",
            media_type="application/json",
            content=(
                b'{"claims":['
                b'{"claim_year":2024,"claim_total":"11000.00","active":false},'
                b'{"claim_year":2025,"claim_total":"12345.67","active":true}'
                b']} '
            ),
            record_path=("claims",),
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
                effective_access_scope_digest=f"sha256:{'a' * 64}",
            ),
        )
    )

    candidate = result.evidence_groups[0].candidate_evidence[0]
    assert candidate.content.structured_data.fields[0].value == 2025
    assert candidate.content.structured_data.fields[1].value == "12345.67"
    assert candidate.content.structured_data.fields[2].value is True
    assert artifacts.get_exact(published.original_artifact).startswith(b'{"claims"')
    assert published.original_artifact.media_type == "application/json"


def test_jsonl_rejects_unknown_fields_and_accepts_exact_typed_records() -> None:
    artifacts = InMemoryImmutableArtifactStore()
    catalog = InMemoryKnowledgeCatalog()
    intake = JsonDatasetIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision="dataset-pipeline-v1",
        max_content_bytes=1024,
        max_records=10,
    )
    command = JsonDatasetIntakeCommand(
        knowledge_space_id="space-insurance",
        knowledge_source_id="source-jsonl",
        display_filename="claims.jsonl",
        media_type="application/x-ndjson",
        content=(
            b'{"claim_year":2025,"active":true}\n'
            b'{"claim_year":2026,"active":false}\n'
        ),
        record_path=(),
        field_types={"claim_year": "integer", "active": "boolean"},
    )

    published = intake.create_source_version(command)

    assert len(published.version.records) == 2
    with pytest.raises(ValueError, match="exactly match"):
        intake.create_source_version(
            JsonDatasetIntakeCommand(
                **{
                    **command.__dict__,
                    "content": b'{"claim_year":2025,"active":true,"secret":1}\n',
                }
            )
        )


@pytest.mark.postgres_integration
@pytest.mark.s3_integration
def test_json_dataset_media_type_survives_postgres_s3_rebuild(
    kss_postgres_dsn: str,
    kss_s3_bucket: tuple[Any, str],
) -> None:
    apply_knowledge_service_migrations(kss_postgres_dsn)
    s3_client, bucket = kss_s3_bucket
    artifacts = S3ImmutableArtifactStore(client=s3_client, bucket=bucket)
    catalog = PostgresKnowledgeCatalog.from_dsn(
        kss_postgres_dsn,
        artifacts=artifacts,
    )
    catalog.create_space("space-json-durable")
    catalog.create_source(
        knowledge_space_id="space-json-durable",
        knowledge_source_id="source-json-durable",
    )
    published = JsonDatasetIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision="dataset-pipeline-v1",
        max_content_bytes=1024 * 1024,
        max_records=100,
    ).create_source_version(
        JsonDatasetIntakeCommand(
            knowledge_space_id="space-json-durable",
            knowledge_source_id="source-json-durable",
            display_filename="records.json",
            media_type="application/json",
            content=b'[{"record_id":1,"active":true}]',
            record_path=(),
            field_types={"record_id": "integer", "active": "boolean"},
        )
    )
    catalog.close()

    rebuilt = PostgresKnowledgeCatalog.from_dsn(
        kss_postgres_dsn,
        artifacts=artifacts,
    ).get_source_version(published.version.knowledge_source_version_id)
    with psycopg.connect(kss_postgres_dsn) as connection:
        media_type = connection.execute(
            "SELECT media_type FROM knowledge_source_versions "
            "WHERE knowledge_source_version_id = %s",
            (published.version.knowledge_source_version_id,),
        ).fetchone()

    assert rebuilt == published.version
    assert media_type == ("application/json",)
