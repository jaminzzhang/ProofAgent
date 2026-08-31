from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
import pytest

from knowledge_source_service.adapters.memory.artifacts import (
    InMemoryImmutableArtifactStore,
)
from knowledge_source_service.adapters.memory.knowledge_catalog import (
    InMemoryKnowledgeCatalog,
)
from knowledge_source_service.adapters.postgres.access_control import KnowledgeAccessConflict
from knowledge_source_service.application.query_grants import (
    KnowledgeQueryGrantProvisioningError,
)
from knowledge_source_service.contracts.access_control import (
    KnowledgeQueryGrant,
    ProvisionKnowledgeQueryGrantRequest,
)
from knowledge_source_service.delivery.management_http import (
    bearer_operator_authenticator,
    create_management_application,
)


class _QueryGrantProvisioningStub:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[ProvisionKnowledgeQueryGrantRequest] = []

    def provision(
        self,
        request: ProvisionKnowledgeQueryGrantRequest,
    ) -> KnowledgeQueryGrant:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return KnowledgeQueryGrant(
            client_grant_id="query-grant-http-v1",
            client_id="proof-agent-runtime",
            knowledge_space_id="space-claims",
            knowledge_base_release_id=request.knowledge_base_release_id,
            allowed_strategies=("single_pass",),
            execution_budget={
                "max_rounds": 1,
                "max_model_calls": 1,
                "max_candidates": 20,
                "max_model_tokens": 1000,
                "max_duration_ms": 5000,
            },
            effective_access_scope_digest=f"sha256:{'c' * 64}",
            active=True,
            created_at=datetime(2026, 8, 30, 13, tzinfo=UTC),
        )


def _environment(
    grants: _QueryGrantProvisioningStub,
    *,
    permissions: frozenset[str] = frozenset({"knowledge_source.edit"}),
) -> TestClient:
    return TestClient(
        create_management_application(
            catalog=InMemoryKnowledgeCatalog(),  # type: ignore[arg-type]
            artifacts=InMemoryImmutableArtifactStore(),
            authenticate_operator=bearer_operator_authenticator(
                operator_id="proof-agent-management",
                expected_token="operator-secret-token",
                permissions=permissions,
            ),
            document_pipeline_revision="document-pipeline-v1",
            dataset_pipeline_revision="dataset-pipeline-v1",
            max_upload_bytes=1024,
            max_dataset_records=100,
            query_grants=grants,  # type: ignore[arg-type]
        )
    )


def test_operator_provisions_only_exact_release_and_receives_secret_free_grant() -> None:
    grants = _QueryGrantProvisioningStub()
    client = _environment(grants)

    response = client.post(
        "/v1/knowledge-query-grants",
        headers={"Authorization": "Bearer operator-secret-token"},
        json={"knowledge_base_release_id": "release-claims-v7"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["schema_version"] == "knowledge-query-grant.v1"
    assert response.json()["knowledge_base_release_id"] == "release-claims-v7"
    assert response.json()["client_id"] == "proof-agent-runtime"
    assert grants.calls == [
        ProvisionKnowledgeQueryGrantRequest(
            knowledge_base_release_id="release-claims-v7",
        )
    ]


@pytest.mark.parametrize(
    ("authorization", "permissions", "status_code", "code"),
    [
        (
            "Bearer runtime-client-token",
            frozenset({"knowledge_source.edit"}),
            401,
            "invalid_operator_credential",
        ),
        (
            "Bearer operator-secret-token",
            frozenset({"knowledge_source.view"}),
            403,
            "knowledge_operator_permission_denied",
        ),
    ],
)
def test_query_grant_provisioning_requires_operator_edit_authority(
    authorization: str,
    permissions: frozenset[str],
    status_code: int,
    code: str,
) -> None:
    grants = _QueryGrantProvisioningStub()
    response = _environment(grants, permissions=permissions).post(
        "/v1/knowledge-query-grants",
        headers={"Authorization": authorization},
        json={"knowledge_base_release_id": "release-claims-v7"},
    )

    assert response.status_code == status_code
    assert response.json()["code"] == code
    assert grants.calls == []


def test_query_grant_request_rejects_forged_policy_fields_without_echo() -> None:
    grants = _QueryGrantProvisioningStub()
    sentinel = "forged-query-grant-policy-secret-sentinel"

    response = _environment(grants).post(
        "/v1/knowledge-query-grants",
        headers={"Authorization": "Bearer operator-secret-token"},
        json={
            "knowledge_base_release_id": "release-claims-v7",
            "client_id": sentinel,
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_management_request"
    assert sentinel not in response.text
    assert grants.calls == []


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (
            KnowledgeAccessConflict("durable-secret-sentinel"),
            409,
            "knowledge_query_grant_conflict",
        ),
        (
            KnowledgeQueryGrantProvisioningError("integrity-secret-sentinel"),
            503,
            "knowledge_query_grant_unavailable",
        ),
    ],
)
def test_query_grant_authority_failures_map_to_bounded_service_problems(
    error: Exception,
    status_code: int,
    code: str,
) -> None:
    response = _environment(_QueryGrantProvisioningStub(error)).post(
        "/v1/knowledge-query-grants",
        headers={"Authorization": "Bearer operator-secret-token"},
        json={"knowledge_base_release_id": "release-claims-v7"},
    )

    assert response.status_code == status_code
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == code
    assert "secret-sentinel" not in response.text
