from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import TracebackType

import pytest
import yaml  # type: ignore[import-untyped]

from proof_agent.contracts import (
    ActiveAgentVersion,
    AgentActivationRecord,
    AgentDraftRecord,
    AgentPublicationRecord,
    AgentValidationRecord,
    AuditActorFacts,
    AuditMetadataRecord,
    ConfigurationOperation,
    ConfigurationOperationAudit,
    ContractBundle,
    DraftKnowledgeReleaseBindingCandidate,
    DraftAgent,
    ExactArtifactRef,
    FormalProductionAgentOnlineSmokeResult,
    FormalProductionAgentPhaseFRecord,
    FormalProductionAgentPublicationEvidence,
    ProductionSecretHandle,
    PublishedAgentVersion,
    ReceiptOutcome,
    RegisteredProductionAgentReleaseReference,
    ResolvedKnowledgeBindingSet,
    ResolvedKnowledgeSourceServiceBinding,
    SecretPurpose,
    SensitiveValidationCaptureArtifact,
    WorkflowStageConfig,
    WorkflowStageContextConfig,
    WorkflowStagePromptConfig,
)
from proof_agent.contracts.knowledge_service_management import (
    KnowledgeServiceManagementWorkspace,
    KnowledgeServiceReadinessProjection,
    KnowledgeServiceReleaseProjection,
)
from proof_agent.contracts.persistence import (
    PersistenceConflictError,
    PersistenceNotFoundError,
    PersistencePointerConflictError,
)
from proof_agent.control.agent_configuration_workspace import (
    AgentConfigurationConflict,
    AgentConfigurationNotFound,
    AgentConfigurationPublicationRejected,
    AgentConfigurationScope,
    AgentConfigurationPublicationValidator,
    AgentConfigurationValidationCaptureError,
    AgentConfigurationValidationExecution,
    AgentConfigurationWorkspace,
    AgentConfigurationWorkflowStageDraftFacts,
    AgentConfigurationWorkflowStageInspector,
)
from proof_agent.control.agent_configuration_skill_packs import (
    BusinessFlowSkillPackConfiguration,
    BusinessFlowSkillPackCreateCommand,
    BusinessFlowSkillPackUpdateCommand,
)
from proof_agent.control.production_agent_publication_configuration import (
    ProductionAgentPublicationConfigurationProjector,
)
from proof_agent.errors import ProofAgentError


class InMemoryAgentLifecycleRepository:
    def __init__(self, records: tuple[AgentDraftRecord, ...]) -> None:
        self.records = {
            (record.draft.agent_id, record.draft.draft_id): record for record in records
        }
        self.published: dict[tuple[str, str], PublishedAgentVersion] = {}
        self.active: dict[str, ActiveAgentVersion] = {}
        self.activations: list[AgentActivationRecord] = []

    def list_drafts(self, agent_id: str | None = None) -> tuple[AgentDraftRecord, ...]:
        records = tuple(self.records.values())
        if agent_id is not None:
            records = tuple(record for record in records if record.draft.agent_id == agent_id)
        return records

    def get_draft(self, agent_id: str, draft_id: str) -> AgentDraftRecord | None:
        return self.records.get((agent_id, draft_id))

    def save_draft(
        self,
        draft: DraftAgent,
        *,
        expected_revision: int,
    ) -> AgentDraftRecord:
        key = (draft.agent_id, draft.draft_id)
        current = self.records.get(key)
        actual_revision = None if current is None else current.revision
        if actual_revision != expected_revision:
            raise PersistenceConflictError(
                resource_type="agent_draft",
                resource_id=draft.draft_id,
                expected_revision=expected_revision,
                actual_revision=actual_revision,
            )
        record = AgentDraftRecord(draft=draft, revision=expected_revision + 1)
        self.records[key] = record
        return record

    def publish_version(
        self,
        publication: AgentPublicationRecord,
        *,
        expected_draft_revision: int,
    ) -> AgentPublicationRecord:
        version = publication.version
        current = self.get_draft(version.agent_id, version.source_draft_id)
        actual_revision = None if current is None else current.revision
        if actual_revision != expected_draft_revision:
            raise PersistenceConflictError(
                resource_type="agent_draft",
                resource_id=version.source_draft_id,
                expected_revision=expected_draft_revision,
                actual_revision=actual_revision,
            )
        expectation = publication.active_pointer_expectation
        current_active = self.active.get(version.agent_id)
        actual_pointer = None if current_active is None else current_active.version_id
        if expectation is not None and expectation.version_id != actual_pointer:
            raise PersistencePointerConflictError(
                resource_type="active_agent_version",
                resource_id=version.agent_id,
                expected_pointer=expectation.version_id,
                actual_pointer=actual_pointer,
            )
        key = (version.agent_id, version.version_id)
        if key in self.published:
            raise PersistenceConflictError(
                resource_type="agent_version",
                resource_id=version.version_id,
                expected_revision=0,
                actual_revision=1,
            )
        self.published[key] = version
        self.active[version.agent_id] = publication.activation
        return publication

    def activate_version(
        self,
        activation: AgentActivationRecord,
    ) -> AgentActivationRecord:
        value = activation.activation
        if (value.agent_id, value.version_id) not in self.published:
            raise PersistenceNotFoundError(
                resource_type="agent_version",
                resource_id=value.version_id,
            )
        current = self.active.get(value.agent_id)
        actual_pointer = None if current is None else current.version_id
        expected_pointer = activation.active_pointer_expectation.version_id
        if actual_pointer != expected_pointer:
            raise PersistencePointerConflictError(
                resource_type="active_agent_version",
                resource_id=value.agent_id,
                expected_pointer=expected_pointer,
                actual_pointer=actual_pointer,
            )
        self.active[value.agent_id] = value
        self.activations.append(activation)
        return activation

    def get_published(
        self,
        agent_id: str,
        version_id: str,
    ) -> PublishedAgentVersion | None:
        return self.published.get((agent_id, version_id))

    def list_published(self, agent_id: str) -> tuple[PublishedAgentVersion, ...]:
        return tuple(
            version
            for (stored_agent_id, _), version in self.published.items()
            if stored_agent_id == agent_id
        )

    def get_active(self, agent_id: str) -> ActiveAgentVersion | None:
        return self.active.get(agent_id)

    def list_active(self) -> tuple[ActiveAgentVersion, ...]:
        return tuple(self.active.values())


class InMemoryAuditRepository:
    def __init__(self, *, fail_append: bool = False) -> None:
        self.events: list[AuditMetadataRecord] = []
        self._fail_append = fail_append

    def append(self, event: AuditMetadataRecord) -> None:
        if self._fail_append:
            raise RuntimeError("simulated audit append failure")
        self.events.append(event)


class InMemoryConfigurationUnitOfWork:
    def __init__(
        self,
        agents: InMemoryAgentLifecycleRepository,
        audit: InMemoryAuditRepository,
        *,
        fail_commit: bool = False,
    ) -> None:
        self.agents = agents
        self.audit = audit
        self.committed = False
        self._fail_commit = fail_commit
        self._records_snapshot = dict(agents.records)
        self._published_snapshot = dict(agents.published)
        self._active_snapshot = dict(agents.active)
        self._activation_count = len(agents.activations)
        self._audit_length = len(audit.events)

    def __enter__(self) -> "InMemoryConfigurationUnitOfWork":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_value, traceback
        if exc_type is not None or not self.committed:
            self.agents.records = self._records_snapshot
            self.agents.published = self._published_snapshot
            self.agents.active = self._active_snapshot
            del self.agents.activations[self._activation_count :]
            del self.audit.events[self._audit_length :]

    def commit(self) -> None:
        if self._fail_commit:
            raise RuntimeError("simulated commit failure")
        self.committed = True


class UnitOfWorkFactory:
    def __init__(
        self,
        records: tuple[AgentDraftRecord, ...],
        *,
        agents: InMemoryAgentLifecycleRepository | None = None,
        fail_audit: bool = False,
        fail_commit: bool = False,
    ) -> None:
        self.agents = agents or InMemoryAgentLifecycleRepository(records)
        self.audit = InMemoryAuditRepository(fail_append=fail_audit)
        self._fail_commit = fail_commit
        self.units: list[InMemoryConfigurationUnitOfWork] = []

    def __call__(self) -> InMemoryConfigurationUnitOfWork:
        unit = InMemoryConfigurationUnitOfWork(
            self.agents,
            self.audit,
            fail_commit=self._fail_commit,
        )
        self.units.append(unit)
        return unit


class MutatingPublishedVersionFactory(UnitOfWorkFactory):
    def __init__(
        self,
        records: tuple[AgentDraftRecord, ...],
        *,
        target: PublishedAgentVersion,
    ) -> None:
        super().__init__(records)
        self._target = target

    def __call__(self) -> InMemoryConfigurationUnitOfWork:
        if self.units:
            key = (self._target.agent_id, self._target.version_id)
            self.agents.published[key] = self._target.model_copy(
                update={"display_name": "mutated immutable target"}
            )
        return super().__call__()


class MutatingActivePointerFactory(UnitOfWorkFactory):
    def __init__(
        self,
        records: tuple[AgentDraftRecord, ...],
        *,
        target: PublishedAgentVersion,
        replacement: ActiveAgentVersion,
    ) -> None:
        super().__init__(records)
        self._target = target
        self._replacement = replacement

    def __call__(self) -> InMemoryConfigurationUnitOfWork:
        if self.units:
            self.agents.active[self._target.agent_id] = self._replacement
        return super().__call__()


class RecordingValidationExecutor:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def validate(
        self,
        *,
        draft: DraftAgent,
        question: str,
        full_capture: bool,
        retain_for_audit: bool,
        actor: AuditActorFacts,
    ) -> AgentConfigurationValidationExecution:
        self.requests.append(
            {
                "draft": draft,
                "question": question,
                "full_capture": full_capture,
                "retain_for_audit": retain_for_audit,
                "actor": actor,
            }
        )
        capture = SensitiveValidationCaptureArtifact(
            capture_id="vcap_validation_1",
            run_id="run_validation_1",
            draft_id=draft.draft_id,
            created_at="2026-08-19T04:30:00Z",
            expires_at="2026-08-20T04:30:00Z",
            created_by=actor.subject,
            artifact_path="validation-captures/vcap_validation_1.json",
            retain_for_audit=retain_for_audit,
        )
        return AgentConfigurationValidationExecution(
            run_id="run_validation_1",
            outcome="passed",
            run_purpose="validation",
            agent_id=draft.agent_id,
            draft_id=draft.draft_id,
            summary="Governed validation answer.",
            trace_events=(
                {
                    "event_type": "model_connection_resolution",
                    "payload": {
                        "connection_id": "model_archived",
                        "role": "reasoning",
                        "warnings": ["connection_archived"],
                    },
                },
            ),
            validation_capture=capture if full_capture else None,
            capture_error=None,
        )


class ConcurrentMutationValidationExecutor(RecordingValidationExecutor):
    def __init__(self, factory: UnitOfWorkFactory) -> None:
        super().__init__()
        self._factory = factory

    def validate(self, **kwargs: object) -> AgentConfigurationValidationExecution:
        draft = kwargs["draft"]
        assert isinstance(draft, DraftAgent)
        current = self._factory.agents.records[(draft.agent_id, draft.draft_id)]
        self._factory.agents.records[(draft.agent_id, draft.draft_id)] = (
            AgentDraftRecord(
                draft=current.draft.model_copy(
                    update={"purpose": "Concurrently updated purpose."}
                ),
                revision=current.revision + 1,
            )
        )
        return super().validate(
            draft=draft,
            question=str(kwargs["question"]),
            full_capture=bool(kwargs["full_capture"]),
            retain_for_audit=bool(kwargs["retain_for_audit"]),
            actor=kwargs["actor"],  # type: ignore[arg-type]
        )


