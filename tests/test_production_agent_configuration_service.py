from __future__ import annotations

from datetime import UTC, datetime
from types import TracebackType

import pytest

from proof_agent.contracts import (
    AgentDraftRecord,
    AuditActorFacts,
    AuditMetadataRecord,
    ConfigurationOperation,
    ContractBundle,
    DraftAgent,
)
from proof_agent.contracts.persistence import PersistenceConflictError
from proof_agent.control.production_agent_configuration import (
    SOLE_PRODUCTION_AGENT_ID,
    ProductionAgentConfigurationConflict,
    ProductionAgentConfigurationNotFound,
    ProductionAgentConfigurationService,
)


class InMemoryAgentRepository:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], AgentDraftRecord] = {}

    def list_drafts(self, agent_id: str | None = None) -> tuple[AgentDraftRecord, ...]:
        records = tuple(self.records.values())
        if agent_id is not None:
            records = tuple(item for item in records if item.draft.agent_id == agent_id)
        return tuple(sorted(records, key=lambda item: item.draft.updated_at))

    def get_draft(self, agent_id: str, draft_id: str) -> AgentDraftRecord | None:
        return self.records.get((agent_id, draft_id))

    def save_draft(
        self,
        draft: DraftAgent,
        *,
        expected_revision: int,
    ) -> AgentDraftRecord:
        key = (draft.agent_id, draft.draft_id)
        existing = self.records.get(key)
        actual_revision = None if existing is None else existing.revision
        if (expected_revision == 0 and existing is not None) or (
            expected_revision > 0 and actual_revision != expected_revision
        ):
            raise PersistenceConflictError(
                resource_type="agent_draft",
                resource_id=draft.draft_id,
                expected_revision=expected_revision,
                actual_revision=actual_revision,
            )
        record = AgentDraftRecord(
            draft=draft,
            revision=1 if existing is None else existing.revision + 1,
        )
        self.records[key] = record
        return record

    def list_published(self, agent_id: str) -> tuple[object, ...]:
        del agent_id
        return ()

    def get_active(self, agent_id: str) -> None:
        del agent_id
        return None


class InMemoryAuditRepository:
    def __init__(self) -> None:
        self.events: list[AuditMetadataRecord] = []

    def append(self, event: AuditMetadataRecord) -> None:
        self.events.append(event)


class InMemoryUnitOfWork:
    def __init__(
        self,
        agents: InMemoryAgentRepository,
        audit: InMemoryAuditRepository,
    ) -> None:
        self.agents = agents
        self.audit = audit
        self.commits = 0

    def __enter__(self) -> "InMemoryUnitOfWork":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback

    def commit(self) -> None:
        self.commits += 1


class UnitOfWorkFactory:
    def __init__(self, agents: InMemoryAgentRepository | None = None) -> None:
        self.agents = agents or InMemoryAgentRepository()
        self.audit = InMemoryAuditRepository()
        self.units: list[InMemoryUnitOfWork] = []

    def __call__(self) -> InMemoryUnitOfWork:
        unit = InMemoryUnitOfWork(self.agents, self.audit)
        self.units.append(unit)
        return unit


def _service(factory: UnitOfWorkFactory) -> ProductionAgentConfigurationService:
    return ProductionAgentConfigurationService(
        unit_of_work_factory=factory,
        template_bundle=ContractBundle(
            agent_yaml=(
                "name: agent_management_insurance_specialist\n"
                "purpose: Canonical governed insurance assistance.\n"
                "workflow:\n"
                "  template: react_enterprise_qa_v3\n"
            ),
            policy_yaml="rules: []\n",
            tools_yaml="tools: []\n",
        ),
        clock=lambda: datetime(2026, 8, 12, tzinfo=UTC),
    )


def _actor() -> AuditActorFacts:
    return AuditActorFacts(
        subject="operator-1",
        identity_provider="enterprise-oidc",
        session_id="session-1",
        permissions=("agent.edit",),
    )


