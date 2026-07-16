from __future__ import annotations

from dataclasses import dataclass
import json
from types import SimpleNamespace

import pytest

from proof_agent.bootstrap.production_roles import (
    ProductionKnowledgeReleaseAuthority,
    ProductionOpenSearchSecretProvider,
    compose_production_run_executor,
)
from proof_agent.contracts import ProductionSecretHandle, SecretHandleValidation
from proof_agent.contracts.ports.guarded_http import GuardedHttpResponse
from proof_agent.contracts.ports.secret_provider import ResolvedSecretMaterial


@dataclass
class Secrets:
    protocol_id: str = "test-provider"

    def resolve(self, handle: ProductionSecretHandle) -> ResolvedSecretMaterial:
        assert handle.handle_id == "knowledge/opensearch"
        assert handle.purpose.value == "knowledge_credential"
        return ResolvedSecretMaterial(
            value=b'{"authorization":"Bearer bounded-token"}',
            provider_version_id="7",
        )

    def validate(
        self,
        handle: ProductionSecretHandle,
        *,
        checked_at: str,
    ) -> SecretHandleValidation:
        return SecretHandleValidation(
            handle=handle,
            resolvable=True,
            provider_version_id="7",
            checked_at=checked_at,
        )


def test_opensearch_secret_adapter_exposes_only_bounded_authorization_header() -> None:
    material = ProductionOpenSearchSecretProvider(Secrets()).resolve(
        "knowledge/opensearch"
    )

    assert material.headers == {"Authorization": "Bearer bounded-token"}
    assert material.client_certificate_path is None


def test_executor_composition_fails_without_postgres_and_never_falls_back_local() -> None:
    with pytest.raises(ValueError, match="POSTGRES_DSN"):
        compose_production_run_executor(
            {
                "PROOF_AGENT_MODE": "production",
            }
        )


class EvaluationSecrets:
    protocol_id = "test-provider"

    def resolve(self, handle: ProductionSecretHandle) -> ResolvedSecretMaterial:
        assert handle.handle_id == "knowledge/evaluator"
        assert handle.purpose.value == "knowledge_credential"
        return ResolvedSecretMaterial(
            value=b"bounded-evaluator-token",
            provider_version_id="8",
        )

    def validate(self, handle, *, checked_at):
        raise AssertionError((handle, checked_at))


class Guarded:
    def __init__(self) -> None:
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return GuardedHttpResponse(
            status_code=200,
            headers={"content-type": "application/json"},
            body=b'{"authorized":true}',
        )


def test_release_authority_uses_guarded_https_and_secret_handle_only() -> None:
    guarded = Guarded()
    authority = ProductionKnowledgeReleaseAuthority(
        endpoint="https://evaluator.internal.example",
        secret_handle="knowledge/evaluator",
        guarded_http_client=guarded,  # type: ignore[arg-type]
        secret_provider=EvaluationSecrets(),  # type: ignore[arg-type]
    )

    authorized = authority.verify_release_record(
        SimpleNamespace(model_dump=lambda **kwargs: {"record_id": "release-1"})
    )

    assert authorized is True
    method, url, request = guarded.calls[0]
    assert method == "POST"
    assert url.endswith("/v1/knowledge-evaluation/release/verify")
    assert request["headers"]["Authorization"] == "Bearer bounded-evaluator-token"
    assert json.loads(request["body"]) == {"record": {"record_id": "release-1"}}
