from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from knowledge_source_service.adapters.postgres.knowledge_catalog import (
    PostgresKnowledgeCatalog,
)
from knowledge_source_service.adapters.postgres.migrations import (
    apply_knowledge_service_migrations,
)
from knowledge_source_service.adapters.s3.artifacts import S3ImmutableArtifactStore
from knowledge_source_service.application.dataset_intake import (
    CsvDatasetIntakeApplication,
    CsvDatasetIntakeCommand,
    XlsxDatasetIntakeApplication,
    XlsxDatasetIntakeCommand,
)
from knowledge_source_service.application.hybrid_retrieval import (
    HybridKnowledgeRetrievalEngine,
)
from knowledge_source_service.application.knowledge_releases import (
    KnowledgeReleaseApplication,
    PublishKnowledgeReleaseCommand,
)
from knowledge_source_service.contracts.knowledge_query import CreateKnowledgeQueryRequest
from knowledge_source_service.domain.knowledge_catalog import DatasetSourceVersion
from knowledge_source_service.ports.authorization import KnowledgeQueryAdmission
from knowledge_source_service.ports.retrieval import AdmittedKnowledgeQuery
from xlsx_fixture import claims_workbook


pytestmark = [pytest.mark.postgres_integration, pytest.mark.s3_integration]


def test_typed_csv_dataset_survives_postgres_s3_rebuild_and_filtering(
    kss_postgres_dsn: str,
    kss_s3_bucket: tuple[Any, str],
) -> None:
    apply_knowledge_service_migrations(kss_postgres_dsn)
    s3_client, bucket = kss_s3_bucket
    artifacts = S3ImmutableArtifactStore(
        client=s3_client,
        bucket=bucket,
        key_prefix="knowledge-source-service/",
    )
    catalog = PostgresKnowledgeCatalog.from_dsn(
        kss_postgres_dsn,
        artifacts=artifacts,
    )
    catalog.create_space("space-insurance")
    catalog.create_source(
        knowledge_space_id="space-insurance",
        knowledge_source_id="source-claims",
    )
    catalog.create_base(
        knowledge_space_id="space-insurance",
        knowledge_base_id="base-insurance",
    )
    intake = CsvDatasetIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision="dataset-pipeline-v1",
        max_content_bytes=1024 * 1024,
        max_records=1000,
    )
    dataset = intake.create_source_version(
        CsvDatasetIntakeCommand(
            knowledge_space_id="space-insurance",
            knowledge_source_id="source-claims",
            display_filename="claims.csv",
            content=(
                "claim_year,claim_total,active,reported_on\n"
                "2024,11000.00,false,2024-12-31\n"
                "2025,12345.67,true,2025-12-31\n"
            ).encode(),
            field_types={
                "claim_year": "integer",
                "claim_total": "decimal",
                "active": "boolean",
                "reported_on": "date",
            },
        )
    )
    replay = intake.create_source_version(
        CsvDatasetIntakeCommand(
            knowledge_space_id="space-insurance",
            knowledge_source_id="source-claims",
            display_filename="renamed.csv",
            content=(
                "claim_year,claim_total,active,reported_on\n"
                "2024,11000.00,false,2024-12-31\n"
                "2025,12345.67,true,2025-12-31\n"
            ).encode(),
            field_types={
                "claim_year": "integer",
                "claim_total": "decimal",
                "active": "boolean",
                "reported_on": "date",
            },
        )
    )
    assert replay.version == dataset.version
    published = KnowledgeReleaseApplication(
        artifacts=artifacts,
        catalog=catalog,
    ).publish(
        PublishKnowledgeReleaseCommand(
            knowledge_space_id="space-insurance",
            knowledge_base_id="base-insurance",
            knowledge_source_version_ids=(
                dataset.version.knowledge_source_version_id,
            ),
        )
    )
    catalog.close()

    rebuilt_catalog = PostgresKnowledgeCatalog.from_dsn(
        kss_postgres_dsn,
        artifacts=artifacts,
    )
    result = HybridKnowledgeRetrievalEngine(catalog=rebuilt_catalog).retrieve(
        AdmittedKnowledgeQuery(
            request=CreateKnowledgeQueryRequest.model_validate(
                {
                    "knowledge_base_release_id": (
                        published.release.knowledge_base_release_id
                    ),
                    "question": "2025 年理赔",
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
    rebuilt_catalog.close()

    group = result.evidence_groups[0]
    assert group.group_type == "structured"
    candidate = group.candidate_evidence[0]
    assert candidate.content.structured_data.fields[0].value == 2025
    assert candidate.content.structured_data.fields[1].value == "12345.67"
    assert candidate.content.structured_data.fields[2].value is True
    assert candidate.content.structured_data.fields[3].value == "2025-12-31"
    assert candidate.citation_locator.record_ids == (dataset.version.record_ids[1],)


def test_typed_xlsx_dataset_survives_postgres_s3_rebuild(
    kss_postgres_dsn: str,
    kss_s3_bucket: tuple[Any, str],
) -> None:
    apply_knowledge_service_migrations(kss_postgres_dsn)
    s3_client, bucket = kss_s3_bucket
    artifacts = S3ImmutableArtifactStore(
        client=s3_client,
        bucket=bucket,
        key_prefix="knowledge-source-service/",
    )
    catalog = PostgresKnowledgeCatalog.from_dsn(
        kss_postgres_dsn,
        artifacts=artifacts,
    )
    catalog.create_space("space-insurance")
    catalog.create_source(
        knowledge_space_id="space-insurance",
        knowledge_source_id="source-xlsx-claims",
    )
    published = XlsxDatasetIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision="dataset-pipeline-v1",
        max_content_bytes=1024 * 1024,
        max_records=100,
    ).create_source_version(
        XlsxDatasetIntakeCommand(
            knowledge_space_id="space-insurance",
            knowledge_source_id="source-xlsx-claims",
            display_filename="claims.xlsx",
            content=claims_workbook(),
            field_types={
                "claim_year": "integer",
                "claim_total": "decimal",
                "active": "boolean",
            },
        )
    )
    catalog.close()

    rebuilt_catalog = PostgresKnowledgeCatalog.from_dsn(
        kss_postgres_dsn,
        artifacts=artifacts,
    )
    rebuilt = rebuilt_catalog.get_source_version(
        published.version.knowledge_source_version_id
    )
    rebuilt_catalog.close()

    assert isinstance(rebuilt, DatasetSourceVersion)
    assert rebuilt.records[-1].fields[0].value == 2025
    assert rebuilt.records[-1].fields[1].value == "12345.67"
    assert rebuilt.records[-1].fields[2].value is True
