from __future__ import annotations

from datetime import UTC, datetime
from collections.abc import Callable, Mapping
from typing import Any

from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from knowledge_source_service.adapters.memory.knowledge_queries import (
    InMemoryKnowledgeQueryRepository,
)
from knowledge_source_service.application.knowledge_queries import (
    KnowledgeQueryApplication,
    KnowledgeServiceClient,
)
from knowledge_source_service.delivery.http import create_application
from knowledge_source_service.ports.authorization import KnowledgeQueryAdmission


class AllowingTestAuthorizer:
    def authorize(self, *, client_id: str, request: Any) -> KnowledgeQueryAdmission:
        return KnowledgeQueryAdmission(
            knowledge_space_id="space-test",
            client_grant_id=f"grant-{client_id}",
            effective_access_scope_digest=f"sha256:{'a' * 64}",
        )


def _valid_request_payload() -> dict[str, Any]:
    return {
        "knowledge_base_release_id": "release-opaque-id",
        "question": "2025 年理赔总额及其主要增长原因是什么？",
        "strategy": "agentic",
        "query_constraints": {
            "as_of": "2025-12-31T23:59:59+08:00",
            "filters": [],
        },
        "access_narrowing_context": {
            "assertion_token": "signed-opaque-assertion",
        },
        "execution_budget": {
            "max_rounds": 3,
            "max_model_calls": 6,
            "max_candidates": 200,
            "max_model_tokens": 12_000,
            "max_duration_ms": 30_000,
        },
        "deadline_at": "2026-08-11T10:30:00Z",
    }


def _authenticate_test_client(request: Request) -> KnowledgeServiceClient:
    if request.headers.get("authorization") != "Bearer test-token":
        raise HTTPException(status_code=401, detail="invalid test credential")
    return KnowledgeServiceClient(client_id="agent-client-1")


def _client(
    *,
    id_factory: Callable[[], str] = lambda: "query-opaque-id",
    trace_id_factory: Callable[[], str] = lambda: "trace-test-1",
    authenticate_client: Callable[[Request], KnowledgeServiceClient] = _authenticate_test_client,
    release_identity: str = "kss-test-release",
    readiness_probe: Callable[[], Mapping[str, bool]] = lambda: {
        "postgresql": True,
        "object_storage": True,
        "search": True,
    },
    query_authorizer: Any | None = None,
) -> TestClient:
    if query_authorizer is None:
        query_authorizer = AllowingTestAuthorizer()
    query_application = KnowledgeQueryApplication(
        repository=InMemoryKnowledgeQueryRepository(),
        clock=lambda: datetime(2026, 8, 11, 10, 29, 10, tzinfo=UTC),
        id_factory=id_factory,
        authorizer=query_authorizer,
    )
    return TestClient(
        create_application(
            query_application=query_application,
            authenticate_client=authenticate_client,
            trace_id_factory=trace_id_factory,
            release_identity=release_identity,
            readiness_probe=readiness_probe,
        )
    )


def test_create_knowledge_query_returns_one_pollable_queued_resource() -> None:
    client = _client()

    response = client.post(
        "/v1/knowledge-queries",
        headers={
            "Authorization": "Bearer test-token",
            "Idempotency-Key": "query-attempt-1",
        },
        json=_valid_request_payload(),
    )

    assert response.status_code == 202, response.text
    assert response.headers["location"] == "/v1/knowledge-queries/query-opaque-id"
    assert response.headers["retry-after"] == "1"
    assert response.json() == {
        "schema_version": "knowledge-query.v1",
        "knowledge_query_id": "query-opaque-id",
        "knowledge_base_release_id": "release-opaque-id",
        "state": "queued",
        "submitted_at": "2026-08-11T10:29:10Z",
        "started_at": None,
        "completed_at": None,
        "deadline_at": "2026-08-11T10:30:00Z",
        "cancel_requested_at": None,
        "result_availability": "pending",
        "result_expires_at": None,
        "result": None,
        "problem": None,
        "links": {
            "self": "/v1/knowledge-queries/query-opaque-id",
            "cancel": "/v1/knowledge-queries/query-opaque-id:cancel",
        },
    }