class InconsistentValidationExecutor(RecordingValidationExecutor):
    def __init__(self, inconsistency: str) -> None:
        super().__init__()
        self._inconsistency = inconsistency

    def validate(self, **kwargs: object) -> AgentConfigurationValidationExecution:
        execution = super().validate(
            draft=kwargs["draft"],  # type: ignore[arg-type]
            question=str(kwargs["question"]),
            full_capture=bool(kwargs["full_capture"]),
            retain_for_audit=bool(kwargs["retain_for_audit"]),
            actor=kwargs["actor"],  # type: ignore[arg-type]
        )
        if self._inconsistency == "execution_draft":
            return replace(execution, draft_id="another_draft")
        assert execution.validation_capture is not None
        if self._inconsistency == "capture_run":
            return replace(
                execution,
                validation_capture=execution.validation_capture.model_copy(
                    update={"run_id": "another_run"}
                ),
            )
        if self._inconsistency == "capture_draft":
            return replace(
                execution,
                validation_capture=execution.validation_capture.model_copy(
                    update={"draft_id": "another_draft"}
                ),
            )
        return replace(
            execution,
            capture_error=AgentConfigurationValidationCaptureError(
                code="VALIDATION_CAPTURE_REJECTED",
                message="Capture rejected.",
                retryable=False,
            ),
        )


class PublishableValidationExecutor(RecordingValidationExecutor):
    def validate(self, **kwargs: object) -> AgentConfigurationValidationExecution:
        execution = super().validate(
            draft=kwargs["draft"],  # type: ignore[arg-type]
            question=str(kwargs["question"]),
            full_capture=bool(kwargs["full_capture"]),
            retain_for_audit=bool(kwargs["retain_for_audit"]),
            actor=kwargs["actor"],  # type: ignore[arg-type]
        )
        return replace(execution, trace_events=())


class FailedValidationExecutor(PublishableValidationExecutor):
    def __init__(self, outcome: str) -> None:
        super().__init__()
        self._outcome = outcome

    def validate(self, **kwargs: object) -> AgentConfigurationValidationExecution:
        return replace(super().validate(**kwargs), outcome=self._outcome)


class RecordingPublicationValidator(AgentConfigurationPublicationValidator):
    def __init__(self) -> None:
        self.requests: list[tuple[DraftAgent, str]] = []

    def validate(
        self,
        *,
        draft: DraftAgent,
        validation: AgentValidationRecord,
    ) -> None:
        self.requests.append((draft, validation.run_id))


class RecordingWorkflowStageInspector(AgentConfigurationWorkflowStageInspector):
    def __init__(self) -> None:
        self.drafts: list[DraftAgent] = []

    def inspect(self, *, draft: DraftAgent) -> AgentConfigurationWorkflowStageDraftFacts:
        self.drafts.append(draft)
        return AgentConfigurationWorkflowStageDraftFacts(
            template_name="react_enterprise_qa_v3",
            agent_purpose=draft.purpose,
            tool_contract_reference="",
            policy_reference="policy.yaml",
            response_disclosure_policy={},
            memory_scope={"enabled": False, "provider": None, "scopes": {}},
        )


class RecordingContractValidator:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.drafts: list[DraftAgent] = []
        self._error = error

    def validate(self, *, draft: DraftAgent) -> None:
        self.drafts.append(draft)
        if self._error is not None:
            raise self._error


class ConcurrentMutationContractValidator(RecordingContractValidator):
    def __init__(self, factory: UnitOfWorkFactory) -> None:
        super().__init__()
        self._factory = factory

    def validate(self, *, draft: DraftAgent) -> None:
        super().validate(draft=draft)
        key = (draft.agent_id, draft.draft_id)
        current = self._factory.agents.records[key]
        self._factory.agents.records[key] = AgentDraftRecord(
            draft=current.draft.model_copy(
                update={"purpose": "Concurrent Contract winner."}
            ),
            revision=current.revision + 1,
        )


class ConcurrentMutationWorkflowStageInspector(RecordingWorkflowStageInspector):
    def __init__(self, factory: UnitOfWorkFactory) -> None:
        super().__init__()
        self._factory = factory

    def inspect(
        self,
        *,
        draft: DraftAgent,
    ) -> AgentConfigurationWorkflowStageDraftFacts:
        facts = super().inspect(draft=draft)
        key = (draft.agent_id, draft.draft_id)
        current = self._factory.agents.records[key]
        self._factory.agents.records[key] = AgentDraftRecord(
            draft=current.draft.model_copy(
                update={"purpose": "Concurrent Workflow winner."}
            ),
            revision=current.revision + 1,
        )
        return facts


class RecordingSkillPackInspector:
    def __init__(self) -> None:
        self.requests: list[DraftAgent] = []
        self.configuration = BusinessFlowSkillPackConfiguration(
            enabled=True,
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            addendum_slots=(),
            configuration_issues=(),
            packs=(),
        )

    def inspect(
        self,
        *,
        draft: DraftAgent,
        allow_configuration_issues: bool = False,
    ) -> BusinessFlowSkillPackConfiguration:
        del allow_configuration_issues
        self.requests.append(draft)
        return self.configuration


class ConcurrentMutationSkillPackInspector(RecordingSkillPackInspector):
    def __init__(self, factory: UnitOfWorkFactory) -> None:
        super().__init__()
        self._factory = factory

    def inspect(
        self,
        *,
        draft: DraftAgent,
        allow_configuration_issues: bool = False,
    ) -> BusinessFlowSkillPackConfiguration:
        configuration = super().inspect(
            draft=draft,
            allow_configuration_issues=allow_configuration_issues,
        )
        key = (draft.agent_id, draft.draft_id)
        current = self._factory.agents.records[key]
        self._factory.agents.records[key] = AgentDraftRecord(
            draft=current.draft.model_copy(
                update={"purpose": "Concurrent Skill Pack winner."}
            ),
            revision=current.revision + 1,
        )
        return configuration


class ConcurrentMutationPublicationValidator(RecordingPublicationValidator):
    def __init__(self, factory: UnitOfWorkFactory) -> None:
        super().__init__()
        self._factory = factory

    def validate(
        self,
        *,
        draft: DraftAgent,
        validation: AgentValidationRecord,
    ) -> None:
        super().validate(draft=draft, validation=validation)
        current = self._factory.agents.records[(draft.agent_id, draft.draft_id)]
        self._factory.agents.records[(draft.agent_id, draft.draft_id)] = AgentDraftRecord(
            draft=current.draft.model_copy(
                update={"purpose": "Concurrently changed after validation."}
            ),
            revision=current.revision + 1,
        )


class PointerConflictAgentRepository(InMemoryAgentLifecycleRepository):
    def publish_version(
        self,
        publication: AgentPublicationRecord,
        *,
        expected_draft_revision: int,
    ) -> AgentPublicationRecord:
        del expected_draft_revision
        raise PersistencePointerConflictError(
            resource_type="active_agent_version",
            resource_id=publication.version.agent_id,
            expected_pointer=(
                None
                if publication.active_pointer_expectation is None
                else publication.active_pointer_expectation.version_id
            ),
            actual_pointer="version_concurrent_winner",
        )


class PointerConflictActivationRepository(InMemoryAgentLifecycleRepository):
    def activate_version(
        self,
        activation: AgentActivationRecord,
    ) -> AgentActivationRecord:
        raise PersistencePointerConflictError(
            resource_type="active_agent_version",
            resource_id=activation.activation.agent_id,
            expected_pointer=activation.active_pointer_expectation.version_id,
            actual_pointer="version_concurrent_winner",
        )


def _draft(agent_id: str, draft_id: str, *, updated_at: str) -> AgentDraftRecord:
    return AgentDraftRecord(
        revision=1,
        draft=DraftAgent(
            agent_id=agent_id,
            draft_id=draft_id,
            display_name=f"{agent_id} display",
            purpose=f"{agent_id} purpose",
            contract_bundle=_template_bundle(agent_id),
            created_at="2026-08-19T00:00:00Z",
            updated_at=updated_at,
            created_by="operator-1",
            updated_by="operator-1",
        ),
    )


