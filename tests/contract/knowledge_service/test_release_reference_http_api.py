from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient
import pytest

from knowledge_source_service.adapters.memory.knowledge_catalog import (
    InMemoryKnowledgeCatalog,
)
from knowledge_source_service.adapters.memory.knowledge_queries import (
    InMemoryKnowledgeQueryRepository,
)
from knowledge_source_service.adapters.memory.release_references import (
    InMemoryReleaseReferenceRepository,
)
from knowledge_source_service.application.knowledge_queries import (
    KnowledgeQueryApplication,
)
from knowledge_source_service.application.release_references import (
    KnowledgeBaseReleaseReferenceApplication,
)
from knowledge_source_service.delivery.http import (
    bearer_client_authenticator,
    create_application,
)
from knowledge_source_service.domain.release_references import ReleaseReferenceError
from knowledge_source_service.ports.authorization import KnowledgeQueryAdmission


NOW = datetime(2026, 8, 30, 13, tzinfo=UTC)


class _AllowingAuthorizer:
    def authorize(self, *, client_id: str, request: Any) -> KnowledgeQueryAdmission:
        return KnowledgeQueryAdmission(
            knowledge_space_id="space-claims",
            client_grant_id=f"grant-{client_id}",
            effective_access_scope_digest=f"sha256:{'a' * 64}",
        )


def _environment() -> tuple[TestClient, KnowledgeBaseReleaseReferenceApplication, dict[str, str]]:
    catalog = InMemoryKnowledgeCatalog()
    source_version = catalog.add_document(
        knowledge_space_id="space-claims",
        knowledge_source_id="source-rules",
        media_type="text/plain",
        content="Synthetic rule for Reference HTTP registration.",
    )
    release = catalog.publish_release(
        knowledge_space_id="space-claims",
        knowledge_base_id="base-claims",
        knowledge_source_version_ids=(source_version.knowledge_source_version_id,),
    )
    references = KnowledgeBaseReleaseReferenceApplication(
        repository=InMemoryReleaseReferenceRepository(catalog=catalog, clock=lambda: NOW)
    )
    query_application = KnowledgeQueryApplication(
        repository=InMemoryKnowledgeQueryRepository(),
        authorizer=_AllowingAuthorizer(),
        clock=lambda: NOW,
        id_factory=lambda: "query-05d",
    )
    application = create_application(
        query_application=query_application,
        release_references=references,
        authenticate_client=bearer_client_authenticator(
            lambda token: "proof-agent-production" if token == "client-token" else None
        ),
        trace_id_factory=lambda: "trace-05d",
        release_identity="kss-tdd-05d",
        readiness_probe=lambda: {
            "postgresql": True,
            "object_storage": True,
            "search": True,
        },
    )
    payload = {
        "knowledge_space_id": release.knowledge_space_id,
        "knowledge_base_id": release.knowledge_base_id,
        "knowledge_base_release_id": release.knowledge_base_release_id,
        "external_resource_kind": "published_agent_version",
        "external_resource_id": "provisional-version-05d",
        "purpose": "execution_or_rollback",
    }
    return TestClient(application), references, payload


def test_authenticated_client_registers_and_replays_exact_release_reference() -> None:
    client, references, payload = _environment()
    headers = {
        "Authorization": "Bearer client-token",
        "Idempotency-Key": "formal-agent-reference:provisional-version-05d",
    }

    first = client.post(
        "/v1/knowledge-base-release-references",
        headers=headers,
        json=payload,
    )
    replay = client.post(
        "/v1/knowledge-base-release-references",
        headers=headers,
        json=payload,
    )

    assert first.status_code == 200, first.text
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()
    resource = first.json()
    assert resource == {
        "schema_version": "knowledge-base-release-reference.v1",
        **payload,
        "release_reference_id": resource["release_reference_id"],
        "authenticated_client_id": "proof-agent-production",
        "registered_at": "2026-08-30T13:00:00Z",
        "state": "active",
    }
    assert references.get(resource["release_reference_id"]) is not None
    assert len(references.audit(payload["knowledge_base_release_id"])) == 1


