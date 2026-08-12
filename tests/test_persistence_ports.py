from __future__ import annotations

from types import TracebackType
from typing import Any

from pydantic import ValidationError

from proof_agent.contracts import (
    ActiveAgentVersion,
    ContextAdmission,
    ContractBundle,
    ConversationRecord,
    ConversationTurn,
    DraftAgent,
    MemoryCandidate,
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
    PublishedAgentVersion,
    ReceiptOutcome,
    RunPurpose,
)
from proof_agent.contracts.persistence import (
    AgentDraftRecord,
    AgentPublicationRecord,
    AuditActorFacts,
    AuditCategory,
    AuditMetadataRecord,
    AuditOutcome,
    CaseMemoryAdmission,
    PersistenceConflictError,
    PersistenceNotFoundError,
    RunLifecycleState,
    RunMetadataRecord,
)
from proof_agent.contracts.shared_assets import (
    ResolvedSharedAssetVersions,
    SharedAssetKind,
    SharedAssetVersionRef,
    SharedAssetVersionRequest,
)
from proof_agent.contracts.ports.agent_lifecycle import AgentLifecycleRepository
from proof_agent.contracts.ports.audit import AuditRepository
from proof_agent.contracts.ports.conversations import ConversationRepository
from proof_agent.contracts.ports.case_memory import CaseMemoryRepository
from proof_agent.contracts.ports.run_metadata import RunMetadataRepository
from proof_agent.contracts.ports.shared_assets import (
    KnowledgeAssetRepository,
    ModelAssetRepository,
    ToolAssetRepository,
    resolve_shared_asset_versions,
)
from proof_agent.contracts.ports.unit_of_work import ConfigurationUnitOfWork


class _InMemoryAgentLifecycleRepository:
    def __init__(self) -> None:
        self._drafts: dict[tuple[str, str], AgentDraftRecord] = {}
        self._published: dict[tuple[str, str], AgentPublicationRecord] = {}
        self._active: dict[str, ActiveAgentVersion] = {}

    def get_draft(self, agent_id: str, draft_id: str) -> AgentDraftRecord | None:
        return self._drafts.get((agent_id, draft_id))

    def list_drafts(self, agent_id: str | None = None) -> tuple[AgentDraftRecord, ...]:
        return tuple(
            record
            for (stored_agent_id, _), record in sorted(self._drafts.items())
            if agent_id is None or stored_agent_id == agent_id
        )

    def save_draft(
        self,
        draft: DraftAgent,
        *,
        expected_revision: int,
    ) -> AgentDraftRecord:
        key = (draft.agent_id, draft.draft_id)
        current = self._drafts.get(key)
        current_revision = 0 if current is None else current.revision
        if current_revision != expected_revision:
            raise PersistenceConflictError(
                resource_type="agent_draft",
                resource_id=draft.draft_id,
                expected_revision=expected_revision,
                actual_revision=current_revision,
            )
        saved = AgentDraftRecord(draft=draft, revision=current_revision + 1)
        self._drafts[key] = saved
        return saved

    def publish_version(
        self,
        publication: AgentPublicationRecord,
        *,
        expected_draft_revision: int,
    ) -> AgentPublicationRecord:
        version = publication.version
        draft_key = (version.agent_id, version.source_draft_id)
        current = self._drafts.get(draft_key)
        actual_revision = None if current is None else current.revision
        if actual_revision != expected_draft_revision:
            raise PersistenceConflictError(
                resource_type="agent_draft",
                resource_id=version.source_draft_id,
                expected_revision=expected_draft_revision,
                actual_revision=actual_revision,
            )
        version_key = (version.agent_id, version.version_id)
        if version_key in self._published:
            raise PersistenceConflictError(
                resource_type="agent_version",
                resource_id=version.version_id,
                expected_revision=0,
                actual_revision=1,
            )
        self._published[version_key] = publication
        self._active[version.agent_id] = publication.activation
        return publication

    def get_published(
        self, agent_id: str, version_id: str
    ) -> PublishedAgentVersion | None:
        publication = self._published.get((agent_id, version_id))
        return None if publication is None else publication.version

    def list_published(self, agent_id: str) -> tuple[PublishedAgentVersion, ...]:
        return tuple(
            publication.version
            for (stored_agent_id, _), publication in sorted(self._published.items())
            if stored_agent_id == agent_id
        )

    def get_active(self, agent_id: str) -> ActiveAgentVersion | None:
        return self._active.get(agent_id)


