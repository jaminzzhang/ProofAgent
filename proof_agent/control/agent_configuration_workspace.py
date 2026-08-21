"""Deep application module for the Agent Configuration Workspace."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
import hashlib
from importlib.metadata import PackageNotFoundError, distribution
import json
from pathlib import Path
from typing import Any, Protocol
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import yaml  # type: ignore[import-untyped]

from proof_agent.configuration.importer import build_agent_package_contract_bundle
from proof_agent.contracts import (
    ActiveAgentPointerExpectation,
    ActiveAgentVersion,
    AgentActivationRecord,
    AgentDraftRecord,
    AgentPublicationRecord,
    AgentValidationRecord,
    AuditActorFacts,
    AuditCategory,
    AuditMetadataRecord,
    AuditOutcome,
    ConfigurationOperation,
    ConfigurationOperationAudit,
    ContractBundle,
    DraftKnowledgeReleaseBindingCandidate,
    DraftAgent,
    PersistenceConflictError,
    PersistenceNotFoundError,
    PersistencePointerConflictError,
    PublishedAgentVersion,
    PublishedWorkflowStageConfigurationSnapshot,
    ResolvedKnowledgeBindingSet,
    SensitiveValidationCaptureArtifact,
    WorkflowStageConfig,
    WorkflowStageConfigurationRuntimeSource,
    WorkflowStageConfigurationRuntimeSourceType,
    WorkflowStagePromptConfig,
)
from proof_agent.contracts.ports import ConfigurationUnitOfWork
from proof_agent.contracts.knowledge_service_management import (
    KnowledgeServiceManagementWorkspace,
)
from proof_agent.control.production_agent_publication import SOLE_PRODUCTION_AGENT_ID
from proof_agent.control.agent_configuration_skill_packs import (
    BusinessFlowSkillPackConfiguration,
    BusinessFlowSkillPackCreateCommand,
    BusinessFlowSkillPackUpdateCommand,
    create_business_flow_skill_pack_bundle,
    delete_business_flow_skill_pack_bundle,
    update_business_flow_skill_pack_bundle,
)
from proof_agent.control.workflow.stage_configuration import (
    resolve_workflow_stage_runtime_configuration,
)
from proof_agent.control.workflow.stage_context import build_workflow_stage_context_preview
from proof_agent.control.workflow.stage_validation import (
    MAX_WORKFLOW_STAGE_TOTAL_PROMPT_CHARS,
    validate_workflow_stage_prompt_config,
)
from proof_agent.control.workflow.templates import resolve_workflow_template
from proof_agent.errors import ProofAgentError


_EXPECTED_WORKFLOW_TEMPLATE = "react_enterprise_qa_v3"
_CREATE_FINGERPRINT_SCHEMA = "proofagent.production-agent-create.v1"
_DRAFT_ID = str(
    uuid5(
        NAMESPACE_URL,
        f"proofagent:{_CREATE_FINGERPRINT_SCHEMA}:{SOLE_PRODUCTION_AGENT_ID}",
    )
)
_SERVER_TEMPLATE_MANIFEST = Path(
    "examples/agent_management_insurance_specialist/agent.yaml"
)


@dataclass(frozen=True)
class AgentConfigurationDraftMutation:
    """A revisioned Draft result plus whether a create command was replayed."""

    record: AgentDraftRecord
    replayed: bool = False


@dataclass(frozen=True)
class AgentConfigurationSummary:
    """Dashboard-safe summary computed inside the Workspace module."""

    agent_id: str
    display_name: str
    purpose: str
    draft_count: int
    latest_draft_id: str | None
    version_count: int
    active_version_id: str | None
    updated_at: str | None


@dataclass(frozen=True)
class AgentConfigurationInventory:
    """Current Agent inventory and initialization capability."""

    agents: tuple[AgentConfigurationSummary, ...]
    can_create: bool


@dataclass(frozen=True)
class AgentConfigurationVersions:
    """Published history and active pointer for one Agent."""

    versions: tuple[PublishedAgentVersion, ...]
    active_version_id: str | None


@dataclass(frozen=True)
class AgentConfigurationRollback:
    """The activation command result and exact immutable version it restored."""

    activation: ActiveAgentVersion
    restored: PublishedAgentVersion

    def __post_init__(self) -> None:
        if (
            self.activation.agent_id != self.restored.agent_id
            or self.activation.version_id != self.restored.version_id
        ):
            raise ValueError(
                "rollback activation must identify the restored Agent Version"
            )


@dataclass(frozen=True)
class AgentConfigurationValidationCaptureError:
    """Stable trace-safe reason why an optional Full Capture was not stored."""

    code: str
    message: str
    retryable: bool


@dataclass(frozen=True)
class AgentConfigurationValidationExecution:
    """Trace-safe evidence returned by one Draft validation adapter."""

    run_id: str
    outcome: str
    run_purpose: str
    agent_id: str
    draft_id: str
    summary: str
    trace_events: tuple[Mapping[str, Any], ...] = ()
    validation_capture: SensitiveValidationCaptureArtifact | None = None
    capture_error: AgentConfigurationValidationCaptureError | None = None
    resolved_knowledge_bindings: ResolvedKnowledgeBindingSet | None = None


@dataclass(frozen=True)
class AgentConfigurationValidationResult:
    """Revisioned Draft state and execution evidence from validation."""

    record: AgentDraftRecord
    validation: AgentValidationRecord
    execution: AgentConfigurationValidationExecution


@dataclass(frozen=True)
class AgentConfigurationWorkflowStageDraftFacts:
    """Adapter-neutral manifest facts used by Workflow Stage configuration."""

    template_name: str
    agent_purpose: str
    tool_contract_reference: str
    policy_reference: str
    response_disclosure_policy: Mapping[str, Any]
    memory_scope: Mapping[str, Any]


@dataclass(frozen=True)
class AgentConfigurationSkillPackResult:
    """Revisioned Draft state and its Skill Pack configuration projection."""

    record: AgentDraftRecord
    configuration: BusinessFlowSkillPackConfiguration


@dataclass(frozen=True)
class AgentConfigurationKnowledgeBindingResult:
    """Revisioned Draft state and live KSS authoring catalog projection."""

    record: AgentDraftRecord
    catalog: KnowledgeServiceManagementWorkspace


class AgentConfigurationValidationExecutor(Protocol):
    """Execute one Draft without owning lifecycle persistence rules."""

    def validate(
        self,
        *,
        draft: DraftAgent,
        question: str,
        full_capture: bool,
        retain_for_audit: bool,
        actor: AuditActorFacts,
    ) -> AgentConfigurationValidationExecution: ...


class AgentConfigurationPublicationValidator(Protocol):
    """Validate adapter-owned package and live-asset publication constraints."""

    def validate(
        self,
        *,
        draft: DraftAgent,
        validation: AgentValidationRecord,
    ) -> None: ...


class AgentConfigurationContractValidator(Protocol):
    """Validate one complete Contract candidate without owning persistence."""

    def validate(
        self,
        *,
        draft: DraftAgent,
    ) -> None: ...


class AgentConfigurationWorkflowStageInspector(Protocol):
    """Compile and inspect one Draft without owning lifecycle writes or rules."""

    def inspect(
        self,
        *,
        draft: DraftAgent,
    ) -> AgentConfigurationWorkflowStageDraftFacts: ...


class AgentConfigurationSkillPackInspector(Protocol):
    """Inspect one Draft's Skill Packs without owning persistence rules."""

    def inspect(
        self,
        *,
        draft: DraftAgent,
        allow_configuration_issues: bool = False,
    ) -> BusinessFlowSkillPackConfiguration: ...


