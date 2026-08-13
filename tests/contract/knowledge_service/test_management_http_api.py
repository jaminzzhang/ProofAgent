from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
import pytest

from knowledge_source_service.adapters.memory.artifacts import (
    InMemoryImmutableArtifactStore,
)
from knowledge_source_service.adapters.postgres.knowledge_catalog import (
    PostgresKnowledgeCatalog,
)
from knowledge_source_service.adapters.postgres.synchronizations import (
    PostgresKnowledgeSourceSynchronizationRepository,
)
from knowledge_source_service.adapters.postgres.migrations import (
    apply_knowledge_service_migrations,
)
from knowledge_source_service.delivery.management_http import (
    bearer_operator_authenticator,
    create_management_application,
)
from knowledge_source_service.application.synchronizations import (
    KnowledgeSourceSynchronizationApplication,
)
from office_fixture import docx_with_paragraphs, pptx_with_slide_shapes
from ocr_fixture import ReviewedOcrExtractor, blank_png
from parquet_fixture import claims_parquet
from pdf_fixture import single_page_pdf
from xlsx_fixture import claims_workbook


pytestmark = pytest.mark.postgres_integration


def test_management_api_lists_exact_space_catalog_for_dashboard_adapter(
    kss_postgres_dsn: str,
) -> None:
    apply_knowledge_service_migrations(kss_postgres_dsn)
    artifacts = InMemoryImmutableArtifactStore()
    catalog = PostgresKnowledgeCatalog.from_dsn(
        kss_postgres_dsn,
        artifacts=artifacts,
    )
    client = TestClient(
        create_management_application(
            catalog=catalog,
            artifacts=artifacts,
            authenticate_operator=bearer_operator_authenticator(
                operator_id="operator-test",
                expected_token="operator-secret-token",
            ),
            document_pipeline_revision="document-pipeline-v1",
            dataset_pipeline_revision="dataset-pipeline-v1",
            max_upload_bytes=1024 * 1024,
            max_dataset_records=1000,
        )
    )
    headers = {"Authorization": "Bearer operator-secret-token"}
    client.post(
        "/v1/knowledge-spaces",
        headers=headers,
        json={"knowledge_space_id": "space-dashboard"},
    ).raise_for_status()
    client.post(
        "/v1/knowledge-spaces/space-dashboard/knowledge-sources",
        headers=headers,
        json={"knowledge_source_id": "source-dashboard"},
    ).raise_for_status()
    client.post(
        "/v1/knowledge-spaces/space-dashboard/knowledge-bases",
        headers=headers,
        json={"knowledge_base_id": "base-dashboard"},
    ).raise_for_status()
    version = client.post(
        ("/v1/knowledge-spaces/space-dashboard/knowledge-sources/source-dashboard/versions:ingest"),
        headers=headers,
        files={
            "file": (
                "policy.md",
                b"# Rule\nHospital delay benefit is 300 CNY.\n",
                "text/markdown",
            )
        },
    )
    version.raise_for_status()
    release = client.post(
        ("/v1/knowledge-spaces/space-dashboard/knowledge-bases/base-dashboard/releases"),
        headers=headers,
        json={"knowledge_source_version_ids": [version.json()["knowledge_source_version_id"]]},
    )
    release.raise_for_status()

    spaces = client.get("/v1/knowledge-spaces", headers=headers)
    sources = client.get(
        "/v1/knowledge-spaces/space-dashboard/knowledge-sources",
        headers=headers,
    )
    bases = client.get(
        "/v1/knowledge-spaces/space-dashboard/knowledge-bases",
        headers=headers,
    )
    versions = client.get(
        ("/v1/knowledge-spaces/space-dashboard/knowledge-sources/source-dashboard/versions"),
        headers=headers,
    )
    releases = client.get(
        ("/v1/knowledge-spaces/space-dashboard/knowledge-bases/base-dashboard/releases"),
        headers=headers,
    )

    assert spaces.status_code == 200
    assert spaces.json() == {
        "schema_version": "knowledge-space-collection.v1",
        "data": [
            {
                "schema_version": "knowledge-space.v1",
                "knowledge_space_id": "space-dashboard",
            }
        ],
        "summary": {"total": 1},
    }
    assert sources.json()["data"] == [
        {
            "schema_version": "knowledge-source.v1",
            "knowledge_space_id": "space-dashboard",
            "knowledge_source_id": "source-dashboard",
        }
    ]
    assert bases.json()["data"] == [
        {
            "schema_version": "knowledge-base.v1",
            "knowledge_space_id": "space-dashboard",
            "knowledge_base_id": "base-dashboard",
        }
    ]
    assert versions.json()["data"] == [
        {
            "schema_version": "knowledge-source-version-summary.v1",
            "knowledge_space_id": "space-dashboard",
            "knowledge_source_id": "source-dashboard",
            "knowledge_source_version_id": version.json()["knowledge_source_version_id"],
            "source_kind": "document",
            "media_type": "text/markdown",
        }
    ]
    assert releases.json()["data"] == [
        {
            "schema_version": "knowledge-base-release-summary.v1",
            "knowledge_space_id": "space-dashboard",
            "knowledge_base_id": "base-dashboard",
            "knowledge_base_version_id": release.json()["knowledge_base_version_id"],
            "knowledge_base_release_id": release.json()["knowledge_base_release_id"],
            "source_version_count": 1,
            "state": "queryable",
        }
    ]
    catalog.close()


