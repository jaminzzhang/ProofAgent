from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import json
from urllib.parse import parse_qs, urlsplit

from authlib.jose import JsonWebKey, jwt
import pytest

from proof_agent.capabilities.identity.oidc_client import (
    GuardedOidcClient,
    OidcProviderConfiguration,
)
from proof_agent.contracts.ports.guarded_http import GuardedHttpResponse
from proof_agent.contracts.ports.oidc import OidcVerificationError


NOW = datetime(2026, 7, 15, 4, 0, tzinfo=UTC)


class QueueGuardedClient:
    def __init__(self, responses: list[GuardedHttpResponse]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        timeout_seconds: float = 10.0,
    ) -> GuardedHttpResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers or {}),
                "body": body,
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.responses.pop(0)


def configuration() -> OidcProviderConfiguration:
    return OidcProviderConfiguration(
        issuer="https://identity.example.com/tenant/v2.0",
        authorization_endpoint="https://identity.example.com/authorize",
        token_endpoint="https://identity.example.com/token",
        jwks_uri="https://identity.example.com/jwks",
        client_id="proof-agent",
        scopes=("openid", "profile", "email"),
        groups_claim="groups",
        roles_claim="roles",
    )


def key_pair() -> tuple[object, dict[str, object]]:
    key = JsonWebKey.generate_key(
        "RSA",
        2048,
        is_private=True,
        options={"kid": "signing-key-1"},
    )
    return key, key.as_dict(is_private=False)


def id_token(
    key: object,
    *,
    issuer: str = "https://identity.example.com/tenant/v2.0",
    audience: str = "proof-agent",
    nonce: str = "expected-nonce",
) -> str:
    encoded = jwt.encode(
        {"alg": "RS256", "kid": "signing-key-1", "typ": "JWT"},
        {
            "iss": issuer,
            "aud": audience,
            "sub": "operator-subject-1",
            "name": "Operator One",
            "groups": ["insurance-ops"],
            "roles": ["knowledge-editor"],
            "nonce": nonce,
            "iat": int(NOW.timestamp()) - 10,
            "auth_time": int(NOW.timestamp()) - 30,
            "exp": int(NOW.timestamp()) + 300,
        },
        key,
    )
    return encoded.decode("ascii")


def guarded_responses(token: str, jwk: dict[str, object]) -> list[GuardedHttpResponse]:
    return [
        GuardedHttpResponse(
            status_code=200,
            headers={"content-type": "application/json"},
            body=json.dumps(
                {
                    "token_type": "Bearer",
                    "access_token": "provider-access-secret",
                    "refresh_token": "provider-refresh-secret",
                    "id_token": token,
                }
            ).encode(),
        ),
        GuardedHttpResponse(
            status_code=200,
            headers={"content-type": "application/json"},
            body=json.dumps({"keys": [jwk]}).encode(),
        ),
    ]


def discovery_response() -> GuardedHttpResponse:
    return GuardedHttpResponse(
        status_code=200,
        headers={"content-type": "application/json"},
        body=json.dumps(
            {
                "issuer": "https://identity.example.com/tenant/v2.0",
                "authorization_endpoint": "https://identity.example.com/authorize",
                "token_endpoint": "https://identity.example.com/token",
                "jwks_uri": "https://identity.example.com/jwks",
            }
        ).encode(),
    )


def test_authorization_url_is_exact_oidc_code_flow_with_s256_pkce() -> None:
    client = GuardedOidcClient(
        QueueGuardedClient([]),
        configuration=configuration(),
        client_secret=b"client-secret",
        clock=lambda: NOW,
    )

    url = client.authorization_url(
        state="one-time-state",
        nonce="one-time-nonce",
        code_challenge="s256-challenge",
        redirect_uri="https://proof-agent.example.com/api/auth/callback",
    )
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)

    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == (
        "https://identity.example.com/authorize"
    )
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] == ["s256-challenge"]
    assert "code_verifier" not in query


