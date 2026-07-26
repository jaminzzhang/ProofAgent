from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml  # type: ignore[import-untyped]

from proof_agent.configuration.importer import build_agent_package_contract_bundle
from proof_agent.configuration.knowledge_release import seal_knowledge_release_record
from proof_agent.contracts import (
    ActiveAgentVersion,
    ExactArtifactRef,
    AuditActorFacts,
    KnowledgeReleaseEvidenceSet,
    InstitutionAuthorizationContext,
    PostgresEncryptedModelCredentialReference,
    ProductionSecretHandle,
    PersistencePointerConflictError,
    PublishedAgentVersion,
    ReceiptOutcome,
    ResolvedHybridKnowledgeBinding,
    ResolvedKnowledgeBindingSet,
    SecretHandleValidation,
    SharedAssetKind,
    SharedAssetVersionRef,
    SharedModelConnection,
    SharedModelConnectionLifecycleState,
)
from proof_agent.contracts.ports.model_credentials import ModelCredentialValidation
from proof_agent.contracts.ports.secret_provider import ResolvedSecretMaterial
from proof_agent.control.production_agent import (
    ProductionAgentValidationError,
    validate_production_agent_candidate,
)
from proof_agent.control.production_agent_publication import (
    ProductionAgentCandidateValidation,
    ProductionAgentPublicationService,
)
from proof_agent.delivery.production_agent_validation import (
    ProductionOnlineAgentCandidateValidator,
)
from proof_agent.delivery.published_agents import PublishedAgent


AGENT_ID = "agent_management_insurance_specialist"
VERSION_ID = "019ba001-1111-7000-8000-000000000001"


class Secrets:
    protocol_id = "vault-v1"

    def __init__(self, *, resolvable: bool = True) -> None:
        self.resolvable = resolvable
        self.validated: list[ProductionSecretHandle] = []

    def resolve(self, handle: ProductionSecretHandle) -> ResolvedSecretMaterial:
        raise AssertionError("readiness must validate, not resolve, model credentials")

    def validate(
        self,
        handle: ProductionSecretHandle,
        *,
        checked_at: str,
    ) -> SecretHandleValidation:
        self.validated.append(handle)
        return SecretHandleValidation(
            handle=handle,
            resolvable=self.resolvable,
            provider_version_id="42" if self.resolvable else None,
            checked_at=checked_at,
            reason_code=None if self.resolvable else "not_found",
        )


class VaultSecrets(Secrets):
    protocol_id = "hashicorp-vault-2.0-kv-v2"


class ModelConnections:
    def __init__(self, *, provider: str = "openai_compatible") -> None:
        self.connection = SharedModelConnection(
            connection_id="model_production_primary",
            display_name="Production Primary",
            provider=provider,
            model_identifier="insurance-model-v1",
            base_url="https://models.internal.example/v1",
            credential_ref=PostgresEncryptedModelCredentialReference(),
            lifecycle_state=SharedModelConnectionLifecycleState.ACTIVE,
            created_at="2026-07-15T00:00:00Z",
            updated_at="2026-07-15T00:00:00Z",
        )

    def get_model_connection(self, connection_id: str):
        return self.connection if connection_id == self.connection.connection_id else None

class ModelCredentials:
    def __init__(self, *, resolvable: bool = True) -> None:
        self.resolvable = resolvable
        self.validated: list[str] = []

    def validate(self, connection_id: str) -> ModelCredentialValidation:
        self.validated.append(connection_id)
        return ModelCredentialValidation(
            connection_id=connection_id,
            resolvable=self.resolvable,
            reason_code=None if self.resolvable else "credential_not_found",
        )


def _validation_dependencies(
    *,
    resolvable: bool = True,
    provider: str = "openai_compatible",
) -> dict[str, object]:
    return {
        "configuration_store": ModelConnections(provider=provider),
        "model_credential_resolver": ModelCredentials(resolvable=resolvable),
    }


