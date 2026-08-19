from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import TracebackType

import pytest

from proof_agent.contracts import (
    ActiveAgentVersion,
    AgentActivationRecord,
    AgentDraftRecord,
    AgentPublicationRecord,
    AgentValidationRecord,
    AuditActorFacts,
    AuditMetadataRecord,
    ContractBundle,
    DraftAgent,
    ProductionSecretHandle,
    PublishedAgentVersion,
    ResolvedKnowledgeBindingSet,
    ResolvedKnowledgeSourceServiceBinding,
    SecretPurpose,
    SensitiveValidationCaptureArtifact,
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
)


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


def _actor() -> AuditActorFacts:
    return AuditActorFacts(
        subject="operator-1",
        identity_provider="local-development",
        session_id="session-1",
        permissions=("agent.edit",),
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


def test_workspace_rollback_atomically_switches_pointer_and_audits_target() -> None:
    current = _draft(
        "agent_alpha",
        "019ba001-1111-7000-8000-000000000831",
        updated_at="2026-08-19T04:00:00Z",
    )
    factory = UnitOfWorkFactory((current,))
    target_bindings = _kss_bindings()
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
    workspace = AgentConfigurationWorkspace(
        unit_of_work_factory=factory,
        template_bundle=_template_bundle(),
        scope=AgentConfigurationScope.MULTI_AGENT,
        clock=lambda: datetime(2026, 8, 19, 7, tzinfo=UTC),
    )

    result = workspace.rollback_version(
        agent_id=current.draft.agent_id,
        version_id=version_one.version_id,
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