def test_readiness_verifies_exact_discovery_metadata_and_nonempty_jwks() -> None:
    _key, jwk = key_pair()
    guarded = QueueGuardedClient(
        [
            discovery_response(),
            GuardedHttpResponse(
                status_code=200,
                headers={"content-type": "application/json"},
                body=json.dumps({"keys": [jwk]}).encode(),
            ),
        ]
    )
    client = GuardedOidcClient(
        guarded,
        configuration=configuration(),
        client_secret=b"client-secret",
        clock=lambda: NOW,
    )

    assert client.check_ready() is True
    assert [call["url"] for call in guarded.calls] == [
        "https://identity.example.com/tenant/v2.0/.well-known/openid-configuration",
        "https://identity.example.com/jwks",
    ]


def test_readiness_rejects_discovery_metadata_drift() -> None:
    response = discovery_response()
    payload = json.loads(response.body)
    payload["jwks_uri"] = "https://identity.example.com/changed-jwks"
    client = GuardedOidcClient(
        QueueGuardedClient(
            [
                GuardedHttpResponse(
                    status_code=200,
                    headers=response.headers,
                    body=json.dumps(payload).encode(),
                )
            ]
        ),
        configuration=configuration(),
        client_secret=b"client-secret",
        clock=lambda: NOW,
    )

    with pytest.raises(OidcVerificationError, match="discovery_metadata_mismatch"):
        client.check_ready()


def test_code_exchange_uses_guarded_token_and_jwks_calls_then_verifies_claims() -> None:
    key, jwk = key_pair()
    guarded = QueueGuardedClient(guarded_responses(id_token(key), jwk))
    client = GuardedOidcClient(
        guarded,
        configuration=configuration(),
        client_secret=b"client-secret",
        clock=lambda: NOW,
    )

    material = client.exchange_code(
        code="authorization-code",
        code_verifier="one-time-verifier",
        expected_nonce="expected-nonce",
        redirect_uri="https://proof-agent.example.com/api/auth/callback",
    )

    assert material.principal.subject == "operator-subject-1"
    assert material.principal.trusted_groups == ("insurance-ops",)
    assert material.principal.trusted_roles == ("knowledge-editor",)
    assert b"provider-refresh-secret" in material.provider_token_material
    assert [call["url"] for call in guarded.calls] == [
        "https://identity.example.com/token",
        "https://identity.example.com/jwks",
    ]
    token_form = parse_qs(guarded.calls[0]["body"].decode())
    assert token_form["grant_type"] == ["authorization_code"]
    assert token_form["code_verifier"] == ["one-time-verifier"]
    assert "client-secret" not in guarded.calls[0]["body"].decode()
    assert guarded.calls[0]["headers"]["Authorization"].startswith("Basic ")


@pytest.mark.parametrize(
    ("claim", "value"),
    (
        ("issuer", "https://identity.example.com/other"),
        ("audience", "another-client"),
        ("nonce", "another-nonce"),
    ),
)
def test_code_exchange_rejects_wrong_issuer_audience_or_nonce(
    claim: str,
    value: str,
) -> None:
    key, jwk = key_pair()
    overrides = {claim: value}
    token = id_token(key, **overrides)
    client = GuardedOidcClient(
        QueueGuardedClient(guarded_responses(token, jwk)),
        configuration=configuration(),
        client_secret=b"client-secret",
        clock=lambda: NOW,
    )

    with pytest.raises(OidcVerificationError):
        client.exchange_code(
            code="authorization-code",
            code_verifier="verifier",
            expected_nonce="expected-nonce",
            redirect_uri="https://proof-agent.example.com/api/auth/callback",
        )


def test_code_exchange_rejects_token_signed_by_untrusted_key() -> None:
    trusted_key, trusted_jwk = key_pair()
    untrusted_key, _ = key_pair()
    del trusted_key
    client = GuardedOidcClient(
        QueueGuardedClient(guarded_responses(id_token(untrusted_key), trusted_jwk)),
        configuration=configuration(),
        client_secret=b"client-secret",
        clock=lambda: NOW,
    )

    with pytest.raises(OidcVerificationError):
        client.exchange_code(
            code="authorization-code",
            code_verifier="verifier",
            expected_nonce="expected-nonce",
            redirect_uri="https://proof-agent.example.com/api/auth/callback",
        )
