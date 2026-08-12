from __future__ import annotations

from datetime import UTC, datetime

import psycopg
import pytest

from knowledge_source_service.adapters.memory.artifacts import (
    InMemoryImmutableArtifactStore,
)
from knowledge_source_service.adapters.memory.knowledge_catalog import (
    InMemoryKnowledgeCatalog,
)
from knowledge_source_service.adapters.postgres.json_snapshot import (
    PostgresJsonSnapshotReader,
)
from knowledge_source_service.application.external_snapshots import (
    PostgresSnapshotIntakeApplication,
    PostgresSnapshotIntakeCommand,
)
from knowledge_source_service.application.hybrid_retrieval import (
    HybridKnowledgeRetrievalEngine,
)
from knowledge_source_service.application.knowledge_releases import (
    KnowledgeReleaseApplication,
    PublishKnowledgeReleaseCommand,
)
from knowledge_source_service.contracts.knowledge_query import (
    CreateKnowledgeQueryRequest,
)
from knowledge_source_service.ports.authorization import KnowledgeQueryAdmission
from knowledge_source_service.ports.retrieval import AdmittedKnowledgeQuery


pytestmark = pytest.mark.postgres_integration


def test_postgres_read_only_snapshot_remains_stable_after_upstream_mutation(
    kss_postgres_dsn: str,
) -> None:
    with psycopg.connect(kss_postgres_dsn) as connection:
        connection.execute(
            """
            CREATE TABLE upstream_claims (
                claim_id text PRIMARY KEY,
                claim_total numeric(18, 2) NOT NULL,
                active boolean NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO upstream_claims VALUES ('claim-1', 12345.67, true)"
        )

    artifacts = InMemoryImmutableArtifactStore()
    catalog = InMemoryKnowledgeCatalog()
    publication = PostgresSnapshotIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        reader=PostgresJsonSnapshotReader(
            dsn=kss_postgres_dsn,
            relation="upstream_claims",
            columns=("claim_id", "claim_total", "active"),
            record_key=("claim_id",),
            max_rows=10,
            max_response_bytes=4096,
            statement_timeout_ms=1000,
            clock=lambda: datetime(2026, 8, 12, 3, 1, tzinfo=UTC),
        ),
        pipeline_revision="dataset-pipeline-v1",
        max_content_bytes=4096,
        max_records=10,
    ).create_source_version(
        PostgresSnapshotIntakeCommand(
            knowledge_space_id="space-postgres",
            knowledge_source_id="source-postgres",
            display_filename="upstream-claims.snapshot.json",
            field_types={
                "claim_id": "string",
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
            knowledge_space_id="space-postgres",
            knowledge_base_id="base-postgres",
            knowledge_source_version_ids=(
                publication.version.knowledge_source_version_id,
            ),
        )
    ).release

    with psycopg.connect(kss_postgres_dsn) as connection:
        connection.execute(
            "UPDATE upstream_claims SET claim_total = 99999.99 WHERE claim_id = 'claim-1'"
        )

    result = HybridKnowledgeRetrievalEngine(catalog=catalog).retrieve(
        AdmittedKnowledgeQuery(
            request=CreateKnowledgeQueryRequest.model_validate(
                {
                    "knowledge_base_release_id": release.knowledge_base_release_id,
                    "question": "claim total",
                    "query_constraints": {
                        "filters": [
                            {
                                "field": "claim_id",
                                "operator": "eq",
                                "value": "claim-1",
                            }
                        ]
                    },
                    "execution_budget": {
                        "max_rounds": 1,
                        "max_model_calls": 1,
                        "max_candidates": 10,
                        "max_model_tokens": 100,
                        "max_duration_ms": 1000,
                    },
                    "deadline_at": "2026-08-12T04:00:00Z",
                }
            ),
            admission=KnowledgeQueryAdmission(
                knowledge_space_id="space-postgres",
                client_grant_id="grant-postgres",
                effective_access_scope_digest=f"sha256:{'b' * 64}",
            ),
        )
    )

    candidate = result.evidence_groups[0].candidate_evidence[0]
    assert candidate.content.structured_data.fields[1].value == "12345.67"
    assert publication.original_artifact.media_type == "application/json"