@pytest.mark.parametrize(
    "authorization",
    [None, "Bearer invalid-client-secret-sentinel"],
)
def test_release_reference_registration_requires_authenticated_client(
    authorization: str | None,
) -> None:
    client, references, payload = _environment()
    headers = {"Idempotency-Key": "reference-without-client"}
    if authorization is not None:
        headers["Authorization"] = authorization

    response = client.post(
        "/v1/knowledge-base-release-references",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "invalid_client_credential"
    assert "invalid-client-secret-sentinel" not in response.text
    assert references.audit(payload["knowledge_base_release_id"]) == ()


def test_release_reference_registration_requires_non_blank_idempotency_key() -> None:
    client, references, payload = _environment()

    response = client.post(
        "/v1/knowledge-base-release-references",
        headers={"Authorization": "Bearer client-token", "Idempotency-Key": "   "},
        json=payload,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_idempotency_key"
    assert references.audit(payload["knowledge_base_release_id"]) == ()


def test_release_reference_registration_rejects_invalid_idempotency_key() -> None:
    client, references, payload = _environment()

    response = client.post(
        "/v1/knowledge-base-release-references",
        headers={"Authorization": "Bearer client-token", "Idempotency-Key": "invalid!key"},
        json=payload,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_release_reference_request"
    assert references.audit(payload["knowledge_base_release_id"]) == ()


def test_release_reference_registration_rejects_idempotency_request_drift() -> None:
    client, references, payload = _environment()
    headers = {
        "Authorization": "Bearer client-token",
        "Idempotency-Key": "formal-agent-reference:provisional-version-05d",
    }
    assert (
        client.post(
            "/v1/knowledge-base-release-references",
            headers=headers,
            json=payload,
        ).status_code
        == 200
    )

    response = client.post(
        "/v1/knowledge-base-release-references",
        headers=headers,
        json={**payload, "external_resource_id": "provisional-version-drifted"},
    )

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "release_reference_conflict"
    assert len(references.audit(payload["knowledge_base_release_id"])) == 1


def test_release_reference_registration_rejects_release_scope_drift() -> None:
    client, references, payload = _environment()

    response = client.post(
        "/v1/knowledge-base-release-references",
        headers={
            "Authorization": "Bearer client-token",
            "Idempotency-Key": "formal-agent-reference:scope-drift",
        },
        json={**payload, "knowledge_base_id": "base-drifted"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "release_reference_not_admissible"
    assert references.audit(payload["knowledge_base_release_id"]) == ()


def test_release_reference_request_validation_does_not_echo_unknown_input() -> None:
    client, references, payload = _environment()
    sentinel = "forged-client-and-secret-sentinel"

    response = client.post(
        "/v1/knowledge-base-release-references",
        headers={
            "Authorization": "Bearer client-token",
            "Idempotency-Key": "formal-agent-reference:forged-client",
        },
        json={**payload, "authenticated_client_id": sentinel},
    )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "invalid_knowledge_service_request"
    assert sentinel not in response.text
    assert references.audit(payload["knowledge_base_release_id"]) == ()


@pytest.mark.parametrize(
    "error_code",
    [
        "release_reference_storage_unavailable",
        "release_reference_integrity_unavailable",
    ],
)
def test_release_reference_storage_or_integrity_failure_is_safe_and_retryable(
    monkeypatch: pytest.MonkeyPatch,
    error_code: str,
) -> None:
    client, references, payload = _environment()

    def fail_registration(*_args: Any, **_kwargs: Any) -> None:
        raise ReleaseReferenceError(error_code)

    monkeypatch.setattr(references, "register", fail_registration)
    response = client.post(
        "/v1/knowledge-base-release-references",
        headers={
            "Authorization": "Bearer client-token",
            "Idempotency-Key": "formal-agent-reference:storage-failure",
        },
        json=payload,
    )

    assert response.status_code == 503
    assert response.json()["code"] == "release_reference_unavailable"
    assert response.json()["retryable"] is True
    assert error_code not in response.text
