from __future__ import annotations

from dataclasses import dataclass
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

import proof_agent.bootstrap.production_roles as production_roles

from proof_agent.bootstrap.production_roles import (
    ProductionKnowledgeReleaseAuthority,
    ProductionOpenSearchSecretProvider,
    create_production_api_application,
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


def test_production_api_injects_the_guarded_hybrid_runtime(monkeypatch) -> None:
    class Persistence:
        engine = object()
        models = object()
        tools = object()
        knowledge = object()
        hybrid_ingestion = object()
        metadata_reviews = object()
        configuration_uow = object()
        security = object()
        run_queue = object()
        conversations = object()
        artifacts = object()

        def close(self) -> None:
            return None

    class Closable:
        def close(self) -> None:
            return None

    artifact_store = SimpleNamespace(check_ready=lambda: True, close=lambda: None)
    hybrid_runtime = SimpleNamespace(
        artifact_store=artifact_store,
        model_graph=SimpleNamespace(build_config=object()),
        publication_api=lambda **kwargs: object(),
        close=lambda: None,
    )
    security = SimpleNamespace(
        operator_session_service=object(),
        stable_origin="https://proof-agent.example",
        recovery_mapping=object(),
        oidc_client=SimpleNamespace(check_ready=lambda: True),
    )
    captured: dict[str, object] = {}

    def create_app_stub(**kwargs):
        captured.update(kwargs)
        return FastAPI()

    monkeypatch.setattr(production_roles, "PostgresPersistenceBundle", Persistence)
    monkeypatch.setattr(
        production_roles, "compose_application_persistence", lambda **kwargs: Persistence()
    )
    monkeypatch.setattr(production_roles, "compose_production_egress_client", lambda value: object())
    monkeypatch.setattr(
        production_roles,
        "compose_production_vault_secret_provider",
        lambda *args, **kwargs: Closable(),
    )
    monkeypatch.setattr(
        production_roles, "compose_production_security", lambda *args, **kwargs: security
    )
    monkeypatch.setattr(
        production_roles,
        "compose_production_hybrid_runtime_from_env",
        lambda *args, **kwargs: hybrid_runtime,
    )
    monkeypatch.setattr(
        production_roles, "ProductionHybridKnowledgeIntakeService", lambda **kwargs: object()
    )
    monkeypatch.setattr(
        production_roles,
        "PostgresHybridPublicationConfigurationStore",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(production_roles, "_artifact_store", lambda values: artifact_store)
    monkeypatch.setattr(production_roles, "_published_agent_authority", lambda *args: object())
    monkeypatch.setattr(production_roles, "RunArtifactResultReader", lambda **kwargs: object())
    monkeypatch.setattr(
        production_roles,
        "compose_model_credential_cipher",
        lambda values: object(),
    )
    monkeypatch.setattr(
        production_roles,
        "PostgresModelCredentialRepository",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        production_roles,
        "PostgresRuntimeSharedAssetReader",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(
        production_roles,
        "_production_readiness_identity",
        lambda values: object(),
    )
    monkeypatch.setattr(production_roles, "create_app", create_app_stub)

    application = create_production_api_application(
        {
            "PROOF_AGENT_MODE": "production",
            "PROOF_AGENT_POSTGRES_DSN": "postgresql+psycopg://proof@postgres/proof",
            "HYBRID_POSTGRES_DSN": "postgresql://proof@postgres/proof",
            "PROOF_AGENT_OPENSEARCH_SECRET_HANDLE": "knowledge/opensearch",
        }
    )

    assert isinstance(application, FastAPI)
    assert captured["hybrid_runtime"] is hybrid_runtime