def test_create_draft_atomically_saves_server_template_and_trace_safe_audit() -> None:
    factory = UnitOfWorkFactory()
    service = _service(factory)

    result = service.create_draft(
        display_name="Insurance Specialist",
        purpose="Answer governed insurance questions.",
        idempotency_key="create-agent-attempt-1",
        actor=_actor(),
    )

    assert result.replayed is False
    assert result.record.revision == 1
    draft = result.record.draft
    assert draft.agent_id == SOLE_PRODUCTION_AGENT_ID
    assert draft.display_name == "Insurance Specialist"
    assert draft.purpose == "Answer governed insurance questions."
    assert draft.contract_bundle.agent_yaml.startswith(
        "name: agent_management_insurance_specialist\n"
    )
    assert draft.operation_audit[0].operation is ConfigurationOperation.CREATED
    operation_metadata = dict(draft.operation_audit[0].metadata)
    assert operation_metadata["request_fingerprint"].startswith("sha256:")
    assert operation_metadata["idempotency_key_sha256"].startswith("sha256:")
    assert "create-agent-attempt-1" not in repr(operation_metadata)
    assert factory.units[0].commits == 1
    assert len(factory.audit.events) == 1
    event = factory.audit.events[0]
    assert event.event_type == "agent.draft.created"
    assert event.target_type == "agent_draft"
    assert event.target_id == draft.draft_id
    assert event.actor == _actor()
    assert "create-agent-attempt-1" not in repr(event.metadata)


def test_create_draft_replays_the_same_idempotent_request_without_new_writes() -> None:
    factory = UnitOfWorkFactory()
    service = _service(factory)
    request = {
        "display_name": "Insurance Specialist",
        "purpose": "Answer governed insurance questions.",
        "idempotency_key": "create-agent-attempt-1",
        "actor": _actor(),
    }

    first = service.create_draft(**request)
    replay = service.create_draft(**request)

    assert replay.replayed is True
    assert replay.record == first.record
    assert len(factory.agents.records) == 1
    assert len(factory.audit.events) == 1
    assert sum(unit.commits for unit in factory.units) == 1


def test_concurrent_same_request_resolves_to_the_committed_winner() -> None:
    factory = UnitOfWorkFactory(_ConcurrentWinnerAgentRepository())
    service = _service(factory)

    result = service.create_draft(
        display_name="Insurance Specialist",
        purpose="Answer governed insurance questions.",
        idempotency_key="create-agent-attempt-1",
        actor=_actor(),
    )

    assert result.replayed is True
    assert result.record.revision == 1
    assert len(factory.agents.records) == 1
    assert factory.audit.events == []
    assert sum(unit.commits for unit in factory.units) == 0


def test_agent_inventory_exposes_the_single_latest_draft_and_create_capability() -> None:
    factory = UnitOfWorkFactory()
    service = _service(factory)

    empty = service.list_agents()
    created = service.create_draft(
        display_name="Insurance Specialist",
        purpose="Answer governed insurance questions.",
        idempotency_key="create-agent-attempt-1",
        actor=_actor(),
    )
    inventory = service.list_agents()

    assert empty.agents == ()
    assert empty.can_create is True
    assert inventory.can_create is False
    assert len(inventory.agents) == 1
    summary = inventory.agents[0]
    assert summary.agent_id == SOLE_PRODUCTION_AGENT_ID
    assert summary.display_name == created.record.draft.display_name
    assert summary.draft_count == 1
    assert summary.latest_draft_id == created.record.draft.draft_id
    assert summary.version_count == 0
    assert summary.active_version_id is None