def test_management_api_creates_and_polls_idempotent_source_synchronization(
    kss_postgres_dsn: str,
) -> None:
    apply_knowledge_service_migrations(kss_postgres_dsn)
    artifacts = InMemoryImmutableArtifactStore()
    catalog = PostgresKnowledgeCatalog.from_dsn(
        kss_postgres_dsn,
        artifacts=artifacts,
    )
    synchronization_repository = PostgresKnowledgeSourceSynchronizationRepository.from_dsn(
        kss_postgres_dsn
    )
    synchronization_application = KnowledgeSourceSynchronizationApplication(
        repository=synchronization_repository,
        clock=lambda: datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
        id_factory=lambda: "source-sync-http-1",
        admit_connection=lambda connection_id: connection_id == "connection-http-1",
    )
    client = TestClient(
        create_management_application(
            catalog=catalog,
            artifacts=artifacts,
            authenticate_operator=bearer_operator_authenticator(
                operator_id="operator-test",
                expected_token="operator-secret-token",
            ),
            document_pipeline_revision="document-pipeline-v1",
            dataset_pipeline_revision="dataset-pipeline-v1",
            max_upload_bytes=1024 * 1024,
            max_dataset_records=1000,
            synchronization_application=synchronization_application,
        )
    )
    authorization = {"Authorization": "Bearer operator-secret-token"}
    client.post(
        "/v1/knowledge-spaces",
        headers=authorization,
        json={"knowledge_space_id": "space-sync-http"},
    ).raise_for_status()
    client.post(
        "/v1/knowledge-spaces/space-sync-http/knowledge-sources",
        headers=authorization,
        json={"knowledge_source_id": "source-sync-http"},
    ).raise_for_status()
    headers = {
        **authorization,
        "Idempotency-Key": "source-sync-http-attempt-1",
    }
    request = {
        "knowledge_space_id": "space-sync-http",
        "knowledge_source_id": "source-sync-http",
        "connection_id": "connection-http-1",
        "display_filename": "claims.snapshot.json",
        "record_path": ["claims"],
        "field_types": {
            "claim_id": "string",
            "claim_total": "decimal",
        },
    }

    created = client.post(
        "/v1/knowledge-source-synchronizations",
        headers=headers,
        json=request,
    )
    replayed = client.post(
        "/v1/knowledge-source-synchronizations",
        headers=headers,
        json=request,
    )
    fetched = client.get(created.headers["location"], headers=authorization)

    assert created.status_code == 202
    assert created.headers["location"].endswith("/source-sync-http-1")
    assert created.headers["retry-after"] == "1"
    assert created.json()["state"] == "queued"
    assert replayed.status_code == 200
    assert replayed.json() == created.json()
    assert fetched.status_code == 200
    assert fetched.json() == created.json()
    synchronization_repository.close()
    catalog.close()