class AgentConfigurationKnowledgeReleaseCatalog(Protocol):
    """Read the live KSS catalog without owning Draft persistence rules."""

    def workspace(self) -> KnowledgeServiceManagementWorkspace: ...


class AgentConfigurationConflict(RuntimeError):
    """Stable Agent configuration conflict."""

    def __init__(self, *, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


class AgentConfigurationNotFound(LookupError):
    """A requested Agent configuration resource does not exist."""

    def __init__(self, *, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


class AgentConfigurationPublicationRejected(ValueError):
    """Stable precondition rejection for one Draft publication command."""

    def __init__(self, *, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


class AgentConfigurationScope(str, Enum):
    """Agent identity scope enforced inside the Workspace implementation."""

    SOLE_AGENT = "sole_agent"
    MULTI_AGENT = "multi_agent"


class AgentConfigurationWorkspace:
    """Own Draft inventory and mutation rules behind one stable interface."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], ConfigurationUnitOfWork],
        template_bundle: ContractBundle,
        validation_executor: AgentConfigurationValidationExecutor | None = None,
        publication_validator: AgentConfigurationPublicationValidator | None = None,
        contract_validator: AgentConfigurationContractValidator | None = None,
        workflow_stage_inspector: AgentConfigurationWorkflowStageInspector | None = None,
        skill_pack_inspector: AgentConfigurationSkillPackInspector | None = None,
        knowledge_release_catalog: AgentConfigurationKnowledgeReleaseCatalog | None = None,
        scope: AgentConfigurationScope = AgentConfigurationScope.SOLE_AGENT,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        _validate_template_bundle(template_bundle)
        self._unit_of_work_factory = unit_of_work_factory
        self._template_bundle = template_bundle
        self._validation_executor = validation_executor
        self._publication_validator = publication_validator
        self._contract_validator = contract_validator
        self._workflow_stage_inspector = workflow_stage_inspector
        self._skill_pack_inspector = skill_pack_inspector
        self._knowledge_release_catalog = knowledge_release_catalog
        self._scope = scope
        self._clock = clock

    def list_agents(self) -> AgentConfigurationInventory:
        with self._unit_of_work_factory() as uow:
            all_drafts = tuple(
                uow.agents.list_drafts(
                    SOLE_PRODUCTION_AGENT_ID
                    if self._scope is AgentConfigurationScope.SOLE_AGENT
                    else None
                )
            )
            active_by_agent = {
                item.agent_id: item for item in uow.agents.list_active()
            }
            agent_ids = (
                (SOLE_PRODUCTION_AGENT_ID,)
                if self._scope is AgentConfigurationScope.SOLE_AGENT
                else tuple(
                    sorted(
                        {
                            *(record.draft.agent_id for record in all_drafts),
                            *active_by_agent,
                        }
                    )
                )
            )
            summaries: list[AgentConfigurationSummary] = []
            for agent_id in agent_ids:
                drafts = tuple(
                    record
                    for record in all_drafts
                    if record.draft.agent_id == agent_id
                )
                versions = tuple(uow.agents.list_published(agent_id))
                if not drafts and not versions:
                    continue
                latest_draft = max(
                    drafts,
                    key=lambda record: record.draft.updated_at,
                    default=None,
                )
                latest_version = versions[0] if versions else None
                if latest_draft is not None:
                    display_name = latest_draft.draft.display_name
                    purpose = latest_draft.draft.purpose
                    updated_at = latest_draft.draft.updated_at
                else:
                    assert latest_version is not None
                    display_name = latest_version.display_name
                    purpose = latest_version.purpose
                    updated_at = latest_version.published_at
                summaries.append(
                    AgentConfigurationSummary(
                        agent_id=agent_id,
                        display_name=display_name,
                        purpose=purpose,
                        draft_count=len(drafts),
                        latest_draft_id=(
                            None
                            if latest_draft is None
                            else latest_draft.draft.draft_id
                        ),
                        version_count=len(versions),
                        active_version_id=(
                            None
                            if agent_id not in active_by_agent
                            else active_by_agent[agent_id].version_id
                        ),
                        updated_at=updated_at,
                    )
                )
        return AgentConfigurationInventory(
            agents=tuple(summaries),
            can_create=(
                self._scope is AgentConfigurationScope.MULTI_AGENT
                or not summaries
            ),
        )

    def get_draft(self, *, agent_id: str, draft_id: str) -> AgentDraftRecord:
        self._require_agent_scope(agent_id)
        self._require_draft_scope(draft_id)
        with self._unit_of_work_factory() as uow:
            record = uow.agents.get_draft(agent_id, draft_id)
        if record is None:
            raise AgentConfigurationNotFound(
                code="agent_draft_not_found",
                detail="The requested Agent Draft was not found.",
            )
        return record

    def list_versions(self, *, agent_id: str) -> AgentConfigurationVersions:
        self._require_agent_scope(agent_id)
        with self._unit_of_work_factory() as uow:
            versions = tuple(uow.agents.list_published(agent_id))
            active = uow.agents.get_active(agent_id)
        return AgentConfigurationVersions(
            versions=versions,
            active_version_id=None if active is None else active.version_id,
        )

    def create_draft(
        self,
        *,
        display_name: str,
        purpose: str,
        idempotency_key: str,
        actor: AuditActorFacts,
    ) -> AgentConfigurationDraftMutation:
        normalized_name = _nonblank(display_name, "display_name", maximum=200)
        normalized_purpose = _bounded(purpose, "purpose", maximum=4_000)
        normalized_key = _nonblank(idempotency_key, "idempotency_key", maximum=255)
        fingerprint = _request_fingerprint(
            display_name=normalized_name,
            purpose=normalized_purpose,
            template_bundle=self._template_bundle,
        )
        key_digest = _digest(f"{actor.subject}\0{normalized_key}")
        now = _timestamp(self._clock())
        metadata = {
            "request_fingerprint": fingerprint,
            "idempotency_key_sha256": key_digest,
            "template_id": SOLE_PRODUCTION_AGENT_ID,
        }
        operation = ConfigurationOperationAudit(
            operation_id=str(uuid5(NAMESPACE_URL, f"{_DRAFT_ID}:created:operation")),
            operation=ConfigurationOperation.CREATED,
            actor=actor.subject,
            created_at=now,
            summary="Initialized the sole production Agent Draft from the server template.",
            metadata=metadata,
        )
        draft = DraftAgent(
            agent_id=SOLE_PRODUCTION_AGENT_ID,
            draft_id=_DRAFT_ID,
            display_name=normalized_name,
            purpose=normalized_purpose,
            contract_bundle=self._template_bundle,
            created_at=now,
            updated_at=now,
            created_by=actor.subject,
            updated_by=actor.subject,
            operation_audit=(operation,),
        )
        event = AuditMetadataRecord(
            audit_id=str(uuid5(NAMESPACE_URL, f"{_DRAFT_ID}:created:audit")),
            category=AuditCategory.CONFIGURATION,
            event_type="agent.draft.created",
            outcome=AuditOutcome.SUCCEEDED,
            actor=actor,
            occurred_at=now,
            target_type="agent_draft",
            target_id=_DRAFT_ID,
            metadata=metadata,
        )
        try:
            with self._unit_of_work_factory() as uow:
                existing = tuple(uow.agents.list_drafts(SOLE_PRODUCTION_AGENT_ID))
                if existing:
                    return _resolve_existing_create(
                        existing,
                        request_fingerprint=fingerprint,
                        idempotency_key_sha256=key_digest,
                    )
                saved = uow.agents.save_draft(draft, expected_revision=0)
                uow.audit.append(event)
                uow.commit()
        except PersistenceConflictError as exc:
            if exc.resource_type == "agent_draft" and exc.resource_id == _DRAFT_ID:
                with self._unit_of_work_factory() as uow:
                    existing = tuple(
                        uow.agents.list_drafts(SOLE_PRODUCTION_AGENT_ID)
                    )
                if existing:
                    return _resolve_existing_create(
                        existing,
                        request_fingerprint=fingerprint,
                        idempotency_key_sha256=key_digest,
                    )
            raise AgentConfigurationConflict(
                code="agent_creation_conflict",
                detail="The production Agent could not be initialized concurrently.",
            ) from exc
        return AgentConfigurationDraftMutation(record=saved)

    def update_draft(
        self,
        *,
        agent_id: str,
        draft_id: str,
        expected_revision: int,
        display_name: str | None,
        purpose: str | None,
        actor: AuditActorFacts,
    ) -> AgentDraftRecord:
        self._require_agent_scope(agent_id)
        self._require_draft_scope(draft_id)
        if expected_revision < 1:
            raise ValueError("expected_revision must be at least one")
        if display_name is None and purpose is None:
            raise ValueError("at least one editable field is required")
        now = _timestamp(self._clock())
        try:
            with self._unit_of_work_factory() as uow:
                existing = uow.agents.get_draft(agent_id, draft_id)
                if existing is None:
                    raise AgentConfigurationNotFound(
                        code="agent_draft_not_found",
                        detail="The requested Agent Draft was not found.",
                    )
                next_name = (
                    existing.draft.display_name
                    if display_name is None
                    else _nonblank(display_name, "display_name", maximum=200)
                )
                next_purpose = (
                    existing.draft.purpose
                    if purpose is None
                    else _bounded(purpose, "purpose", maximum=4_000)
                )
                metadata = {"expected_revision": expected_revision}
                operation = ConfigurationOperationAudit(
                    operation_id=str(
                        uuid5(
                            NAMESPACE_URL,
                            f"{draft_id}:updated:{expected_revision + 1}:operation",
                        )
                    ),
                    operation=ConfigurationOperation.UPDATED,
                    actor=actor.subject,
                    created_at=now,
                    summary="Updated Agent Draft metadata.",
                    metadata=metadata,
                )
                updated = existing.draft.model_copy(
                    update={
                        "display_name": next_name,
                        "purpose": next_purpose,
                        "updated_at": now,
                        "updated_by": actor.subject,
                        "operation_audit": (*existing.draft.operation_audit, operation),
                    }
                )
                saved = uow.agents.save_draft(
                    updated,
                    expected_revision=expected_revision,
                )
                uow.audit.append(
                    AuditMetadataRecord(
                        audit_id=str(
                            uuid5(
                                NAMESPACE_URL,
                                f"{draft_id}:updated:{saved.revision}:audit",
                            )
                        ),
                        category=AuditCategory.CONFIGURATION,
                        event_type="agent.draft.updated",
                        outcome=AuditOutcome.SUCCEEDED,
                        actor=actor,
                        occurred_at=now,
                        target_type="agent_draft",
                        target_id=draft_id,
                        metadata=metadata,
                    )
                )
                uow.commit()
        except PersistenceConflictError as exc:
            raise AgentConfigurationConflict(
                code="agent_draft_revision_conflict",
                detail="The Agent Draft changed; reload it before saving.",
            ) from exc
        return saved

    def update_contract(
        self,
        *,
        agent_id: str,
        draft_id: str,
        expected_revision: int,
        agent_yaml: str | None,
        policy_yaml: str | None,
        tools_yaml: str | None,
        actor: AuditActorFacts,
    ) -> AgentDraftRecord:
        """Validate and atomically save one complete raw Contract candidate."""

        self._require_agent_scope(agent_id)
        self._require_draft_scope(draft_id)
        if expected_revision < 1:
            raise ValueError("expected_revision must be at least one")
        if self._contract_validator is None:
            raise AgentConfigurationConflict(
                code="agent_contract_update_unavailable",
                detail="Agent Contract editing is unavailable.",
            )
        current = self.get_draft(agent_id=agent_id, draft_id=draft_id)
        if current.revision != expected_revision:
            raise AgentConfigurationConflict(
                code="agent_draft_revision_conflict",
                detail="The Agent Draft changed; reload it before saving.",
            )
        current_bundle = current.draft.contract_bundle
        bundle = ContractBundle(
            agent_yaml=(
                current_bundle.agent_yaml if agent_yaml is None else agent_yaml
            ),
            policy_yaml=(
                current_bundle.policy_yaml if policy_yaml is None else policy_yaml
            ),
            tools_yaml=(
                current_bundle.tools_yaml if tools_yaml is None else tools_yaml
            ),
            extra_files=current_bundle.extra_files,
            advanced_fields=current_bundle.advanced_fields,
        )
        now = _timestamp(self._clock())
        metadata = {
            "expected_revision": expected_revision,
            "changed_files": [
                name
                for name, value in (
                    ("agent.yaml", agent_yaml),
                    ("policy.yaml", policy_yaml),
                    ("tools.yaml", tools_yaml),
                )
                if value is not None
            ],
        }
        operation = ConfigurationOperationAudit(
            operation_id=str(
                uuid5(
                    NAMESPACE_URL,
                    f"{draft_id}:contract:{expected_revision + 1}:operation",
                )
            ),
            operation=ConfigurationOperation.UPDATED,
            actor=actor.subject,
            created_at=now,
            summary="Updated Agent Contract.",
            metadata=metadata,
        )
        candidate = current.draft.model_copy(
            update={
                "contract_bundle": bundle,
                "updated_at": now,
                "updated_by": actor.subject,
                "operation_audit": (*current.draft.operation_audit, operation),
            }
        )
        self._contract_validator.validate(draft=candidate)
        try:
            with self._unit_of_work_factory() as uow:
                saved = uow.agents.save_draft(
                    candidate,
                    expected_revision=expected_revision,
                )
                uow.audit.append(
                    AuditMetadataRecord(
                        audit_id=str(uuid4()),
                        category=AuditCategory.CONFIGURATION,
                        event_type="agent.draft.contract_updated",
                        outcome=AuditOutcome.SUCCEEDED,
                        actor=actor,
                        occurred_at=now,
                        target_type="agent_draft",
                        target_id=draft_id,
                        metadata=metadata,
                    )
                )
                uow.commit()
        except PersistenceConflictError as exc:
            raise AgentConfigurationConflict(
                code="agent_draft_revision_conflict",
                detail="The Agent Draft changed; reload it before saving.",
            ) from exc
        return saved

    def get_business_flow_skill_packs(
        self,
        *,
        agent_id: str,
        draft_id: str,
    ) -> AgentConfigurationSkillPackResult:
        """Return one revisioned Draft's inspected Business Flow Skill Packs."""

        self._require_agent_scope(agent_id)
        self._require_draft_scope(draft_id)
        inspector = self._require_skill_pack_inspector()
        current = self.get_draft(agent_id=agent_id, draft_id=draft_id)
        return AgentConfigurationSkillPackResult(
            record=current,
            configuration=inspector.inspect(
                draft=current.draft,
                allow_configuration_issues=True,
            ),
        )

    def get_knowledge_release_binding_candidate(
        self,
        *,
        agent_id: str,
        draft_id: str,
    ) -> AgentConfigurationKnowledgeBindingResult:
        """Return one Draft candidate with the current live KSS catalog."""

        self._require_agent_scope(agent_id)
        self._require_draft_scope(draft_id)
        current = self.get_draft(agent_id=agent_id, draft_id=draft_id)
        catalog = self._require_knowledge_release_catalog().workspace()
        return AgentConfigurationKnowledgeBindingResult(
            record=current,
            catalog=catalog,
        )

    def update_knowledge_release_binding_candidate(
        self,
        *,
        agent_id: str,
        draft_id: str,
        expected_revision: int,
        candidate: DraftKnowledgeReleaseBindingCandidate,
        actor: AuditActorFacts,
    ) -> AgentConfigurationKnowledgeBindingResult:
        """Validate and atomically save one exact secret-free KSS Release candidate."""

        self._require_agent_scope(agent_id)
        self._require_draft_scope(draft_id)
        if expected_revision < 1:
            raise ValueError("expected_revision must be at least one")
        current = self.get_draft(agent_id=agent_id, draft_id=draft_id)
        if current.revision != expected_revision:
            raise AgentConfigurationConflict(
                code="agent_draft_revision_conflict",
                detail="The Agent Draft changed; reload it before saving.",
            )
        catalog = self._require_knowledge_release_catalog().workspace()
        if catalog.readiness.state != "ready":
            raise AgentConfigurationConflict(
                code="agent_knowledge_catalog_unavailable",
                detail="The Knowledge Source Service catalog is unavailable.",
            )
        if not any(
            release.state == "queryable"
            and release.knowledge_space_id == candidate.knowledge_space_id
            and release.knowledge_base_id == candidate.knowledge_base_id
            and release.knowledge_base_version_id
            == candidate.knowledge_base_version_id
            and release.knowledge_base_release_id
            == candidate.knowledge_base_release_id
            for release in catalog.releases
        ):
            raise AgentConfigurationConflict(
                code="agent_knowledge_release_not_queryable",
                detail="The selected KSS Release is not queryable for the exact parent identities.",
            )
        now = _timestamp(self._clock())
        metadata = {
            "expected_revision": expected_revision,
            "knowledge_space_id": candidate.knowledge_space_id,
            "knowledge_base_id": candidate.knowledge_base_id,
            "knowledge_base_version_id": candidate.knowledge_base_version_id,
            "knowledge_base_release_id": candidate.knowledge_base_release_id,
            "kss_catalog_revision": catalog.readiness.revision,
        }
        operation = ConfigurationOperationAudit(
            operation_id=str(
                uuid5(
                    NAMESPACE_URL,
                    f"{draft_id}:kss-release:{expected_revision + 1}:operation",
                )
            ),
            operation=ConfigurationOperation.UPDATED,
            actor=actor.subject,
            created_at=now,
            summary="Updated Draft KSS Release Binding Candidate.",
            metadata=metadata,
        )
        updated = current.draft.model_copy(
            update={
                "knowledge_release_binding_candidate": candidate,
                "updated_at": now,
                "updated_by": actor.subject,
                "operation_audit": (*current.draft.operation_audit, operation),
            }
        )
        try:
            with self._unit_of_work_factory() as uow:
                saved = uow.agents.save_draft(
                    updated,
                    expected_revision=expected_revision,
                )
                uow.audit.append(
                    AuditMetadataRecord(
                        audit_id=str(uuid4()),
                        category=AuditCategory.CONFIGURATION,
                        event_type=(
                            "agent.draft.knowledge_release_binding_candidate_updated"
                        ),
                        outcome=AuditOutcome.SUCCEEDED,
                        actor=actor,
                        occurred_at=now,
                        target_type="agent_draft",
                        target_id=draft_id,
                        metadata=metadata,
                    )
                )
                uow.commit()
        except PersistenceConflictError as exc:
            raise AgentConfigurationConflict(
                code="agent_draft_revision_conflict",
                detail="The Agent Draft changed; reload it before saving.",
            ) from exc
        return AgentConfigurationKnowledgeBindingResult(
            record=saved,
            catalog=catalog,
        )

    def create_business_flow_skill_pack(
        self,
        *,
        agent_id: str,
        draft_id: str,
        expected_revision: int,
        command: BusinessFlowSkillPackCreateCommand,
        actor: AuditActorFacts,
    ) -> AgentConfigurationSkillPackResult:
        """Create one complete Business Flow Skill Pack atomically."""

        return self._mutate_business_flow_skill_pack(
            agent_id=agent_id,
            draft_id=draft_id,
            pack_id=command.pack_id,
            expected_revision=expected_revision,
            action="created",
            event_type="agent.draft.skill_pack_created",
            bundle_factory=lambda draft: create_business_flow_skill_pack_bundle(
                draft,
                command,
            ),
            actor=actor,
        )

    def update_business_flow_skill_pack(
        self,
        *,
        agent_id: str,
        draft_id: str,
        pack_id: str,
        expected_revision: int,
        command: BusinessFlowSkillPackUpdateCommand,
        actor: AuditActorFacts,
    ) -> AgentConfigurationSkillPackResult:
        """Update one Business Flow Skill Pack atomically."""

        return self._mutate_business_flow_skill_pack(
            agent_id=agent_id,
            draft_id=draft_id,
            pack_id=pack_id,
            expected_revision=expected_revision,
            action="updated",
            event_type="agent.draft.skill_pack_updated",
            bundle_factory=lambda draft: update_business_flow_skill_pack_bundle(
                draft,
                pack_id=pack_id,
                command=command,
            ),
            actor=actor,
        )

    def delete_business_flow_skill_pack(
        self,
        *,
        agent_id: str,
        draft_id: str,
        pack_id: str,
        expected_revision: int,
        actor: AuditActorFacts,
    ) -> AgentConfigurationSkillPackResult:
        """Delete one Business Flow Skill Pack atomically."""

        return self._mutate_business_flow_skill_pack(
            agent_id=agent_id,
            draft_id=draft_id,
            pack_id=pack_id,
            expected_revision=expected_revision,
            action="deleted",
            event_type="agent.draft.skill_pack_deleted",
            bundle_factory=lambda draft: delete_business_flow_skill_pack_bundle(
                draft,
                pack_id=pack_id,
            ),
            actor=actor,
        )

    def _mutate_business_flow_skill_pack(
        self,
        *,
        agent_id: str,
        draft_id: str,
        pack_id: str,
        expected_revision: int,
        action: str,
        event_type: str,
        bundle_factory: Callable[[DraftAgent], tuple[ContractBundle, str]],
        actor: AuditActorFacts,
    ) -> AgentConfigurationSkillPackResult:
        self._require_agent_scope(agent_id)
        self._require_draft_scope(draft_id)
        if expected_revision < 1:
            raise ValueError("expected_revision must be at least one")
        inspector = self._require_skill_pack_inspector()
        current = self.get_draft(agent_id=agent_id, draft_id=draft_id)
        if current.revision != expected_revision:
            raise AgentConfigurationConflict(
                code="agent_draft_revision_conflict",
                detail="The Agent Draft changed; reload it before saving.",
            )
        bundle, definition_path = bundle_factory(current.draft)
        now = _timestamp(self._clock())
        metadata = {
            "action": action,
            "pack_id": pack_id,
            "definition": definition_path,
            "expected_revision": expected_revision,
        }
        operation = ConfigurationOperationAudit(
            operation_id=str(
                uuid5(
                    NAMESPACE_URL,
                    f"{draft_id}:skill-pack:{pack_id}:{action}:"
                    f"{expected_revision + 1}:operation",
                )
            ),
            operation=ConfigurationOperation.UPDATED,
            actor=actor.subject,
            created_at=now,
            summary=f"{action.capitalize()} Business Flow Skill Pack.",
            metadata=metadata,
        )
        candidate = current.draft.model_copy(
            update={
                "contract_bundle": bundle,
                "updated_at": now,
                "updated_by": actor.subject,
                "operation_audit": (*current.draft.operation_audit, operation),
            }
        )
        configuration = inspector.inspect(draft=candidate)
        try:
            with self._unit_of_work_factory() as uow:
                saved = uow.agents.save_draft(
                    candidate,
                    expected_revision=expected_revision,
                )
                uow.audit.append(
                    AuditMetadataRecord(
                        audit_id=str(uuid4()),
                        category=AuditCategory.CONFIGURATION,
                        event_type=event_type,
                        outcome=AuditOutcome.SUCCEEDED,
                        actor=actor,
                        occurred_at=now,
                        target_type="agent_draft",
                        target_id=draft_id,
                        metadata=metadata,
                    )
                )
                uow.commit()
        except PersistenceConflictError as exc:
            raise AgentConfigurationConflict(
                code="agent_draft_revision_conflict",
                detail="The Agent Draft changed; reload it before saving.",
            ) from exc
        return AgentConfigurationSkillPackResult(
            record=saved,
            configuration=configuration,
        )

    def _require_skill_pack_inspector(self) -> AgentConfigurationSkillPackInspector:
        if self._skill_pack_inspector is None:
            raise AgentConfigurationConflict(
                code="agent_skill_pack_configuration_unavailable",
                detail="Business Flow Skill Pack configuration is unavailable.",
            )
        return self._skill_pack_inspector

    def _require_knowledge_release_catalog(
        self,
    ) -> AgentConfigurationKnowledgeReleaseCatalog:
        if self._knowledge_release_catalog is None:
            raise AgentConfigurationConflict(
                code="agent_knowledge_catalog_unavailable",
                detail="KSS Knowledge configuration is unavailable.",
            )
        return self._knowledge_release_catalog

    def update_workflow_stages(
        self,
        *,
        agent_id: str,
        draft_id: str,
        expected_revision: int,
        template: str | None,
        template_descriptor_version: str | None,
        stages: tuple[WorkflowStageConfig, ...],
        actor: AuditActorFacts,
    ) -> AgentDraftRecord:
        """Validate and atomically replace one Draft's Workflow Stage settings."""

        self._require_agent_scope(agent_id)
        self._require_draft_scope(draft_id)
        if expected_revision < 1:
            raise ValueError("expected_revision must be at least one")
        if self._workflow_stage_inspector is None:
            raise AgentConfigurationConflict(
                code="agent_workflow_stage_configuration_unavailable",
                detail="Workflow Stage configuration is unavailable.",
            )
        current = self.get_draft(agent_id=agent_id, draft_id=draft_id)
        if current.revision != expected_revision:
            raise AgentConfigurationConflict(
                code="agent_draft_revision_conflict",
                detail="The Agent Draft changed; reload it before saving.",
            )
        now = _timestamp(self._clock())
        bundle, workflow_template = _workflow_stage_contract_bundle(
            current.draft.contract_bundle,
            template=template,
            template_descriptor_version=template_descriptor_version,
            stages=stages,
        )
        _validate_workflow_stage_command(
            workflow_template=workflow_template,
            template_descriptor_version=template_descriptor_version,
            stages=stages,
        )
        metadata = {
            "expected_revision": expected_revision,
            "workflow_template": workflow_template,
            "template_descriptor_version": template_descriptor_version,
            "stage_ids": [stage.id for stage in stages],
        }
        operation = ConfigurationOperationAudit(
            operation_id=str(
                uuid5(
                    NAMESPACE_URL,
                    f"{draft_id}:workflow-stages:{expected_revision + 1}:operation",
                )
            ),
            operation=ConfigurationOperation.UPDATED,
            actor=actor.subject,
            created_at=now,
            summary="Updated Workflow Stage configuration.",
            metadata=metadata,
        )
        candidate = current.draft.model_copy(
            update={
                "contract_bundle": bundle,
                "updated_at": now,
                "updated_by": actor.subject,
                "operation_audit": (*current.draft.operation_audit, operation),
            }
        )
        facts = self._workflow_stage_inspector.inspect(draft=candidate)
        if facts.template_name != workflow_template:
            raise RuntimeError(
                "Workflow Stage inspection returned inconsistent template identity"
            )
        try:
            with self._unit_of_work_factory() as uow:
                saved = uow.agents.save_draft(
                    candidate,
                    expected_revision=expected_revision,
                )
                uow.audit.append(
                    AuditMetadataRecord(
                        audit_id=str(uuid4()),
                        category=AuditCategory.CONFIGURATION,
                        event_type="agent.draft.workflow_stages_updated",
                        outcome=AuditOutcome.SUCCEEDED,
                        actor=actor,
                        occurred_at=now,
                        target_type="agent_draft",
                        target_id=draft_id,
                        metadata=metadata,
                    )
                )
                uow.commit()
        except PersistenceConflictError as exc:
            raise AgentConfigurationConflict(
                code="agent_draft_revision_conflict",
                detail="The Agent Draft changed; reload it before saving.",
            ) from exc
        return saved

    def preview_workflow_stage(
        self,
        *,
        agent_id: str,
        draft_id: str,
        stage_id: str,
        prompt: WorkflowStagePromptConfig,
        context_options: Mapping[str, bool],
    ) -> dict[str, Any]:
        """Render a redacted Workflow Stage Context Preview without execution."""

        self._require_agent_scope(agent_id)
        self._require_draft_scope(draft_id)
        if self._workflow_stage_inspector is None:
            raise AgentConfigurationConflict(
                code="agent_workflow_stage_configuration_unavailable",
                detail="Workflow Stage configuration is unavailable.",
            )
        current = self.get_draft(agent_id=agent_id, draft_id=draft_id)
        facts = self._workflow_stage_inspector.inspect(draft=current.draft)
        descriptor = resolve_workflow_template(facts.template_name)
        stage_descriptor = descriptor.stage(stage_id)
        validate_workflow_stage_prompt_config(
            stage_id=stage_id,
            prompt=prompt,
            stage_descriptor=stage_descriptor,
        )
        return build_workflow_stage_context_preview(
            descriptor=descriptor,
            stage_id=stage_id,
            prompt=prompt,
            context_options=context_options,
            sample_context={
                "agent_purpose": facts.agent_purpose,
                "bound_knowledge_sources": [],
                "bound_tools": facts.tool_contract_reference,
                "policy_outline": facts.policy_reference,
                "response_disclosure_policy": dict(
                    facts.response_disclosure_policy
                ),
                "memory_scope": dict(facts.memory_scope),
            },
        )

    def validate_draft(
        self,
        *,
        agent_id: str,
        draft_id: str,
        question: str,
        full_capture: bool,
        retain_for_audit: bool,
        actor: AuditActorFacts,
    ) -> AgentConfigurationValidationResult:
        """Execute and atomically attach one governed Validation Record."""

        self._require_agent_scope(agent_id)
        self._require_draft_scope(draft_id)
        if not question:
            raise ValueError("validation question must not be empty")
        if self._validation_executor is None:
            raise RuntimeError("Agent Draft validation is unavailable")
        current = self.get_draft(agent_id=agent_id, draft_id=draft_id)
        execution = self._validation_executor.validate(
            draft=current.draft,
            question=question,
            full_capture=full_capture,
            retain_for_audit=retain_for_audit,
            actor=actor,
        )
        _validate_execution_identity(
            execution,
            agent_id=agent_id,
            draft_id=draft_id,
            full_capture=full_capture,
        )
        warnings, publish_blockers = _validation_model_connection_warnings(
            execution.trace_events
        )
        now = _timestamp(self._clock())
        validation = AgentValidationRecord(
            validation_id=f"validation_{uuid4().hex[:8]}",
            draft_id=draft_id,
            run_id=execution.run_id,
            status=execution.outcome,
            created_at=now,
            validation_capture_id=_validation_capture_id(
                execution.validation_capture
            ),
            summary=execution.summary[:500],
            warnings=warnings,
            publish_blockers=publish_blockers,
            resolved_knowledge_bindings=execution.resolved_knowledge_bindings,
        )
        metadata = {
            "run_id": validation.run_id,
            "status": validation.status,
            "draft_revision": current.revision,
        }
        operation = ConfigurationOperationAudit(
            operation_id=str(
                uuid5(
                    NAMESPACE_URL,
                    f"{validation.validation_id}:validated:operation",
                )
            ),
            operation=ConfigurationOperation.VALIDATED,
            actor=actor.subject,
            created_at=now,
            summary=f"Validated Agent Draft {draft_id}.",
            metadata=metadata,
        )
        try:
            with self._unit_of_work_factory() as uow:
                latest = uow.agents.get_draft(agent_id, draft_id)
                if latest is None:
                    raise AgentConfigurationNotFound(
                        code="agent_draft_not_found",
                        detail="The requested Agent Draft was not found.",
                    )
                updated = latest.draft.model_copy(
                    update={
                        "updated_at": now,
                        "updated_by": actor.subject,
                        "validation_records": (
                            *latest.draft.validation_records,
                            validation,
                        ),
                        "operation_audit": (
                            *latest.draft.operation_audit,
                            operation,
                        ),
                    }
                )
                saved = uow.agents.save_draft(
                    updated,
                    expected_revision=current.revision,
                )
                uow.audit.append(
                    AuditMetadataRecord(
                        audit_id=str(
                            uuid5(
                                NAMESPACE_URL,
                                f"{validation.validation_id}:validated:audit",
                            )
                        ),
                        category=AuditCategory.CONFIGURATION,
                        event_type="agent.draft.validated",
                        outcome=AuditOutcome.SUCCEEDED,
                        actor=actor,
                        occurred_at=now,
                        target_type="agent_draft",
                        target_id=draft_id,
                        metadata=metadata,
                    )
                )
                uow.commit()
        except PersistenceConflictError as exc:
            raise AgentConfigurationConflict(
                code="agent_draft_revision_conflict",
                detail="The Agent Draft changed during validation; reload it before retrying.",
            ) from exc
        return AgentConfigurationValidationResult(
            record=saved,
            validation=validation,
            execution=execution,
        )

    def publish_draft(
        self,
        *,
        agent_id: str,
        draft_id: str,
        validation_run_id: str | None,
        actor: AuditActorFacts,
    ) -> PublishedAgentVersion:
        """Publish and activate one currently validated Draft atomically."""

        self._require_agent_scope(agent_id)
        self._require_draft_scope(draft_id)
        if self._publication_validator is None:
            raise RuntimeError("Agent Draft publication is unavailable")
        current = self.get_draft(agent_id=agent_id, draft_id=draft_id)
        validation = _current_publication_validation(
            current,
            validation_run_id=validation_run_id,
        )
        self._publication_validator.validate(
            draft=current.draft,
            validation=validation,
        )
        version_id = f"version_{uuid4().hex[:8]}"
        published_at = _timestamp(self._clock())
        stage_facts = resolve_workflow_stage_runtime_configuration(
            current.draft.contract_bundle.agent_yaml,
            source=WorkflowStageConfigurationRuntimeSource(
                source_type=(
                    WorkflowStageConfigurationRuntimeSourceType.PUBLISHED_AGENT_VERSION
                ),
                reference=(
                    f"published_version:{version_id}:"
                    "effective_workflow_stage_configuration"
                ),
            ),
        )
        if stage_facts is None:
            raise AgentConfigurationPublicationRejected(
                code="agent_publication_configuration_invalid",
                detail="The Agent Draft has no publishable Workflow configuration.",
            )
        operation = ConfigurationOperationAudit(
            operation_id=str(uuid4()),
            operation=ConfigurationOperation.PUBLISHED,
            actor=actor.subject,
            created_at=published_at,
            summary=f"Published Agent Draft {draft_id}.",
            metadata={
                "validation_run_id": validation.run_id,
                "draft_revision": current.revision,
            },
        )
        version = PublishedAgentVersion(
            agent_id=agent_id,
            version_id=version_id,
            source_draft_id=draft_id,
            validation_run_id=validation.run_id,
            display_name=current.draft.display_name,
            purpose=current.draft.purpose,
            contract_bundle=current.draft.contract_bundle,
            published_at=published_at,
            published_by=actor.subject,
            operation_audit=(operation,),
            resolved_knowledge_bindings=validation.resolved_knowledge_bindings,
            workflow_stage_availability=stage_facts.workflow_stage_availability,
            effective_workflow_stage_configuration=(
                PublishedWorkflowStageConfigurationSnapshot.model_validate(
                    stage_facts.effective_stage_configuration.model_dump(mode="python")
                )
            ),
        )
        try:
            with self._unit_of_work_factory() as uow:
                latest = uow.agents.get_draft(agent_id, draft_id)
                if latest is None:
                    raise AgentConfigurationNotFound(
                        code="agent_draft_not_found",
                        detail="The requested Agent Draft was not found.",
                    )
                active = uow.agents.get_active(agent_id)
                publication = AgentPublicationRecord(
                    version=version,
                    activation=ActiveAgentVersion(
                        agent_id=agent_id,
                        version_id=version_id,
                        activated_at=published_at,
                        activated_by=actor.subject,
                    ),
                    draft_revision=current.revision,
                    active_pointer_expectation=ActiveAgentPointerExpectation(
                        version_id=None if active is None else active.version_id
                    ),
                )
                saved = uow.agents.publish_version(
                    publication,
                    expected_draft_revision=current.revision,
                )
                uow.audit.append(
                    AuditMetadataRecord(
                        audit_id=str(uuid4()),
                        category=AuditCategory.CONFIGURATION,
                        event_type="agent.version.published",
                        outcome=AuditOutcome.SUCCEEDED,
                        actor=actor,
                        occurred_at=published_at,
                        target_type="agent_version",
                        target_id=version_id,
                        metadata={
                            "agent_id": agent_id,
                            "draft_id": draft_id,
                            "draft_revision": current.revision,
                            "validation_run_id": validation.run_id,
                            "replaced_active_version_id": (
                                None if active is None else active.version_id
                            ),
                        },
                    )
                )
                uow.commit()
        except PersistenceConflictError as exc:
            raise AgentConfigurationConflict(
                code="agent_draft_revision_conflict",
                detail=(
                    "The Agent Draft changed during publication; "
                    "validate it again before retrying."
                ),
            ) from exc
        except PersistencePointerConflictError as exc:
            raise AgentConfigurationConflict(
                code="active_agent_version_conflict",
                detail="The Active Agent Version changed; reload before retrying.",
            ) from exc
        return saved.version

    def rollback_version(
        self,
        *,
        agent_id: str,
        version_id: str,
        actor: AuditActorFacts,
    ) -> AgentConfigurationRollback:
        """Atomically point one Agent at an existing immutable Published Version."""

        self._require_agent_scope(agent_id)
        _require_safe_resource_id(version_id, resource="Agent Version")
        activated_at = _timestamp(self._clock())
        try:
            with self._unit_of_work_factory() as uow:
                restored = uow.agents.get_published(agent_id, version_id)
                if restored is None:
                    raise AgentConfigurationNotFound(
                        code="agent_version_not_found",
                        detail="The requested Published Agent Version was not found.",
                    )
                current = uow.agents.get_active(agent_id)
                replaced_version_id = (
                    None if current is None else current.version_id
                )
                activation = AgentActivationRecord(
                    activation=ActiveAgentVersion(
                        agent_id=agent_id,
                        version_id=version_id,
                        activated_at=activated_at,
                        activated_by=actor.subject,
                        rollback_from_version_id=replaced_version_id,
                    ),
                    active_pointer_expectation=ActiveAgentPointerExpectation(
                        version_id=replaced_version_id
                    ),
                )
                saved = uow.agents.activate_version(activation)
                uow.audit.append(
                    AuditMetadataRecord(
                        audit_id=str(uuid4()),
                        category=AuditCategory.CONFIGURATION,
                        event_type="agent.version.rolled_back",
                        outcome=AuditOutcome.SUCCEEDED,
                        actor=actor,
                        occurred_at=activated_at,
                        target_type="agent_version",
                        target_id=version_id,
                        metadata={
                            "agent_id": agent_id,
                            "replaced_active_version_id": replaced_version_id,
                            "restored_validation_run_id": (
                                restored.validation_run_id
                            ),
                        },
                    )
                )
                uow.commit()
        except PersistenceNotFoundError as exc:
            raise AgentConfigurationNotFound(
                code="agent_version_not_found",
                detail="The requested Published Agent Version was not found.",
            ) from exc
        except (PersistencePointerConflictError, PersistenceConflictError) as exc:
            raise AgentConfigurationConflict(
                code="active_agent_version_conflict",
                detail="The Active Agent Version changed; reload before retrying.",
            ) from exc
        return AgentConfigurationRollback(
            activation=saved.activation,
            restored=restored,
        )

    def _require_agent_scope(self, agent_id: str) -> None:
        _require_safe_resource_id(agent_id, resource="Agent")
        if (
            self._scope is AgentConfigurationScope.SOLE_AGENT
            and agent_id != SOLE_PRODUCTION_AGENT_ID
        ):
            raise AgentConfigurationNotFound(
                code="agent_not_found",
                detail="The requested Agent was not found.",
            )

    def _require_draft_scope(self, draft_id: str) -> None:
        if self._scope is AgentConfigurationScope.SOLE_AGENT:
            _require_draft_id(draft_id)
            return
        _require_safe_resource_id(draft_id, resource="Agent Draft")


def load_server_owned_agent_template() -> ContractBundle:
    """Load the immutable Agent template shipped in the installed server artifact."""

    try:
        package = distribution("proof-agent")
    except PackageNotFoundError as exc:
        raise RuntimeError("the proof-agent distribution is unavailable") from exc
    manifest_path = Path(str(package.locate_file(_SERVER_TEMPLATE_MANIFEST))).resolve()
    if not manifest_path.is_file():
        raise RuntimeError("the server-owned production Agent template is unavailable")
    return build_agent_package_contract_bundle(
        manifest_path,
        require_writable_artifacts=False,
    )


def _resolve_existing_create(
    records: tuple[AgentDraftRecord, ...],
    *,
    request_fingerprint: str,
    idempotency_key_sha256: str,
) -> AgentConfigurationDraftMutation:
    for record in records:
        metadata = _creation_metadata(record.draft)
        if metadata.get("idempotency_key_sha256") != idempotency_key_sha256:
            continue
        if metadata.get("request_fingerprint") != request_fingerprint:
            raise AgentConfigurationConflict(
                code="idempotency_key_mismatch",
                detail="The Idempotency-Key was already used for a different request.",
            )
        return AgentConfigurationDraftMutation(record=record, replayed=True)
    raise AgentConfigurationConflict(
        code="sole_agent_already_exists",
        detail="The sole production Agent has already been initialized.",
    )


def _creation_metadata(draft: DraftAgent) -> dict[str, Any]:
    for operation in draft.operation_audit:
        if operation.operation is ConfigurationOperation.CREATED:
            return dict(operation.metadata)
    return {}


def _validate_template_bundle(bundle: ContractBundle) -> None:
    try:
        agent = yaml.safe_load(bundle.agent_yaml)
    except yaml.YAMLError as exc:
        raise ValueError("production Agent template YAML is invalid") from exc
    if not isinstance(agent, dict) or agent.get("name") != SOLE_PRODUCTION_AGENT_ID:
        raise ValueError("production Agent template must use the sole Agent identity")
    workflow = agent.get("workflow")
    if not isinstance(workflow, dict) or workflow.get("template") != _EXPECTED_WORKFLOW_TEMPLATE:
        raise ValueError("production Agent template must use react_enterprise_qa_v3")


def _workflow_stage_contract_bundle(
    bundle: ContractBundle,
    *,
    template: str | None,
    template_descriptor_version: str | None,
    stages: tuple[WorkflowStageConfig, ...],
) -> tuple[ContractBundle, str]:
    try:
        raw = yaml.safe_load(bundle.agent_yaml)
    except yaml.YAMLError as exc:
        raise ValueError("agent_yaml is invalid YAML") from exc
    if not isinstance(raw, dict):
        raise ValueError("agent_yaml must be a mapping")
    workflow = raw.get("workflow")
    if not isinstance(workflow, dict):
        raise ValueError("agent_yaml workflow must be a mapping")
    if template is not None:
        workflow["template"] = _nonblank(template, "template", maximum=255)
    workflow_template = workflow.get("template")
    if not isinstance(workflow_template, str) or not workflow_template.strip():
        raise ValueError("agent_yaml workflow.template must be a non-empty string")
    if template_descriptor_version is not None:
        workflow["template_descriptor_version"] = _nonblank(
            template_descriptor_version,
            "template_descriptor_version",
            maximum=255,
        )
    workflow["stages"] = [_workflow_stage_payload(stage) for stage in stages]
    workflow.pop("nodes", None)
    raw["workflow"] = workflow
    agent_yaml = yaml.safe_dump(
        raw,
        sort_keys=False,
        allow_unicode=True,
        width=1000,
    )
    return (
        ContractBundle(
            agent_yaml=agent_yaml,
            policy_yaml=bundle.policy_yaml,
            tools_yaml=bundle.tools_yaml,
            extra_files=bundle.extra_files,
            advanced_fields=bundle.advanced_fields,
        ),
        workflow_template,
    )


def _workflow_stage_payload(stage: WorkflowStageConfig) -> dict[str, Any]:
    payload: dict[str, Any] = {"id": stage.id}
    prompt: dict[str, Any] = {}
    if stage.prompt.business_context:
        prompt["business_context"] = stage.prompt.business_context
    if stage.prompt.task_instructions:
        prompt["task_instructions"] = list(stage.prompt.task_instructions)
    if stage.prompt.output_preferences:
        prompt["output_preferences"] = list(stage.prompt.output_preferences)
    if prompt:
        payload["prompt"] = prompt
    context = dict(stage.context.options)
    if context:
        payload["context"] = context
    return payload


def _validate_workflow_stage_command(
    *,
    workflow_template: str,
    template_descriptor_version: str | None,
    stages: tuple[WorkflowStageConfig, ...],
) -> None:
    descriptor = resolve_workflow_template(workflow_template)
    if (
        template_descriptor_version is not None
        and template_descriptor_version != descriptor.descriptor_version
    ):
        raise ProofAgentError(
            "PA_CONFIG_002",
            "workflow.template_descriptor_version does not match registered template descriptor",
            f"Set workflow.template_descriptor_version to {descriptor.descriptor_version}.",
        )
    seen: set[str] = set()
    total_prompt_chars = 0
    for stage in stages:
        if stage.id in seen:
            raise ProofAgentError(
                "PA_CONFIG_002",
                f"duplicate workflow stage id: {stage.id}",
                "Use each workflow.stages[].id at most once.",
            )
        seen.add(stage.id)
        stage_descriptor = descriptor.stage(stage.id)
        unsupported_context_options = sorted(
            option
            for option in stage.context.options
            if option not in stage_descriptor.context_options
        )
        if unsupported_context_options:
            raise ProofAgentError(
                "PA_CONFIG_002",
                f"unsupported context option for workflow stage {stage.id}: {', '.join(unsupported_context_options)}",
                f"Use context options: {', '.join(stage_descriptor.context_options)}.",
            )
        total_prompt_chars += validate_workflow_stage_prompt_config(
            stage_id=stage.id,
            prompt=stage.prompt,
            stage_descriptor=stage_descriptor,
        )
    if total_prompt_chars > MAX_WORKFLOW_STAGE_TOTAL_PROMPT_CHARS:
        raise ProofAgentError(
            "PA_CONFIG_002",
            "workflow stage prompt text exceeds total size limit",
            f"Use at most {MAX_WORKFLOW_STAGE_TOTAL_PROMPT_CHARS} total prompt characters.",
        )


def _require_draft_id(draft_id: str) -> None:
    try:
        UUID(draft_id)
    except (TypeError, ValueError, AttributeError) as exc:
        raise AgentConfigurationNotFound(
            code="agent_draft_not_found",
            detail="The requested Agent Draft was not found.",
        ) from exc


def _require_safe_resource_id(value: str, *, resource: str) -> None:
    if (
        not value
        or value != value.strip()
        or len(value) > 255
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
    ):
        raise AgentConfigurationNotFound(
            code=f"{resource.lower().replace(' ', '_')}_not_found",
            detail=f"The requested {resource} was not found.",
        )


def _validate_execution_identity(
    execution: AgentConfigurationValidationExecution,
    *,
    agent_id: str,
    draft_id: str,
    full_capture: bool,
) -> None:
    if (
        execution.run_purpose != "validation"
        or execution.agent_id != agent_id
        or execution.draft_id != draft_id
        or not execution.run_id
        or not execution.outcome
    ):
        raise RuntimeError("Agent Draft validation returned inconsistent evidence")
    capture = execution.validation_capture
    capture_error = execution.capture_error
    if capture is not None and capture_error is not None:
        raise RuntimeError("Agent Draft validation returned inconsistent evidence")
    if full_capture and capture is None and capture_error is None:
        raise RuntimeError("Agent Draft validation returned inconsistent evidence")
    if not full_capture and (capture is not None or capture_error is not None):
        raise RuntimeError("Agent Draft validation returned inconsistent evidence")
    if capture is not None and (
        capture.run_id != execution.run_id
        or capture.draft_id != execution.draft_id
        or not capture.capture_id
    ):
        raise RuntimeError("Agent Draft validation returned inconsistent evidence")


def _validation_capture_id(
    capture: SensitiveValidationCaptureArtifact | None,
) -> str | None:
    return None if capture is None else capture.capture_id


def _current_publication_validation(
    record: AgentDraftRecord,
    *,
    validation_run_id: str | None,
) -> AgentValidationRecord:
    validations = record.draft.validation_records
    selected_run_id = validation_run_id or (
        None if not validations else validations[-1].run_id
    )
    if selected_run_id is None:
        raise AgentConfigurationPublicationRejected(
            code="agent_validation_required",
            detail="A validation run is required before publication.",
        )
    validation = next(
        (item for item in validations if item.run_id == selected_run_id),
        None,
    )
    if validation is None or validation.draft_id != record.draft.draft_id:
        raise AgentConfigurationPublicationRejected(
            code="agent_validation_not_recorded",
            detail="The requested validation run is not recorded for this Draft.",
        )
    latest_operation = (
        None if not record.draft.operation_audit else record.draft.operation_audit[-1]
    )
    validated_revision = (
        None
        if latest_operation is None
        else latest_operation.metadata.get("draft_revision")
    )
    if (
        latest_operation is None
        or latest_operation.operation is not ConfigurationOperation.VALIDATED
        or latest_operation.metadata.get("run_id") != validation.run_id
        or not isinstance(validated_revision, int)
        or isinstance(validated_revision, bool)
        or validated_revision + 1 != record.revision
    ):
        raise AgentConfigurationPublicationRejected(
            code="agent_validation_stale",
            detail="The Agent Draft changed after validation; validate it again.",
        )
    normalized_status = validation.status.strip().upper()
    if (
        not normalized_status
        or normalized_status == "ERROR"
        or normalized_status.startswith("FAILED")
    ):
        raise AgentConfigurationPublicationRejected(
            code="agent_validation_failed",
            detail="The Agent Draft validation did not complete successfully.",
        )
    if validation.errors or validation.publish_blockers:
        raise AgentConfigurationPublicationRejected(
            code="agent_validation_blocked",
            detail="The Agent Draft validation contains publication blockers.",
        )
    return validation


def _validation_model_connection_warnings(
    trace_events: tuple[Mapping[str, Any], ...],
) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
    warnings: list[dict[str, Any]] = []
    publish_blockers: list[dict[str, Any]] = []
    seen_connections: set[tuple[str | None, str | None]] = set()
    for event in trace_events:
        if event.get("event_type") != "model_connection_resolution":
            continue
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            continue
        event_warnings = payload.get("warnings")
        if not isinstance(event_warnings, list | tuple):
            continue
        if "connection_archived" not in event_warnings:
            continue
        connection_id = payload.get("connection_id")
        role = payload.get("role")
        key = (
            connection_id if isinstance(connection_id, str) else None,
            role if isinstance(role, str) else None,
        )
        if key in seen_connections:
            continue
        seen_connections.add(key)
        if not isinstance(connection_id, str) or not isinstance(role, str):
            continue
        warnings.append(
            {
                "code": "model_connection_archived",
                "connection_id": connection_id,
                "role": role,
                "message": f"Shared Model Connection is archived: {connection_id}.",
            }
        )
        publish_blockers.append(
            {
                "code": "archived_model_connection",
                "connection_id": connection_id,
                "role": role,
                "message": (
                    "Publish is blocked while Shared Model Connection "
                    f"{connection_id} is archived."
                ),
            }
        )
    return tuple(warnings), tuple(publish_blockers)


def _request_fingerprint(
    *,
    display_name: str,
    purpose: str,
    template_bundle: ContractBundle,
) -> str:
    payload = {
        "schema": _CREATE_FINGERPRINT_SCHEMA,
        "agent_id": SOLE_PRODUCTION_AGENT_ID,
        "display_name": display_name,
        "purpose": purpose,
        "template_bundle": template_bundle.model_dump(mode="json"),
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def _digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _nonblank(value: str, field: str, *, maximum: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{field} is empty or outside its length limit")
    return normalized


def _bounded(value: str, field: str, *, maximum: int) -> str:
    normalized = value.strip()
    if len(normalized) > maximum:
        raise ValueError(f"{field} is outside its length limit")
    return normalized


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("production Agent configuration clock must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "SOLE_PRODUCTION_AGENT_ID",
    "AgentConfigurationConflict",
    "AgentConfigurationDraftMutation",
    "AgentConfigurationInventory",
    "AgentConfigurationNotFound",
    "AgentConfigurationRollback",
    "AgentConfigurationScope",
    "AgentConfigurationSummary",
    "AgentConfigurationVersions",
    "AgentConfigurationWorkspace",
    "load_server_owned_agent_template",
]