def _template_bundle(agent_id: str = "agent_management_insurance_specialist") -> ContractBundle:
    return ContractBundle(
        agent_yaml=(
            f"name: {agent_id}\n"
            "purpose: Governed test Agent.\n"
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


def _published_version(
    *,
    agent_id: str,
    draft_id: str,
    version_id: str,
    published_at: str,
    resolved_knowledge_bindings: ResolvedKnowledgeBindingSet | None = None,
) -> PublishedAgentVersion:
    return PublishedAgentVersion(
        agent_id=agent_id,
        version_id=version_id,
        source_draft_id=draft_id,
        validation_run_id=f"run_{version_id}",
        display_name=f"{agent_id} display",
        purpose=f"{agent_id} purpose",
        contract_bundle=_template_bundle(agent_id),
        published_at=published_at,
        published_by="operator-1",
        resolved_knowledge_bindings=resolved_knowledge_bindings,
    )


def _kss_bindings() -> ResolvedKnowledgeBindingSet:
    return ResolvedKnowledgeBindingSet(
        bindings=(
            ResolvedKnowledgeSourceServiceBinding(
                binding_id="insurance-knowledge",
                knowledge_base_release_id="release-insurance-2026-08-18",
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


def _rollback_release_catalog(
    *,
    release_state: str = "queryable",
    readiness: str = "ready",
) -> KnowledgeServiceManagementWorkspace:
    return KnowledgeServiceManagementWorkspace(
        readiness=KnowledgeServiceReadinessProjection(
            state=readiness,
            revision="kss-rollback-2026-09-01",
            blockers=() if readiness == "ready" else ("catalog",),
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
                knowledge_base_release_id="release-insurance-2026-08-18",
                source_version_count=3,
                state=release_state,
            ),
        ),
    )


def _formal_rollback_version(
    *,
    agent_id: str,
    draft_id: str,
    version_id: str,
) -> PublishedAgentVersion:
    validation_run_id = f"run_{version_id}"

    def artifact(kind: str, character: str) -> ExactArtifactRef:
        return ExactArtifactRef(
            artifact_uri=f"s3://proof-agent/formal-publication/{kind}.json",
            version_id=f"opaque-{kind}",
            sha256=character * 64,
            size_bytes=128,
            media_type="application/json",
        )

    phase_f_record = FormalProductionAgentPhaseFRecord(
        record_id="019ba001-1111-7000-8000-000000000841",
        provisional_version_id=version_id,
        validation_run_id=validation_run_id,
        formal_candidate_sha256="1" * 64,
        knowledge_release_candidate_sha256="2" * 64,
        evidence={
            "shadow": artifact("shadow", "3"),
            "capacity": artifact("capacity", "4"),
            "acceptance": artifact("acceptance", "5"),
            "recovery": artifact("recovery", "6"),
        },
        created_at="2026-08-19T04:30:00Z",
        created_by="operator-1",
        record_sha256="7" * 64,
    )
    reference = RegisteredProductionAgentReleaseReference(
        knowledge_space_id="insurance",
        knowledge_base_id="insurance-guidance",
        knowledge_base_release_id="release-insurance-2026-08-18",
        external_resource_id=version_id,
        release_reference_id="019ba001-1111-7000-8000-000000000842",
        authenticated_client_id="proof-agent-production",
        registered_at=datetime(2026, 8, 19, 4, 40, tzinfo=UTC),
    )
    smoke_result = FormalProductionAgentOnlineSmokeResult(
        agent_id=agent_id,
        provisional_version_id=version_id,
        validation_run_id=validation_run_id,
        release_reference_id=reference.release_reference_id,
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        accepted_citation_count=1,
        trace_ref=artifact("trace", "8"),
        receipt_ref=artifact("receipt", "9"),
    )
    return PublishedAgentVersion(
        agent_id=agent_id,
        version_id=version_id,
        source_draft_id=draft_id,
        validation_run_id=validation_run_id,
        display_name=f"{agent_id} display",
        purpose=f"{agent_id} purpose",
        contract_bundle=_template_bundle(agent_id),
        published_at="2026-08-19T05:00:00Z",
        published_by="operator-1",
        operation_audit=(
            ConfigurationOperationAudit(
                operation_id="019ba001-1111-7000-8000-000000000843",
                operation=ConfigurationOperation.PUBLISHED,
                actor="operator-1",
                created_at="2026-08-19T05:00:00Z",
            ),
        ),
        resolved_knowledge_bindings=_kss_bindings(),
        formal_production_evidence=FormalProductionAgentPublicationEvidence(
            source_draft_revision=14,
            phase_f_record=phase_f_record,
            release_reference=reference,
            online_smoke_result=smoke_result,
        ),
    )


def _actor() -> AuditActorFacts:
    return AuditActorFacts(
        subject="operator-1",
        identity_provider="local-development",
        session_id="session-1",
        permissions=("agent.edit",),
    )


def _skill_pack_draft() -> AgentDraftRecord:
    return AgentDraftRecord(
        revision=4,
        draft=DraftAgent(
            agent_id="skill_pack_agent",
            draft_id="draft_skill_pack",
            display_name="Skill Pack Agent",
            purpose="Configure governed Business Flow Skill Packs.",
            contract_bundle=ContractBundle(
                agent_yaml="""
name: skill_pack_agent
purpose: Configure governed Business Flow Skill Packs.
workflow:
  template: react_enterprise_qa_v3
  template_descriptor_version: react_enterprise_qa.v3
capabilities:
  tools:
    enabled: false
  memory:
    enabled: false
  skills:
    enabled: true
    business_flows:
      - id: claims_qa
        definition: ./skills/claims.yaml
        default: true
""",
                policy_yaml="rules: []\n",
                tools_yaml="tools: []\n",
                extra_files={
                    "skills/claims.yaml": """
schema_version: business_flow_skill_pack.v1
id: claims_qa
label: Claims QA
description: Existing governed claim guidance.
intent_patterns:
  - claim status
intent_taxonomy_refs: []
stage_prompt_addenda: {}
knowledge_binding_refs: []
tool_contract_refs: []
policy_rule_refs: []
validator_refs: []
admission: {}
""",
                },
            ),
            created_at="2026-08-20T01:00:00Z",
            updated_at="2026-08-20T02:00:00Z",
            created_by="operator-1",
            updated_by="operator-1",
        ),
    )


def test_multi_agent_workspace_hides_inventory_and_update_rules_behind_one_interface() -> None:
    first = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000801",
        updated_at="2026-08-19T01:00:00Z",
    )
    second = _draft(
        "agent_beta",
        "019ba001-1111-7000-8000-000000000802",
        updated_at="2026-08-19T02:00:00Z",
    )
    factory = UnitOfWorkFactory((first, second))
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        scope=AgentConfigurationScope.MULTI_AGENT,
        clock=lambda: datetime(2026, 8, 19, 3, tzinfo=UTC),
    )

    inventory = workspace.list_agents()
    updated = workspace.update_draft(
        agent_id=second.draft.agent_id,
        draft_id=second.draft.draft_id,
        expected_revision=1,
        display_name="Beta governed Agent",
        purpose=None,
        actor=_actor(),
    )

    assert tuple(item.agent_id for item in inventory.agents) == (
        "agent_alpha",
        "agent_beta",
    )
    assert inventory.can_create is True
    assert updated.revision == 2
    assert updated.draft.display_name == "Beta governed Agent"
    assert updated.draft.purpose == second.draft.purpose
    assert factory.units[-1].committed is True
    assert factory.audit.events[-1].event_type == "agent.draft.updated"
    assert factory.audit.events[-1].target_id == second.draft.draft_id


def test_workspace_validates_and_atomically_updates_raw_contract_with_revision_cas() -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000811",
        updated_at="2026-08-19T03:00:00Z",
    )
    preserved_bundle = current.draft.contract_bundle.model_copy(
        update={
            "extra_files": {"skills/claims.yaml": "id: claims\n"},
            "advanced_fields": {"extension": {"enabled": True}},
        }
    )
    current = AgentDraftRecord(
        draft=current.draft.model_copy(update={"contract_bundle": preserved_bundle}),
        revision=current.revision,
    )
    factory = UnitOfWorkFactory((current,))
    validator = RecordingContractValidator()
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        contract_validator=validator,
        scope=AgentConfigurationScope.MULTI_AGENT,
        clock=lambda: datetime(2026, 8, 19, 4, tzinfo=UTC),
    )

    saved = workspace.update_contract(
        agent_id=current.draft.agent_id,
        draft_id=current.draft.draft_id,
        expected_revision=1,
        agent_yaml=current.draft.contract_bundle.agent_yaml.replace(
            "Governed test Agent.",
            "Updated governed Agent.",
        ),
        policy_yaml=None,
        tools_yaml="tools:\n  - id: governed_lookup\n",
        actor=_actor(),
    )

    assert saved.revision == 2
    assert len(validator.drafts) == 1
    assert validator.drafts[0].contract_bundle == saved.draft.contract_bundle
    assert "Updated governed Agent." in saved.draft.contract_bundle.agent_yaml
    assert saved.draft.contract_bundle.policy_yaml == preserved_bundle.policy_yaml
    assert saved.draft.contract_bundle.tools_yaml == (
        "tools:\n  - id: governed_lookup\n"
    )
    assert saved.draft.contract_bundle.extra_files == preserved_bundle.extra_files
    assert saved.draft.contract_bundle.advanced_fields == preserved_bundle.advanced_fields
    assert saved.draft.operation_audit[-1].summary == "Updated Agent Contract."
    assert factory.audit.events[-1].event_type == "agent.draft.contract_updated"
    audit_text = repr(saved.draft.operation_audit[-1].metadata) + repr(
        factory.audit.events[-1].metadata
    )
    assert "Updated governed Agent." not in audit_text
    assert "governed_lookup" not in audit_text
    assert factory.units[-1].committed is True
    assert factory.agents.list_published(current.draft.agent_id) == ()
    assert factory.agents.get_active(current.draft.agent_id) is None


@pytest.mark.parametrize("level", ["minimal", "balanced", "thorough"])
def test_workspace_saves_and_reloads_agent_clarification_level(level: str) -> None:
    from proof_agent.contracts.manifest import ResponseConfig

    current = _draft("agent_alpha", "draft_clarification", updated_at="2026-09-10T00:00:00Z")
    factory = UnitOfWorkFactory((current,))
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory, template_bundle=_template_bundle(),
        contract_validator=RecordingContractValidator(), scope=AgentConfigurationScope.MULTI_AGENT,
        clock=lambda: datetime(2026, 9, 10, 4, tzinfo=UTC),
    )
    saved = workspace.update_contract(
        agent_id="agent_alpha", draft_id="draft_clarification", expected_revision=1,
        agent_yaml=current.draft.contract_bundle.agent_yaml + f"response:\n  clarification_level: {level}\n",
        policy_yaml=None, tools_yaml=None, actor=_actor(),
    )
    reloaded = workspace.get_draft(agent_id="agent_alpha", draft_id="draft_clarification")
    assert reloaded.revision == saved.revision == 2
    assert ResponseConfig.model_validate(yaml.safe_load(reloaded.draft.contract_bundle.agent_yaml)["response"]).clarification_level == level
    assert reloaded.draft.contract_bundle.policy_yaml == current.draft.contract_bundle.policy_yaml
    assert factory.agents.get_active("agent_alpha") is None


def test_workspace_contract_update_rejects_stale_revision_before_validation() -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000812",
        updated_at="2026-08-19T03:00:00Z",
    )
    factory = UnitOfWorkFactory((current,))
    validator = RecordingContractValidator()
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        contract_validator=validator,
        scope=AgentConfigurationScope.MULTI_AGENT,
    )

    with pytest.raises(AgentConfigurationConflict) as error:
        workspace.update_contract(
            agent_id=current.draft.agent_id,
            draft_id=current.draft.draft_id,
            expected_revision=2,
            agent_yaml="name: stale\n",
            policy_yaml=None,
            tools_yaml=None,
            actor=_actor(),
        )

    assert error.value.code == "agent_draft_revision_conflict"
    assert validator.drafts == []
    assert factory.agents.get_draft(
        current.draft.agent_id,
        current.draft.draft_id,
    ) == current
    assert factory.audit.events == []


def test_workspace_contract_update_does_not_overwrite_concurrent_validation_winner() -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000813",
        updated_at="2026-08-19T03:00:00Z",
    )
    factory = UnitOfWorkFactory((current,))
    validator = ConcurrentMutationContractValidator(factory)
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        contract_validator=validator,
        scope=AgentConfigurationScope.MULTI_AGENT,
    )

    with pytest.raises(AgentConfigurationConflict) as error:
        workspace.update_contract(
            agent_id=current.draft.agent_id,
            draft_id=current.draft.draft_id,
            expected_revision=1,
            agent_yaml="name: losing_contract\n",
            policy_yaml=None,
            tools_yaml=None,
            actor=_actor(),
        )

    assert error.value.code == "agent_draft_revision_conflict"
    winner = factory.agents.get_draft(
        current.draft.agent_id,
        current.draft.draft_id,
    )
    assert winner is not None
    assert winner.revision == 2
    assert winner.draft.purpose == "Concurrent Contract winner."
    assert winner.draft.contract_bundle == current.draft.contract_bundle
    assert factory.audit.events == []


@pytest.mark.parametrize("failure", ("validator", "audit", "commit"))
def test_workspace_contract_update_failure_leaves_draft_and_audit_unchanged(
    failure: str,
) -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000814",
        updated_at="2026-08-19T03:00:00Z",
    )
    factory = UnitOfWorkFactory(
        (current,),
        fail_audit=failure == "audit",
        fail_commit=failure == "commit",
    )
    validator = RecordingContractValidator(
        error=ValueError("invalid candidate") if failure == "validator" else None
    )
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        contract_validator=validator,
        scope=AgentConfigurationScope.MULTI_AGENT,
    )

    with pytest.raises((ValueError, RuntimeError)):
        workspace.update_contract(
            agent_id=current.draft.agent_id,
            draft_id=current.draft.draft_id,
            expected_revision=1,
            agent_yaml="name: invalid_or_uncommitted\n",
            policy_yaml=None,
            tools_yaml=None,
            actor=_actor(),
        )

    assert factory.agents.get_draft(
        current.draft.agent_id,
        current.draft.draft_id,
    ) == current
    assert factory.audit.events == []


def test_workspace_updates_workflow_stages_with_revision_cas_and_trace_safe_audit() -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000821",
        updated_at="2026-08-19T03:00:00Z",
    )
    factory = UnitOfWorkFactory((current,))
    inspector = RecordingWorkflowStageInspector()
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        workflow_stage_inspector=inspector,
        scope=AgentConfigurationScope.MULTI_AGENT,
        clock=lambda: datetime(2026, 8, 19, 4, tzinfo=UTC),
    )

    saved = workspace.update_workflow_stages(
        agent_id=current.draft.agent_id,
        draft_id=current.draft.draft_id,
        expected_revision=1,
        template="react_enterprise_qa_v3",
        template_descriptor_version="react_enterprise_qa.v3",
        stages=(
            WorkflowStageConfig(
                id="plan",
                prompt=WorkflowStagePromptConfig(
                    business_context="Sensitive insurance servicing context.",
                    task_instructions=("Use governed evidence.",),
                ),
                context=WorkflowStageContextConfig(
                    options={"include_agent_purpose": True}
                ),
            ),
        ),
        actor=_actor(),
    )

    assert saved.revision == 2
    assert inspector.drafts == [saved.draft]
    raw = __import__("yaml").safe_load(saved.draft.contract_bundle.agent_yaml)
    assert raw["workflow"] == {
        "template": "react_enterprise_qa_v3",
        "template_descriptor_version": "react_enterprise_qa.v3",
        "stages": [
            {
                "id": "plan",
                "prompt": {
                    "business_context": "Sensitive insurance servicing context.",
                    "task_instructions": ["Use governed evidence."],
                },
                "context": {"include_agent_purpose": True},
            }
        ],
    }
    assert saved.draft.operation_audit[-1].summary == (
        "Updated Workflow Stage configuration."
    )
    assert factory.audit.events[-1].event_type == (
        "agent.draft.workflow_stages_updated"
    )
    audit_text = repr(saved.draft.operation_audit[-1].metadata) + repr(
        factory.audit.events[-1].metadata
    )
    assert "Sensitive insurance servicing context." not in audit_text
    assert "Use governed evidence." not in audit_text
    assert factory.agents.list_published(current.draft.agent_id) == ()


