from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import pytest
import httpx

from proof_agent.capabilities.egress.guarded_http import (
    GuardedHttpsClient,
    PinnedHttpTransport,
)
from proof_agent.capabilities.egress.httpx_adapter import GuardedHttpxTransport
from proof_agent.contracts import EgressOriginRule, EgressPolicyVersion, ExactHttpsOrigin
from proof_agent.contracts.ports.guarded_http import GuardedHttpResponse
from proof_agent.control.security.egress import CompiledEgressPolicy, EgressDeniedError


@dataclass
class RecordingResolver:
    answers: list[tuple[str, ...]]
    calls: list[tuple[str, int]] = field(default_factory=list)

    def resolve(self, hostname: str, port: int, *, timeout_seconds: float) -> tuple[str, ...]:
        del timeout_seconds
        self.calls.append((hostname, port))
        return self.answers.pop(0)


@dataclass
class RecordingTransport(PinnedHttpTransport):
    responses: list[GuardedHttpResponse]
    calls: list[dict[str, object]] = field(default_factory=list)

    def send(
        self,
        method: str,
        url: str,
        *,
        connect_address: str,
        tls_hostname: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> GuardedHttpResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "connect_address": connect_address,
                "tls_hostname": tls_hostname,
                "headers": dict(headers),
                "body": body,
                "timeout_seconds": timeout_seconds,
                "max_response_bytes": max_response_bytes,
            }
        )
        return self.responses.pop(0)


def response(
    status_code: int = 200,
    *,
    headers: Mapping[str, str] | None = None,
    body: bytes = b"{}",
) -> GuardedHttpResponse:
    return GuardedHttpResponse(status_code=status_code, headers=headers or {}, body=body)


def compiled_policy() -> CompiledEgressPolicy:
    return CompiledEgressPolicy(
        EgressPolicyVersion(
            version_id="019ba001-1111-7000-8000-000000000401",
            revision=1,
            rules=(
                EgressOriginRule(
                    origin=ExactHttpsOrigin.parse("https://api.example.com"),
                    allowed_ip_networks=("203.0.113.0/24",),
                ),
                EgressOriginRule(
                    origin=ExactHttpsOrigin.parse("https://redirect.example.net:8443"),
                    allowed_ip_networks=("198.51.100.0/24",),
                ),
            ),
            created_at="2026-07-15T00:00:00Z",
            created_by="security-admin",
        )
    )


def test_guarded_client_connects_to_validated_ip_with_original_tls_hostname() -> None:
    resolver = RecordingResolver(answers=[("203.0.113.8", "203.0.113.9")])
    transport = RecordingTransport(responses=[response(body=b'{"ok":true}')])
    client = GuardedHttpsClient(
        policy=compiled_policy(), resolver=resolver, transport=transport
    )

    result = client.request("GET", "https://API.example.com/v1/models?limit=1")

    assert result.body == b'{"ok":true}'
    assert resolver.calls == [("api.example.com", 443)]
    assert transport.calls[0]["connect_address"] == "203.0.113.8"
    assert transport.calls[0]["tls_hostname"] == "api.example.com"


def test_guarded_client_reauthorizes_an_exact_redirect_before_following() -> None:
    resolver = RecordingResolver(
        answers=[("203.0.113.8",), ("198.51.100.10",)]
    )
    transport = RecordingTransport(
        responses=[
            response(307, headers={"location": "https://redirect.example.net:8443/next"}),
            response(body=b"done"),
        ]
    )
    client = GuardedHttpsClient(
        policy=compiled_policy(), resolver=resolver, transport=transport
    )

    assert client.request("POST", "https://api.example.com/start", body=b"x").body == b"done"
    assert resolver.calls == [
        ("api.example.com", 443),
        ("redirect.example.net", 8443),
    ]
    assert transport.calls[1]["tls_hostname"] == "redirect.example.net"


def test_guarded_client_denies_off_policy_redirect_before_dns_or_transport() -> None:
    resolver = RecordingResolver(answers=[("203.0.113.8",)])
    transport = RecordingTransport(
        responses=[response(302, headers={"location": "https://evil.example.org/steal"})]
    )
    client = GuardedHttpsClient(
        policy=compiled_policy(), resolver=resolver, transport=transport
    )

    with pytest.raises(EgressDeniedError, match="origin_not_allowed"):
        client.request("GET", "https://api.example.com/start")
    assert resolver.calls == [("api.example.com", 443)]
    assert len(transport.calls) == 1


def test_guarded_client_denies_mixed_dns_answer_set_before_connecting() -> None:
    resolver = RecordingResolver(answers=[("203.0.113.8", "10.0.0.8")])
    transport = RecordingTransport(responses=[])
    client = GuardedHttpsClient(
        policy=compiled_policy(), resolver=resolver, transport=transport
    )

    with pytest.raises(EgressDeniedError, match="dns_address_not_allowed"):
        client.request("GET", "https://api.example.com/data")
    assert transport.calls == []


def test_guarded_client_reresolves_retry_and_fails_closed_on_dns_rebinding() -> None:
    resolver = RecordingResolver(
        answers=[("203.0.113.8",), ("192.0.2.99",)]
    )
    transport = RecordingTransport(responses=[response(503)])
    client = GuardedHttpsClient(
        policy=compiled_policy(),
        resolver=resolver,
        transport=transport,
        max_attempts_per_hop=2,
    )

    with pytest.raises(EgressDeniedError, match="dns_address_not_allowed"):
        client.request("GET", "https://api.example.com/data")
    assert resolver.calls == [
        ("api.example.com", 443),
        ("api.example.com", 443),
    ]
    assert len(transport.calls) == 1


def test_denial_audit_is_trace_safe_and_never_contains_query_or_credentials() -> None:
    denials: list[tuple[str, str | None]] = []
    resolver = RecordingResolver(answers=[("203.0.113.8",)])
    client = GuardedHttpsClient(
        policy=compiled_policy(),
        resolver=resolver,
        transport=RecordingTransport(responses=[]),
        denial_audit_sink=lambda reason, origin: denials.append((reason, origin)),
    )

    with pytest.raises(EgressDeniedError):
        client.request(
            "GET",
            "https://user:super-secret@api.example.com/data?token=never-log-this",
        )
    assert denials == [("userinfo_forbidden", None)]
    assert "secret" not in repr(denials)
    assert "token" not in repr(denials)


def test_httpx_sdk_bridge_has_no_transport_except_guarded_client() -> None:
    guarded = RecordingGuardedClientForHttpx()

    with httpx.Client(transport=GuardedHttpxTransport(guarded)) as client:
        result = client.post(
            "https://api.example.com/v1/chat/completions?mode=strict",
            headers={"Authorization": "Bearer secret"},
            content=b"{}",
            timeout=3.0,
        )

    assert result.json() == {"guarded": True}
    assert guarded.calls[0][0:2] == (
        "POST",
        "https://api.example.com/v1/chat/completions?mode=strict",
    )


@dataclass
class RecordingGuardedClientForHttpx:
    calls: list[tuple[str, str, dict[str, str], bytes | None]] = field(
        default_factory=list
    )

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        timeout_seconds: float = 10.0,
    ) -> GuardedHttpResponse:
        del timeout_seconds
        self.calls.append((method, url, dict(headers or {}), body))
        return response(body=b'{"guarded":true}')