def test_management_api_ingests_reviewed_ocr_image_as_document(
    kss_postgres_dsn: str,
) -> None:
    apply_knowledge_service_migrations(kss_postgres_dsn)
    artifacts = InMemoryImmutableArtifactStore()
    catalog = PostgresKnowledgeCatalog.from_dsn(
        kss_postgres_dsn,
        artifacts=artifacts,
    )
    client = TestClient(
        create_management_application(
            catalog=catalog,
            artifacts=artifacts,
            authenticate_operator=bearer_operator_authenticator(
                operator_id="operator-test",
                expected_token="operator-secret-token",
            ),
            document_pipeline_revision="document-pipeline-v1",
            dataset_pipeline_revision="dataset-pipeline-v1",
            max_upload_bytes=1024 * 1024,
            max_dataset_records=1000,
            ocr_extractor=ReviewedOcrExtractor(),
        )
    )
    headers = {"Authorization": "Bearer operator-secret-token"}
    client.post(
        "/v1/knowledge-spaces",
        headers=headers,
        json={"knowledge_space_id": "space-ocr"},
    ).raise_for_status()
    client.post(
        "/v1/knowledge-spaces/space-ocr/knowledge-sources",
        headers=headers,
        json={"knowledge_source_id": "source-ocr"},
    ).raise_for_status()

    response = client.post(
        ("/v1/knowledge-spaces/space-ocr/knowledge-sources/source-ocr/versions:ingest"),
        headers=headers,
        files={"file": ("policy.png", blank_png(), "image/png")},
    )

    assert response.status_code == 201
    assert response.json()["source_kind"] == "document"
    assert response.json()["media_type"] == "image/png"
    assert response.json()["evidence_unit_count"] == 1