class _InMemorySharedAssetRepository:
    def __init__(self, refs: tuple[SharedAssetVersionRef, ...]) -> None:
        self._refs = {(ref.asset_id, ref.version_id): ref for ref in refs}

    def resolve_version(
        self,
        asset_id: str,
        *,
        version_id: str | None = None,
    ) -> SharedAssetVersionRef | None:
        matches = [
            ref
            for (stored_asset_id, _), ref in self._refs.items()
            if stored_asset_id == asset_id
            and (version_id is None or ref.version_id == version_id)
        ]
        if not matches:
            return None
        return max(matches, key=lambda item: item.revision)

    def get_model_connection(self, connection_id: str) -> Any:
        _ = connection_id
        return None

    def get_tool_source(self, source_id: str) -> Any:
        _ = source_id
        return None


class _InMemoryRunMetadataRepository:
    def __init__(self) -> None:
        self._records: dict[str, RunMetadataRecord] = {}

    def append(self, record: RunMetadataRecord) -> None:
        if record.run_id in self._records:
            raise PersistenceConflictError(
                resource_type="run",
                resource_id=record.run_id,
                expected_revision=0,
                actual_revision=self._records[record.run_id].state_version,
            )
        self._records[record.run_id] = record

    def get(self, run_id: str) -> RunMetadataRecord | None:
        return self._records.get(run_id)


class _InMemoryConversationRepository:
    def __init__(self) -> None:
        self._records: dict[str, ConversationRecord] = {}

    def create(self, record: ConversationRecord) -> None:
        if record.conversation_id in self._records:
            raise PersistenceConflictError(
                resource_type="conversation",
                resource_id=record.conversation_id,
                expected_revision=0,
                actual_revision=len(self._records[record.conversation_id].turns),
            )
        self._records[record.conversation_id] = record

    def get(self, conversation_id: str) -> ConversationRecord | None:
        return self._records.get(conversation_id)

    def append_turn(
        self,
        conversation_id: str,
        turn: ConversationTurn,
        *,
        expected_turn_count: int,
    ) -> ConversationRecord:
        current = self._records.get(conversation_id)
        if current is None:
            raise PersistenceNotFoundError(
                resource_type="conversation", resource_id=conversation_id
            )
        if len(current.turns) != expected_turn_count:
            raise PersistenceConflictError(
                resource_type="conversation",
                resource_id=conversation_id,
                expected_revision=expected_turn_count,
                actual_revision=len(current.turns),
            )
        if any(existing.turn_id == turn.turn_id for existing in current.turns):
            raise PersistenceConflictError(
                resource_type="conversation_turn",
                resource_id=turn.turn_id,
                expected_revision=0,
                actual_revision=1,
            )
        updated = current.model_copy(
            update={"updated_at": turn.created_at, "turns": (*current.turns, turn)}
        )
        self._records[conversation_id] = updated
        return updated


