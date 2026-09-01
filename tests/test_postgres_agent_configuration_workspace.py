from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

import pytest
from sqlalchemy import Engine

from proof_agent.capabilities.persistence.postgres.agent_repository import (
    PostgresAgentLifecycleRepository,
)
from proof_agent.capabilities.persistence.postgres.audit_repository import (
    PostgresAuditRepository,
)
from proof_agent.capabilities.persistence.postgres.configuration_uow import (
    PostgresConfigurationUnitOfWork,
)
from proof_agent.contracts import (
    ActiveAgentPointerExpectation,
    ActiveAgentVersion,
    AgentPublicationRecord,
    AuditActorFacts,
    AuditMetadataRecord,
    ContractBundle,
    DraftAgent,
    ProductionSecretHandle,
    PublishedAgentVersion,
    ResolvedKnowledgeBindingSet,
    ResolvedKnowledgeSourceServiceBinding,
    SecretPurpose,
)
from proof_agent.contracts.knowledge_service_management import (
    KnowledgeServiceManagementWorkspace,
    KnowledgeServiceReadinessProjection,
    KnowledgeServiceReleaseProjection,
)
from proof_agent.control.agent_configuration_workspace import (
    AgentConfigurationConflict,
    AgentConfigurationWorkspace,
)


pytestmark = pytest.mark.postgres_integration
pytest_plugins = ("postgres_fixtures",)

_AGENT_ID = "agent_management_insurance_specialist"
_TARGET_DRAFT_ID = "019ba001-1111-7000-8000-000000000901"
_CURRENT_DRAFT_ID = "019ba001-1111-7000-8000-000000000902"
_TARGET_VERSION_ID = "019ba001-1111-7000-8000-000000000911"
_CURRENT_VERSION_ID = "019ba001-1111-7000-8000-000000000912"
_RELEASE_ID = "release-insurance-2026-08-18"


class StaticKnowledgeReleaseCatalog:
    def __init__(self, projection: KnowledgeServiceManagementWorkspace) -> None:
        self._projection = projection

    def workspace(self) -> KnowledgeServiceManagementWorkspace:
        return self._projection


class BarrierKnowledgeReleaseCatalog(StaticKnowledgeReleaseCatalog):
    def __init__(
        self,
        projection: KnowledgeServiceManagementWorkspace,
        *,
        barrier: Barrier,
    ) -> None:
        super().__init__(projection)
        self._barrier = barrier

    def workspace(self) -> KnowledgeServiceManagementWorkspace:
        self._barrier.wait(timeout=10)
        return super().workspace()


class FailAfterRollbackAudit:
    def __init__(self, repository: PostgresAuditRepository) -> None:
        self._repository = repository

    def append(self, event: AuditMetadataRecord) -> None:
        self._repository.append(event)
        if event.event_type == "agent.version.rolled_back":
            raise RuntimeError("injected rollback audit failure")


class FailAfterRollbackAuditUnitOfWork(PostgresConfigurationUnitOfWork):
    def __enter__(self) -> FailAfterRollbackAuditUnitOfWork:
        super().__enter__()
        self.audit = FailAfterRollbackAudit(self.audit)  # type: ignore[assignment]
        return self


def _template_bundle() -> ContractBundle:
    return ContractBundle(
        agent_yaml=(
            f"name: {_AGENT_ID}\n"
            "purpose: Governed PostgreSQL rollback verification.\n"
            "workflow:\n"
            "  template: react_enterprise_qa_v3\n"
            "capabilities:\n"
            "  tools:\n"
            "    enabled: false\n"
            "  memory:\n"
            "    enabled: false\n"
        ),
        policy_yaml="rules: []\n",
        tools_yaml="tools: []\n",
    )


def _draft(*, draft_id: str, purpose: str, updated_at: str) -> DraftAgent:
    return DraftAgent(
        agent_id=_AGENT_ID,
        draft_id=draft_id,
        display_name="Insurance Specialist",
        purpose=purpose,
        contract_bundle=_template_bundle(),
        created_at="2026-09-01T12:00:00Z",
        updated_at=updated_at,
        created_by="operator-1",
        updated_by="operator-1",
    )


