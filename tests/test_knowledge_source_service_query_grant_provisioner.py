from __future__ import annotations

import json
from typing import Any

import pytest

from proof_agent.capabilities.knowledge.source_service_query_grant_provisioner import (
    KnowledgeSourceServiceQueryGrantProvisioner,
)
from proof_agent.contracts import ProductionAgentKnowledgeQueryGrantRequest
from proof_agent.contracts.ports.guarded_http import GuardedHttpResponse
from proof_agent.errors import ProofAgentError


class _RecordingHttpClient:
    def __init__(self, response: GuardedHttpResponse) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> GuardedHttpResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.response


def _request() -> ProductionAgentKnowledgeQueryGrantRequest:
    return ProductionAgentKnowledgeQueryGrantRequest(
        knowledge_base_release_id="release-claims-v7",
    )


def _wire_receipt() -> dict[str, Any]:
    return {
        "schema_version": "knowledge-query-grant.v1",
        "client_grant_id": "query-grant-runtime-v7",
        "client_id": "proof-agent-runtime",
        "knowledge_space_id": "space-claims",
        "knowledge_base_release_id": "release-claims-v7",
        "allowed_strategies": ["single_pass", "agentic"],
        "execution_budget": {
            "max_rounds": 1,
            "max_model_calls": 1,
            "max_candidates": 20,
            "max_model_tokens": 1000,
            "max_duration_ms": 5000,
        },
        "effective_access_scope_digest": f"sha256:{'c' * 64}",
        "active": True,
        "created_at": "2026-08-30T13:00:00Z",
    }


def _response(
    payload: dict[str, Any],
    *,
    status_code: int = 200,
) -> GuardedHttpResponse:
    return GuardedHttpResponse(
        status_code=status_code,
        headers={"Content-Type": "application/json"},
        body=json.dumps(payload).encode(),
    )


def test_provisioner_posts_only_exact_release_and_returns_strict_receipt() -> None:
    http = _RecordingHttpClient(_response(_wire_receipt()))
    provisioner = KnowledgeSourceServiceQueryGrantProvisioner(
        endpoint="https://knowledge.internal",
        http_client=http,
        authorization_header_factory=lambda: "Bearer operator-service-token",
        timeout_seconds=4.0,
    )

    receipt = provisioner.provision_query_grant(_request())

    assert receipt.model_dump(mode="json") == _wire_receipt()
    assert http.calls == [
        {
            "method": "POST",
            "url": "https://knowledge.internal/v1/knowledge-query-grants",
            "headers": {
                "Authorization": "Bearer operator-service-token",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            "body": b'{"knowledge_base_release_id":"release-claims-v7"}',
            "timeout_seconds": 4.0,
        }
    ]


@pytest.mark.parametrize(
    "changes",
    [
        {"knowledge_base_release_id": "release-drifted"},
        {"unknown_response_field": "response-secret-sentinel"},
        {"active": False},
        {"allowed_strategies": ["single_pass", "single_pass"]},
    ],
)
def test_provisioner_fails_closed_on_receipt_contract_or_release_drift(
    changes: dict[str, Any],
) -> None:
    payload = {**_wire_receipt(), **changes}
    provisioner = KnowledgeSourceServiceQueryGrantProvisioner(
        endpoint="https://knowledge.internal",
        http_client=_RecordingHttpClient(_response(payload)),
        authorization_header_factory=lambda: "Bearer operator-service-token",
    )

    with pytest.raises(ProofAgentError) as captured:
        provisioner.provision_query_grant(_request())

    assert captured.value.code == "PA_KNOWLEDGE_002"
    assert "response-secret-sentinel" not in str(captured.value)


@pytest.mark.parametrize(
    ("response", "max_response_bytes"),
    [
        (_response(_wire_receipt(), status_code=307), 1024),
        (_response({"detail": "upstream-secret-sentinel"}, status_code=409), 1024),
        (
            GuardedHttpResponse(status_code=200, headers={}, body=b"{" + b"x" * 1024),
            128,
        ),
    ],
)
def test_provisioner_rejects_redirect_error_and_oversized_responses_without_echo(
    response: GuardedHttpResponse,
    max_response_bytes: int,
) -> None:
    provisioner = KnowledgeSourceServiceQueryGrantProvisioner(
        endpoint="https://knowledge.internal",
        http_client=_RecordingHttpClient(response),
        authorization_header_factory=lambda: "Bearer operator-service-token",
        max_response_bytes=max_response_bytes,
    )

    with pytest.raises(ProofAgentError) as captured:
        provisioner.provision_query_grant(_request())

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
def test_provisioner_requires_https_origin(endpoint: str) -> None:
    with pytest.raises(ValueError, match="HTTPS origin"):
        KnowledgeSourceServiceQueryGrantProvisioner(
            endpoint=endpoint,
            http_client=_RecordingHttpClient(_response(_wire_receipt())),
            authorization_header_factory=lambda: "Bearer operator-service-token",
        )


@pytest.mark.parametrize(
    "authorization",
    ["", "operator-service-token", "Basic operator-service-token", "Bearer token with-space"],
)
def test_provisioner_requires_exact_bearer_operator_authorization(
    authorization: str,
) -> None:
    http = _RecordingHttpClient(_response(_wire_receipt()))
    provisioner = KnowledgeSourceServiceQueryGrantProvisioner(
        endpoint="https://knowledge.internal",
        http_client=http,
        authorization_header_factory=lambda: authorization,
    )

    with pytest.raises(ProofAgentError) as captured:
        provisioner.provision_query_grant(_request())

    assert captured.value.code == "PA_KNOWLEDGE_002"
    assert http.calls == []