class _InMemoryCaseMemoryRepository:
    def __init__(self) -> None:
        self._records: dict[str, MemoryRecord] = {}

    def admit(self, admission: CaseMemoryAdmission) -> MemoryRecord:
        candidate = admission.candidate
        record = MemoryRecord(
            memory_id=f"memory-{len(self._records) + 1}",
            scope=candidate.scope,
            case_id=candidate.case_id,
            subject_ref=candidate.subject_ref,
            agent_id=candidate.agent_id,
            summary=candidate.summary,
            facts=candidate.facts,
            source_run_id=candidate.source_run_id,
            source_turn_id=candidate.source_turn_id,
            created_at=admission.admitted_at,
            expires_at=candidate.expires_at,
            sensitivity=candidate.sensitivity,
        )
        self._records[record.memory_id] = record
        return record

    def read(self, query: MemoryQuery, *, as_of: str) -> tuple[MemoryRecord, ...]:
        return tuple(
            record
            for record in self._records.values()
            if record.scope is MemoryScope.CASE
            and record.case_id == query.case_id
            and record.agent_id == query.agent_id
            and record.status is MemoryStatus.ACTIVE
            and record.expires_at > as_of
        )[: query.max_records]

    def expire_due(self, *, as_of: str) -> int:
        expired = 0
        for memory_id, record in tuple(self._records.items()):
            if record.status is MemoryStatus.ACTIVE and record.expires_at <= as_of:
                self._records[memory_id] = record.model_copy(
                    update={"status": MemoryStatus.DELETED}
                )
                expired += 1
        return expired


class _InMemoryAuditRepository:
    def __init__(self) -> None:
        self._events: dict[str, AuditMetadataRecord] = {}

    def append(self, event: AuditMetadataRecord) -> None:
        if event.audit_id in self._events:
            raise PersistenceConflictError(
                resource_type="audit_event",
                resource_id=event.audit_id,
                expected_revision=0,
                actual_revision=1,
            )
        self._events[event.audit_id] = event

    def get(self, audit_id: str) -> AuditMetadataRecord | None:
        return self._events.get(audit_id)


class _InMemoryConfigurationUnitOfWork:
    def __init__(self) -> None:
        agent_repository = _InMemoryAgentLifecycleRepository()
        self.agents: AgentLifecycleRepository = agent_repository
        self._agent_repository = agent_repository
        empty = _InMemorySharedAssetRepository(())
        self.knowledge: KnowledgeAssetRepository = empty
        self.models: ModelAssetRepository = empty
        self.tools: ToolAssetRepository = empty
        audit_repository = _InMemoryAuditRepository()
        self.audit: AuditRepository = audit_repository
        self._audit_repository = audit_repository
        self._agent_snapshot: tuple[
            dict[tuple[str, str], AgentDraftRecord],
            dict[tuple[str, str], AgentPublicationRecord],
            dict[str, ActiveAgentVersion],
        ] | None = None
        self._audit_snapshot: dict[str, AuditMetadataRecord] | None = None
        self._committed = False

    def __enter__(self) -> "_InMemoryConfigurationUnitOfWork":
        self._agent_snapshot = (
            dict(self._agent_repository._drafts),
            dict(self._agent_repository._published),
            dict(self._agent_repository._active),
        )
        self._audit_snapshot = dict(self._audit_repository._events)
        self._committed = False
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is not None or not self._committed:
            self.rollback()

    def commit(self) -> None:
        self._committed = True

    def rollback(self) -> None:
        if self._agent_snapshot is not None:
            drafts, published, active = self._agent_snapshot
            self._agent_repository._drafts = drafts
            self._agent_repository._published = published
            self._agent_repository._active = active
        if self._audit_snapshot is not None:
            self._audit_repository._events = self._audit_snapshot


def _draft(*, purpose: str = "Answer insurance product questions") -> DraftAgent:
    return DraftAgent(
        agent_id="agent_management_insurance_specialist",
        draft_id="draft_01",
        display_name="Insurance Specialist",
        purpose=purpose,
        contract_bundle=ContractBundle(
            agent_yaml="schema_version: 3\n",
            policy_yaml="rules: []\n",
            tools_yaml="tools: []\n",
        ),
        created_at="2026-07-15T00:00:00Z",
        updated_at="2026-07-15T00:00:00Z",
        created_by="operator-1",
        updated_by="operator-1",
    )


def _round_trip_draft(repository: AgentLifecycleRepository) -> AgentDraftRecord:
    saved = repository.save_draft(_draft(), expected_revision=0)
    loaded = repository.get_draft(saved.draft.agent_id, saved.draft.draft_id)
    assert loaded == saved
    return saved