def _knowledge_bindings() -> ResolvedKnowledgeBindingSet:
    return ResolvedKnowledgeBindingSet(
        bindings=(
            ResolvedKnowledgeSourceServiceBinding(
                binding_id="insurance-knowledge",
                knowledge_base_release_id=_RELEASE_ID,
                client_credential_ref=ProductionSecretHandle(
                    protocol_id="hashicorp-vault-2.0-kv-v2",
                    handle_id="knowledge/source-service/agent-client",
                    purpose=SecretPurpose.KNOWLEDGE_CREDENTIAL,
                    version_id="credential-v7",
                ),
                admission_scorer_id="insurance-evidence-admission",
                admission_scorer_revision="insurance-evidence-admission.v3",
            ),
        )
    )


def _publication(
    draft: DraftAgent,
    *,
    version_id: str,
    published_at: str,
    expected_active_version_id: str | None,
) -> AgentPublicationRecord:
    version = PublishedAgentVersion(
        agent_id=draft.agent_id,
        version_id=version_id,
        source_draft_id=draft.draft_id,
        validation_run_id=f"run_{version_id}",
        display_name=draft.display_name,
        purpose=draft.purpose,
        contract_bundle=draft.contract_bundle,
        published_at=published_at,
        published_by="operator-1",
        resolved_knowledge_bindings=_knowledge_bindings(),
    )
    return AgentPublicationRecord(
        version=version,
        activation=ActiveAgentVersion(
            agent_id=draft.agent_id,
            version_id=version_id,
            activated_at=published_at,
            activated_by="operator-1",
        ),
        draft_revision=1,
        active_pointer_expectation=ActiveAgentPointerExpectation(
            version_id=expected_active_version_id
        ),
    )


def _seed_versions(
    engine: Engine,
) -> tuple[AgentPublicationRecord, AgentPublicationRecord]:
    repository = PostgresAgentLifecycleRepository(engine)
    target_draft = repository.save_draft(
        _draft(
            draft_id=_TARGET_DRAFT_ID,
            purpose="Target immutable version",
            updated_at="2026-09-01T12:00:00Z",
        ),
        expected_revision=0,
    )
    target = _publication(
        target_draft.draft,
        version_id=_TARGET_VERSION_ID,
        published_at="2026-09-01T12:01:00Z",
        expected_active_version_id=None,
    )
    repository.publish_version(target, expected_draft_revision=target_draft.revision)

    current_draft = repository.save_draft(
        _draft(
            draft_id=_CURRENT_DRAFT_ID,
            purpose="Current immutable version",
            updated_at="2026-09-01T12:02:00Z",
        ),
        expected_revision=0,
    )
    current = _publication(
        current_draft.draft,
        version_id=_CURRENT_VERSION_ID,
        published_at="2026-09-01T12:03:00Z",
        expected_active_version_id=_TARGET_VERSION_ID,
    )
    repository.publish_version(current, expected_draft_revision=current_draft.revision)
    return target, current


def _catalog() -> KnowledgeServiceManagementWorkspace:
    return KnowledgeServiceManagementWorkspace(
        readiness=KnowledgeServiceReadinessProjection(
            state="ready",
            revision="kss-postgres-rollback-2026-09-01",
            blockers=(),
        ),
        spaces=(),
        sources=(),
        bases=(),
        source_versions=(),
        releases=(
            KnowledgeServiceReleaseProjection(
                knowledge_space_id="insurance",
                knowledge_base_id="insurance-guidance",
                knowledge_base_version_id="insurance-guidance-v3",
                knowledge_base_release_id=_RELEASE_ID,
                source_version_count=3,
                state="queryable",
            ),
        ),
    )


def _workspace(engine: Engine) -> AgentConfigurationWorkspace:
    return AgentConfigurationWorkspace(
        unit_of_work_factory=lambda: PostgresConfigurationUnitOfWork(engine),
        template_bundle=_template_bundle(),
        knowledge_release_catalog=StaticKnowledgeReleaseCatalog(_catalog()),
        clock=lambda: datetime(2026, 9, 1, 12, 5, tzinfo=UTC),
    )


