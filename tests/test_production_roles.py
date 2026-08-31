from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

import proof_agent.bootstrap.production_roles as production_roles

from proof_agent.bootstrap.production_roles import (
    ProductionKnowledgeReleaseAuthority,
    create_production_api_application,
    compose_production_run_executor,
)
from proof_agent.capabilities.knowledge.source_service_release_reference_registrar import (
    KnowledgeSourceServiceReleaseReferenceRegistrar,
)
from proof_agent.capabilities.knowledge.source_service_query_grant_provisioner import (
    KnowledgeSourceServiceQueryGrantProvisioner,
)
from proof_agent.contracts import ProductionSecretHandle, SecretPurpose
from proof_agent.contracts.ports.guarded_http import GuardedHttpResponse
from proof_agent.contracts.ports.secret_provider import ResolvedSecretMaterial
from proof_agent.control.formal_production_agent_online_smoke import (
    FormalProductionAgentOnlineSmokeService,
)
from proof_agent.control.formal_production_agent_publication_command import (
    FormalProductionAgentPublicationCommandService,
)
from proof_agent.delivery.production_agent_validation import (
    FormalProductionAgentCandidateExternalSmokeRunner,
    FormalProductionAgentOnlineSmokeRunner,
)


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


class RecordingSecrets:
    protocol_id = "vault-kv-v2"

    def __init__(self) -> None:
        self.resolved: list[ProductionSecretHandle] = []

    def resolve(self, handle: ProductionSecretHandle) -> ResolvedSecretMaterial:
        self.resolved.append(handle)
        return ResolvedSecretMaterial(
            value=b"dedicated-reference-token",
            provider_version_id=handle.version_id or "unversioned",
        )

    def validate(self, handle, *, checked_at):
        raise AssertionError((handle, checked_at))


class MismatchedVersionSecrets(RecordingSecrets):
    def resolve(self, handle: ProductionSecretHandle) -> ResolvedSecretMaterial:
        self.resolved.append(handle)
        return ResolvedSecretMaterial(
            value=b"stale-reference-token",
            provider_version_id="different-version",
        )


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


def test_phase_f_authority_uses_the_same_guarded_independent_verifier() -> None:
    guarded = Guarded()
    authority = ProductionKnowledgeReleaseAuthority(
        endpoint="https://evaluator.internal.example",
        secret_handle="knowledge/evaluator",
        guarded_http_client=guarded,  # type: ignore[arg-type]
        secret_provider=EvaluationSecrets(),  # type: ignore[arg-type]
    )

    authorized = authority.verify_phase_f_record(
        SimpleNamespace(model_dump=lambda **kwargs: {"record_id": "phase-f-1"})
    )

    assert authorized is True
    method, url, request = guarded.calls[0]
    assert method == "POST"
    assert url.endswith("/v1/knowledge-evaluation/release/verify")
    assert json.loads(request["body"]) == {"record": {"record_id": "phase-f-1"}}