def _publication() -> AgentPublicationRecord:
    draft = _draft()
    version = PublishedAgentVersion(
        agent_id=draft.agent_id,
        version_id="v1",
        source_draft_id=draft.draft_id,
        validation_run_id="validation-1",
        display_name=draft.display_name,
        purpose=draft.purpose,
        contract_bundle=draft.contract_bundle,
        published_at="2026-07-15T00:01:00Z",
        published_by="operator-1",
    )
    activation = ActiveAgentVersion(
        agent_id=draft.agent_id,
        version_id=version.version_id,
        activated_at=version.published_at,
        activated_by=version.published_by,
    )
    return AgentPublicationRecord(version=version, activation=activation, draft_revision=1)


def test_agent_lifecycle_port_saves_and_reads_revisioned_draft() -> None:
    repository = _InMemoryAgentLifecycleRepository()

    first = _round_trip_draft(repository)
    second = repository.save_draft(_draft(purpose="Updated purpose"), expected_revision=1)

    assert first.revision == 1
    assert second.revision == 2
    assert second.draft.purpose == "Updated purpose"


def test_agent_lifecycle_port_rejects_stale_draft_revision() -> None:
    repository = _InMemoryAgentLifecycleRepository()
    _round_trip_draft(repository)

    try:
        repository.save_draft(_draft(purpose="Stale update"), expected_revision=0)
    except PersistenceConflictError as exc:
        assert exc.resource_type == "agent_draft"
        assert exc.resource_id == "draft_01"
        assert exc.expected_revision == 0
        assert exc.actual_revision == 1
    else:
        raise AssertionError("stale draft update must fail")


def test_agent_lifecycle_port_atomically_publishes_and_activates_version() -> None:
    repository = _InMemoryAgentLifecycleRepository()
    _round_trip_draft(repository)
    publication = _publication()

    saved = repository.publish_version(publication, expected_draft_revision=1)

    assert saved == publication
    assert repository.get_published(publication.version.agent_id, "v1") == publication.version
    assert repository.list_published(publication.version.agent_id) == (publication.version,)
    assert repository.get_active(publication.version.agent_id) == publication.activation


def test_agent_lifecycle_port_publish_conflict_leaves_no_partial_version() -> None:
    repository = _InMemoryAgentLifecycleRepository()
    _round_trip_draft(repository)
    publication = _publication()

    try:
        repository.publish_version(publication, expected_draft_revision=0)
    except PersistenceConflictError:
        pass
    else:
        raise AssertionError("stale publication must fail")

    assert repository.get_published(publication.version.agent_id, "v1") is None
    assert repository.get_active(publication.version.agent_id) is None


def test_shared_asset_ports_resolve_exact_immutable_versions() -> None:
    knowledge_ref = SharedAssetVersionRef(
        kind=SharedAssetKind.KNOWLEDGE_SOURCE,
        asset_id="insurance-clauses",
        version_id="snapshot-7",
        revision=7,
        content_digest="a" * 64,
    )
    model_ref = SharedAssetVersionRef(
        kind=SharedAssetKind.MODEL_CONNECTION,
        asset_id="answer-model",
        version_id="model-config-3",
        revision=3,
        content_digest="b" * 64,
    )
    tool_ref = SharedAssetVersionRef(
        kind=SharedAssetKind.TOOL_SOURCE,
        asset_id="policy-lookup",
        version_id="tool-config-2",
        revision=2,
        content_digest="c" * 64,
    )
    knowledge: KnowledgeAssetRepository = _InMemorySharedAssetRepository((knowledge_ref,))
    models: ModelAssetRepository = _InMemorySharedAssetRepository((model_ref,))
    tools: ToolAssetRepository = _InMemorySharedAssetRepository((tool_ref,))

    resolved = resolve_shared_asset_versions(
        (
            SharedAssetVersionRequest(
                kind=knowledge_ref.kind,
                asset_id=knowledge_ref.asset_id,
                version_id=knowledge_ref.version_id,
            ),
            SharedAssetVersionRequest(
                kind=model_ref.kind,
                asset_id=model_ref.asset_id,
                version_id=model_ref.version_id,
            ),
            SharedAssetVersionRequest(
                kind=tool_ref.kind,
                asset_id=tool_ref.asset_id,
                version_id=tool_ref.version_id,
            ),
        ),
        knowledge=knowledge,
        models=models,
        tools=tools,
    )

    assert resolved == ResolvedSharedAssetVersions(
        versions=(knowledge_ref, model_ref, tool_ref)
    )


