from pathlib import Path

import pytest

from proof_agent.capabilities.persistence.local import LocalPersistenceBundle
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import (
    ActiveAgentPointerExpectation,
    ActiveAgentVersion,
    AgentPublicationRecord,
    AuditActorFacts,
    AuditCategory,
    AuditMetadataRecord,
    AuditOutcome,
    CaseMemoryAdmission,
    ContextAdmission,
    ContractBundle,
    ConversationRecord,
    ConversationTurn,
    DraftAgent,
    EnvironmentModelCredentialReference,
    MemoryCandidate,
    MemoryQuery,
    MemoryScope,
    PersistenceConflictError,
    PersistencePointerConflictError,
    PublishedAgentVersion,
    ReceiptOutcome,
    RunLifecycleState,
    RunAttemptMetadataRecord,
    RunMetadataRecord,
    RunPurpose,
    SharedAssetKind,
)


def _draft(*, purpose: str) -> DraftAgent:
    return DraftAgent(
        agent_id="agent_management_insurance_specialist",
        draft_id="draft-local-1",
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


def test_local_bundle_persists_optimistic_draft_revision_across_restarts(
    tmp_path: Path,
) -> None:
    first_bundle = LocalPersistenceBundle.create(tmp_path)
    first = first_bundle.agents.save_draft(
        _draft(purpose="Initial purpose"),
        expected_revision=0,
    )

    restarted_bundle = LocalPersistenceBundle.create(tmp_path)
    second = restarted_bundle.agents.save_draft(
        _draft(purpose="Updated purpose"),
        expected_revision=first.revision,
    )

    assert first.revision == 1
    assert second.revision == 2
    assert restarted_bundle.agents.get_draft(
        second.draft.agent_id,
        second.draft.draft_id,
    ) == second


def _publication(draft: DraftAgent, *, draft_revision: int) -> AgentPublicationRecord:
    version = PublishedAgentVersion(
        agent_id=draft.agent_id,
        version_id="version-local-1",
        source_draft_id=draft.draft_id,
        validation_run_id="validation-local-1",
        display_name=draft.display_name,
        purpose=draft.purpose,
        contract_bundle=draft.contract_bundle,
        published_at="2026-07-15T00:01:00Z",
        published_by="operator-1",
    )
    return AgentPublicationRecord(
        version=version,
        activation=ActiveAgentVersion(
            agent_id=draft.agent_id,
            version_id=version.version_id,
            activated_at=version.published_at,
            activated_by=version.published_by,
        ),
        draft_revision=draft_revision,
    )


def test_local_bundle_atomically_publishes_prepared_version(tmp_path: Path) -> None:
    bundle = LocalPersistenceBundle.create(tmp_path)
    draft = bundle.agents.save_draft(_draft(purpose="Purpose"), expected_revision=0)
    publication = _publication(draft.draft, draft_revision=draft.revision)

    saved = bundle.agents.publish_version(
        publication,
        expected_draft_revision=draft.revision,
    )

    assert saved == publication
    assert bundle.agents.get_published(draft.draft.agent_id, "version-local-1") == (
        publication.version
    )
    assert bundle.agents.get_active(draft.draft.agent_id) == publication.activation


def test_local_bundle_publish_conflict_leaves_no_partial_state(tmp_path: Path) -> None:
    bundle = LocalPersistenceBundle.create(tmp_path)
    draft = bundle.agents.save_draft(_draft(purpose="Purpose"), expected_revision=0)
    publication = _publication(draft.draft, draft_revision=draft.revision)

    try:
        bundle.agents.publish_version(publication, expected_draft_revision=0)
    except PersistenceConflictError:
        pass
    else:
        raise AssertionError("stale local publication must fail")

    assert bundle.agents.get_published(draft.draft.agent_id, "version-local-1") is None
    assert bundle.agents.get_active(draft.draft.agent_id) is None


def test_local_bundle_rejects_stale_active_pointer_expectation(tmp_path: Path) -> None:
    bundle = LocalPersistenceBundle.create(tmp_path)
    first_draft = bundle.agents.save_draft(
        _draft(purpose="First purpose"), expected_revision=0
    )
    first = _publication(first_draft.draft, draft_revision=first_draft.revision)
    bundle.agents.publish_version(first, expected_draft_revision=first_draft.revision)
    second_draft_value = _draft(purpose="Second purpose").model_copy(
        update={"draft_id": "draft-local-2"}
    )
    second_draft = bundle.agents.save_draft(second_draft_value, expected_revision=0)
    second = _publication(
        second_draft.draft, draft_revision=second_draft.revision
    ).model_copy(
        update={
            "version": _publication(
                second_draft.draft, draft_revision=second_draft.revision
            ).version.model_copy(update={"version_id": "version-local-2"}),
            "activation": ActiveAgentVersion(
                agent_id=second_draft.draft.agent_id,
                version_id="version-local-2",
                activated_at="2026-07-15T00:02:00Z",
                activated_by="operator-2",
            ),
            "active_pointer_expectation": ActiveAgentPointerExpectation(version_id=None),
        }
    )

    with pytest.raises(PersistencePointerConflictError):
        bundle.agents.publish_version(
            second,
            expected_draft_revision=second_draft.revision,
        )

    assert bundle.agents.get_published(
        second.version.agent_id, second.version.version_id
    ) is None
    assert bundle.agents.get_active(first.version.agent_id) == first.activation


def test_local_bundle_resolves_current_model_connection_to_content_addressed_version(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path / "configuration")
    store.create_model_connection(
        connection_id="answer-model",
        display_name="Answer Model",
        provider="openai",
        model_identifier="gpt-test",
        credential_ref=EnvironmentModelCredentialReference(type="env", name="MODEL_API_KEY"),
        actor="operator-1",
    )
    bundle = LocalPersistenceBundle.create(tmp_path)

    resolved = bundle.models.resolve_version("answer-model")

    assert resolved is not None
    assert resolved.kind is SharedAssetKind.MODEL_CONNECTION
    assert resolved.asset_id == "answer-model"
    assert resolved.version_id.startswith("model:")
    assert len(resolved.content_digest) == 64
    assert bundle.models.resolve_version(
        "answer-model", version_id=resolved.version_id
    ) == resolved
    assert bundle.models.resolve_version("answer-model", version_id="model:stale") is None


def test_local_bundle_persists_trace_safe_run_metadata_separately(tmp_path: Path) -> None:
    bundle = LocalPersistenceBundle.create(tmp_path)
    record = RunMetadataRecord(
        run_id="019ba001-1111-7000-8000-000000000010",
        state=RunLifecycleState.QUEUED,
        state_version=1,
        run_purpose=RunPurpose.PRODUCTION,
        agent_id="agent_management_insurance_specialist",
        agent_version_id="v1",
        submitted_by="operator-1",
        created_at="2026-07-15T00:00:00Z",
        updated_at="2026-07-15T00:00:00Z",
    )

    bundle.runs.append(record)

    restarted = LocalPersistenceBundle.create(tmp_path)
    persisted = restarted.runs.get(record.run_id)
    assert persisted == record
    assert persisted is not None
    assert "question" not in persisted.model_dump()


def test_local_bundle_matches_run_attempt_conditional_port(tmp_path: Path) -> None:
    bundle = LocalPersistenceBundle.create(tmp_path)
    attempt = RunAttemptMetadataRecord(
        attempt_id="019ba001-1111-7000-8000-000000000020",
        run_id="019ba001-1111-7000-8000-000000000010",
        attempt_number=1,
        state=RunLifecycleState.RUNNING,
        state_version=1,
        fencing_token=1,
        lease_owner="local-executor",
        lease_expires_at="2026-07-15T00:02:00Z",
        created_at="2026-07-15T00:01:00Z",
        updated_at="2026-07-15T00:01:00Z",
    )
    bundle.runs.append_attempt(attempt)
    finalizing = attempt.model_copy(
        update={
            "state": RunLifecycleState.FINALIZING,
            "state_version": 2,
            "updated_at": "2026-07-15T00:01:30Z",
        }
    )

    assert bundle.runs.transition_attempt(
        finalizing,
        expected_state_version=1,
        expected_fencing_token=1,
    ) == finalizing
    assert LocalPersistenceBundle.create(tmp_path).runs.get_attempt(attempt.attempt_id) == (
        finalizing
    )


def test_local_bundle_conditionally_appends_conversation_turn(tmp_path: Path) -> None:
    bundle = LocalPersistenceBundle.create(tmp_path)
    conversation = ConversationRecord(
        conversation_id="019ba001-1111-7000-8000-000000000011",
        agent_id="agent_management_insurance_specialist",
        created_at="2026-07-15T00:00:00Z",
        updated_at="2026-07-15T00:00:00Z",
    )
    turn = ConversationTurn(
        turn_id="019ba001-1111-7000-8000-000000000012",
        run_id="019ba001-1111-7000-8000-000000000010",
        agent_id=conversation.agent_id,
        question="等待期如何规定？",
        final_output="依据条款……",
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        created_at="2026-07-15T00:01:00Z",
        context_admission=ContextAdmission(admitted=False),
    )
    bundle.conversations.create(conversation)

    updated = bundle.conversations.append_turn(
        conversation.conversation_id,
        turn,
        expected_turn_count=0,
    )

    assert updated.turns == (turn,)
    assert LocalPersistenceBundle.create(tmp_path).conversations.get(
        conversation.conversation_id
    ) == updated


def test_local_bundle_hides_case_memory_at_expiry(tmp_path: Path) -> None:
    bundle = LocalPersistenceBundle.create(tmp_path)
    admission = CaseMemoryAdmission(
        candidate=MemoryCandidate(
            scope=MemoryScope.CASE,
            case_id="019ba001-1111-7000-8000-000000000011",
            agent_id="agent_management_insurance_specialist",
            summary="关注等待期。",
            facts={"case_focus": ["waiting_period"]},
            source_run_id="019ba001-1111-7000-8000-000000000010",
            source_turn_id="019ba001-1111-7000-8000-000000000012",
            expires_at="2026-08-14T00:00:00Z",
        ),
        admitted_at="2026-07-15T00:00:00Z",
    )
    stored = bundle.case_memory.admit(admission)
    query = MemoryQuery(
        scope=MemoryScope.CASE,
        case_id=admission.candidate.case_id,
        agent_id=admission.candidate.agent_id,
    )

    assert bundle.case_memory.read(query, as_of="2026-08-13T23:59:59Z") == (stored,)
    assert bundle.case_memory.expire_due(as_of="2026-08-14T00:00:00Z") == 1
    assert bundle.case_memory.read(query, as_of="2026-08-14T00:00:00Z") == ()


def test_local_bundle_persists_append_only_audit_metadata(tmp_path: Path) -> None:
    bundle = LocalPersistenceBundle.create(tmp_path)
    event = AuditMetadataRecord(
        audit_id="019ba001-1111-7000-8000-000000000013",
        category=AuditCategory.CONFIGURATION,
        event_type="agent.version.published",
        outcome=AuditOutcome.SUCCEEDED,
        actor=AuditActorFacts(
            subject="operator-1",
            identity_provider="enterprise-oidc",
            session_id="session-1",
            permissions=("agent.publish",),
        ),
        occurred_at="2026-07-15T00:01:00Z",
        target_type="agent_version",
        target_id="agent_management_insurance_specialist:version-local-1",
        metadata={"draft_revision": 1},
    )

    bundle.audit.append(event)

    assert LocalPersistenceBundle.create(tmp_path).audit.get(event.audit_id) == event


def test_local_configuration_unit_of_work_commits_or_rolls_back_as_one_scope(
    tmp_path: Path,
) -> None:
    bundle = LocalPersistenceBundle.create(tmp_path)
    event = AuditMetadataRecord(
        audit_id="019ba001-1111-7000-8000-000000000014",
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
        target_id="draft-local-1",
    )

    try:
        with bundle.configuration_uow() as uow:
            uow.agents.save_draft(_draft(purpose="Rolled back"), expected_revision=0)
            uow.audit.append(event)
            raise RuntimeError("fail before commit")
    except RuntimeError:
        pass

    assert bundle.agents.get_draft(_draft(purpose="x").agent_id, "draft-local-1") is None
    assert bundle.audit.get(event.audit_id) is None

    with bundle.configuration_uow() as uow:
        saved = uow.agents.save_draft(_draft(purpose="Committed"), expected_revision=0)
        uow.audit.append(event)
        uow.commit()

    assert bundle.agents.get_draft(saved.draft.agent_id, saved.draft.draft_id) == saved
    assert bundle.audit.get(event.audit_id) == event