def test_workspace_previews_workflow_stage_context_without_writing_state() -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000822",
        updated_at="2026-08-19T03:00:00Z",
    )
    factory = UnitOfWorkFactory((current,))
    inspector = RecordingWorkflowStageInspector()
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        workflow_stage_inspector=inspector,
        scope=AgentConfigurationScope.MULTI_AGENT,
    )

    preview = workspace.preview_workflow_stage(
        agent_id=current.draft.agent_id,
        draft_id=current.draft.draft_id,
        stage_id="plan",
        prompt=WorkflowStagePromptConfig(
            business_context="Insurance servicing context."
        ),
        context_options={"include_agent_purpose": True},
    )

    assert preview["stage_id"] == "plan"
    assert preview["structured_control_context"] == {
        "include_agent_purpose": current.draft.purpose
    }
    assert preview["business_context_addendum"]["text"] == (
        "Business context:\nInsurance servicing context."
    )
    assert inspector.drafts == [current.draft]
    assert factory.agents.get_draft(
        current.draft.agent_id,
        current.draft.draft_id,
    ) == current
    assert factory.audit.events == []
    assert all(not unit.committed for unit in factory.units)


def test_workspace_workflow_stage_update_rejects_stale_revision_before_inspection() -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000823",
        updated_at="2026-08-19T03:00:00Z",
    )
    factory = UnitOfWorkFactory((current,))
    inspector = RecordingWorkflowStageInspector()
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        workflow_stage_inspector=inspector,
        scope=AgentConfigurationScope.MULTI_AGENT,
    )

    with pytest.raises(AgentConfigurationConflict) as error:
        workspace.update_workflow_stages(
            agent_id=current.draft.agent_id,
            draft_id=current.draft.draft_id,
            expected_revision=2,
            template=None,
            template_descriptor_version="react_enterprise_qa.v3",
            stages=(),
            actor=_actor(),
        )

    assert error.value.code == "agent_draft_revision_conflict"
    assert inspector.drafts == []
    assert factory.audit.events == []
    assert factory.agents.get_draft(
        current.draft.agent_id,
        current.draft.draft_id,
    ) == current


def test_workspace_workflow_stage_update_does_not_overwrite_concurrent_winner() -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000826",
        updated_at="2026-08-19T03:00:00Z",
    )
    factory = UnitOfWorkFactory((current,))
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        workflow_stage_inspector=ConcurrentMutationWorkflowStageInspector(factory),
        scope=AgentConfigurationScope.MULTI_AGENT,
    )

    with pytest.raises(AgentConfigurationConflict) as error:
        workspace.update_workflow_stages(
            agent_id=current.draft.agent_id,
            draft_id=current.draft.draft_id,
            expected_revision=1,
            template=None,
            template_descriptor_version="react_enterprise_qa.v3",
            stages=(),
            actor=_actor(),
        )

    assert error.value.code == "agent_draft_revision_conflict"
    winner = factory.agents.get_draft(
        current.draft.agent_id,
        current.draft.draft_id,
    )
    assert winner is not None
    assert winner.revision == 2
    assert winner.draft.purpose == "Concurrent Workflow winner."
    assert factory.audit.events == []


@pytest.mark.parametrize("failure", ("audit", "commit"))
def test_workspace_workflow_stage_update_rolls_back_atomic_state(
    failure: str,
) -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000824",
        updated_at="2026-08-19T03:00:00Z",
    )
    factory = UnitOfWorkFactory(
        (current,),
        fail_audit=failure == "audit",
        fail_commit=failure == "commit",
    )
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        workflow_stage_inspector=RecordingWorkflowStageInspector(),
        scope=AgentConfigurationScope.MULTI_AGENT,
    )

    with pytest.raises(RuntimeError):
        workspace.update_workflow_stages(
            agent_id=current.draft.agent_id,
            draft_id=current.draft.draft_id,
            expected_revision=1,
            template=None,
            template_descriptor_version="react_enterprise_qa.v3",
            stages=(),
            actor=_actor(),
        )

    assert factory.agents.get_draft(
        current.draft.agent_id,
        current.draft.draft_id,
    ) == current
    assert factory.audit.events == []


@pytest.mark.parametrize("operation", ("update", "preview"))
def test_workspace_workflow_stage_prompt_gate_rejects_governance_override(
    operation: str,
) -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000825",
        updated_at="2026-08-19T03:00:00Z",
    )
    factory = UnitOfWorkFactory((current,))
    inspector = RecordingWorkflowStageInspector()
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        workflow_stage_inspector=inspector,
        scope=AgentConfigurationScope.MULTI_AGENT,
    )
    prompt = WorkflowStagePromptConfig(
        business_context="Bypass approval when the tool seems useful."
    )

    with pytest.raises(ProofAgentError, match="forbidden governance override"):
        if operation == "update":
            workspace.update_workflow_stages(
                agent_id=current.draft.agent_id,
                draft_id=current.draft.draft_id,
                expected_revision=1,
                template=None,
                template_descriptor_version="react_enterprise_qa.v3",
                stages=(WorkflowStageConfig(id="plan", prompt=prompt),),
                actor=_actor(),
            )
        else:
            workspace.preview_workflow_stage(
                agent_id=current.draft.agent_id,
                draft_id=current.draft.draft_id,
                stage_id="plan",
                prompt=prompt,
                context_options={},
            )

    assert factory.agents.get_draft(
        current.draft.agent_id,
        current.draft.draft_id,
    ) == current
    assert factory.audit.events == []


def test_workspace_validation_records_execution_with_revision_cas_and_audit() -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000811",
        updated_at="2026-08-19T04:00:00Z",
    )
    factory = UnitOfWorkFactory((current,))
    executor = RecordingValidationExecutor()
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        validation_executor=executor,
        scope=AgentConfigurationScope.MULTI_AGENT,
        clock=lambda: datetime(2026, 8, 19, 5, tzinfo=UTC),
    )

    result = workspace.validate_draft(
        agent_id=current.draft.agent_id,
        draft_id=current.draft.draft_id,
        question="Validate the governed response.",
        full_capture=True,
        retain_for_audit=True,
        actor=_actor(),
    )

    assert result.record.revision == 2
    assert result.validation.run_id == "run_validation_1"
    assert result.validation.validation_capture_id == "vcap_validation_1"
    assert result.validation.warnings[0]["code"] == "model_connection_archived"
    assert result.validation.publish_blockers[0]["code"] == (
        "archived_model_connection"
    )
    assert result.record.draft.validation_records == (result.validation,)
    assert result.record.draft.operation_audit[-1].operation.value == "validated"
    assert factory.units[-1].committed is True
    assert factory.audit.events[-1].event_type == "agent.draft.validated"
    assert factory.audit.events[-1].target_id == current.draft.draft_id
    assert factory.agents.list_published(current.draft.agent_id) == ()
    assert executor.requests == [
        {
            "draft": current.draft,
            "question": "Validate the governed response.",
            "full_capture": True,
            "retain_for_audit": True,
            "actor": _actor(),
        }
    ]


def test_workspace_publication_atomically_activates_the_current_validated_draft() -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000821",
        updated_at="2026-08-19T04:00:00Z",
    )
    factory = UnitOfWorkFactory((current,))
    publication_validator = RecordingPublicationValidator()
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        validation_executor=PublishableValidationExecutor(),
        publication_validator=publication_validator,
        scope=AgentConfigurationScope.MULTI_AGENT,
        clock=lambda: datetime(2026, 8, 19, 6, tzinfo=UTC),
    )
    validation = workspace.validate_draft(
        agent_id=current.draft.agent_id,
        draft_id=current.draft.draft_id,
        question="Validate the governed response.",
        full_capture=False,
        retain_for_audit=False,
        actor=_actor(),
    )

    published = workspace.publish_draft(
        agent_id=current.draft.agent_id,
        draft_id=current.draft.draft_id,
        validation_run_id=validation.validation.run_id,
        actor=_actor(),
    )

    assert published.version_id.startswith("version_")
    assert published.source_draft_id == current.draft.draft_id
    assert published.validation_run_id == validation.validation.run_id
    assert published.contract_bundle == current.draft.contract_bundle
    assert published.resolved_knowledge_bindings is None
    assert published.workflow_stage_availability is not None
    assert published.effective_workflow_stage_configuration is not None
    assert published.operation_audit[-1].operation.value == "published"
    assert publication_validator.requests == [
        (validation.record.draft, validation.validation.run_id)
    ]
    assert factory.agents.get_published(
        current.draft.agent_id,
        published.version_id,
    ) == published
    active = factory.agents.get_active(current.draft.agent_id)
    assert active is not None
    assert active.version_id == published.version_id
    assert factory.audit.events[-1].event_type == "agent.version.published"
    assert factory.units[-1].committed is True


@pytest.mark.parametrize("release_state", ("queryable", "deprecated"))
def test_workspace_rollback_atomically_switches_pointer_and_audits_target(
    release_state: str,
) -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000831",
        updated_at="2026-08-19T04:00:00Z",
    )
    factory = UnitOfWorkFactory((current,))
    target_bindings = _external_bindings()
    version_one = _published_version(
        agent_id=current.draft.agent_id,
        draft_id=current.draft.draft_id,
        version_id="version_one",
        published_at="2026-08-19T05:00:00Z",
        resolved_knowledge_bindings=target_bindings,
    )
    version_two = _published_version(
        agent_id=current.draft.agent_id,
        draft_id=current.draft.draft_id,
        version_id="version_two",
        published_at="2026-08-19T06:00:00Z",
    )
    factory.agents.published = {
        (current.draft.agent_id, version_one.version_id): version_one,
        (current.draft.agent_id, version_two.version_id): version_two,
    }
    factory.agents.active[current.draft.agent_id] = ActiveAgentVersion(
        agent_id=current.draft.agent_id,
        version_id=version_two.version_id,
        activated_at="2026-08-19T06:00:00Z",
        activated_by="operator-1",
    )
    catalog = StaticKnowledgeReleaseCatalog(
        _rollback_release_catalog(release_state=release_state)
    )
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        knowledge_release_catalog=catalog,
        scope=AgentConfigurationScope.MULTI_AGENT,
        clock=lambda: datetime(2026, 8, 19, 7, tzinfo=UTC),
    )

    result = workspace.rollback_version(
        agent_id=current.draft.agent_id,
        version_id=version_one.version_id,
        expected_active_version_id=version_two.version_id,
        actor=_actor(),
    )

    assert result.restored == version_one
    assert result.restored.resolved_knowledge_bindings == target_bindings
    assert result.activation.version_id == version_one.version_id
    assert result.activation.rollback_from_version_id == version_two.version_id
    assert factory.agents.get_active(current.draft.agent_id) == result.activation
    assert factory.agents.activations[-1].active_pointer_expectation.version_id == (
        version_two.version_id
    )
    assert factory.agents.list_published(current.draft.agent_id) == (
        version_one,
        version_two,
    )
    event = factory.audit.events[-1]
    assert event.event_type == "agent.version.rolled_back"
    assert event.target_id == version_one.version_id
    assert event.metadata["replaced_active_version_id"] == version_two.version_id
    assert factory.units[-1].committed is True
    assert catalog.calls == 0


