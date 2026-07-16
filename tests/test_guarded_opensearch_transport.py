from __future__ import annotations

import json
from collections.abc import Mapping

import pytest

from proof_agent.capabilities.knowledge.hybrid.opensearch import (
    GuardedOpenSearchTransport,
    OpenSearchProjectionError,
    OpenSearchSecretMaterial,
)
from proof_agent.contracts.ports.guarded_http import GuardedHttpResponse


class RecordingGuardedClient:
    def __init__(self, responses: list[GuardedHttpResponse]) -> None:
        self.responses = responses
        self.requests: list[dict[str, object]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        timeout_seconds: float = 10.0,
    ) -> GuardedHttpResponse:
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers or {}),
                "body": body,
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.responses.pop(0)


class SecretProvider:
    def __init__(self, material: OpenSearchSecretMaterial) -> None:
        self.material = material
        self.handles: list[str] = []

    def resolve(self, secret_handle: str) -> OpenSearchSecretMaterial:
        self.handles.append(secret_handle)
        return self.material


def response(status_code: int, body: object) -> GuardedHttpResponse:
    return GuardedHttpResponse(
        status_code=status_code,
        headers={"content-type": "application/json"},
        body=json.dumps(body).encode(),
    )


def test_guarded_opensearch_routes_exact_request_through_active_egress_client() -> None:
    client = RecordingGuardedClient([response(200, {"hits": {"hits": []}})])
    secrets = SecretProvider(
        OpenSearchSecretMaterial(headers={"Authorization": "Bearer opaque"})
    )
    transport = GuardedOpenSearchTransport(
        endpoint="https://search.internal.example:9443",
        guarded_http_client=client,
        secret_handle="vault://knowledge/opensearch",
        secret_provider=secrets,
    )

    result = transport.request(
        method="POST",
        path="/pa-knowledge-source/_search",
        json_body={"size": 10},
        query_params={"search_pipeline": "proof-agent-v1"},
    )

    assert result.status_code == 200
    assert result.body == {"hits": {"hits": []}}
    assert secrets.handles == ["vault://knowledge/opensearch"]
    assert client.requests == [
        {
            "method": "POST",
            "url": (
                "https://search.internal.example:9443/pa-knowledge-source/_search"
                "?search_pipeline=proof-agent-v1"
            ),
            "headers": {
                "Authorization": "Bearer opaque",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            "body": b'{"size":10}',
            "timeout_seconds": 10.0,
        }
    ]


@pytest.mark.parametrize(
    ("endpoint", "message"),
    [
        ("http://search.internal.example", "HTTPS"),
        ("https://user@search.internal.example", "credentials"),
        ("https://search.internal.example/base", "path"),
    ],
)
def test_guarded_opensearch_requires_one_exact_https_origin(
    endpoint: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        GuardedOpenSearchTransport(
            endpoint=endpoint,
            guarded_http_client=RecordingGuardedClient([]),
        )

def test_guarded_opensearch_rejects_redirects_and_oversized_responses() -> None:
    redirecting = GuardedOpenSearchTransport(
        endpoint="https://search.internal.example",
        guarded_http_client=RecordingGuardedClient([response(307, {})]),
    )
    with pytest.raises(OpenSearchProjectionError, match="redirects"):
        redirecting.request(method="GET", path="/_cluster/health")

    oversized = GuardedOpenSearchTransport(
        endpoint="https://search.internal.example",
        guarded_http_client=RecordingGuardedClient(
            [GuardedHttpResponse(status_code=200, headers={}, body=b"{" + b"x" * 128)]
        ),
        max_response_bytes=64,
    )
    with pytest.raises(OpenSearchProjectionError, match="configured limit"):
        oversized.request(method="GET", path="/_cluster/health")


def test_guarded_opensearch_rejects_file_based_tls_secret_material() -> None:
    secrets = SecretProvider(
        OpenSearchSecretMaterial(
            headers={},
            client_certificate_path="/run/secrets/client.pem",
            client_key_path="/run/secrets/client.key",
        )
    )

    with pytest.raises(ValueError, match="per-origin mTLS"):
        GuardedOpenSearchTransport(
            endpoint="https://search.internal.example",
            guarded_http_client=RecordingGuardedClient([]),
            secret_handle="vault://knowledge/opensearch",
            secret_provider=secrets,
        )
