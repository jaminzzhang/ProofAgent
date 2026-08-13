from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from proof_agent.contracts import Permission
from proof_agent.contracts.knowledge_service_management import (
    KnowledgeServiceBaseProjection,
    KnowledgeServiceManagementWorkspace,
    KnowledgeServiceReadinessProjection,
    KnowledgeServiceReleaseProjection,
    KnowledgeServiceSourceProjection,
    KnowledgeServiceSourceVersionProjection,
    KnowledgeServiceSpaceProjection,
)
from proof_agent.delivery.knowledge_service_management_api import router
from proof_agent.errors import ProofAgentError
from proof_agent.observability.api.dependencies import get_operator_identity
from proof_agent.observability.api.operator_identity import OperatorIdentityContext


class RecordingKnowledgeServiceManagementClient:
    def __init__(self) -> None:
        self.created: list[tuple[str, ...]] = []

    def workspace(self) -> KnowledgeServiceManagementWorkspace:
        return KnowledgeServiceManagementWorkspace(
            readiness=KnowledgeServiceReadinessProjection(
                state="ready",
                revision="knowledge-source-service-v1",
                blockers=(),
            ),
            spaces=(KnowledgeServiceSpaceProjection(knowledge_space_id="space-insurance"),),
            sources=(
                KnowledgeServiceSourceProjection(
                    knowledge_space_id="space-insurance",
                    knowledge_source_id="source-policy",
                ),
            ),
            bases=(
                KnowledgeServiceBaseProjection(
                    knowledge_space_id="space-insurance",
                    knowledge_base_id="base-insurance",
                ),
            ),
            source_versions=(
                KnowledgeServiceSourceVersionProjection(
                    knowledge_space_id="space-insurance",
                    knowledge_source_id="source-policy",
                    knowledge_source_version_id="source-version-1",
                    source_kind="document",
                    media_type="application/pdf",
                ),
            ),
            releases=(
                KnowledgeServiceReleaseProjection(
                    knowledge_space_id="space-insurance",
                    knowledge_base_id="base-insurance",
                    knowledge_base_version_id="base-version-1",
                    knowledge_base_release_id="release-1",
                    source_version_count=1,
                    state="queryable",
                ),
            ),
        )

    def create_space(self, knowledge_space_id: str) -> None:
        self.created.append(("space", knowledge_space_id))

    def create_source(
        self,
        *,
        knowledge_space_id: str,
        knowledge_source_id: str,
    ) -> None:
        self.created.append(("source", knowledge_space_id, knowledge_source_id))

    def create_base(
        self,
        *,
        knowledge_space_id: str,
        knowledge_base_id: str,
    ) -> None:
        self.created.append(("base", knowledge_space_id, knowledge_base_id))


def _client(
    management: RecordingKnowledgeServiceManagementClient,
    *,
    permissions: frozenset[Permission],
) -> TestClient:
    application = FastAPI()
    application.state.knowledge_service_management_client = management
    application.include_router(router, prefix="/api")
    application.dependency_overrides[get_operator_identity] = lambda: OperatorIdentityContext(
        operator_id="operator-test",
        display_name="Operator Test",
        permissions=permissions,
        permission_mapping_version_id="mapping-v1",
        permission_epoch=1,
    )
    return TestClient(application)


def test_dashboard_bff_reads_remote_workspace_without_exposing_service_credential() -> None:
    management = RecordingKnowledgeServiceManagementClient()
    client = _client(
        management,
        permissions=frozenset({Permission.KNOWLEDGE_SOURCE_VIEW}),
    )

    response = client.get("/api/config/knowledge-service/workspace")

    assert response.status_code == 200
    assert response.json()["readiness"] == {
        "state": "ready",
        "revision": "knowledge-source-service-v1",
        "blockers": [],
    }
    assert response.json()["summary"] == {
        "spaces": 1,
        "sources": 1,
        "bases": 1,
        "source_versions": 1,
        "releases": 1,
    }
    assert "credential" not in response.text.casefold()
    assert "token" not in response.text.casefold()


def test_dashboard_bff_requires_edit_permission_for_remote_catalog_mutations() -> None:
    management = RecordingKnowledgeServiceManagementClient()
    viewer = _client(
        management,
        permissions=frozenset({Permission.KNOWLEDGE_SOURCE_VIEW}),
    )
    editor = _client(
        management,
        permissions=frozenset({Permission.KNOWLEDGE_SOURCE_VIEW, Permission.KNOWLEDGE_SOURCE_EDIT}),
    )

    denied = viewer.post(
        "/api/config/knowledge-service/spaces",
        json={"knowledge_space_id": "space-new"},
    )
    created_space = editor.post(
        "/api/config/knowledge-service/spaces",
        json={"knowledge_space_id": "space-new"},
    )
    created_source = editor.post(
        "/api/config/knowledge-service/spaces/space-new/sources",
        json={"knowledge_source_id": "source-new"},
    )
    created_base = editor.post(
        "/api/config/knowledge-service/spaces/space-new/bases",
        json={"knowledge_base_id": "base-new"},
    )

    assert denied.status_code == 403
    assert created_space.status_code == 201
    assert created_source.status_code == 201
    assert created_base.status_code == 201
    assert management.created == [
        ("space", "space-new"),
        ("source", "space-new", "source-new"),
        ("base", "space-new", "base-new"),
    ]


def test_dashboard_bff_maps_management_failure_to_safe_service_unavailable() -> None:
    class UnavailableManagementClient(RecordingKnowledgeServiceManagementClient):
        def workspace(self) -> KnowledgeServiceManagementWorkspace:
            raise ProofAgentError(
                "PA_KNOWLEDGE_002",
                "Knowledge Source Service management request failed.",
                "Restore the guarded service connection.",
            )

    client = _client(
        UnavailableManagementClient(),
        permissions=frozenset({Permission.KNOWLEDGE_SOURCE_VIEW}),
    )

    response = client.get("/api/config/knowledge-service/workspace")

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "PA_KNOWLEDGE_002",
        "message": "Knowledge Source Service management request failed.",
        "fix": "Restore the guarded service connection.",
    }