def test_management_api_creates_document_dataset_and_exact_release_without_storage_leak(
    kss_postgres_dsn: str,
) -> None:
    apply_knowledge_service_migrations(kss_postgres_dsn)
    artifacts = InMemoryImmutableArtifactStore()
    catalog = PostgresKnowledgeCatalog.from_dsn(
        kss_postgres_dsn,
        artifacts=artifacts,
    )

    client = TestClient(
        create_management_application(
            catalog=catalog,
            artifacts=artifacts,
            authenticate_operator=bearer_operator_authenticator(
                operator_id="operator-test",
                expected_token="operator-secret-token",
            ),
            document_pipeline_revision="document-pipeline-v1",
            dataset_pipeline_revision="dataset-pipeline-v1",
            max_upload_bytes=1024 * 1024,
            max_dataset_records=1000,
        )
    )
    headers = {"Authorization": "Bearer operator-secret-token"}

    denied = client.post(
        "/v1/knowledge-spaces",
        headers={"Authorization": "Bearer wrong-operator-token"},
        json={"knowledge_space_id": "space-hidden"},
    )

    space = client.post(
        "/v1/knowledge-spaces",
        headers=headers,
        json={"knowledge_space_id": "space-managed"},
    )
    document_source = client.post(
        "/v1/knowledge-spaces/space-managed/knowledge-sources",
        headers=headers,
        json={"knowledge_source_id": "source-document"},
    )
    dataset_source = client.post(
        "/v1/knowledge-spaces/space-managed/knowledge-sources",
        headers=headers,
        json={"knowledge_source_id": "source-dataset"},
    )
    json_source = client.post(
        "/v1/knowledge-spaces/space-managed/knowledge-sources",
        headers=headers,
        json={"knowledge_source_id": "source-json"},
    )
    xlsx_source = client.post(
        "/v1/knowledge-spaces/space-managed/knowledge-sources",
        headers=headers,
        json={"knowledge_source_id": "source-xlsx"},
    )
    parquet_source = client.post(
        "/v1/knowledge-spaces/space-managed/knowledge-sources",
        headers=headers,
        json={"knowledge_source_id": "source-parquet"},
    )
    knowledge_base = client.post(
        "/v1/knowledge-spaces/space-managed/knowledge-bases",
        headers=headers,
        json={"knowledge_base_id": "base-managed"},
    )
    document_version = client.post(
        ("/v1/knowledge-spaces/space-managed/knowledge-sources/source-document/versions:ingest"),
        headers=headers,
        files={"file": ("policy.md", b"# Rule\nDelay benefit is 300 CNY.\n", "text/markdown")},
    )
    dataset_version = client.post(
        ("/v1/knowledge-spaces/space-managed/knowledge-sources/source-dataset/versions:ingest"),
        headers=headers,
        files={
            "file": (
                "claims.csv",
                b"claim_year,claim_total\n2025,12345.67\n",
                "text/csv",
            )
        },
        data={"field_types": '{"claim_year":"integer","claim_total":"decimal"}'},
    )
    json_version = client.post(
        ("/v1/knowledge-spaces/space-managed/knowledge-sources/source-json/versions:ingest"),
        headers=headers,
        files={
            "file": (
                "claims.json",
                b'{"claims":[{"claim_year":2026,"active":true}]}',
                "application/json",
            )
        },
        data={
            "field_types": '{"claim_year":"integer","active":"boolean"}',
            "record_path": '["claims"]',
        },
    )
    xlsx_version = client.post(
        ("/v1/knowledge-spaces/space-managed/knowledge-sources/source-xlsx/versions:ingest"),
        headers=headers,
        files={
            "file": (
                "claims.xlsx",
                claims_workbook(),
                ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            )
        },
        data={
            "field_types": ('{"claim_year":"integer","claim_total":"decimal","active":"boolean"}')
        },
    )
    parquet_version = client.post(
        ("/v1/knowledge-spaces/space-managed/knowledge-sources/source-parquet/versions:ingest"),
        headers=headers,
        files={
            "file": (
                "claims.parquet",
                claims_parquet(),
                "application/vnd.apache.parquet",
            )
        },
        data={
            "field_types": ('{"claim_year":"integer","claim_total":"decimal","active":"boolean"}')
        },
    )
    release = client.post(
        ("/v1/knowledge-spaces/space-managed/knowledge-bases/base-managed/releases"),
        headers=headers,
        json={
            "knowledge_source_version_ids": [
                document_version.json()["knowledge_source_version_id"],
                dataset_version.json()["knowledge_source_version_id"],
                json_version.json()["knowledge_source_version_id"],
                xlsx_version.json()["knowledge_source_version_id"],
                parquet_version.json()["knowledge_source_version_id"],
            ]
        },
    )

    assert denied.status_code == 401
    assert denied.headers["www-authenticate"] == "Bearer"
    assert space.status_code == 201
    assert document_source.status_code == 201
    assert dataset_source.status_code == 201
    assert json_source.status_code == 201
    assert xlsx_source.status_code == 201
    assert parquet_source.status_code == 201
    assert knowledge_base.status_code == 201
    assert document_version.status_code == 201
    assert document_version.json()["source_kind"] == "document"
    assert dataset_version.status_code == 201
    assert dataset_version.json()["source_kind"] == "dataset"
    assert dataset_version.json()["record_count"] == 1
    assert json_version.status_code == 201
    assert json_version.json()["source_kind"] == "dataset"
    assert json_version.json()["media_type"] == "application/json"
    assert xlsx_version.status_code == 201
    assert xlsx_version.json()["source_kind"] == "dataset"
    assert xlsx_version.json()["record_count"] == 2
    assert parquet_version.status_code == 201
    assert parquet_version.json()["source_kind"] == "dataset"
    assert parquet_version.json()["record_count"] == 2
    assert release.status_code == 201
    assert release.json()["state"] == "queryable"
    assert release.json()["knowledge_source_version_ids"] == [
        document_version.json()["knowledge_source_version_id"],
        dataset_version.json()["knowledge_source_version_id"],
        json_version.json()["knowledge_source_version_id"],
        xlsx_version.json()["knowledge_source_version_id"],
        parquet_version.json()["knowledge_source_version_id"],
    ]
    response_text = " ".join(
        (
            document_version.text,
            dataset_version.text,
            json_version.text,
            xlsx_version.text,
            parquet_version.text,
            release.text,
        )
    )
    assert "object_key" not in response_text
    assert '"version_id":' not in response_text
    assert "memory-version" not in response_text


