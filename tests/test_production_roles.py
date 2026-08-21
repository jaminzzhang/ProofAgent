from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

import proof_agent.bootstrap.production_roles as production_roles

from proof_agent.bootstrap.production_roles import (
    ProductionKnowledgeReleaseAuthority,
    create_production_api_application,
    compose_production_run_executor,
)
from proof_agent.contracts import ProductionSecretHandle
from proof_agent.contracts.ports.guarded_http import GuardedHttpResponse
from proof_agent.contracts.ports.secret_provider import ResolvedSecretMaterial


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


def test_production_api_uses_kss_as_its_only_knowledge_authority(monkeypatch) -> None:
    class Persistence:
        engine = object()
        models = object()
        tools = object()
        knowledge = object()
        hybrid_ingestion = object()
        knowledge_source_operations = object()
        metadata_reviews = object()
        metadata_workbooks = object()
        configuration_uow = object()
        security = object()
        run_queue = object()
        conversations = object()
        artifacts = object()
        releases = object()
        audit = object()

        def close(self) -> None:
            return None

    class Closable:
        def close(self) -> None:
            return None

    artifact_store = SimpleNamespace(check_ready=lambda: True, close=lambda: None)
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
    monkeypatch.setattr(
        production_roles, "compose_production_egress_client", lambda value: object()
    )
    monkeypatch.setattr(
        production_roles,
        "compose_production_vault_secret_provider",
        lambda *args, **kwargs: Closable(),
    )
    monkeypatch.setattr(
        production_roles, "compose_production_security", lambda *args, **kwargs: security
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
    monkeypatch.setattr(
        production_roles,
        "VerifiedArtifactMaterializer",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        production_roles,
        "_release_attestation_verifier",
        lambda values: object(),
    )
    monkeypatch.setattr(production_roles, "create_app", create_app_stub)

    application = create_production_api_application(
        {
            "PROOF_AGENT_MODE": "production",
            "PROOF_AGENT_POSTGRES_DSN": "postgresql+psycopg://proof@postgres/proof",
            "PROOF_AGENT_KSS_ENDPOINT": ("https://proof-agent.example:8444"),
            "PROOF_AGENT_KSS_OPERATOR_SECRET_HANDLE": ("knowledge/source-service/operator"),
            "PROOF_AGENT_RELEASE_BUNDLE_CACHE_DIR": "/tmp/release-bundles",
        }
    )

    assert isinstance(application, FastAPI)
    assert "hybrid_runtime" not in captured
    assert "production_hybrid_intake_service" not in captured
    assert "production_knowledge_repository" not in captured
    assert "knowledge_source_configuration_application" not in captured
    assert isinstance(
        captured["knowledge_service_management_client"],
        production_roles.KnowledgeSourceServiceManagementClient,
    )
    assert isinstance(
        captured["agent_configuration_workspace"],
        production_roles.AgentConfigurationWorkspace,
    )
    assert isinstance(
        captured["agent_configuration_workspace"]._contract_validator,
        production_roles.LocalAgentConfigurationContractValidator,
    )
    assert isinstance(
        captured["agent_configuration_workspace"]._workflow_stage_inspector,
        production_roles.LocalAgentConfigurationWorkflowStageAdapter,
    )
    assert isinstance(
        captured["agent_configuration_workspace"]._skill_pack_inspector,
        production_roles.LocalAgentConfigurationSkillPackAdapter,
    )
    assert (
        captured["agent_configuration_workspace"]._knowledge_release_catalog
        is captured["knowledge_service_management_client"]
    )


def test_embedded_reference_profile_source_selection_is_removed() -> None:
    assert not hasattr(production_roles, "_reference_profile_source_ids")


def test_publisher_binding_freezes_deployment_kss_authority() -> None:
    provider = SimpleNamespace(protocol_id="vault-kv-v2")

    binding = production_roles._production_kss_binding(
        {
            "PROOF_AGENT_KSS_BINDING_ID": "insurance-knowledge",
            "PROOF_AGENT_KSS_RELEASE_ID": "release-insurance-2026-08-18",
            "PROOF_AGENT_KSS_CLIENT_SECRET_HANDLE": (
                "knowledge/source-service/agent-client"
            ),
            "PROOF_AGENT_KSS_CLIENT_SECRET_VERSION_ID": "credential-v7",
            "PROOF_AGENT_KSS_ADMISSION_SCORER_ID": (
                "insurance-evidence-admission"
            ),
            "PROOF_AGENT_KSS_ADMISSION_SCORER_REVISION": (
                "insurance-evidence-admission.v3"
            ),
        },
        provider,
    )

    assert binding.knowledge_base_release_id == "release-insurance-2026-08-18"
    assert binding.client_credential_ref.protocol_id == "vault-kv-v2"
    assert binding.client_credential_ref.version_id == "credential-v7"
    assert binding.admission_scorer_revision == "insurance-evidence-admission.v3"