def test_production_api_composes_exact_formal_command_with_dedicated_reference_client(
    tmp_path,
) -> None:
    secrets = RecordingSecrets()
    runtime_configuration = object()
    knowledge_runtime = object()
    guarded = object()
    artifact_store = object()

    command = production_roles._compose_formal_production_agent_publication_command(
        values={
            "PROOF_AGENT_KSS_ENDPOINT": "https://knowledge.internal.example",
            "PROOF_AGENT_KSS_BINDING_ID": "insurance-knowledge",
            "PROOF_AGENT_KSS_CLIENT_SECRET_HANDLE": "knowledge/runtime-client",
            "PROOF_AGENT_KSS_CLIENT_SECRET_VERSION_ID": "runtime-client-v7",
            "PROOF_AGENT_KSS_ADMISSION_SCORER_ID": "insurance-admission",
            "PROOF_AGENT_KSS_ADMISSION_SCORER_REVISION": "insurance-admission.v3",
            "PROOF_AGENT_KSS_REFERENCE_CLIENT_SECRET_HANDLE": ("knowledge/reference-client"),
            "PROOF_AGENT_KSS_REFERENCE_CLIENT_SECRET_VERSION_ID": ("reference-client-v4"),
            "PROOF_AGENT_KSS_OPERATOR_SECRET_HANDLE": "knowledge/operator-client",
            "PA_KNOWLEDGE_EVALUATION_ENDPOINT": ("https://evaluator.internal.example"),
            "PROOF_AGENT_KNOWLEDGE_EVALUATION_SECRET_HANDLE": ("knowledge/evaluator"),
            "PROOF_AGENT_RELEASE_INSTITUTION_AUTHORIZATION_JSON": (
                '{"roles":["release-validator"]}'
            ),
            "PROOF_AGENT_RELEASE_WORK_DIR": str(tmp_path / "formal-publication"),
            "PROOF_AGENT_FORMAL_PUBLICATION_COMMAND_LEASE_SECONDS": "600",
        },
        unit_of_work_factory=lambda: None,  # type: ignore[arg-type,return-value]
        knowledge_service_management=object(),
        runtime_configuration=runtime_configuration,
        knowledge_candidate_runtime=knowledge_runtime,
        guarded_http_client=guarded,  # type: ignore[arg-type]
        secret_provider=secrets,  # type: ignore[arg-type]
        model_credential_resolver=object(),
        artifact_store=artifact_store,
    )

    assert isinstance(command, FormalProductionAgentPublicationCommandService)
    assert command._lease_duration == timedelta(seconds=600)
    assert command._binding_profile.binding_id == "insurance-knowledge"
    assert command._binding_profile.client_credential_ref.handle_id == ("knowledge/runtime-client")
    assert command._binding_profile.client_credential_ref.version_id == ("runtime-client-v7")
    publisher = command._publisher
    assert publisher._candidate_assembler._knowledge_release_catalog is not None
    assert isinstance(
        publisher._online_smoke_service,
        FormalProductionAgentOnlineSmokeService,
    )
    runner = publisher._online_smoke_service._online_smoke_validator
    assert isinstance(runner, FormalProductionAgentOnlineSmokeRunner)
    assert runner._runtime._configuration_store is runtime_configuration
    assert runner._runtime._knowledge_candidate_runtime is knowledge_runtime
    assert runner._runtime._artifact_store is artifact_store
    registrar = publisher._reference_stager._registrar
    assert isinstance(registrar, KnowledgeSourceServiceReleaseReferenceRegistrar)
    assert registrar._authorization_header() == "Bearer dedicated-reference-token"
    provisioner = publisher._query_grant_stager._provisioner
    assert isinstance(provisioner, KnowledgeSourceServiceQueryGrantProvisioner)
    assert provisioner._authorization_header() == "Bearer dedicated-reference-token"
    assert secrets.resolved == [
        ProductionSecretHandle(
            protocol_id="vault-kv-v2",
            handle_id="knowledge/reference-client",
            purpose=SecretPurpose.KNOWLEDGE_CREDENTIAL,
            version_id="reference-client-v4",
        ),
        ProductionSecretHandle(
            protocol_id="vault-kv-v2",
            handle_id="knowledge/operator-client",
            purpose=SecretPurpose.KNOWLEDGE_CREDENTIAL,
        ),
    ]


def test_production_composes_candidate_external_smoke_from_the_same_runtime(
    tmp_path,
) -> None:
    runtime_configuration = object()
    knowledge_runtime = object()
    artifact_store = object()

    runner = production_roles._compose_formal_candidate_external_smoke_runner(
        values={
            "PROOF_AGENT_RELEASE_INSTITUTION_AUTHORIZATION_JSON": (
                '{"roles":["release-validator"]}'
            ),
            "PROOF_AGENT_RELEASE_WORK_DIR": str(tmp_path / "formal-publication"),
        },
        runtime_configuration=runtime_configuration,
        knowledge_candidate_runtime=knowledge_runtime,
        guarded_http_client=object(),  # type: ignore[arg-type]
        secret_provider=object(),  # type: ignore[arg-type]
        model_credential_resolver=object(),
        artifact_store=artifact_store,
    )

    assert isinstance(runner, FormalProductionAgentCandidateExternalSmokeRunner)
    assert runner._runtime._configuration_store is runtime_configuration
    assert runner._runtime._knowledge_candidate_runtime is knowledge_runtime
    assert runner._runtime._artifact_store is artifact_store