def _artifact(kind: str) -> ExactArtifactRef:
    return ExactArtifactRef(
        artifact_uri=f"s3://proof-agent/phase-f/{kind}.json",
        version_id=f"opaque-{kind}-version",
        sha256={
            "manifest": "0",
            "shadow": "1",
            "capacity": "2",
            "acceptance": "3",
            "recovery": "4",
        }[kind]
        * 64,
        size_bytes=1024,
        media_type="application/json",
    )


def _binding() -> ResolvedHybridKnowledgeBinding:
    return ResolvedHybridKnowledgeBinding(
        binding_id="insurance_hybrid",
        source_id="insurance-rules",
        source_publication_id="publication-1",
        source_snapshot_id="snapshot-1",
        index_generation_id="generation-1",
        source_publication_seq=1,
        retrieval_profile_revision_id="profile-1",
        manifest_ref=_artifact("manifest"),
        publication_attestation_id="attestation-1",
    )


def _write_manifest(
    tmp_path: Path,
    *,
    answer_provider: str = "openai_compatible",
    memory_enabled: bool = False,
) -> Path:
    fixture = Path(
        "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"
    )
    raw = yaml.safe_load(fixture.read_text(encoding="utf-8"))
    raw["name"] = AGENT_ID
    raw["package_knowledge_sources"] = []
    raw["knowledge_bindings"] = [
        {
            "binding_id": "insurance_hybrid",
            "source_ref": {"scope": "shared", "source_id": "insurance-rules"},
            "retrieval_profile_revision_id": "profile-1",
            "failure_mode": "required",
        }
    ]
    raw["model"] = (
        {
            "model_source": "shared",
            "connection_id": "model_production_primary",
            "params": {"max_output_tokens": 2000},
        }
        if answer_provider != "deterministic"
        else {"provider": "deterministic", "name": "demo", "params": {}}
    )
    raw["react"]["planner"] = {
        "model_source": "shared",
        "connection_id": "model_production_primary",
        "params": {"max_output_tokens": 1200},
    }
    raw["review"] = {
        "mode": "auto",
        "low_risk_fast_path": False,
        "subagent": {
            "model_source": "shared",
            "connection_id": "model_production_primary",
            "fail_closed": True,
            "params": {"max_output_tokens": 1200},
        },
    }
    raw["capabilities"]["memory"] = (
        {
            "enabled": True,
            "provider": "local",
            "scopes": {
                "case": {
                    "enabled": True,
                    "retention_days": 30,
                    "max_records": 5,
                    "allow_restricted": False,
                },
                "user": {"enabled": False},
                "shared": {"enabled": False},
            },
        }
        if memory_enabled
        else {"enabled": False}
    )
    package = tmp_path / "agent"
    package.mkdir()
    manifest_path = package / "agent.yaml"
    manifest_path.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    policy_source = fixture.with_name("policy.yaml")
    (package / "policy.yaml").write_text(
        policy_source.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return manifest_path


def _candidate(
    tmp_path: Path,
    *,
    answer_provider: str = "openai_compatible",
    with_release: bool = True,
) -> tuple[PublishedAgent, PublishedAgentVersion]:
    manifest_path = _write_manifest(tmp_path, answer_provider=answer_provider)
    bundle = build_agent_package_contract_bundle(manifest_path)
    bindings = ResolvedKnowledgeBindingSet(bindings=(_binding(),))
    release = (
        seal_knowledge_release_record(
            record_id="release-1",
            contract_bundle=bundle,
            resolved_knowledge_bindings=bindings,
            shadow_artifact=_artifact("shadow"),
            capacity_artifact=_artifact("capacity"),
            acceptance_artifact=_artifact("acceptance"),
            recovery_artifact=_artifact("recovery"),
            created_at="2026-07-15T00:00:00Z",
            created_by="release-service",
        )
        if with_release
        else None
    )
    version = PublishedAgentVersion(
        agent_id=AGENT_ID,
        version_id=VERSION_ID,
        source_draft_id="019ba001-1111-7000-8000-000000000002",
        validation_run_id="019ba001-1111-7000-8000-000000000003",
        display_name="Insurance Specialist",
        purpose="Answer governed insurance questions",
        contract_bundle=bundle,
        published_at="2026-07-15T00:00:00Z",
        published_by="release-service",
        resolved_knowledge_bindings=bindings,
        knowledge_release_record=release,
    )
    return (
        PublishedAgent(
            agent_id=AGENT_ID,
            manifest_path=manifest_path,
            display_name=version.display_name,
            purpose=version.purpose,
            customer_facing=False,
            agent_version_id=version.version_id,
            source_draft_id=version.source_draft_id,
            validation_run_id=version.validation_run_id,
            resolved_knowledge_bindings=bindings,
            source="postgres_publication",
        ),
        version,
    )


def test_accepts_exact_real_model_hybrid_phase_f_candidate(tmp_path: Path) -> None:
    agent, version = _candidate(tmp_path)
    credentials = ModelCredentials()

    validate_production_agent_candidate(
        agent=agent,
        version=version,
        configuration_store=ModelConnections(),
        model_credential_resolver=credentials,
    )

    assert credentials.validated == ["model_production_primary"] * 3


def test_deployment_package_is_an_admissible_production_candidate() -> None:
    manifest_path = Path(
        "deploy/production/agent_management_insurance_specialist/agent.yaml"
    ).resolve()
    bundle = build_agent_package_contract_bundle(manifest_path)
    binding = _binding().model_copy(
        update={"retrieval_profile_revision_id": "insurance-profile-v1"}
    )
    bindings = ResolvedKnowledgeBindingSet(bindings=(binding,))
    release = seal_knowledge_release_record(
        record_id="production-package-release",
        contract_bundle=bundle,
        resolved_knowledge_bindings=bindings,
        shadow_artifact=_artifact("shadow"),
        capacity_artifact=_artifact("capacity"),
        acceptance_artifact=_artifact("acceptance"),
        recovery_artifact=_artifact("recovery"),
        created_at="2026-07-15T00:00:00Z",
        created_by="release-service",
    )
    version = PublishedAgentVersion(
        agent_id=AGENT_ID,
        version_id=VERSION_ID,
        source_draft_id="019ba001-1111-7000-8000-000000000002",
        validation_run_id="019ba001-1111-7000-8000-000000000003",
        display_name="Insurance Specialist",
        purpose="Answer governed insurance questions",
        contract_bundle=bundle,
        published_at="2026-07-15T00:00:00Z",
        published_by="release-service",
        resolved_knowledge_bindings=bindings,
        knowledge_release_record=release,
    )
    agent = PublishedAgent(
        agent_id=AGENT_ID,
        manifest_path=manifest_path,
        display_name=version.display_name,
        purpose=version.purpose,
        customer_facing=False,
        agent_version_id=version.version_id,
        source_draft_id=version.source_draft_id,
        validation_run_id=version.validation_run_id,
        resolved_knowledge_bindings=bindings,
        source="postgres_publication",
    )
    credentials = ModelCredentials()

    validate_production_agent_candidate(
        agent=agent,
        version=version,
        configuration_store=ModelConnections(),
        model_credential_resolver=credentials,
    )

    assert credentials.validated == ["model_production_primary"] * 3


def test_rejects_deterministic_answer_model(tmp_path: Path) -> None:
    agent, version = _candidate(tmp_path, answer_provider="deterministic")

    with pytest.raises(ProductionAgentValidationError, match="Shared Model Connection"):
        validate_production_agent_candidate(
            agent=agent,
            version=version,
            **_validation_dependencies(),
        )


def test_rejects_runtime_memory_for_initial_private_pilot(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path, memory_enabled=True)
    bundle = build_agent_package_contract_bundle(manifest_path)
    candidate_root = tmp_path / "candidate"
    candidate_root.mkdir()
    agent, version = _candidate(candidate_root)
    agent = replace(agent, manifest_path=manifest_path)
    version = version.model_copy(update={"contract_bundle": bundle})

    with pytest.raises(
        ProductionAgentValidationError,
        match="cannot enable non-authoritative runtime memory",
    ):
        validate_production_agent_candidate(
            agent=agent,
            version=version,
            **_validation_dependencies(),
        )


def test_rejects_missing_phase_f_release_record(tmp_path: Path) -> None:
    agent, version = _candidate(tmp_path, with_release=False)

    with pytest.raises(ProductionAgentValidationError, match="Release Record"):
        validate_production_agent_candidate(
            agent=agent,
            version=version,
            **_validation_dependencies(),
        )


def test_rejects_unresolvable_postgres_model_credential(tmp_path: Path) -> None:
    agent, version = _candidate(tmp_path)

    with pytest.raises(ProductionAgentValidationError, match="not resolvable"):
        validate_production_agent_candidate(
            agent=agent,
            version=version,
            **_validation_dependencies(resolvable=False),
        )


def test_rejects_more_than_one_frozen_hybrid_binding(tmp_path: Path) -> None:
    agent, version = _candidate(tmp_path)
    extra = _binding().model_copy(
        update={
            "binding_id": "insurance_hybrid_extra",
            "source_id": "insurance-rules-extra",
        }
    )
    bindings = ResolvedKnowledgeBindingSet(bindings=(_binding(), extra))

    with pytest.raises(ProductionAgentValidationError, match="exactly one"):
        validate_production_agent_candidate(
            agent=replace(agent, resolved_knowledge_bindings=bindings),
            version=version.model_copy(
                update={"resolved_knowledge_bindings": bindings}
            ),
            **_validation_dependencies(),
        )


class Agents:
    def __init__(self) -> None:
        self.drafts = []
        self.publications = []
        self.active = None

    def save_draft(self, draft, *, expected_revision):
        assert expected_revision == 0
        self.drafts.append(draft)
        return SimpleNamespace(draft=draft, revision=1)

    def publish_version(self, publication, *, expected_draft_revision):
        assert expected_draft_revision == 1
        expectation = publication.active_pointer_expectation
        if expectation is not None:
            actual = None if self.active is None else self.active.version_id
            if actual != expectation.version_id:
                raise PersistencePointerConflictError(
                    resource_type="active_agent_version",
                    resource_id=publication.version.agent_id,
                    expected_pointer=expectation.version_id,
                    actual_pointer=actual,
                )
        self.publications.append(publication)
        self.active = publication.activation
        return publication

    def list_active(self):
        return () if self.active is None else (self.active,)

    def get_active(self, agent_id):
        if self.active is None or self.active.agent_id != agent_id:
            return None
        return self.active


class Knowledge:
    def resolve_version(self, asset_id, *, version_id=None):
        assert asset_id == "insurance-rules"
        assert version_id is None
        return SharedAssetVersionRef(
            kind=SharedAssetKind.KNOWLEDGE_SOURCE,
            asset_id=asset_id,
            version_id="019ba001-1111-7000-8000-000000000010",
            revision=7,
            content_digest="5" * 64,
        )


class Audits:
    def __init__(self) -> None:
        self.events = []

    def append(self, event) -> None:
        self.events.append(event)


class UnitOfWork:
    def __init__(self, agents: Agents, audits: Audits) -> None:
        self.agents = agents
        self.knowledge = Knowledge()
        self.audit = audits
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def commit(self):
        self.committed = True


class ReleaseAuthority:
    def __init__(self, *, authorized: bool = True) -> None:
        self.authorized = authorized
        self.records = []

    def verify_release_record(self, record):
        self.records.append(record)
        return self.authorized


class CandidateRunner:
    def __init__(self) -> None:
        self.calls = []

    def validate(self, *, agent, version, question):
        self.calls.append((agent, version, question))
        return ProductionAgentCandidateValidation(
            run_id=version.validation_run_id,
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            accepted_citation_count=2,
            trace_ref=_artifact("shadow"),
            receipt_ref=_artifact("capacity"),
        )


def _publication_service(
    *,
    agents: Agents,
    audits: Audits,
    release_authority: ReleaseAuthority,
    runner: CandidateRunner,
) -> ProductionAgentPublicationService:
    binding = _binding()
    snapshot = SimpleNamespace(
        publication=SimpleNamespace(
            publication_id=binding.source_publication_id,
            source_id=binding.source_id,
            source_snapshot_id=binding.source_snapshot_id,
            generation_id=binding.index_generation_id,
            source_publication_seq=binding.source_publication_seq,
            manifest_ref=binding.manifest_ref,
            attestation=SimpleNamespace(
                attestation_id=binding.publication_attestation_id,
            ),
        ),
        retrieval_profile=SimpleNamespace(
            profile_revision_id=binding.retrieval_profile_revision_id,
        ),
    )
    return ProductionAgentPublicationService(
        unit_of_work_factory=lambda: UnitOfWork(agents, audits),
        binding_authority=SimpleNamespace(
            resolve_binding_authority=lambda **kwargs: snapshot
        ),
        release_authority=release_authority,
        configuration_store=ModelConnections(),
        model_credential_resolver=ModelCredentials(),
        candidate_validator=runner,
        clock=lambda: datetime(2026, 7, 15, tzinfo=UTC),
    )


def test_publication_service_validates_phase_f_and_smoke_run_before_atomic_activation(
    tmp_path: Path,
) -> None:
    path = _write_manifest(tmp_path)
    agents = Agents()
    audits = Audits()
    authority = ReleaseAuthority()
    runner = CandidateRunner()
    service = _publication_service(
        agents=agents,
        audits=audits,
        release_authority=authority,
        runner=runner,
    )

    publication = service.publish(
        agent_manifest_path=path,
        evidence=KnowledgeReleaseEvidenceSet(
            shadow=_artifact("shadow"),
            capacity=_artifact("capacity"),
            acceptance=_artifact("acceptance"),
            recovery=_artifact("recovery"),
        ),
        smoke_question="等待期如何解释？",
        actor=AuditActorFacts(
            subject="release-operator",
            identity_provider="deployment-identity",
            session_id="release-session-1",
        ),
    )

    assert publication.version.agent_id == AGENT_ID
    assert publication.version.knowledge_release_record == authority.records[0]
    assert publication.version.validation_run_id == runner.calls[0][1].validation_run_id
    assert len(agents.drafts) == 1
    assert agents.publications == [publication]
    assert publication.active_pointer_expectation is not None
    assert publication.active_pointer_expectation.version_id is None
    operation_metadata = publication.version.operation_audit[0].metadata
    assert operation_metadata["validation_trace_ref"]["artifact_uri"].startswith("s3://")
    assert operation_metadata["validation_receipt_ref"]["version_id"].startswith(
        "opaque-"
    )
    assert [event.event_type for event in audits.events] == [
        "agent.candidate_staged",
        "agent.version_published",
    ]
    publication_audit = audits.events[-1].metadata
    assert publication_audit["validation_trace_ref"]["sha256"] == "1" * 64
    assert publication_audit["validation_receipt_ref"]["sha256"] == "2" * 64


def test_publication_service_never_runs_or_activates_unauthorized_phase_f_record(
    tmp_path: Path,
) -> None:
    path = _write_manifest(tmp_path)
    agents = Agents()
    audits = Audits()
    runner = CandidateRunner()
    service = _publication_service(
        agents=agents,
        audits=audits,
        release_authority=ReleaseAuthority(authorized=False),
        runner=runner,
    )

    with pytest.raises(ProductionAgentValidationError, match="authority"):
        service.publish(
            agent_manifest_path=path,
            evidence=KnowledgeReleaseEvidenceSet(
                shadow=_artifact("shadow"),
                capacity=_artifact("capacity"),
                acceptance=_artifact("acceptance"),
                recovery=_artifact("recovery"),
            ),
            smoke_question="等待期如何解释？",
            actor=AuditActorFacts(
                subject="release-operator",
                identity_provider="deployment-identity",
                session_id="release-session-1",
            ),
        )

    assert agents.drafts == []
    assert agents.publications == []
    assert runner.calls == []


def test_publication_service_rejects_activation_pointer_changed_during_smoke(
    tmp_path: Path,
) -> None:
    path = _write_manifest(tmp_path)
    agents = Agents()
    audits = Audits()

    class ConcurrentActivationRunner(CandidateRunner):
        def validate(self, *, agent, version, question):
            result = super().validate(agent=agent, version=version, question=question)
            agents.active = ActiveAgentVersion(
                agent_id=AGENT_ID,
                version_id="019ba001-1111-7000-8000-000000000099",
                activated_at="2026-07-15T00:00:30Z",
                activated_by="other-release",
            )
            return result

    service = _publication_service(
        agents=agents,
        audits=audits,
        release_authority=ReleaseAuthority(),
        runner=ConcurrentActivationRunner(),
    )

    with pytest.raises(PersistencePointerConflictError):
        service.publish(
            agent_manifest_path=path,
            evidence=KnowledgeReleaseEvidenceSet(
                shadow=_artifact("shadow"),
                capacity=_artifact("capacity"),
                acceptance=_artifact("acceptance"),
                recovery=_artifact("recovery"),
            ),
            smoke_question="等待期如何解释？",
            actor=AuditActorFacts(
                subject="release-operator",
                identity_provider="deployment-identity",
                session_id="release-session-1",
            ),
        )

    assert agents.publications == []
    assert [event.event_type for event in audits.events] == ["agent.candidate_staged"]


class ExactStore:
    def __init__(self) -> None:
        self.values = {}

    def put_immutable(self, *, key, content, media_type):
        ref = ExactArtifactRef(
            artifact_uri=f"s3://proof-agent/{key}",
            version_id=f"opaque-{len(self.values) + 1}",
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            media_type=media_type,
        )
        self.values[ref] = content
        return ref

    def get_exact(self, ref):
        return self.values[ref]


def test_online_candidate_validator_executes_real_path_and_retains_exact_artifacts(
    tmp_path: Path,
) -> None:
    agent, version = _candidate(tmp_path)
    store = ExactStore()

    def execute(**kwargs):
        assert kwargs["run_id"] == version.validation_run_id
        assert kwargs["institution_authorization"].institutions == ("branch-shanghai",)
        trace = tmp_path / "trace.jsonl"
        receipt = tmp_path / "receipt.md"
        trace.write_bytes(b'{"event_type":"final_output"}\n')
        receipt.write_bytes(b"# governed receipt\n")
        return SimpleNamespace(
            result=SimpleNamespace(trace_path=trace, receipt_path=receipt),
            detail=SimpleNamespace(
                outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
                evidence_chunks=(
                    SimpleNamespace(status="accepted", citation="knowledge://rules/r1#p1"),
                    SimpleNamespace(status="accepted", citation="knowledge://rules/r2#p2"),
                ),
            ),
        )

    validator = ProductionOnlineAgentCandidateValidator(
        configuration_store=object(),
        hybrid_runtime=object(),
        guarded_http_client=object(),
        secret_provider=Secrets(),
        model_credential_resolver=ModelCredentials(),
        artifact_store=store,
        work_root=tmp_path / "validation-work",
        institution_authorization=InstitutionAuthorizationContext(
            institutions=("branch-shanghai",)
        ),
        execute=execute,
    )

    result = validator.validate(
        agent=agent,
        version=version,
        question="等待期如何解释？",
    )

    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert result.accepted_citation_count == 2
    assert store.get_exact(result.trace_ref).endswith(b"\n")
    assert store.get_exact(result.receipt_ref).startswith(b"# governed")