def test_update_draft_uses_revision_cas_and_appends_audit_in_the_same_unit() -> None:
    factory = UnitOfWorkFactory()
    service = _service(factory)
    created = service.create_draft(
        display_name="Insurance Specialist",
        purpose="Answer governed insurance questions.",
        idempotency_key="create-agent-attempt-1",
        actor=_actor(),
    )

    updated = service.update_draft(
        agent_id=SOLE_PRODUCTION_AGENT_ID,
        draft_id=created.record.draft.draft_id,
        expected_revision=1,
        display_name="Governed Insurance Specialist",
        purpose=None,
        actor=_actor(),
    )

    assert updated.revision == 2
    assert updated.draft.display_name == "Governed Insurance Specialist"
    assert updated.draft.purpose == created.record.draft.purpose
    assert updated.draft.created_at == created.record.draft.created_at
    assert updated.draft.operation_audit[-1].operation is ConfigurationOperation.UPDATED
    assert updated.draft.operation_audit[-1].metadata == {"expected_revision": 1}
    assert factory.units[-1].commits == 1
    assert [event.event_type for event in factory.audit.events] == [
        "agent.draft.created",
        "agent.draft.updated",
    ]


def test_create_draft_rejects_idempotency_mismatch_and_second_initialization() -> None:
    factory = UnitOfWorkFactory()
    service = _service(factory)
    service.create_draft(
        display_name="Insurance Specialist",
        purpose="Answer governed insurance questions.",
        idempotency_key="create-agent-attempt-1",
        actor=_actor(),
    )

    with pytest.raises(ProductionAgentConfigurationConflict) as mismatch:
        service.create_draft(
            display_name="Different name",
            purpose="Answer governed insurance questions.",
            idempotency_key="create-agent-attempt-1",
            actor=_actor(),
        )
    with pytest.raises(ProductionAgentConfigurationConflict) as duplicate:
        service.create_draft(
            display_name="Insurance Specialist",
            purpose="Answer governed insurance questions.",
            idempotency_key="create-agent-attempt-2",
            actor=_actor(),
        )

    assert mismatch.value.code == "idempotency_key_mismatch"
    assert duplicate.value.code == "sole_agent_already_exists"
    assert len(factory.audit.events) == 1


def test_read_history_and_revision_conflicts_are_stable_application_results() -> None:
    factory = UnitOfWorkFactory()
    service = _service(factory)
    created = service.create_draft(
        display_name="Insurance Specialist",
        purpose="Answer governed insurance questions.",
        idempotency_key="create-agent-attempt-1",
        actor=_actor(),
    )

    assert service.get_draft(
        agent_id=SOLE_PRODUCTION_AGENT_ID,
        draft_id=created.record.draft.draft_id,
    ) == created.record
    assert service.list_versions(agent_id=SOLE_PRODUCTION_AGENT_ID).versions == ()

    with pytest.raises(ProductionAgentConfigurationConflict) as stale:
        service.update_draft(
            agent_id=SOLE_PRODUCTION_AGENT_ID,
            draft_id=created.record.draft.draft_id,
            expected_revision=2,
            display_name="Stale update",
            purpose=None,
            actor=_actor(),
        )
    with pytest.raises(ProductionAgentConfigurationNotFound) as unknown:
        service.get_draft(agent_id="unknown", draft_id=created.record.draft.draft_id)
    with pytest.raises(ProductionAgentConfigurationNotFound) as malformed:
        service.get_draft(
            agent_id=SOLE_PRODUCTION_AGENT_ID,
            draft_id="not-a-production-draft-id",
        )

    assert stale.value.code == "agent_draft_revision_conflict"
    assert unknown.value.code == "agent_not_found"
    assert malformed.value.code == "agent_draft_not_found"
    assert len(factory.audit.events) == 1


class _ConcurrentWinnerAgentRepository(InMemoryAgentRepository):
    """Simulate another transaction committing the deterministic Draft first."""

    def save_draft(
        self,
        draft: DraftAgent,
        *,
        expected_revision: int,
    ) -> AgentDraftRecord:
        if expected_revision == 0 and not self.records:
            winner = AgentDraftRecord(draft=draft, revision=1)
            self.records[(draft.agent_id, draft.draft_id)] = winner
            raise PersistenceConflictError(
                resource_type="agent_draft",
                resource_id=draft.draft_id,
                expected_revision=0,
                actual_revision=1,
            )
        return super().save_draft(draft, expected_revision=expected_revision)
