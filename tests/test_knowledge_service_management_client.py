from __future__ import annotations

import json
from typing import Any

from proof_agent.capabilities.knowledge.source_service_management_client import (
    KnowledgeSourceServiceManagementClient,
)
from proof_agent.contracts.ports.guarded_http import GuardedHttpResponse


class ScriptedManagementHttpClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.responses = [
            _response(
                {
                    "schema_version": "knowledge-service-readiness.v1",
                    "status": "ready",
                    "service": "knowledge-source-service",
                    "release_identity": "knowledge-source-service-v1",
                    "dependencies": [
                        {"name": "postgresql", "status": "ready"},
                        {"name": "object_storage", "status": "ready"},
                        {"name": "search", "status": "ready"},
                    ],
                }
            ),
            _collection(
                "knowledge-space-collection.v1",
                [{"schema_version": "knowledge-space.v1", "knowledge_space_id": "space-1"}],
            ),
            _collection(
                "knowledge-source-collection.v1",
                [
                    {
                        "schema_version": "knowledge-source.v1",
                        "knowledge_space_id": "space-1",
                        "knowledge_source_id": "source-1",
                    }
                ],
            ),
            _collection(
                "knowledge-base-collection.v1",
                [
                    {
                        "schema_version": "knowledge-base.v1",
                        "knowledge_space_id": "space-1",
                        "knowledge_base_id": "base-1",
                    }
                ],
            ),
            _collection(
                "knowledge-source-version-collection.v1",
                [
                    {
                        "schema_version": "knowledge-source-version-summary.v1",
                        "knowledge_space_id": "space-1",
                        "knowledge_source_id": "source-1",
                        "knowledge_source_version_id": "source-version-1",
                        "source_kind": "document",
                        "media_type": "application/pdf",
                    }
                ],
            ),
            _collection(
                "knowledge-base-release-collection.v1",
                [
                    {
                        "schema_version": "knowledge-base-release-summary.v1",
                        "knowledge_space_id": "space-1",
                        "knowledge_base_id": "base-1",
                        "knowledge_base_version_id": "base-version-1",
                        "knowledge_base_release_id": "release-1",
                        "source_version_count": 1,
                        "state": "queryable",
                    }
                ],
            ),
        ]

    def request(self, method: str, url: str, **kwargs: Any) -> GuardedHttpResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.responses.pop(0)


def _response(payload: dict[str, Any], *, status_code: int = 200) -> GuardedHttpResponse:
    return GuardedHttpResponse(
        status_code=status_code,
        headers={"Content-Type": "application/json"},
        body=json.dumps(payload).encode(),
    )


def _collection(schema_version: str, data: list[dict[str, Any]]) -> GuardedHttpResponse:
    return _response(
        {
            "schema_version": schema_version,
            "data": data,
            "summary": {"total": len(data)},
        }
    )


def test_management_client_builds_exact_dashboard_workspace_through_guarded_https() -> None:
    http = ScriptedManagementHttpClient()
    client = KnowledgeSourceServiceManagementClient(
        endpoint="https://knowledge.internal:8444",
        http_client=http,
        authorization_header_factory=lambda: "Bearer operator-service-token",
    )

    workspace = client.workspace()

    assert workspace.readiness.state == "ready"
    assert workspace.readiness.revision == "knowledge-source-service-v1"
    assert workspace.summary.model_dump() == {
        "spaces": 1,
        "sources": 1,
        "bases": 1,
        "source_versions": 1,
        "releases": 1,
    }
    assert workspace.source_versions[0].knowledge_source_version_id == "source-version-1"
    assert workspace.releases[0].knowledge_base_release_id == "release-1"
    assert [call["method"] for call in http.calls] == ["GET"] * 6
    assert all(
        call["headers"]["Authorization"] == "Bearer operator-service-token"
        for call in http.calls[1:]
    )
    assert "Authorization" not in http.calls[0]["headers"]


def test_management_client_creates_catalog_resources_with_server_credential() -> None:
    class CreateHttpClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def request(self, method: str, url: str, **kwargs: Any) -> GuardedHttpResponse:
            self.calls.append({"method": method, "url": url, **kwargs})
            return _response({}, status_code=201)

    http = CreateHttpClient()
    client = KnowledgeSourceServiceManagementClient(
        endpoint="https://knowledge.internal:8444",
        http_client=http,
        authorization_header_factory=lambda: "Bearer operator-service-token",
    )

    client.create_space("space-1")
    client.create_source(knowledge_space_id="space-1", knowledge_source_id="source-1")
    client.create_base(knowledge_space_id="space-1", knowledge_base_id="base-1")

    assert [call["url"] for call in http.calls] == [
        "https://knowledge.internal:8444/v1/knowledge-spaces",
        "https://knowledge.internal:8444/v1/knowledge-spaces/space-1/knowledge-sources",
        "https://knowledge.internal:8444/v1/knowledge-spaces/space-1/knowledge-bases",
    ]
    assert [json.loads(call["body"]) for call in http.calls] == [
        {"knowledge_space_id": "space-1"},
        {"knowledge_source_id": "source-1"},
        {"knowledge_base_id": "base-1"},
    ]
