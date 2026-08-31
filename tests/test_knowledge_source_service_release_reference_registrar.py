from __future__ import annotations

import json
from typing import Any

import pytest

from proof_agent.capabilities.knowledge.source_service_release_reference_registrar import (
    KnowledgeSourceServiceReleaseReferenceRegistrar,
)
from proof_agent.contracts import ProductionAgentReleaseReferenceRequest
from proof_agent.contracts.ports.guarded_http import GuardedHttpResponse
from proof_agent.errors import ProofAgentError


def _request() -> ProductionAgentReleaseReferenceRequest:
    return ProductionAgentReleaseReferenceRequest(
        knowledge_space_id="space-claims",
        knowledge_base_id="base-claims",
        knowledge_base_release_id="release-claims-v7",
        external_resource_id="provisional-agent-version-05d",
    )


def _wire_resource(**changes: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "knowledge-base-release-reference.v1",
        **_request().model_dump(mode="json"),
        "release_reference_id": "release-reference-05d",
        "authenticated_client_id": "proof-agent-production",
        "registered_at": "2026-08-30T13:00:00Z",
        "state": "active",
    }
    payload.update(changes)
    return payload


class _RecordingHttpClient:
    def __init__(self, response: GuardedHttpResponse) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> GuardedHttpResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.response


def _response(payload: dict[str, Any], *, status_code: int = 200) -> GuardedHttpResponse:
    return GuardedHttpResponse(
        status_code=status_code,
        headers={"Content-Type": "application/json"},
        body=json.dumps(payload).encode(),
    )


def test_registrar_posts_exact_reference_through_dedicated_guarded_client() -> None:
    http = _RecordingHttpClient(_response(_wire_resource()))
    registrar = KnowledgeSourceServiceReleaseReferenceRegistrar(
        endpoint="https://knowledge.internal",
        http_client=http,
        authorization_header_factory=lambda: "Bearer reference-client-token",
        timeout_seconds=4.0,
    )

    result = registrar.register_release_reference(
        _request(),
        idempotency_key="formal-agent-reference:provisional-agent-version-05d",
    )

    assert result.model_dump(mode="json") == {
        "schema_version": "registered-production-agent-release-reference.v1",
        **_request().model_dump(mode="json"),
        "release_reference_id": "release-reference-05d",
        "authenticated_client_id": "proof-agent-production",
        "registered_at": "2026-08-30T13:00:00Z",
        "state": "active",
    }
    assert http.calls == [
        {
            "method": "POST",
            "url": "https://knowledge.internal/v1/knowledge-base-release-references",
            "headers": {
                "Authorization": "Bearer reference-client-token",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Idempotency-Key": ("formal-agent-reference:provisional-agent-version-05d"),
            },
            "body": json.dumps(
                _request().model_dump(mode="json"),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode(),
            "timeout_seconds": 4.0,
        }
    ]


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": "knowledge-base-release-reference.v2"},
        {"knowledge_base_release_id": "release-drifted"},
        {"external_resource_id": "version-drifted"},
        {"state": "deregistered"},
        {"unknown_response_field": "response-secret-sentinel"},
    ],
)
def test_registrar_fails_closed_on_wire_contract_or_identity_drift(
    changes: dict[str, Any],
) -> None:
    http = _RecordingHttpClient(_response(_wire_resource(**changes)))
    registrar = KnowledgeSourceServiceReleaseReferenceRegistrar(
        endpoint="https://knowledge.internal",
        http_client=http,
        authorization_header_factory=lambda: "Bearer reference-client-token",
    )

    with pytest.raises(ProofAgentError) as captured:
        registrar.register_release_reference(_request(), idempotency_key="reference-key-05d")

    assert captured.value.code == "PA_KNOWLEDGE_002"
    assert "response-secret-sentinel" not in str(captured.value)


@pytest.mark.parametrize(
    ("response", "max_response_bytes"),
    [
        (_response(_wire_resource(), status_code=307), 1024),
        (_response({"detail": "upstream-secret-sentinel"}, status_code=409), 1024),
        (
            GuardedHttpResponse(status_code=200, headers={}, body=b"{" + b"x" * 1024),
            128,
        ),
    ],
)
def test_registrar_rejects_redirect_error_and_oversized_responses_without_echo(
    response: GuardedHttpResponse,
    max_response_bytes: int,
) -> None:
    registrar = KnowledgeSourceServiceReleaseReferenceRegistrar(
        endpoint="https://knowledge.internal",
        http_client=_RecordingHttpClient(response),
        authorization_header_factory=lambda: "Bearer reference-client-token",
        max_response_bytes=max_response_bytes,
    )

    with pytest.raises(ProofAgentError) as captured:
        registrar.register_release_reference(_request(), idempotency_key="reference-key-05d")

    assert captured.value.code == "PA_KNOWLEDGE_002"
    assert "upstream-secret-sentinel" not in str(captured.value)


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://knowledge.internal",
        "https://user:password@knowledge.internal",
        "https://knowledge.internal/api",
        "https://knowledge.internal?token=secret",
    ],
)
def test_registrar_requires_https_origin(endpoint: str) -> None:
    with pytest.raises(ValueError, match="HTTPS origin"):
        KnowledgeSourceServiceReleaseReferenceRegistrar(
            endpoint=endpoint,
            http_client=_RecordingHttpClient(_response(_wire_resource())),
            authorization_header_factory=lambda: "Bearer reference-client-token",
        )


@pytest.mark.parametrize(
    "authorization",
    ["", "operator-service-token", "Basic operator-service-token", "Bearer token with-space"],
)
def test_registrar_requires_exact_bearer_client_authorization(authorization: str) -> None:
    http = _RecordingHttpClient(_response(_wire_resource()))
    registrar = KnowledgeSourceServiceReleaseReferenceRegistrar(
        endpoint="https://knowledge.internal",
        http_client=http,
        authorization_header_factory=lambda: authorization,
    )

    with pytest.raises(ProofAgentError) as captured:
        registrar.register_release_reference(_request(), idempotency_key="reference-key-05d")

    assert captured.value.code == "PA_KNOWLEDGE_002"
    assert http.calls == []