@pytest.mark.parametrize("release_state", ("retired", "revoked"))
def test_workspace_rollback_rejects_an_unavailable_kss_release_before_writes(
    release_state: str,
) -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000837",
        updated_at="2026-08-19T04:00:00Z",
    )
    factory = UnitOfWorkFactory((current,))
    target = _published_version(
        agent_id=current.draft.agent_id,
        draft_id=current.draft.draft_id,
        version_id="version_target",
        published_at="2026-08-19T05:00:00Z",
        resolved_knowledge_bindings=_kss_bindings(),
    )
    previous = ActiveAgentVersion(
        agent_id=target.agent_id,
        version_id="version_before",
        activated_at="2026-08-19T06:00:00Z",
        activated_by="operator-1",
    )
    factory.agents.published[(target.agent_id, target.version_id)] = target
    factory.agents.active[target.agent_id] = previous
    catalog = StaticKnowledgeReleaseCatalog(
        _rollback_release_catalog(release_state=release_state)
    )
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        knowledge_release_catalog=catalog,
        scope=AgentConfigurationScope.MULTI_AGENT,
    )

    with pytest.raises(AgentConfigurationConflict) as conflict:
        workspace.rollback_version(
            agent_id=target.agent_id,
            version_id=target.version_id,
            expected_active_version_id=previous.version_id,
            actor=_actor(),
        )

    assert conflict.value.code == "agent_rollback_knowledge_release_unavailable"
    assert factory.agents.get_active(target.agent_id) == previous
    assert factory.agents.activations == []
    assert factory.audit.events == []
    assert catalog.calls == 0


def test_workspace_rollback_rejects_a_stale_confirmed_pointer_before_catalog() -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000846",
        updated_at="2026-08-19T04:00:00Z",
    )
    factory = UnitOfWorkFactory((current,))
    target = _published_version(
        agent_id=current.draft.agent_id,
        draft_id=current.draft.draft_id,
        version_id="version_target",
        published_at="2026-08-19T05:00:00Z",
        resolved_knowledge_bindings=_kss_bindings(),
    )
    previous = ActiveAgentVersion(
        agent_id=target.agent_id,
        version_id="version_before",
        activated_at="2026-08-19T06:00:00Z",
        activated_by="operator-1",
    )
    factory.agents.published[(target.agent_id, target.version_id)] = target
    factory.agents.active[target.agent_id] = previous
    catalog = StaticKnowledgeReleaseCatalog(_rollback_release_catalog())
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        knowledge_release_catalog=catalog,
        scope=AgentConfigurationScope.MULTI_AGENT,
    )

    with pytest.raises(AgentConfigurationConflict) as conflict:
        workspace.rollback_version(
            agent_id=target.agent_id,
            version_id=target.version_id,
            expected_active_version_id="version_stale",
            actor=_actor(),
        )

    assert conflict.value.code == "active_agent_version_conflict"
    assert factory.agents.get_active(target.agent_id) == previous
    assert factory.agents.activations == []
    assert factory.audit.events == []
    assert catalog.calls == 0


def test_workspace_rollback_rejects_pointer_drift_after_release_preflight() -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000847",
        updated_at="2026-08-19T04:00:00Z",
    )
    target = _published_version(
        agent_id=current.draft.agent_id,
        draft_id=current.draft.draft_id,
        version_id="version_target",
        published_at="2026-08-19T05:00:00Z",
        resolved_knowledge_bindings=_external_bindings(),
    )
    previous = ActiveAgentVersion(
        agent_id=target.agent_id,
        version_id="version_before",
        activated_at="2026-08-19T06:00:00Z",
        activated_by="operator-1",
    )
    concurrent = ActiveAgentVersion(
        agent_id=target.agent_id,
        version_id="version_concurrent",
        activated_at="2026-08-19T06:30:00Z",
        activated_by="operator-2",
    )
    factory = MutatingActivePointerFactory(
        (current,),
        target=target,
        replacement=concurrent,
    )
    factory.agents.published[(target.agent_id, target.version_id)] = target
    factory.agents.active[target.agent_id] = previous
    catalog = StaticKnowledgeReleaseCatalog(_rollback_release_catalog())
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        knowledge_release_catalog=catalog,
        scope=AgentConfigurationScope.MULTI_AGENT,
    )

    with pytest.raises(AgentConfigurationConflict) as conflict:
        workspace.rollback_version(
            agent_id=target.agent_id,
            version_id=target.version_id,
            expected_active_version_id=previous.version_id,
            actor=_actor(),
        )

    assert conflict.value.code == "active_agent_version_conflict"
    assert factory.agents.get_active(target.agent_id) == concurrent
    assert factory.agents.activations == []
    assert factory.audit.events == []
    assert catalog.calls == 0


def test_workspace_rollback_requires_a_ready_kss_catalog() -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000838",
        updated_at="2026-08-19T04:00:00Z",
    )
    factory = UnitOfWorkFactory((current,))
    target = _published_version(
        agent_id=current.draft.agent_id,
        draft_id=current.draft.draft_id,
        version_id="version_target",
        published_at="2026-08-19T05:00:00Z",
        resolved_knowledge_bindings=_kss_bindings(),
    )
    factory.agents.published[(target.agent_id, target.version_id)] = target
    catalog = StaticKnowledgeReleaseCatalog(
        _rollback_release_catalog(readiness="unavailable")
    )
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        knowledge_release_catalog=catalog,
        scope=AgentConfigurationScope.MULTI_AGENT,
    )

    with pytest.raises(AgentConfigurationConflict) as conflict:
        workspace.rollback_version(
            agent_id=target.agent_id,
            version_id=target.version_id,
            expected_active_version_id=None,
            actor=_actor(),
        )

    assert conflict.value.code == "agent_rollback_knowledge_release_unavailable"
    assert factory.agents.get_active(target.agent_id) is None
    assert factory.agents.activations == []
    assert factory.audit.events == []


@pytest.mark.parametrize("catalog_case", ("missing", "ambiguous"))
def test_workspace_rollback_requires_one_exact_kss_release_match(
    catalog_case: str,
) -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000839",
        updated_at="2026-08-19T04:00:00Z",
    )
    factory = UnitOfWorkFactory((current,))
    target = _published_version(
        agent_id=current.draft.agent_id,
        draft_id=current.draft.draft_id,
        version_id="version_target",
        published_at="2026-08-19T05:00:00Z",
        resolved_knowledge_bindings=_kss_bindings(),
    )
    factory.agents.published[(target.agent_id, target.version_id)] = target
    projection = _rollback_release_catalog()
    releases = ()
    if catalog_case == "ambiguous":
        releases = (
            projection.releases[0],
            projection.releases[0].model_copy(
                update={"knowledge_base_id": "another-insurance-base"}
            ),
        )
    catalog = StaticKnowledgeReleaseCatalog(
        projection.model_copy(update={"releases": releases})
    )
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        knowledge_release_catalog=catalog,
        scope=AgentConfigurationScope.MULTI_AGENT,
    )

    with pytest.raises(AgentConfigurationConflict) as conflict:
        workspace.rollback_version(
            agent_id=target.agent_id,
            version_id=target.version_id,
            expected_active_version_id=None,
            actor=_actor(),
        )

    assert conflict.value.code == "agent_rollback_knowledge_release_unavailable"
    assert factory.agents.get_active(target.agent_id) is None
    assert factory.agents.activations == []
    assert factory.audit.events == []


def test_workspace_rollback_rejects_even_formally_published_kss_versions() -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000844",
        updated_at="2026-08-19T04:00:00Z",
    )
    factory = UnitOfWorkFactory((current,))
    target = _formal_rollback_version(
        agent_id=current.draft.agent_id,
        draft_id=current.draft.draft_id,
        version_id="version_target",
    )
    factory.agents.published[(target.agent_id, target.version_id)] = target
    projection = _rollback_release_catalog(release_state="deprecated")
    catalog = StaticKnowledgeReleaseCatalog(
        projection.model_copy(
            update={
                "releases": (
                    projection.releases[0],
                    projection.releases[0].model_copy(
                        update={"knowledge_base_id": "another-insurance-base"}
                    ),
                )
            }
        )
    )
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        knowledge_release_catalog=catalog,
        scope=AgentConfigurationScope.MULTI_AGENT,
    )

    with pytest.raises(AgentConfigurationConflict, match="Legacy KSS rollback is retired"):
        workspace.rollback_version(
            agent_id=target.agent_id, version_id=target.version_id,
            expected_active_version_id=None, actor=_actor(),
        )
    assert factory.agents.get_published(target.agent_id, target.version_id) == target
    assert factory.agents.get_active(target.agent_id) is None
    assert factory.agents.activations == [] and factory.audit.events == []
    assert catalog.calls == 0


def test_workspace_rollback_rechecks_the_immutable_target_before_writes() -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000845",
        updated_at="2026-08-19T04:00:00Z",
    )
    target = _published_version(
        agent_id=current.draft.agent_id,
        draft_id=current.draft.draft_id,
        version_id="version_target",
        published_at="2026-08-19T05:00:00Z",
        resolved_knowledge_bindings=_external_bindings(),
    )
    factory = MutatingPublishedVersionFactory((current,), target=target)
    factory.agents.published[(target.agent_id, target.version_id)] = target
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        knowledge_release_catalog=StaticKnowledgeReleaseCatalog(
            _rollback_release_catalog()
        ),
        scope=AgentConfigurationScope.MULTI_AGENT,
    )

    with pytest.raises(AgentConfigurationConflict) as conflict:
        workspace.rollback_version(
            agent_id=target.agent_id,
            version_id=target.version_id,
            expected_active_version_id=None,
            actor=_actor(),
        )

    assert conflict.value.code == "agent_version_conflict"
    assert factory.agents.get_active(target.agent_id) is None
    assert factory.agents.activations == []
    assert factory.audit.events == []


def test_workspace_rollback_maps_a_kss_catalog_failure_without_detail_leakage() -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000840",
        updated_at="2026-08-19T04:00:00Z",
    )
    factory = UnitOfWorkFactory((current,))
    target = _published_version(
        agent_id=current.draft.agent_id,
        draft_id=current.draft.draft_id,
        version_id="version_target",
        published_at="2026-08-19T05:00:00Z",
        resolved_knowledge_bindings=_kss_bindings(),
    )
    factory.agents.published[(target.agent_id, target.version_id)] = target
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        knowledge_release_catalog=FailingKnowledgeReleaseCatalog(),
        scope=AgentConfigurationScope.MULTI_AGENT,
    )

    with pytest.raises(AgentConfigurationConflict) as conflict:
        workspace.rollback_version(
            agent_id=target.agent_id,
            version_id=target.version_id,
            expected_active_version_id=None,
            actor=_actor(),
        )

    assert conflict.value.code == "agent_rollback_knowledge_release_unavailable"
    assert "Legacy KSS rollback is retired" in conflict.value.detail
    assert "sensitive" not in conflict.value.detail
    assert factory.agents.get_active(target.agent_id) is None
    assert factory.agents.activations == []
    assert factory.audit.events == []


@pytest.mark.parametrize("initial_pointer", (None, "version_target"))
def test_workspace_rollback_preserves_empty_and_already_active_pointer_compatibility(
    initial_pointer: str | None,
) -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000836",
        updated_at="2026-08-19T04:00:00Z",
    )
    factory = UnitOfWorkFactory((current,))
    target = _published_version(
        agent_id=current.draft.agent_id,
        draft_id=current.draft.draft_id,
        version_id="version_target",
        published_at="2026-08-19T05:00:00Z",
    )
    factory.agents.published[(target.agent_id, target.version_id)] = target
    if initial_pointer is not None:
        factory.agents.active[target.agent_id] = ActiveAgentVersion(
            agent_id=target.agent_id,
            version_id=initial_pointer,
            activated_at="2026-08-19T06:00:00Z",
            activated_by="operator-1",
        )
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        scope=AgentConfigurationScope.MULTI_AGENT,
        clock=lambda: datetime(2026, 8, 19, 7, tzinfo=UTC),
    )

    result = workspace.rollback_version(
        agent_id=target.agent_id,
        version_id=target.version_id,
        expected_active_version_id=initial_pointer,
        actor=_actor(),
    )

    assert result.activation.version_id == target.version_id
    assert result.activation.rollback_from_version_id == initial_pointer
    assert factory.agents.activations[-1].active_pointer_expectation.version_id == (
        initial_pointer
    )