def test_one_space_can_authorize_multiple_agents_without_authorizing_every_agent() -> None:
    class SharedSpaceAuthorizer:
        def authorize(
            self, *, client_id: str, request: Any
        ) -> KnowledgeQueryAdmission | None:
            if client_id not in {"agent-one", "agent-two"}:
                return None
            assert request.knowledge_base_release_id == "release-opaque-id"
            return KnowledgeQueryAdmission(
                knowledge_space_id="space-shared",
                client_grant_id=f"grant-{client_id}",
                effective_access_scope_digest=f"sha256:{client_id[6] * 64}",
            )

    def authenticate(request: Request) -> KnowledgeServiceClient:
        clients = {
            "Bearer agent-one": "agent-one",
            "Bearer agent-two": "agent-two",
            "Bearer agent-three": "agent-three",
        }
        return KnowledgeServiceClient(client_id=clients[request.headers["authorization"]])

    query_ids = iter(("query-agent-one", "query-agent-two", "query-must-not-exist"))
    client = _client(
        authenticate_client=authenticate,
        id_factory=query_ids.__next__,
        query_authorizer=SharedSpaceAuthorizer(),
    )

    responses = [
        client.post(
            "/v1/knowledge-queries",
            headers={
                "Authorization": f"Bearer {agent}",
                "Idempotency-Key": "shared-attempt-key",
            },
            json=_valid_request_payload(),
        )
        for agent in ("agent-one", "agent-two", "agent-three")
    ]

    assert [response.status_code for response in responses] == [202, 202, 403]
    assert responses[0].json()["knowledge_query_id"] == "query-agent-one"
    assert responses[1].json()["knowledge_query_id"] == "query-agent-two"
    assert "knowledge_space_id" not in responses[0].json()
    assert responses[2].json() == {
        "type": "urn:knowledge-source-service:problem:knowledge-query-access-denied",
        "title": "Knowledge Query access denied",
        "status": 403,
        "code": "knowledge_query_access_denied",
        "detail": (
            "The client is not permitted to query the selected Knowledge Base Release."
        ),
        "trace_id": "trace-test-1",
        "retryable": False,
        "blockers": [],
    }


def test_created_knowledge_query_is_pollable_through_its_location() -> None:
    client = _client()
    create_response = client.post(
        "/v1/knowledge-queries",
        headers={
            "Authorization": "Bearer test-token",
            "Idempotency-Key": "query-attempt-1",
        },
        json=_valid_request_payload(),
    )

    get_response = client.get(
        create_response.headers["location"],
        headers={"Authorization": "Bearer test-token"},
    )

    assert get_response.status_code == 200, get_response.text
    assert get_response.json() == create_response.json()


def test_exact_idempotency_replay_returns_the_same_knowledge_query() -> None:
    query_ids = iter(("query-first", "query-must-not-be-created"))
    client = _client(id_factory=query_ids.__next__)
    headers = {
        "Authorization": "Bearer test-token",
        "Idempotency-Key": "query-attempt-1",
    }

    first_response = client.post(
        "/v1/knowledge-queries",
        headers=headers,
        json=_valid_request_payload(),
    )
    replay_response = client.post(
        "/v1/knowledge-queries",
        headers=headers,
        json=_valid_request_payload(),
    )

    assert first_response.status_code == 202, first_response.text
    assert replay_response.status_code == 200, replay_response.text
    assert replay_response.headers["location"] == first_response.headers["location"]
    assert replay_response.json() == first_response.json()


def test_idempotency_key_reuse_with_another_request_returns_safe_conflict() -> None:
    query_ids = iter(("query-first", "query-must-not-be-created"))
    client = _client(id_factory=query_ids.__next__)
    headers = {
        "Authorization": "Bearer test-token",
        "Idempotency-Key": "query-attempt-1",
    }
    first_payload = _valid_request_payload()
    conflicting_payload = _valid_request_payload()
    conflicting_payload["question"] = "另一条问题"

    first_response = client.post(
        "/v1/knowledge-queries",
        headers=headers,
        json=first_payload,
    )
    conflict_response = client.post(
        "/v1/knowledge-queries",
        headers=headers,
        json=conflicting_payload,
    )

    assert first_response.status_code == 202
    assert conflict_response.status_code == 409, conflict_response.text
    assert conflict_response.headers["content-type"].startswith("application/problem+json")
    assert conflict_response.json() == {
        "type": "urn:knowledge-source-service:problem:idempotency-key-mismatch",
        "title": "Idempotency key conflict",
        "status": 409,
        "code": "idempotency_key_mismatch",
        "detail": "The Idempotency-Key is already bound to a different request.",
        "trace_id": "trace-test-1",
        "retryable": False,
        "blockers": [],
    }


def test_one_client_cannot_poll_another_clients_knowledge_query() -> None:
    def authenticate(request: Request) -> KnowledgeServiceClient:
        client_by_credential = {
            "Bearer client-one-token": KnowledgeServiceClient(client_id="client-one"),
            "Bearer client-two-token": KnowledgeServiceClient(client_id="client-two"),
        }
        credential = request.headers.get("authorization")
        if credential not in client_by_credential:
            raise HTTPException(status_code=401, detail="invalid test credential")
        return client_by_credential[credential]

    client = _client(authenticate_client=authenticate)
    create_response = client.post(
        "/v1/knowledge-queries",
        headers={
            "Authorization": "Bearer client-one-token",
            "Idempotency-Key": "query-attempt-1",
        },
        json=_valid_request_payload(),
    )

    foreign_get_response = client.get(
        create_response.headers["location"],
        headers={"Authorization": "Bearer client-two-token"},
    )

    assert create_response.status_code == 202
    assert foreign_get_response.status_code == 404
    assert "query-opaque-id" not in foreign_get_response.text