def test_management_api_ingests_native_pdf_docx_and_pptx_as_documents(
    kss_postgres_dsn: str,
) -> None:
    apply_knowledge_service_migrations(kss_postgres_dsn)
    artifacts = InMemoryImmutableArtifactStore()
    catalog = PostgresKnowledgeCatalog.from_dsn(
        kss_postgres_dsn,
        artifacts=artifacts,
    )
    client = TestClient(
        create_management_application(
            catalog=catalog,
            artifacts=artifacts,
            authenticate_operator=bearer_operator_authenticator(
                operator_id="operator-test",
                expected_token="operator-secret-token",
            ),
            document_pipeline_revision="document-pipeline-v1",
            dataset_pipeline_revision="dataset-pipeline-v1",
            max_upload_bytes=1024 * 1024,
            max_dataset_records=1000,
        )
    )
    headers = {"Authorization": "Bearer operator-secret-token"}
    client.post(
        "/v1/knowledge-spaces",
        headers=headers,
        json={"knowledge_space_id": "space-pdf"},
    ).raise_for_status()
    client.post(
        "/v1/knowledge-spaces/space-pdf/knowledge-sources",
        headers=headers,
        json={"knowledge_source_id": "source-pdf"},
    ).raise_for_status()
    client.post(
        "/v1/knowledge-spaces/space-pdf/knowledge-sources",
        headers=headers,
        json={"knowledge_source_id": "source-docx"},
    ).raise_for_status()
    client.post(
        "/v1/knowledge-spaces/space-pdf/knowledge-sources",
        headers=headers,
        json={"knowledge_source_id": "source-pptx"},
    ).raise_for_status()

    response = client.post(
        ("/v1/knowledge-spaces/space-pdf/knowledge-sources/source-pdf/versions:ingest"),
        headers=headers,
        files={
            "file": (
                "policy.pdf",
                single_page_pdf("Flight delay benefit is 300 CNY."),
                "application/pdf",
            )
        },
    )
    docx_response = client.post(
        ("/v1/knowledge-spaces/space-pdf/knowledge-sources/source-docx/versions:ingest"),
        headers=headers,
        files={
            "file": (
                "policy.docx",
                docx_with_paragraphs("Flight delay benefit is 300 CNY."),
                ("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            )
        },
    )
    pptx_response = client.post(
        ("/v1/knowledge-spaces/space-pdf/knowledge-sources/source-pptx/versions:ingest"),
        headers=headers,
        files={
            "file": (
                "policy.pptx",
                pptx_with_slide_shapes(((7, "Flight delay benefit is 300 CNY."),)),
                ("application/vnd.openxmlformats-officedocument.presentationml.presentation"),
            )
        },
    )

    assert response.status_code == 201
    assert response.json()["source_kind"] == "document"
    assert response.json()["media_type"] == "application/pdf"
    assert response.json()["evidence_unit_count"] == 1
    assert docx_response.status_code == 201
    assert docx_response.json()["source_kind"] == "document"
    assert docx_response.json()["media_type"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert docx_response.json()["evidence_unit_count"] == 1
    assert pptx_response.status_code == 201
    assert pptx_response.json()["source_kind"] == "document"
    assert pptx_response.json()["media_type"] == (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )
    assert pptx_response.json()["evidence_unit_count"] == 1