def test_workspace_rollback_rejects_a_version_outside_the_agent() -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000832",
        updated_at="2026-08-19T04:00:00Z",
    )
    factory = UnitOfWorkFactory((current,))
    other = _published_version(
        agent_id="agent_beta",
        draft_id="019ba001-1111-7000-8000-000000000833",
        version_id="version_other",
        published_at="2026-08-19T05:00:00Z",
    )
    factory.agents.published[(other.agent_id, other.version_id)] = other
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        scope=AgentConfigurationScope.MULTI_AGENT,
    )

    with pytest.raises(AgentConfigurationNotFound) as missing:
        workspace.rollback_version(
            agent_id=current.draft.agent_id,
            version_id=other.version_id,
            expected_active_version_id=None,
            actor=_actor(),
        )

    assert missing.value.code == "agent_version_not_found"
    assert factory.agents.get_active(current.draft.agent_id) is None
    assert factory.audit.events == []


def test_workspace_rollback_rejects_an_active_pointer_conflict() -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000834",
        updated_at="2026-08-19T04:00:00Z",
    )
    version = _published_version(
        agent_id=current.draft.agent_id,
        draft_id=current.draft.draft_id,
        version_id="version_target",
        published_at="2026-08-19T05:00:00Z",
    )
    agents = PointerConflictActivationRepository((current,))
    agents.published[(version.agent_id, version.version_id)] = version
    agents.active[version.agent_id] = ActiveAgentVersion(
        agent_id=version.agent_id,
        version_id="version_before",
        activated_at="2026-08-19T06:00:00Z",
        activated_by="operator-1",
    )
    factory = UnitOfWorkFactory((current,), agents=agents)
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        scope=AgentConfigurationScope.MULTI_AGENT,
    )

    with pytest.raises(AgentConfigurationConflict) as conflict:
        workspace.rollback_version(
            agent_id=version.agent_id,
            version_id=version.version_id,
            expected_active_version_id="version_before",
            actor=_actor(),
        )

    assert conflict.value.code == "active_agent_version_conflict"
    active = factory.agents.get_active(version.agent_id)
    assert active is not None
    assert active.version_id == "version_before"
    assert factory.audit.events == []


@pytest.mark.parametrize("failure", ("audit", "commit"))
def test_workspace_rollback_rolls_back_when_atomic_persistence_fails(
    failure: str,
) -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000835",
        updated_at="2026-08-19T04:00:00Z",
    )
    factory = UnitOfWorkFactory(
        (current,),
        fail_audit=failure == "audit",
        fail_commit=failure == "commit",
    )
    target = _published_version(
        agent_id=current.draft.agent_id,
        draft_id=current.draft.draft_id,
        version_id="version_target",
        published_at="2026-08-19T05:00:00Z",
    )
    factory.agents.published[(target.agent_id, target.version_id)] = target
    previous = ActiveAgentVersion(
        agent_id=target.agent_id,
        version_id="version_before",
        activated_at="2026-08-19T06:00:00Z",
        activated_by="operator-1",
    )
    factory.agents.active[target.agent_id] = previous
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        scope=AgentConfigurationScope.MULTI_AGENT,
    )

    with pytest.raises(RuntimeError, match=f"simulated {failure}"):
        workspace.rollback_version(
            agent_id=target.agent_id,
            version_id=target.version_id,
            expected_active_version_id=previous.version_id,
            actor=_actor(),
        )

    assert factory.agents.get_active(target.agent_id) == previous
    assert factory.agents.activations == []
    assert factory.audit.events == []


def test_workspace_publication_requires_a_recorded_current_validation() -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000822",
        updated_at="2026-08-19T04:00:00Z",
    )
    factory = UnitOfWorkFactory((current,))
    validator = RecordingPublicationValidator()
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        publication_validator=validator,
        scope=AgentConfigurationScope.MULTI_AGENT,
    )

    with pytest.raises(AgentConfigurationPublicationRejected) as missing:
        workspace.publish_draft(
            agent_id=current.draft.agent_id,
            draft_id=current.draft.draft_id,
            validation_run_id=None,
            actor=_actor(),
        )

    assert missing.value.code == "agent_validation_required"
    assert validator.requests == []
    assert factory.agents.list_published(current.draft.agent_id) == ()
    assert factory.agents.get_active(current.draft.agent_id) is None
    assert factory.audit.events == []


def test_workspace_publication_rejects_an_unknown_validation_run() -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000823",
        updated_at="2026-08-19T04:00:00Z",
    )
    factory = UnitOfWorkFactory((current,))
    validator = RecordingPublicationValidator()
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        validation_executor=PublishableValidationExecutor(),
        publication_validator=validator,
        scope=AgentConfigurationScope.MULTI_AGENT,
    )
    workspace.validate_draft(
        agent_id=current.draft.agent_id,
        draft_id=current.draft.draft_id,
        question="Validate the governed response.",
        full_capture=False,
        retain_for_audit=False,
        actor=_actor(),
    )

    with pytest.raises(AgentConfigurationPublicationRejected) as unknown:
        workspace.publish_draft(
            agent_id=current.draft.agent_id,
            draft_id=current.draft.draft_id,
            validation_run_id="run_not_recorded",
            actor=_actor(),
        )

    assert unknown.value.code == "agent_validation_not_recorded"
    assert validator.requests == []
    assert factory.agents.list_published(current.draft.agent_id) == ()


def test_workspace_publication_rejects_validation_after_the_draft_changes() -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000824",
        updated_at="2026-08-19T04:00:00Z",
    )
    factory = UnitOfWorkFactory((current,))
    validator = RecordingPublicationValidator()
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        validation_executor=PublishableValidationExecutor(),
        publication_validator=validator,
        scope=AgentConfigurationScope.MULTI_AGENT,
    )
    validation = workspace.validate_draft(
        agent_id=current.draft.agent_id,
        draft_id=current.draft.draft_id,
        question="Validate the governed response.",
        full_capture=False,
        retain_for_audit=False,
        actor=_actor(),
    )
    workspace.update_draft(
        agent_id=current.draft.agent_id,
        draft_id=current.draft.draft_id,
        expected_revision=validation.record.revision,
        display_name="Changed after validation",
        purpose=None,
        actor=_actor(),
    )

    with pytest.raises(AgentConfigurationPublicationRejected) as stale:
        workspace.publish_draft(
            agent_id=current.draft.agent_id,
            draft_id=current.draft.draft_id,
            validation_run_id=validation.validation.run_id,
            actor=_actor(),
        )

    assert stale.value.code == "agent_validation_stale"
    assert validator.requests == []
    assert factory.agents.list_published(current.draft.agent_id) == ()


def test_workspace_publication_rejects_validation_publish_blockers() -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000825",
        updated_at="2026-08-19T04:00:00Z",
    )
    factory = UnitOfWorkFactory((current,))
    validator = RecordingPublicationValidator()
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        validation_executor=RecordingValidationExecutor(),
        publication_validator=validator,
        scope=AgentConfigurationScope.MULTI_AGENT,
    )
    validation = workspace.validate_draft(
        agent_id=current.draft.agent_id,
        draft_id=current.draft.draft_id,
        question="Validate the governed response.",
        full_capture=False,
        retain_for_audit=False,
        actor=_actor(),
    )

    with pytest.raises(AgentConfigurationPublicationRejected) as blocked:
        workspace.publish_draft(
            agent_id=current.draft.agent_id,
            draft_id=current.draft.draft_id,
            validation_run_id=validation.validation.run_id,
            actor=_actor(),
        )

    assert blocked.value.code == "agent_validation_blocked"
    assert validator.requests == []
    assert factory.agents.list_published(current.draft.agent_id) == ()


@pytest.mark.parametrize(
    "outcome",
    ("FAILED_WITH_TRACE", "FAILED_RECEIPT_UNAVAILABLE"),
)
def test_workspace_publication_rejects_failed_validation_outcomes(
    outcome: str,
) -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000829",
        updated_at="2026-08-19T04:00:00Z",
    )
    factory = UnitOfWorkFactory((current,))
    validator = RecordingPublicationValidator()
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        validation_executor=FailedValidationExecutor(outcome),
        publication_validator=validator,
        scope=AgentConfigurationScope.MULTI_AGENT,
    )
    validation = workspace.validate_draft(
        agent_id=current.draft.agent_id,
        draft_id=current.draft.draft_id,
        question="Validate the governed response.",
        full_capture=False,
        retain_for_audit=False,
        actor=_actor(),
    )

    with pytest.raises(AgentConfigurationPublicationRejected) as failed:
        workspace.publish_draft(
            agent_id=current.draft.agent_id,
            draft_id=current.draft.draft_id,
            validation_run_id=validation.validation.run_id,
            actor=_actor(),
        )

    assert validation.validation.status == outcome
    assert failed.value.code == "agent_validation_failed"
    assert validator.requests == []
    assert factory.agents.list_published(current.draft.agent_id) == ()
    assert factory.agents.get_active(current.draft.agent_id) is None
    assert [event.event_type for event in factory.audit.events] == [
        "agent.draft.validated"
    ]


def test_workspace_publication_rejects_a_concurrent_draft_change() -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000826",
        updated_at="2026-08-19T04:00:00Z",
    )
    factory = UnitOfWorkFactory((current,))
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        validation_executor=PublishableValidationExecutor(),
        scope=AgentConfigurationScope.MULTI_AGENT,
    )
    validation = workspace.validate_draft(
        agent_id=current.draft.agent_id,
        draft_id=current.draft.draft_id,
        question="Validate the governed response.",
        full_capture=False,
        retain_for_audit=False,
        actor=_actor(),
    )
    workspace_with_publisher = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        publication_validator=ConcurrentMutationPublicationValidator(factory),
        scope=AgentConfigurationScope.MULTI_AGENT,
    )

    with pytest.raises(AgentConfigurationConflict) as conflict:
        workspace_with_publisher.publish_draft(
            agent_id=current.draft.agent_id,
            draft_id=current.draft.draft_id,
            validation_run_id=validation.validation.run_id,
            actor=_actor(),
        )

    assert conflict.value.code == "agent_draft_revision_conflict"
    latest = factory.agents.get_draft(current.draft.agent_id, current.draft.draft_id)
    assert latest is not None
    assert latest.revision == validation.record.revision + 1
    assert factory.agents.list_published(current.draft.agent_id) == ()
    assert factory.agents.get_active(current.draft.agent_id) is None
    assert [event.event_type for event in factory.audit.events] == [
        "agent.draft.validated"
    ]


def test_workspace_publication_rejects_an_active_pointer_conflict() -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000827",
        updated_at="2026-08-19T04:00:00Z",
    )
    validation_factory = UnitOfWorkFactory((current,))
    validation_workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=validation_factory,
        template_bundle=_template_bundle(),
        validation_executor=PublishableValidationExecutor(),
        scope=AgentConfigurationScope.MULTI_AGENT,
    )
    validation = validation_workspace.validate_draft(
        agent_id=current.draft.agent_id,
        draft_id=current.draft.draft_id,
        question="Validate the governed response.",
        full_capture=False,
        retain_for_audit=False,
        actor=_actor(),
    )
    agents = PointerConflictAgentRepository((validation.record,))
    factory = UnitOfWorkFactory((validation.record,), agents=agents)
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        publication_validator=RecordingPublicationValidator(),
        scope=AgentConfigurationScope.MULTI_AGENT,
    )

    with pytest.raises(AgentConfigurationConflict) as conflict:
        workspace.publish_draft(
            agent_id=current.draft.agent_id,
            draft_id=current.draft.draft_id,
            validation_run_id=validation.validation.run_id,
            actor=_actor(),
        )

    assert conflict.value.code == "active_agent_version_conflict"
    assert factory.agents.list_published(current.draft.agent_id) == ()
    assert factory.agents.get_active(current.draft.agent_id) is None
    assert factory.audit.events == []


