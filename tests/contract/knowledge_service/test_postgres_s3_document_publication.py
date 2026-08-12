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
from knowledge_source_service.application.document_intake import (
    DocumentIntakeApplication,
    DocumentIntakeCommand,
)
from knowledge_source_service.application.hybrid_retrieval import (
    HybridKnowledgeRetrievalEngine,
)
from knowledge_source_service.application.knowledge_releases import (
    KnowledgeReleaseApplication,
    PublishKnowledgeReleaseCommand,
)
from knowledge_source_service.contracts.knowledge_query import CreateKnowledgeQueryRequest
from knowledge_source_service.domain.knowledge_catalog import DocumentSourceVersion
from knowledge_source_service.ports.authorization import KnowledgeQueryAdmission
from knowledge_source_service.ports.retrieval import AdmittedKnowledgeQuery
from office_fixture import docx_with_table, pptx_with_slide_shapes
from ocr_fixture import ReviewedOcrExtractor, ReviewedPdfOcrExtractor, blank_png
from pdf_fixture import single_page_pdf


pytestmark = [pytest.mark.postgres_integration, pytest.mark.s3_integration]


def test_postgres_catalog_rebuilds_exact_source_and_release_from_s3(
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
        knowledge_source_id="source-policy",
    )
    catalog.create_base(
        knowledge_space_id="space-insurance",
        knowledge_base_id="base-insurance",
    )
    intake = DocumentIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision="document-pipeline-v1",
        max_content_bytes=1024 * 1024,
    )
    source_version = intake.create_source_version(
        DocumentIntakeCommand(
            knowledge_space_id="space-insurance",
            knowledge_source_id="source-policy",
            display_filename="policy.md",
            media_type="text/markdown",
            content="# 免赔额\n本产品每次事故免赔额为 500 元。\n".encode(),
        )
    )
    published = KnowledgeReleaseApplication(
        artifacts=artifacts,
        catalog=catalog,
    ).publish(
        PublishKnowledgeReleaseCommand(
            knowledge_space_id="space-insurance",
            knowledge_base_id="base-insurance",
            knowledge_source_version_ids=(
                source_version.version.knowledge_source_version_id,
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
                    "question": "事故免赔额 500 元",
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

    candidate = result.evidence_groups[0].candidate_evidence[0]
    assert candidate.knowledge_source_version_id == (
        source_version.version.knowledge_source_version_id
    )
    assert candidate.content.text == "本产品每次事故免赔额为 500 元。"
    assert candidate.citation_locator.start_line == 2
    assert result.retrieval_lineage.release_manifest_digest == (
        published.release.release_manifest_digest
    )


def test_postgres_catalog_rebuilds_pdf_page_citations_from_s3(
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
        knowledge_source_id="source-pdf-policy",
    )
    catalog.create_base(
        knowledge_space_id="space-insurance",
        knowledge_base_id="base-insurance",
    )
    source_version = DocumentIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision="document-pipeline-v1",
        max_content_bytes=1024 * 1024,
    ).create_source_version(
        DocumentIntakeCommand(
            knowledge_space_id="space-insurance",
            knowledge_source_id="source-pdf-policy",
            display_filename="policy.pdf",
            media_type="application/pdf",
            content=single_page_pdf(
                "Flight delay benefit is 300 CNY after four hours."
            ),
        )
    )
    published = KnowledgeReleaseApplication(
        artifacts=artifacts,
        catalog=catalog,
    ).publish(
        PublishKnowledgeReleaseCommand(
            knowledge_space_id="space-insurance",
            knowledge_base_id="base-insurance",
            knowledge_source_version_ids=(
                source_version.version.knowledge_source_version_id,
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
                    "question": "flight delay four hours benefit",
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

    candidate = result.evidence_groups[0].candidate_evidence[0]
    assert candidate.content.text == (
        "Flight delay benefit is 300 CNY after four hours."
    )
    assert candidate.citation_locator.model_dump(mode="json") == {
        "kind": "pdf_page",
        "page_number": 1,
    }


def test_postgres_catalog_rebuilds_docx_table_cell_citations_from_s3(
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
        knowledge_source_id="source-docx-policy",
    )
    published = DocumentIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision="document-pipeline-v1",
        max_content_bytes=1024 * 1024,
    ).create_source_version(
        DocumentIntakeCommand(
            knowledge_space_id="space-insurance",
            knowledge_source_id="source-docx-policy",
            display_filename="policy.docx",
            media_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            content=docx_with_table(
                (
                    ("Event", "Benefit"),
                    ("Flight delay after four hours", "300 CNY"),
                )
            ),
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

    assert isinstance(rebuilt, DocumentSourceVersion)
    locator = rebuilt.evidence_units[-1].citation_locator
    assert locator.kind == "docx_table_cell"
    assert locator.table_number == 1
    assert locator.row_number == 2
    assert locator.column_number == 2


def test_postgres_catalog_rebuilds_pptx_shape_citations_from_s3(
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
        knowledge_source_id="source-pptx-policy",
    )
    published = DocumentIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision="document-pipeline-v1",
        max_content_bytes=1024 * 1024,
    ).create_source_version(
        DocumentIntakeCommand(
            knowledge_space_id="space-insurance",
            knowledge_source_id="source-pptx-policy",
            display_filename="policy.pptx",
            media_type=(
                "application/vnd.openxmlformats-officedocument."
                "presentationml.presentation"
            ),
            content=pptx_with_slide_shapes(
                ((2, "Policy overview"),),
                ((7, "Flight delay benefit is 300 CNY."),),
            ),
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

    assert isinstance(rebuilt, DocumentSourceVersion)
    locator = rebuilt.evidence_units[-1].citation_locator
    assert locator.kind == "pptx_shape"
    assert locator.slide_number == 2
    assert locator.shape_id == 7


def test_postgres_catalog_rebuilds_ocr_region_citations_from_s3(
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
        knowledge_source_id="source-scan-policy",
    )
    published = DocumentIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision="document-pipeline-v1",
        max_content_bytes=1024 * 1024,
        ocr_extractor=ReviewedOcrExtractor(),
    ).create_source_version(
        DocumentIntakeCommand(
            knowledge_space_id="space-insurance",
            knowledge_source_id="source-scan-policy",
            display_filename="policy.png",
            media_type="image/png",
            content=blank_png(),
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

    assert isinstance(rebuilt, DocumentSourceVersion)
    locator = rebuilt.evidence_units[0].citation_locator
    assert locator.kind == "ocr_region"
    assert locator.page_number == 1
    assert (locator.x_min, locator.y_min, locator.x_max, locator.y_max) == (
        10,
        12,
        190,
        42,
    )


def test_postgres_catalog_rebuilds_scanned_pdf_ocr_citation_from_s3(
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
    catalog.create_space("space-scanned-pdf")
    catalog.create_source(
        knowledge_space_id="space-scanned-pdf",
        knowledge_source_id="source-scanned-pdf",
    )
    published = DocumentIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision="document-pipeline-v1",
        max_content_bytes=1024 * 1024,
        ocr_extractor=ReviewedPdfOcrExtractor(),
    ).create_source_version(
        DocumentIntakeCommand(
            knowledge_space_id="space-scanned-pdf",
            knowledge_source_id="source-scanned-pdf",
            display_filename="scanned-policy.pdf",
            media_type="application/pdf",
            content=single_page_pdf(""),
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

    assert isinstance(rebuilt, DocumentSourceVersion)
    locator = rebuilt.evidence_units[0].citation_locator
    assert locator.kind == "ocr_region"
    assert locator.page_number == 1
    assert (locator.x_min, locator.y_min, locator.x_max, locator.y_max) == (
        72,
        60,
        420,
        100,
    )