def test_shared_asset_resolution_fails_closed_when_version_is_missing() -> None:
    empty = _InMemorySharedAssetRepository(())

    try:
        resolve_shared_asset_versions(
            (
                SharedAssetVersionRequest(
                    kind=SharedAssetKind.KNOWLEDGE_SOURCE,
                    asset_id="missing",
                    version_id="snapshot-1",
                ),
            ),
            knowledge=empty,
            models=empty,
            tools=empty,
        )
    except PersistenceNotFoundError as exc:
        assert exc.resource_type == "knowledge_source_version"
        assert exc.resource_id == "missing:snapshot-1"
    else:
        raise AssertionError("missing immutable asset version must fail closed")


def test_run_metadata_port_appends_and_reads_trace_safe_metadata() -> None:
    repository: RunMetadataRepository = _InMemoryRunMetadataRepository()
    record = RunMetadataRecord(
        run_id="019ba001-1111-7000-8000-000000000001",
        state=RunLifecycleState.QUEUED,
        state_version=1,
        run_purpose=RunPurpose.PRODUCTION,
        agent_id="agent_management_insurance_specialist",
        agent_version_id="v1",
        submitted_by="operator-1",
        created_at="2026-07-15T00:00:00Z",
        updated_at="2026-07-15T00:00:00Z",
    )

    repository.append(record)

    assert repository.get(record.run_id) == record
    assert "question" not in record.model_dump()
    assert "raw_prompt" not in record.model_dump()


def test_conversation_port_appends_an_ordered_governed_turn() -> None:
    repository: ConversationRepository = _InMemoryConversationRepository()
    conversation = ConversationRecord(
        conversation_id="019ba001-1111-7000-8000-000000000002",
        agent_id="agent_management_insurance_specialist",
        created_at="2026-07-15T00:00:00Z",
        updated_at="2026-07-15T00:00:00Z",
    )
    turn = ConversationTurn(
        turn_id="019ba001-1111-7000-8000-000000000003",
        run_id="019ba001-1111-7000-8000-000000000001",
        agent_id=conversation.agent_id,
        question="等待期如何规定？",
        final_output="依据产品条款，等待期为……",
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        created_at="2026-07-15T00:01:00Z",
        context_admission=ContextAdmission(admitted=False),
    )
    repository.create(conversation)

    updated = repository.append_turn(
        conversation.conversation_id,
        turn,
        expected_turn_count=0,
    )

    assert updated.turns == (turn,)
    assert repository.get(conversation.conversation_id) == updated


def _case_memory_candidate(*, expires_at: str) -> MemoryCandidate:
    return MemoryCandidate(
        scope=MemoryScope.CASE,
        case_id="conversation-1",
        agent_id="agent_management_insurance_specialist",
        summary="当前关注等待期与续保条件。",
        facts={"case_focus": ["waiting_period", "renewal"]},
        source_run_id="019ba001-1111-7000-8000-000000000001",
        source_turn_id="019ba001-1111-7000-8000-000000000003",
        expires_at=expires_at,
    )