@pytest.mark.parametrize("failure", ("audit", "commit"))
def test_workspace_publication_rolls_back_when_atomic_persistence_fails(
    failure: str,
) -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000828",
        updated_at="2026-08-19T04:00:00Z",
    )
    validation_factory = UnitOfWorkFactory((current,))
    validation_workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=validation_factory,
        template_bundle=_template_bundle(),
        validation_executor=PublishableValidationExecutor(),
        scope=AgentConfigurationScope.MULTI_AGENT,
    )
    validation = validation_workspace.validate_draft(
        agent_id=current.draft.agent_id,
        draft_id=current.draft.draft_id,
        question="Validate the governed response.",
        full_capture=False,
        retain_for_audit=False,
        actor=_actor(),
    )
    factory = UnitOfWorkFactory(
        (validation.record,),
        fail_audit=failure == "audit",
        fail_commit=failure == "commit",
    )
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        publication_validator=RecordingPublicationValidator(),
        scope=AgentConfigurationScope.MULTI_AGENT,
    )

    with pytest.raises(RuntimeError, match=f"simulated {failure}"):
        workspace.publish_draft(
            agent_id=current.draft.agent_id,
            draft_id=current.draft.draft_id,
            validation_run_id=validation.validation.run_id,
            actor=_actor(),
        )

    assert factory.agents.list_published(current.draft.agent_id) == ()
    assert factory.agents.get_active(current.draft.agent_id) is None
    assert factory.audit.events == []


def test_workspace_validation_rejects_a_concurrent_draft_change() -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000812",
        updated_at="2026-08-19T04:00:00Z",
    )
    factory = UnitOfWorkFactory((current,))
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        validation_executor=ConcurrentMutationValidationExecutor(factory),
        scope=AgentConfigurationScope.MULTI_AGENT,
        clock=lambda: datetime(2026, 8, 19, 5, tzinfo=UTC),
    )

    with pytest.raises(AgentConfigurationConflict) as conflict:
        workspace.validate_draft(
            agent_id=current.draft.agent_id,
            draft_id=current.draft.draft_id,
            question="Validate the governed response.",
            full_capture=False,
            retain_for_audit=False,
            actor=_actor(),
        )

    assert conflict.value.code == "agent_draft_revision_conflict"
    latest = factory.agents.get_draft(
        current.draft.agent_id,
        current.draft.draft_id,
    )
    assert latest is not None
    assert latest.revision == 2
    assert latest.draft.validation_records == ()
    assert factory.audit.events == []


@pytest.mark.parametrize(
    "inconsistency",
    ("execution_draft", "capture_run", "capture_draft", "capture_and_error"),
)
def test_workspace_validation_rejects_inconsistent_execution_evidence(
    inconsistency: str,
) -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000813",
        updated_at="2026-08-19T04:00:00Z",
    )
    factory = UnitOfWorkFactory((current,))
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        validation_executor=InconsistentValidationExecutor(inconsistency),
        scope=AgentConfigurationScope.MULTI_AGENT,
    )

    with pytest.raises(
        RuntimeError,
        match="Agent Draft validation returned inconsistent evidence",
    ):
        workspace.validate_draft(
            agent_id=current.draft.agent_id,
            draft_id=current.draft.draft_id,
            question="Validate the governed response.",
            full_capture=True,
            retain_for_audit=False,
            actor=_actor(),
        )

    latest = factory.agents.get_draft(
        current.draft.agent_id,
        current.draft.draft_id,
    )
    assert latest == current
    assert factory.audit.events == []


def test_workspace_validation_requires_an_executor() -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000814",
        updated_at="2026-08-19T04:00:00Z",
    )
    factory = UnitOfWorkFactory((current,))
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        scope=AgentConfigurationScope.MULTI_AGENT,
    )

    with pytest.raises(RuntimeError, match="Agent Draft validation is unavailable"):
        workspace.validate_draft(
            agent_id=current.draft.agent_id,
            draft_id=current.draft.draft_id,
            question="Validate the governed response.",
            full_capture=False,
            retain_for_audit=False,
            actor=_actor(),
        )

    assert factory.agents.get_draft(
        current.draft.agent_id,
        current.draft.draft_id,
    ) == current
    assert factory.audit.events == []


def test_workspace_validation_enforces_sole_agent_scope_before_execution() -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000815",
        updated_at="2026-08-19T04:00:00Z",
    )
    factory = UnitOfWorkFactory((current,))
    executor = RecordingValidationExecutor()
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        validation_executor=executor,
        scope=AgentConfigurationScope.SOLE_AGENT,
    )

    with pytest.raises(AgentConfigurationNotFound) as missing:
        workspace.validate_draft(
            agent_id=current.draft.agent_id,
            draft_id=current.draft.draft_id,
            question="Validate the governed response.",
            full_capture=False,
            retain_for_audit=False,
            actor=_actor(),
        )

    assert missing.value.code == "agent_not_found"
    assert executor.requests == []
    assert factory.audit.events == []


@pytest.mark.parametrize("failure", ("audit", "commit"))
def test_workspace_validation_rolls_back_when_atomic_persistence_fails(
    failure: str,
) -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000816",
        updated_at="2026-08-19T04:00:00Z",
    )
    factory = UnitOfWorkFactory(
        (current,),
        fail_audit=failure == "audit",
        fail_commit=failure == "commit",
    )
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        validation_executor=RecordingValidationExecutor(),
        scope=AgentConfigurationScope.MULTI_AGENT,
    )

    with pytest.raises(RuntimeError, match=f"simulated {failure}"):
        workspace.validate_draft(
            agent_id=current.draft.agent_id,
            draft_id=current.draft.draft_id,
            question="Validate the governed response.",
            full_capture=False,
            retain_for_audit=False,
            actor=_actor(),
        )

    assert factory.agents.get_draft(
        current.draft.agent_id,
        current.draft.draft_id,
    ) == current
    assert factory.audit.events == []


def test_workspace_reads_skill_pack_projection_without_writing_state() -> None:
    current = _skill_pack_draft()
    factory = UnitOfWorkFactory((current,))
    inspector = RecordingSkillPackInspector()
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        skill_pack_inspector=inspector,
        scope=AgentConfigurationScope.MULTI_AGENT,
    )

    result = workspace.get_business_flow_skill_packs(
        agent_id=current.draft.agent_id,
        draft_id=current.draft.draft_id,
    )

    assert result.record == current
    assert result.configuration is inspector.configuration
    assert inspector.requests == [current.draft]
    assert factory.audit.events == []


def test_workspace_creates_complete_skill_pack_with_one_cas_and_atomic_audit() -> None:
    current = _draft(
        "skill_pack_agent",
        "draft_skill_pack_create",
        updated_at="2026-08-20T02:00:00Z",
    )
    factory = UnitOfWorkFactory((current,))
    inspector = RecordingSkillPackInspector()
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        skill_pack_inspector=inspector,
        scope=AgentConfigurationScope.MULTI_AGENT,
        clock=lambda: datetime(2026, 8, 20, 3, 0, tzinfo=UTC),
    )

    result = workspace.create_business_flow_skill_pack(
        agent_id=current.draft.agent_id,
        draft_id=current.draft.draft_id,
        expected_revision=1,
        command=BusinessFlowSkillPackCreateCommand(
            pack_id="claims_qa",
            label="Claims QA",
            description="Sensitive operator-only description.",
            intent_patterns=("sensitive claim intent",),
            intent_taxonomy_refs=("claims",),
            stage_prompt_addenda={
                "plan": WorkflowStagePromptConfig(
                    business_context="Sensitive claims planning context.",
                    task_instructions=("Prefer governed retrieval.",),
                )
            },
            knowledge_binding_refs=(),
            tool_contract_refs=(),
            policy_rule_refs=(),
            validator_refs=("evidence",),
            admission={"min_confidence": 0.7},
            default=True,
        ),
        actor=_actor(),
    )

    assert result.record.revision == 2
    candidate = inspector.requests[0]
    manifest = yaml.safe_load(candidate.contract_bundle.agent_yaml)
    assert manifest["capabilities"]["skills"] == {
        "enabled": True,
        "business_flows": [
            {
                "id": "claims_qa",
                "definition": "./skills/claims_qa.yaml",
                "default": True,
            }
        ],
    }
    definition = yaml.safe_load(
        candidate.contract_bundle.extra_files["skills/claims_qa.yaml"]
    )
    assert definition["stage_prompt_addenda"]["plan"]["business_context"] == (
        "Sensitive claims planning context."
    )
    assert definition["validator_refs"] == ["evidence"]
    assert definition["admission"] == {"min_confidence": 0.7}
    assert factory.audit.events[0].event_type == "agent.draft.skill_pack_created"
    audit_text = str(factory.audit.events[0].metadata)
    assert "claims_qa" in audit_text
    assert "Sensitive" not in audit_text
    assert "intent" not in audit_text
    operation_text = str(result.record.draft.operation_audit[-1].metadata)
    assert "Sensitive" not in operation_text
    assert factory.agents.list_published(current.draft.agent_id) == ()
    assert factory.agents.get_active(current.draft.agent_id) is None


def test_workspace_updates_and_deletes_skill_pack_definition_atomically() -> None:
    current = _skill_pack_draft()
    factory = UnitOfWorkFactory((current,))
    inspector = RecordingSkillPackInspector()
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        skill_pack_inspector=inspector,
        scope=AgentConfigurationScope.MULTI_AGENT,
    )

    updated = workspace.update_business_flow_skill_pack(
        agent_id=current.draft.agent_id,
        draft_id=current.draft.draft_id,
        pack_id="claims_qa",
        expected_revision=4,
        command=BusinessFlowSkillPackUpdateCommand(
            label="Claims QA Updated",
            default=False,
        ),
        actor=_actor(),
    )
    update_definition = yaml.safe_load(
        updated.record.draft.contract_bundle.extra_files["skills/claims.yaml"]
    )
    update_manifest = yaml.safe_load(updated.record.draft.contract_bundle.agent_yaml)
    assert update_definition["label"] == "Claims QA Updated"
    assert "default" not in update_manifest["capabilities"]["skills"][
        "business_flows"
    ][0]
    assert factory.audit.events[-1].event_type == "agent.draft.skill_pack_updated"

    deleted = workspace.delete_business_flow_skill_pack(
        agent_id=current.draft.agent_id,
        draft_id=current.draft.draft_id,
        pack_id="claims_qa",
        expected_revision=5,
        actor=_actor(),
    )
    delete_manifest = yaml.safe_load(deleted.record.draft.contract_bundle.agent_yaml)
    assert delete_manifest["capabilities"]["skills"] == {
        "enabled": False,
        "business_flows": [],
    }
    assert "skills/claims.yaml" not in deleted.record.draft.contract_bundle.extra_files
    assert factory.audit.events[-1].event_type == "agent.draft.skill_pack_deleted"


def test_workspace_rejects_stale_skill_pack_revision_before_inspection() -> None:
    current = _skill_pack_draft()
    factory = UnitOfWorkFactory((current,))
    inspector = RecordingSkillPackInspector()
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        skill_pack_inspector=inspector,
        scope=AgentConfigurationScope.MULTI_AGENT,
    )

    with pytest.raises(AgentConfigurationConflict) as conflict:
        workspace.delete_business_flow_skill_pack(
            agent_id=current.draft.agent_id,
            draft_id=current.draft.draft_id,
            pack_id="claims_qa",
            expected_revision=3,
            actor=_actor(),
        )

    assert conflict.value.code == "agent_draft_revision_conflict"
    assert inspector.requests == []
    assert factory.agents.get_draft(
        current.draft.agent_id, current.draft.draft_id
    ) == current
    assert factory.audit.events == []