def _actor() -> AuditActorFacts:
    return AuditActorFacts(
        subject="operator-1",
        identity_provider="enterprise-oidc",
        session_id="session-postgres-rollback",
        permissions=("agent.publish",),
    )


def test_postgres_workspace_rollback_commits_pointer_and_audit_atomically(
    postgres_engine: Engine,
) -> None:
    target, current = _seed_versions(postgres_engine)

    result = _workspace(postgres_engine).rollback_version(
        agent_id=_AGENT_ID,
        version_id=target.version.version_id,
        expected_active_version_id=current.version.version_id,
        actor=_actor(),
    )

    agents = PostgresAgentLifecycleRepository(postgres_engine)
    assert result.restored == target.version
    assert result.activation.version_id == target.version.version_id
    assert result.activation.rollback_from_version_id == current.version.version_id
    assert agents.get_active(_AGENT_ID) == result.activation
    assert {item.version_id for item in agents.list_published(_AGENT_ID)} == {
        target.version.version_id,
        current.version.version_id,
    }
    audits = PostgresAuditRepository(postgres_engine).list_for_target(
        target_type="agent_version",
        target_id=target.version.version_id,
    )
    assert len(audits) == 1
    assert audits[0].event_type == "agent.version.rolled_back"
    assert audits[0].metadata["agent_id"] == _AGENT_ID
    assert (
        audits[0].metadata["replaced_active_version_id"]
        == current.version.version_id
    )


def test_postgres_workspace_rollback_allows_only_one_concurrent_pointer_winner(
    postgres_engine: Engine,
) -> None:
    target, current = _seed_versions(postgres_engine)
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=lambda: PostgresConfigurationUnitOfWork(postgres_engine),
        template_bundle=_template_bundle(),
        knowledge_release_catalog=BarrierKnowledgeReleaseCatalog(
            _catalog(),
            barrier=Barrier(2),
        ),
        clock=lambda: datetime(2026, 9, 1, 12, 5, tzinfo=UTC),
    )

    def rollback() -> str:
        try:
            workspace.rollback_version(
                agent_id=_AGENT_ID,
                version_id=target.version.version_id,
                expected_active_version_id=current.version.version_id,
                actor=_actor(),
            )
        except AgentConfigurationConflict as exc:
            return exc.code
        return "rolled_back"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _: rollback(), range(2)))

    assert sorted(results) == ["active_agent_version_conflict", "rolled_back"]
    agents = PostgresAgentLifecycleRepository(postgres_engine)
    active = agents.get_active(_AGENT_ID)
    assert active is not None
    assert active.version_id == target.version.version_id
    assert active.rollback_from_version_id == current.version.version_id
    audits = PostgresAuditRepository(postgres_engine).list_for_target(
        target_type="agent_version",
        target_id=target.version.version_id,
    )
    assert len(audits) == 1
    assert audits[0].event_type == "agent.version.rolled_back"


def test_postgres_workspace_rollback_restores_pointer_when_audit_boundary_fails(
    postgres_engine: Engine,
) -> None:
    target, current = _seed_versions(postgres_engine)
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=lambda: FailAfterRollbackAuditUnitOfWork(postgres_engine),
        template_bundle=_template_bundle(),
        knowledge_release_catalog=StaticKnowledgeReleaseCatalog(_catalog()),
        clock=lambda: datetime(2026, 9, 1, 12, 5, tzinfo=UTC),
    )

    with pytest.raises(RuntimeError, match="injected rollback audit failure"):
        workspace.rollback_version(
            agent_id=_AGENT_ID,
            version_id=target.version.version_id,
            expected_active_version_id=current.version.version_id,
            actor=_actor(),
        )

    agents = PostgresAgentLifecycleRepository(postgres_engine)
    assert agents.get_active(_AGENT_ID) == current.activation
    assert {item.version_id for item in agents.list_published(_AGENT_ID)} == {
        target.version.version_id,
        current.version.version_id,
    }
    assert PostgresAuditRepository(postgres_engine).list_for_target(
        target_type="agent_version",
        target_id=target.version.version_id,
    ) == ()