def test_case_memory_port_admits_reads_and_expires_thirty_day_memory() -> None:
    repository: CaseMemoryRepository = _InMemoryCaseMemoryRepository()
    admission = CaseMemoryAdmission(
        candidate=_case_memory_candidate(expires_at="2026-08-14T00:00:00Z"),
        admitted_at="2026-07-15T00:00:00Z",
    )
    stored = repository.admit(admission)
    query = MemoryQuery(
        scope=MemoryScope.CASE,
        case_id="conversation-1",
        agent_id="agent_management_insurance_specialist",
    )

    assert repository.read(query, as_of="2026-08-13T23:59:59Z") == (stored,)
    assert repository.expire_due(as_of="2026-08-14T00:00:00Z") == 1
    assert repository.read(query, as_of="2026-08-14T00:00:00Z") == ()


def test_case_memory_admission_rejects_user_scope_and_overlong_retention() -> None:
    user_candidate = _case_memory_candidate(
        expires_at="2026-08-14T00:00:00Z"
    ).model_copy(update={"scope": MemoryScope.USER, "subject_ref": "oidc-subject"})

    for candidate in (
        user_candidate,
        _case_memory_candidate(expires_at="2026-08-14T00:00:01Z"),
    ):
        try:
            CaseMemoryAdmission(
                candidate=candidate,
                admitted_at="2026-07-15T00:00:00Z",
            )
        except ValidationError:
            pass
        else:
            raise AssertionError("invalid initial-production Case Memory must be rejected")


def test_audit_port_appends_trace_safe_actor_and_operation_metadata() -> None:
    repository: AuditRepository = _InMemoryAuditRepository()
    event = AuditMetadataRecord(
        audit_id="019ba001-1111-7000-8000-000000000004",
        category=AuditCategory.CONFIGURATION,
        event_type="agent.version.published",
        outcome=AuditOutcome.SUCCEEDED,
        actor=AuditActorFacts(
            subject="operator-1",
            identity_provider="enterprise-oidc",
            session_id="session-1",
            permissions=("agent.publish",),
            matched_groups=("insurance-ops",),
        ),
        occurred_at="2026-07-15T00:01:00Z",
        target_type="agent_version",
        target_id="agent_management_insurance_specialist:v1",
        metadata={"draft_revision": 1, "shared_asset_count": 3},
    )

    repository.append(event)

    assert repository.get(event.audit_id) == event


def test_audit_metadata_rejects_secret_or_raw_payload_fields() -> None:
    for metadata in (
        {"api_key": "must-not-persist"},
        {"nested": {"raw_prompt": "must-not-persist"}},
    ):
        try:
            AuditMetadataRecord(
                audit_id="019ba001-1111-7000-8000-000000000005",
                category=AuditCategory.SECURITY,
                event_type="secret_handle.resolved",
                outcome=AuditOutcome.SUCCEEDED,
                actor=AuditActorFacts(
                    subject="operator-1",
                    identity_provider="enterprise-oidc",
                    session_id="session-1",
                ),
                occurred_at="2026-07-15T00:01:00Z",
                target_type="secret_handle",
                target_id="model-provider-primary",
                metadata=metadata,
            )
        except ValidationError:
            pass
        else:
            raise AssertionError("audit metadata must reject secret or raw fields")


def test_configuration_unit_of_work_rolls_back_multiple_repositories() -> None:
    uow: ConfigurationUnitOfWork = _InMemoryConfigurationUnitOfWork()
    audit = AuditMetadataRecord(
        audit_id="019ba001-1111-7000-8000-000000000006",
        category=AuditCategory.CONFIGURATION,
        event_type="agent.draft.saved",
        outcome=AuditOutcome.SUCCEEDED,
        actor=AuditActorFacts(
            subject="operator-1",
            identity_provider="enterprise-oidc",
            session_id="session-1",
        ),
        occurred_at="2026-07-15T00:00:00Z",
        target_type="agent_draft",
        target_id="draft_01",
    )

    try:
        with uow:
            uow.agents.save_draft(_draft(), expected_revision=0)
            uow.audit.append(audit)
            raise RuntimeError("simulated publication failure")
    except RuntimeError:
        pass

    assert uow.agents.get_draft(_draft().agent_id, _draft().draft_id) is None
    assert uow.audit.get(audit.audit_id) is None
