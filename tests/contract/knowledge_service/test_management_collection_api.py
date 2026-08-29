from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from knowledge_source_service.adapters.memory.artifacts import (
    InMemoryImmutableArtifactStore,
)
from knowledge_source_service.adapters.memory.knowledge_catalog import InMemoryKnowledgeCatalog
from knowledge_source_service.adapters.memory.release_references import (
    InMemoryReleaseReferenceRepository,
)
from knowledge_source_service.application.release_references import (
    KnowledgeBaseReleaseLifecycleApplication,
    KnowledgeBaseReleaseReferenceApplication,
)
from knowledge_source_service.contracts.release_references import (
    RegisterKnowledgeBaseReleaseReferenceRequest,
)
from knowledge_source_service.delivery.management_http import (
    bearer_operator_authenticator,
    create_management_application,
)


class RecordingCatalog:
    def list_spaces(self) -> tuple[str, ...]:
        return ("space-dashboard",)

    def list_sources(self, knowledge_space_id: str) -> tuple[str, ...]:
        assert knowledge_space_id == "space-dashboard"
        return ("source-dashboard",)

    def list_bases(self, knowledge_space_id: str) -> tuple[str, ...]:
        assert knowledge_space_id == "space-dashboard"
        return ("base-dashboard",)

    def list_source_versions(
        self,
        *,
        knowledge_space_id: str,
        knowledge_source_id: str,
    ) -> tuple[object, ...]:
        assert knowledge_space_id == "space-dashboard"
        assert knowledge_source_id == "source-dashboard"
        return ()

    def list_releases(
        self,
        *,
        knowledge_space_id: str,
        knowledge_base_id: str,
    ) -> tuple[object, ...]:
        assert knowledge_space_id == "space-dashboard"
        assert knowledge_base_id == "base-dashboard"
        return ()


def test_management_collections_are_operator_authenticated_and_space_scoped() -> None:
    client = TestClient(
        create_management_application(
            catalog=RecordingCatalog(),  # type: ignore[arg-type]
            artifacts=InMemoryImmutableArtifactStore(),
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

    denied = client.get("/v1/knowledge-spaces")
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

    assert denied.status_code == 401
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
    assert sources.json()["data"][0]["knowledge_source_id"] == "source-dashboard"
    assert bases.json()["data"][0]["knowledge_base_id"] == "base-dashboard"
    assert versions.json()["data"] == []
    assert releases.json()["data"] == []


def test_management_reads_exact_release_lifecycle_and_reference_summary() -> None:
    catalog = InMemoryKnowledgeCatalog()
    version = catalog.add_document(
        knowledge_space_id="space-dashboard",
        knowledge_source_id="source-dashboard",
        media_type="text/plain",
        content="Synthetic release lifecycle fixture.",
    )
    release = catalog.publish_release(
        knowledge_space_id="space-dashboard",
        knowledge_base_id="base-dashboard",
        knowledge_source_version_ids=(version.knowledge_source_version_id,),
    )
    repository = InMemoryReleaseReferenceRepository(
        catalog=catalog,
        clock=lambda: datetime(2026, 8, 29, tzinfo=UTC),
    )
    KnowledgeBaseReleaseReferenceApplication(repository=repository).register(
        RegisterKnowledgeBaseReleaseReferenceRequest(
            knowledge_space_id="space-dashboard",
            knowledge_base_id="base-dashboard",
            knowledge_base_release_id=release.knowledge_base_release_id,
            external_resource_kind="published_agent_version",
            external_resource_id="agent-version-1",
            purpose="execution_or_rollback",
        ),
        authenticated_client_id="proof-agent",
        idempotency_key="register-agent-version-1",
    )
    client = TestClient(
        create_management_application(
            catalog=catalog,  # type: ignore[arg-type]
            artifacts=InMemoryImmutableArtifactStore(),
            authenticate_operator=bearer_operator_authenticator(
                operator_id="operator-test",
                expected_token="operator-secret-token",
            ),
            document_pipeline_revision="document-pipeline-v1",
            dataset_pipeline_revision="dataset-pipeline-v1",
            max_upload_bytes=1024 * 1024,
            max_dataset_records=1000,
            release_lifecycle=KnowledgeBaseReleaseLifecycleApplication(repository=repository),
        )
    )

    response = client.get(
        (
            "/v1/knowledge-spaces/space-dashboard/knowledge-bases/base-dashboard/"
            f"releases/{release.knowledge_base_release_id}/deletion-eligibility"
        ),
        headers={"Authorization": "Bearer operator-secret-token"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "schema_version": "knowledge-base-release-deletion-eligibility.v1",
        "knowledge_space_id": "space-dashboard",
        "knowledge_base_id": "base-dashboard",
        "knowledge_base_release_id": release.knowledge_base_release_id,
        "release_state": "queryable",
        "eligible": False,
        "blockers": ["release_not_retired", "active_release_references_present"],
        "active_reference_count": 1,
        "deregistered_reference_count": 0,
        "retired_at": None,
        "revoked_at": None,
        "assessed_at": "2026-08-29T00:00:00Z",
        "artifact_retention_state": "not_assessed",
        "artifact_retention_authority_id": None,
        "artifact_retention_assessment_id": None,
    }


def test_management_release_lifecycle_read_requires_knowledge_view_permission() -> None:
    catalog = InMemoryKnowledgeCatalog()
    repository = InMemoryReleaseReferenceRepository(
        catalog=catalog,
        clock=lambda: datetime(2026, 8, 29, tzinfo=UTC),
    )
    client = TestClient(
        create_management_application(
            catalog=catalog,  # type: ignore[arg-type]
            artifacts=InMemoryImmutableArtifactStore(),
            authenticate_operator=bearer_operator_authenticator(
                operator_id="operator-editor-only",
                expected_token="operator-editor-token",
                permissions=frozenset({"knowledge_source.edit"}),
            ),
            document_pipeline_revision="document-pipeline-v1",
            dataset_pipeline_revision="dataset-pipeline-v1",
            max_upload_bytes=1024 * 1024,
            max_dataset_records=1000,
            release_lifecycle=KnowledgeBaseReleaseLifecycleApplication(repository=repository),
        )
    )

    response = client.get(
        (
            "/v1/knowledge-spaces/space-dashboard/knowledge-bases/base-dashboard/"
            "releases/release-1/deletion-eligibility"
        ),
        headers={"Authorization": "Bearer operator-editor-token"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "knowledge_operator_permission_denied"
