from __future__ import annotations

from fastapi.testclient import TestClient

from knowledge_source_service.adapters.memory.artifacts import (
    InMemoryImmutableArtifactStore,
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