def test_create_knowledge_query_requires_a_non_blank_idempotency_key_header() -> None:
    client = _client()

    response = client.post(
        "/v1/knowledge-queries",
        headers={
            "Authorization": "Bearer test-token",
            "Idempotency-Key": "   ",
        },
        json=_valid_request_payload(),
    )

    assert response.status_code == 400, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json() == {
        "type": "urn:knowledge-source-service:problem:invalid-idempotency-key",
        "title": "Invalid Idempotency-Key",
        "status": 400,
        "code": "invalid_idempotency_key",
        "detail": "A non-blank Idempotency-Key header is required.",
        "trace_id": "trace-test-1",
        "retryable": False,
        "blockers": [],
    }


def test_unknown_knowledge_query_returns_safe_problem_details() -> None:
    client = _client()

    response = client.get(
        "/v1/knowledge-queries/not-visible",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json() == {
        "type": "urn:knowledge-source-service:problem:knowledge-query-not-found",
        "title": "Knowledge Query not found",
        "status": 404,
        "code": "knowledge_query_not_found",
        "detail": "The Knowledge Query does not exist or is not visible to this client.",
        "trace_id": "trace-test-1",
        "retryable": False,
        "blockers": [],
    }


def test_cancel_queued_knowledge_query_returns_the_same_terminal_resource() -> None:
    client = _client()
    create_response = client.post(
        "/v1/knowledge-queries",
        headers={
            "Authorization": "Bearer test-token",
            "Idempotency-Key": "query-attempt-1",
        },
        json=_valid_request_payload(),
    )

    cancel_response = client.post(
        create_response.json()["links"]["cancel"],
        headers={"Authorization": "Bearer test-token"},
    )

    assert cancel_response.status_code == 200, cancel_response.text
    assert cancel_response.json() == {
        **create_response.json(),
        "state": "cancelled",
        "completed_at": "2026-08-11T10:29:10Z",
        "cancel_requested_at": "2026-08-11T10:29:10Z",
        "result_availability": "unavailable",
    }


def test_create_rejects_a_knowledge_query_deadline_that_has_already_elapsed() -> None:
    client = _client()
    payload = _valid_request_payload()
    payload["deadline_at"] = "2026-08-11T10:29:09Z"

    response = client.post(
        "/v1/knowledge-queries",
        headers={
            "Authorization": "Bearer test-token",
            "Idempotency-Key": "query-attempt-1",
        },
        json=payload,
    )

    assert response.status_code == 422, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json() == {
        "type": "urn:knowledge-source-service:problem:knowledge-query-deadline-elapsed",
        "title": "Knowledge Query deadline elapsed",
        "status": 422,
        "code": "knowledge_query_deadline_elapsed",
        "detail": "deadline_at must be later than the Query submission time.",
        "trace_id": "trace-test-1",
        "retryable": False,
        "blockers": [],
    }


def test_liveness_exposes_the_running_service_release_without_authentication() -> None:
    client = _client(release_identity="sha256:test-release")

    response = client.get("/livez")

    assert response.status_code == 200
    assert response.json() == {
        "schema_version": "knowledge-service-health.v1",
        "status": "alive",
        "service": "knowledge-source-service",
        "release_identity": "sha256:test-release",
    }


def test_readiness_reports_only_bounded_required_dependency_states() -> None:
    client = _client()

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {
        "schema_version": "knowledge-service-readiness.v1",
        "status": "ready",
        "service": "knowledge-source-service",
        "release_identity": "kss-test-release",
        "dependencies": [
            {"name": "postgresql", "status": "ready"},
            {"name": "object_storage", "status": "ready"},
            {"name": "search", "status": "ready"},
        ],
    }


def test_readiness_fails_closed_when_a_required_dependency_is_unavailable() -> None:
    client = _client(
        readiness_probe=lambda: {
            "postgresql": True,
            "object_storage": False,
            "search": True,
            "private_object_store_endpoint": True,
        }
    )

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {
        "schema_version": "knowledge-service-readiness.v1",
        "status": "unavailable",
        "service": "knowledge-source-service",
        "release_identity": "kss-test-release",
        "dependencies": [
            {"name": "postgresql", "status": "ready"},
            {"name": "object_storage", "status": "unavailable"},
            {"name": "search", "status": "ready"},
        ],
    }
    assert "private_object_store_endpoint" not in response.text
