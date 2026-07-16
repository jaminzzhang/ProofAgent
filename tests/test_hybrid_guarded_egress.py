from __future__ import annotations

from collections.abc import Mapping

import pytest

from proof_agent.bootstrap.composition import compose_hybrid_knowledge_from_env
from proof_agent.capabilities.egress.guarded_http import GuardedHttpsClient
from proof_agent.contracts import (
    EgressOriginRule,
    EgressPolicyVersion,
    ExactHttpsOrigin,
)
from proof_agent.contracts.ports.guarded_http import GuardedHttpResponse
from proof_agent.control.security.egress import CompiledEgressPolicy


class NoNetworkResolver:
    def resolve(self, hostname: str, port: int, *, timeout_seconds: float) -> tuple[str, ...]:
        raise AssertionError((hostname, port, timeout_seconds))


class NoNetworkTransport:
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
        raise AssertionError(
            (
                method,
                url,
                connect_address,
                tls_hostname,
                headers,
                body,
                timeout_seconds,
                max_response_bytes,
            )
        )


def environment() -> dict[str, str]:
    return {
        "PROOF_AGENT_MODE": "production",
        "PA_HYBRID_KNOWLEDGE_MODELS_ENABLED": "true",
        "PA_KNOWLEDGE_MODEL_SCHEDULER_ENDPOINT": "https://scheduler.internal",
        "PA_KNOWLEDGE_MODEL_SCHEDULER_NAMESPACE": "proof-agent",
        "PA_KNOWLEDGE_DOCLING_ENDPOINT": "https://docling.internal",
        "PA_KNOWLEDGE_PADDLE_ENDPOINT": "https://paddle.internal",
        "PA_KNOWLEDGE_EMBEDDING_ENDPOINT": "https://embedding.internal",
        "PA_KNOWLEDGE_RERANKER_ENDPOINT": "https://reranker.internal",
        "PA_KNOWLEDGE_MODEL_ALLOWED_HOSTS": (
            "scheduler.internal,docling.internal,paddle.internal,"
            "embedding.internal,reranker.internal"
        ),
        "PA_KNOWLEDGE_MODEL_ALLOWED_CIDRS": "10.0.0.0/8",
        "PA_KNOWLEDGE_PARSER_REVISION": "parser-v1",
        "PA_KNOWLEDGE_MODEL_DIGESTS": "model@sha256:abc",
        "PA_KNOWLEDGE_PARSER_CONFIGURATION_SHA256": "a" * 64,
    }


def guarded_client() -> GuardedHttpsClient:
    hosts = (
        "scheduler.internal",
        "docling.internal",
        "paddle.internal",
        "embedding.internal",
        "reranker.internal",
    )
    policy = EgressPolicyVersion(
        version_id="019ba001-1111-7000-8000-000000000701",
        revision=1,
        rules=tuple(
            EgressOriginRule(
                origin=ExactHttpsOrigin.parse(f"https://{host}"),
                allowed_ip_networks=("10.0.0.0/8",),
            )
            for host in hosts
        ),
        created_at="2026-07-15T00:00:00Z",
        created_by="security-admin",
    )
    return GuardedHttpsClient(
        policy=CompiledEgressPolicy(policy),
        resolver=NoNetworkResolver(),
        transport=NoNetworkTransport(),
        max_response_bytes=64 * 1024 * 1024,
    )


def test_production_hybrid_fails_closed_without_active_egress_client() -> None:
    with pytest.raises(ValueError, match="active Egress Policy"):
        compose_hybrid_knowledge_from_env(environment())


def test_production_hybrid_composes_all_private_services_through_guarded_client() -> None:
    composition = compose_hybrid_knowledge_from_env(
        environment(),
        guarded_http_client=guarded_client(),
    )
    assert composition is not None
    try:
        assert type(composition._transports.scheduler).__name__ == "GuardedSchedulerTransport"
        assert type(composition._transports.docling).__name__ == (
            "GuardedParserHttpTransport"
        )
        assert type(composition._transports.embedding).__name__ == (
            "GuardedEmbeddingHttpTransport"
        )
        assert type(composition._transports.reranker).__name__ == (
            "GuardedRerankerHttpTransport"
        )
    finally:
        composition.close()