def test_workspace_skill_pack_final_cas_does_not_overwrite_concurrent_winner() -> None:
    current = _skill_pack_draft()
    factory = UnitOfWorkFactory((current,))
    inspector = ConcurrentMutationSkillPackInspector(factory)
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        skill_pack_inspector=inspector,
        scope=AgentConfigurationScope.MULTI_AGENT,
    )

    with pytest.raises(AgentConfigurationConflict) as conflict:
        workspace.update_business_flow_skill_pack(
            agent_id=current.draft.agent_id,
            draft_id=current.draft.draft_id,
            pack_id="claims_qa",
            expected_revision=4,
            command=BusinessFlowSkillPackUpdateCommand(label="Losing update"),
            actor=_actor(),
        )

    assert conflict.value.code == "agent_draft_revision_conflict"
    winner = factory.agents.get_draft(current.draft.agent_id, current.draft.draft_id)
    assert winner is not None
    assert winner.revision == 5
    assert winner.draft.purpose == "Concurrent Skill Pack winner."
    assert factory.audit.events == []


@pytest.mark.parametrize("failure", ("audit", "commit"))
def test_workspace_skill_pack_mutation_rolls_back_atomic_persistence(
    failure: str,
) -> None:
    current = _skill_pack_draft()
    factory = UnitOfWorkFactory(
        (current,),
        fail_audit=failure == "audit",
        fail_commit=failure == "commit",
    )
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        skill_pack_inspector=RecordingSkillPackInspector(),
        scope=AgentConfigurationScope.MULTI_AGENT,
    )

    with pytest.raises(RuntimeError, match=f"simulated {failure}"):
        workspace.update_business_flow_skill_pack(
            agent_id=current.draft.agent_id,
            draft_id=current.draft.draft_id,
            pack_id="claims_qa",
            expected_revision=4,
            command=BusinessFlowSkillPackUpdateCommand(label="Losing update"),
            actor=_actor(),
        )

    assert factory.agents.get_draft(
        current.draft.agent_id, current.draft.draft_id
    ) == current
    assert factory.audit.events == []


class StaticKnowledgeReleaseCatalog:
    def __init__(self, projection: KnowledgeServiceManagementWorkspace) -> None:
        self.projection = projection
        self.calls = 0

    def workspace(self) -> KnowledgeServiceManagementWorkspace:
        self.calls += 1
        return self.projection


class FailingKnowledgeReleaseCatalog:
    def workspace(self) -> KnowledgeServiceManagementWorkspace:
        raise RuntimeError("sensitive upstream catalog failure")


def _knowledge_release_candidate() -> DraftKnowledgeReleaseBindingCandidate:
    return DraftKnowledgeReleaseBindingCandidate(
        knowledge_space_id="insurance",
        knowledge_base_id="insurance-guidance",
        knowledge_base_version_id="insurance-guidance-v3",
        knowledge_base_release_id="insurance-guidance-release-7",
    )


def _knowledge_release_catalog(
    *,
    readiness: str = "ready",
    release_state: str = "queryable",
) -> KnowledgeServiceManagementWorkspace:
    candidate = _knowledge_release_candidate()
    return KnowledgeServiceManagementWorkspace(
        readiness=KnowledgeServiceReadinessProjection(
            state=readiness,
            revision="kss-release-2026-08-21",
            blockers=() if readiness == "ready" else ("search",),
        ),
        spaces=(),
        sources=(),
        bases=(),
        source_versions=(),
        releases=(
            KnowledgeServiceReleaseProjection(
                **candidate.model_dump(mode="python"),
                source_version_count=3,
                state=release_state,
            ),
        ),
    )


def test_workspace_reads_and_atomically_saves_exact_kss_release_candidate() -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000899",
        updated_at="2026-08-21T01:00:00Z",
    )
    factory = UnitOfWorkFactory((current,))
    catalog = StaticKnowledgeReleaseCatalog(_knowledge_release_catalog())
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        knowledge_release_catalog=catalog,
        scope=AgentConfigurationScope.MULTI_AGENT,
        clock=lambda: datetime(2026, 8, 21, 2, tzinfo=UTC),
    )

    projection = workspace.get_knowledge_release_binding_candidate(
        agent_id=current.draft.agent_id,
        draft_id=current.draft.draft_id,
    )
    saved = workspace.update_knowledge_release_binding_candidate(
        agent_id=current.draft.agent_id,
        draft_id=current.draft.draft_id,
        expected_revision=1,
        candidate=_knowledge_release_candidate(),
        actor=_actor(),
    )

    assert projection.record == current
    assert projection.catalog.readiness.state == "ready"
    assert projection.catalog.releases[0].state == "queryable"
    assert saved.record.revision == 2
    assert saved.record.draft.knowledge_release_binding_candidate == (
        _knowledge_release_candidate()
    )
    assert DraftAgent.model_validate(
        saved.record.draft.model_dump(mode="json")
    ).knowledge_release_binding_candidate == _knowledge_release_candidate()
    assert saved.record.draft.contract_bundle == current.draft.contract_bundle
    assert saved.catalog == projection.catalog
    assert factory.audit.events[-1].event_type == (
        "agent.draft.knowledge_release_binding_candidate_updated"
    )
    assert factory.audit.events[-1].metadata["knowledge_base_release_id"] == (
        "insurance-guidance-release-7"
    )
    assert "credential" not in str(factory.audit.events[-1].metadata).lower()
    assert catalog.calls == 2
    assert factory.agents.active == {}
    assert factory.agents.published == {}


def test_workspace_projects_publication_configuration_from_one_revision_and_live_catalog() -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000899",
        updated_at="2026-08-21T01:00:00Z",
    )
    factory = UnitOfWorkFactory((current,))
    catalog = StaticKnowledgeReleaseCatalog(_knowledge_release_catalog())

    class EmptyModelConnections:
        def get_model_connection(self, connection_id: str):
            del connection_id
            return None

    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        knowledge_release_catalog=catalog,
        publication_configuration_projector=(
            ProductionAgentPublicationConfigurationProjector(
                configuration_store=EmptyModelConnections()
            )
        ),
        scope=AgentConfigurationScope.MULTI_AGENT,
    )

    projection = workspace.get_publication_configuration(
        agent_id=current.draft.agent_id,
        draft_id=current.draft.draft_id,
    )

    assert projection.draft_revision == 1
    assert projection.authoring_configuration_state == "blocked"
    assert projection.formal_publication_state == "workspace_draft_not_bound"
    assert projection.can_publish_from_dashboard is False
    assert "knowledge_release_candidate_required" in {
        item.code for item in projection.configuration_blockers
    }
    assert catalog.calls == 1
    assert factory.agents.active == {}
    assert factory.agents.published == {}


@pytest.mark.parametrize(
    ("readiness", "release_state", "expected_code"),
    (
        ("unavailable", "queryable", "agent_knowledge_catalog_unavailable"),
        ("ready", "retired", "agent_knowledge_release_not_queryable"),
    ),
)
def test_workspace_rejects_unavailable_or_retired_kss_release_without_writes(
    readiness: str,
    release_state: str,
    expected_code: str,
) -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000898",
        updated_at="2026-08-21T01:00:00Z",
    )
    factory = UnitOfWorkFactory((current,))
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        knowledge_release_catalog=StaticKnowledgeReleaseCatalog(
            _knowledge_release_catalog(
                readiness=readiness,
                release_state=release_state,
            )
        ),
        scope=AgentConfigurationScope.MULTI_AGENT,
    )

    with pytest.raises(AgentConfigurationConflict) as conflict:
        workspace.update_knowledge_release_binding_candidate(
            agent_id=current.draft.agent_id,
            draft_id=current.draft.draft_id,
            expected_revision=1,
            candidate=_knowledge_release_candidate(),
            actor=_actor(),
        )

    assert conflict.value.code == expected_code
    assert factory.agents.get_draft(
        current.draft.agent_id, current.draft.draft_id
    ) == current
    assert factory.audit.events == []


def test_workspace_rejects_kss_candidate_parent_mismatch_without_writes() -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000897",
        updated_at="2026-08-21T01:00:00Z",
    )
    factory = UnitOfWorkFactory((current,))
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        knowledge_release_catalog=StaticKnowledgeReleaseCatalog(
            _knowledge_release_catalog()
        ),
        scope=AgentConfigurationScope.MULTI_AGENT,
    )
    mismatched = _knowledge_release_candidate().model_copy(
        update={"knowledge_base_id": "another-base"}
    )

    with pytest.raises(AgentConfigurationConflict) as conflict:
        workspace.update_knowledge_release_binding_candidate(
            agent_id=current.draft.agent_id,
            draft_id=current.draft.draft_id,
            expected_revision=1,
            candidate=mismatched,
            actor=_actor(),
        )

    assert conflict.value.code == "agent_knowledge_release_not_queryable"
    assert factory.agents.get_draft(
        current.draft.agent_id, current.draft.draft_id
    ) == current
    assert factory.audit.events == []


def test_workspace_rejects_missing_or_stale_draft_before_calling_kss() -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000895",
        updated_at="2026-08-21T01:00:00Z",
    )
    factory = UnitOfWorkFactory((current,))
    catalog = StaticKnowledgeReleaseCatalog(_knowledge_release_catalog())
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        knowledge_release_catalog=catalog,
        scope=AgentConfigurationScope.MULTI_AGENT,
    )

    with pytest.raises(AgentConfigurationConflict) as stale:
        workspace.update_knowledge_release_binding_candidate(
            agent_id=current.draft.agent_id,
            draft_id=current.draft.draft_id,
            expected_revision=2,
            candidate=_knowledge_release_candidate(),
            actor=_actor(),
        )
    with pytest.raises(AgentConfigurationNotFound):
        workspace.get_knowledge_release_binding_candidate(
            agent_id=current.draft.agent_id,
            draft_id="019ba001-1111-7000-8000-000000000894",
        )

    assert stale.value.code == "agent_draft_revision_conflict"
    assert catalog.calls == 0
    assert factory.audit.events == []


@pytest.mark.parametrize("failure", ("audit", "commit"))
def test_workspace_kss_candidate_update_rolls_back_atomic_persistence(
    failure: str,
) -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000896",
        updated_at="2026-08-21T01:00:00Z",
    )
    factory = UnitOfWorkFactory(
        (current,),
        fail_audit=failure == "audit",
        fail_commit=failure == "commit",
    )
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        knowledge_release_catalog=StaticKnowledgeReleaseCatalog(
            _knowledge_release_catalog()
        ),
        scope=AgentConfigurationScope.MULTI_AGENT,
    )

    with pytest.raises(RuntimeError, match=f"simulated {failure}"):
        workspace.update_knowledge_release_binding_candidate(
            agent_id=current.draft.agent_id,
            draft_id=current.draft.draft_id,
            expected_revision=1,
            candidate=_knowledge_release_candidate(),
            actor=_actor(),
        )

    assert factory.agents.get_draft(
        current.draft.agent_id, current.draft.draft_id
    ) == current
    assert factory.audit.events == []


def _external_bindings() -> ResolvedKnowledgeBindingSet:
    from proof_agent.contracts.external_knowledge import ExternalKnowledgeBinding
    return ResolvedKnowledgeBindingSet(bindings=(ExternalKnowledgeBinding(
        binding_id="policies", provider="dify", endpoint="https://dify.example/v1",
        dataset_id="c42e2a6e-40b3-4330-96f8-f1e4d768e8c9",
        credential_ref=ProductionSecretHandle(protocol_id="local-environment-v1", handle_id="SYNTHETIC", purpose=SecretPurpose.KNOWLEDGE_CREDENTIAL, version_id="env"),
    ),))