@pytest.mark.parametrize(
    "shared_handle",
    ("knowledge/runtime-client", "knowledge/operator-client"),
)
def test_production_formal_command_rejects_a_shared_reference_client_handle(
    tmp_path,
    shared_handle: str,
) -> None:
    with pytest.raises(
        ValueError,
        match="Reference client must use a dedicated Secret Handle",
    ):
        production_roles._compose_formal_production_agent_publication_command(
            values={
                "PROOF_AGENT_KSS_ENDPOINT": "https://knowledge.internal.example",
                "PROOF_AGENT_KSS_BINDING_ID": "insurance-knowledge",
                "PROOF_AGENT_KSS_CLIENT_SECRET_HANDLE": "knowledge/runtime-client",
                "PROOF_AGENT_KSS_CLIENT_SECRET_VERSION_ID": "runtime-client-v7",
                "PROOF_AGENT_KSS_OPERATOR_SECRET_HANDLE": "knowledge/operator-client",
                "PROOF_AGENT_KSS_ADMISSION_SCORER_ID": "insurance-admission",
                "PROOF_AGENT_KSS_ADMISSION_SCORER_REVISION": "insurance-admission.v3",
                "PROOF_AGENT_KSS_REFERENCE_CLIENT_SECRET_HANDLE": shared_handle,
                "PROOF_AGENT_KSS_REFERENCE_CLIENT_SECRET_VERSION_ID": ("reference-client-v4"),
                "PA_KNOWLEDGE_EVALUATION_ENDPOINT": ("https://evaluator.internal.example"),
                "PROOF_AGENT_KNOWLEDGE_EVALUATION_SECRET_HANDLE": ("knowledge/evaluator"),
                "PROOF_AGENT_RELEASE_INSTITUTION_AUTHORIZATION_JSON": (
                    '{"roles":["release-validator"]}'
                ),
                "PROOF_AGENT_RELEASE_WORK_DIR": str(tmp_path / "formal-publication"),
            },
            unit_of_work_factory=lambda: None,  # type: ignore[arg-type,return-value]
            knowledge_service_management=object(),
            runtime_configuration=object(),
            knowledge_candidate_runtime=object(),
            guarded_http_client=object(),  # type: ignore[arg-type]
            secret_provider=RecordingSecrets(),  # type: ignore[arg-type]
            model_credential_resolver=object(),
            artifact_store=object(),
        )


def test_reference_client_authorization_fails_closed_on_secret_version_drift() -> None:
    provider = MismatchedVersionSecrets()
    handle = ProductionSecretHandle(
        protocol_id=provider.protocol_id,
        handle_id="knowledge/reference-client",
        purpose=SecretPurpose.KNOWLEDGE_CREDENTIAL,
        version_id="reference-client-v4",
    )

    with pytest.raises(ValueError, match="version is unavailable"):
        production_roles._knowledge_service_client_authorization(provider, handle)


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
    formal_publication_command = object()
    formal_candidate_external_smoke_runner = object()

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
    monkeypatch.setattr(
        production_roles,
        "compose_production_knowledge_candidate_runtime",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        production_roles,
        "_compose_formal_production_agent_publication_command",
        lambda **kwargs: formal_publication_command,
    )
    monkeypatch.setattr(
        production_roles,
        "_compose_formal_candidate_external_smoke_runner",
        lambda **kwargs: formal_candidate_external_smoke_runner,
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
    assert isinstance(
        captured["agent_configuration_workspace"]._publication_configuration_projector,
        production_roles.ProductionAgentPublicationConfigurationProjector,
    )
    assert captured["formal_production_agent_publication_command"] is formal_publication_command
    assert (
        application.state.formal_production_agent_candidate_external_smoke_runner
        is formal_candidate_external_smoke_runner
    )


def test_embedded_reference_profile_source_selection_is_removed() -> None:
    assert not hasattr(production_roles, "_reference_profile_source_ids")


def test_formal_publisher_profile_freezes_deployment_kss_authority() -> None:
    provider = SimpleNamespace(protocol_id="vault-kv-v2")

    binding = production_roles._production_kss_binding_profile(
        {
            "PROOF_AGENT_KSS_BINDING_ID": "insurance-knowledge",
            "PROOF_AGENT_KSS_RELEASE_ID": "must-not-select-release-from-deployment",
            "PROOF_AGENT_KSS_CLIENT_SECRET_HANDLE": ("knowledge/source-service/agent-client"),
            "PROOF_AGENT_KSS_CLIENT_SECRET_VERSION_ID": "credential-v7",
            "PROOF_AGENT_KSS_ADMISSION_SCORER_ID": ("insurance-evidence-admission"),
            "PROOF_AGENT_KSS_ADMISSION_SCORER_REVISION": ("insurance-evidence-admission.v3"),
        },
        provider,
    )

    assert binding.client_credential_ref.protocol_id == "vault-kv-v2"
    assert binding.client_credential_ref.version_id == "credential-v7"
    assert binding.admission_scorer_revision == "insurance-evidence-admission.v3"
    assert not hasattr(binding, "knowledge_base_release_id")


def test_legacy_manifest_publisher_composition_is_removed() -> None:
    assert not hasattr(production_roles, "compose_production_agent_publisher")
