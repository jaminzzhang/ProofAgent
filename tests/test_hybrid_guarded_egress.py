from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json

import pytest

from proof_agent.bootstrap.composition import compose_hybrid_knowledge_from_env
from proof_agent.capabilities.egress.guarded_http import GuardedHttpsClient
from proof_agent.capabilities.knowledge.hybrid.guarded_transports import (
    GuardedParserHttpTransport,
)
from proof_agent.capabilities.knowledge.hybrid.model_clients import (
    KnowledgeModelCancellation,
)
from proof_agent.capabilities.knowledge.hybrid.parser_clients import (
    ParserServiceRequest,
    canonical_vendor_json_bytes,
)
from proof_agent.contracts import (
    EgressOriginRule,
    EgressPolicyVersion,
    ExactHttpsOrigin,
)
from proof_agent.contracts.knowledge_index import ExactArtifactRef
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


class StaticGuardedClient:
    def __init__(self, response: GuardedHttpResponse) -> None:
        self.response = response
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
                "headers": headers,
                "body": body,
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.response


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


def test_guarded_parser_accepts_json_arrays_for_strict_tuple_fields() -> None:
    original_ref = ExactArtifactRef(
        artifact_uri="s3://knowledge/original.pdf",
        version_id="version-1",
        sha256="b" * 64,
        size_bytes=128,
        media_type="application/pdf",
    )
    request = ParserServiceRequest(
        document_id="document-1",
        revision_id="revision-1",
        original_ref=original_ref,
        page_numbers=(1, 2),
        parser_revision="docling@sha256:parser-v1",
        model_digests=("docling@sha256:model-v1",),
        configuration_sha256="a" * 64,
    )
    vendor_json = {
        "document_id": request.document_id,
        "revision_id": request.revision_id,
        "source_sha256": original_ref.sha256,
        "pages": [
            {"page_number": 1},
            {"page_number": 2},
        ],
    }
    vendor_bytes = canonical_vendor_json_bytes(vendor_json)
    response_payload = {
        "parser_adapter": "docling",
        "original_ref": original_ref.model_dump(mode="json"),
        "page_numbers": [1, 2],
        "parser_revision": request.parser_revision,
        "model_digests": ["docling@sha256:model-v1"],
        "configuration_sha256": request.configuration_sha256,
        "vendor_json_sha256": hashlib.sha256(vendor_bytes).hexdigest(),
        "vendor_json": vendor_json,
    }
    client = StaticGuardedClient(
        GuardedHttpResponse(
            status_code=200,
            headers={"Content-Type": "application/json"},
            body=json.dumps(response_payload).encode("utf-8"),
        )
    )
    transport = GuardedParserHttpTransport(
        client,
        endpoint="https://docling.internal",
    )

    attestation = transport.parse_scheduled(
        request,
        timeout_seconds=30.0,
        follow_redirects=False,
        allow_runtime_downloads=False,
        cancellation=KnowledgeModelCancellation(),
    )

    assert attestation.page_numbers == (1, 2)
    assert attestation.model_digests == ("docling@sha256:model-v1",)
    assert attestation.vendor_json_bytes == vendor_bytes
