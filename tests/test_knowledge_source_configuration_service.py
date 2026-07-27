"""Application-level policy tests for Knowledge Source configuration."""

from __future__ import annotations

from proof_agent.control.knowledge.application import (
    KnowledgeSourceCommandContext,
    KnowledgeSourceCommandRejectedError,
)
from proof_agent.control.knowledge.configuration_service import (
    KnowledgeSourceConfigurationService,
)
from proof_agent.contracts import (
    AuditActorFacts,
    KnowledgeSource,
    KnowledgeSourceCapabilityProjection,
    KnowledgeSourceIntakeCapability,
    KnowledgeSourceLifecycleState,
    KnowledgeSourceProviderCapability,
    KnowledgeSourceProviderReadiness,
    KnowledgeSourceRecord,
    Permission,
)

import pytest


class _Knowledge:
    def __init__(self, record: KnowledgeSourceRecord) -> None:
        self.record = record

    def get_source_record(self, source_id: str) -> KnowledgeSourceRecord | None:
        return self.record if source_id == self.record.source.source_id else None

    def save_source(
        self,
        source: KnowledgeSource,
        *,
        expected_revision: int,
    ) -> object:
        if expected_revision != self.record.revision:
            raise AssertionError("unexpected revision")
        self.record = KnowledgeSourceRecord(
            source=source,
            revision=expected_revision + 1,
        )
        return object()


class _Audit:
    def __init__(self) -> None:
        self.events: list[object] = []

    def append(self, event: object) -> None:
        self.events.append(event)


class _UnitOfWork:
    def __init__(self, knowledge: _Knowledge) -> None:
        self.knowledge = knowledge
        self.audit = _Audit()
        self.committed = False

    def __enter__(self) -> "_UnitOfWork":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def commit(self) -> None:
        self.committed = True


class _Summaries:
    def summary_for_source(self, source_id: str) -> dict[str, int]:
        assert source_id == "ks_hybrid"
        return {"documents": 10, "ready": 8, "review_required": 2}


class _FileDefectSummaries:
    def summary_for_source(self, source_id: str) -> dict[str, int]:
        assert source_id == "ks_hybrid"
        return {
            "documents": 1,
            "ready": 0,
            "review_required": 0,
            "retryable_ingestion": 0,
            "cancellable_ingestion": 0,
            "replacement_required": 1,
        }


def _capabilities() -> KnowledgeSourceCapabilityProjection:
    return KnowledgeSourceCapabilityProjection(
        providers=(
            KnowledgeSourceProviderCapability(
                provider="hybrid_index",
                creation_supported=True,
                intake=KnowledgeSourceIntakeCapability(
                    content_types=("application/pdf",),
                    max_file_bytes=50 * 1024 * 1024,
                    max_batch_files=50,
                    max_source_documents=10_000,
                ),
                features=("documents", "metadata_reviews", "publication"),
                readiness=KnowledgeSourceProviderReadiness(
                    state="ready",
                    revision="hybrid-private-plane.v1",
                ),
            ),
        )
    )


def test_configuration_detail_and_command_use_the_same_action_policy() -> None:
    service = KnowledgeSourceConfigurationService(
        knowledge=_Knowledge(
            KnowledgeSourceRecord(
                source=KnowledgeSource(
                    source_id="ks_hybrid",
                    name="Insurance Rules",
                    provider="hybrid_index",
                    lifecycle_state=KnowledgeSourceLifecycleState.ACTIVE,
                    params={},
                    created_at="2026-07-27T00:00:00Z",
                    updated_at="2026-07-27T00:01:00Z",
                ),
                revision=7,
            )
        ),
        summaries=_Summaries(),
        capabilities=_capabilities(),
    )
    context = KnowledgeSourceCommandContext(
        operator_subject="operator-1",
        permissions=(Permission.KNOWLEDGE_SOURCE_VIEW,),
    )

    detail = service.detail("ks_hybrid", context=context)
    upload = next(
        action
        for action in detail.action_capabilities.actions
        if action.action == "upload_document"
    )

    assert upload.allowed is False
    assert [blocker.code for blocker in upload.blockers] == ["permission_required"]
    with pytest.raises(KnowledgeSourceCommandRejectedError) as caught:
        service.require_action(
            "ks_hybrid",
            action="upload_document",
            context=context,
        )
    assert caught.value.blockers == upload.blockers


def test_non_recoverable_file_defect_blocks_retry_and_requires_replacement() -> None:
    service = KnowledgeSourceConfigurationService(
        knowledge=_Knowledge(
            KnowledgeSourceRecord(
                source=KnowledgeSource(
                    source_id="ks_hybrid",
                    name="Insurance Rules",
                    provider="hybrid_index",
                    lifecycle_state=KnowledgeSourceLifecycleState.ACTIVE,
                    params={},
                    created_at="2026-07-27T00:00:00Z",
                    updated_at="2026-07-27T00:01:00Z",
                ),
                revision=8,
            )
        ),
        summaries=_FileDefectSummaries(),
        capabilities=_capabilities(),
    )
    detail = service.detail(
        "ks_hybrid",
        context=KnowledgeSourceCommandContext(
            operator_subject="operator-1",
            permissions=(
                Permission.KNOWLEDGE_SOURCE_VIEW,
                Permission.KNOWLEDGE_SOURCE_EDIT,
            ),
        ),
    )

    retry = next(
        action
        for action in detail.action_capabilities.actions
        if action.action == "retry_ingestion"
    )
    cancel = next(
        action
        for action in detail.action_capabilities.actions
        if action.action == "cancel_ingestion"
    )
    replace = next(
        action
        for action in detail.action_capabilities.actions
        if action.action == "replace_document"
    )

    assert [blocker.code for blocker in retry.blockers] == [
        "document_replacement_required"
    ]
    assert [blocker.code for blocker in cancel.blockers] == [
        "no_cancellable_ingestion"
    ]
    assert replace.allowed is True


def test_archive_uses_action_policy_source_cas_and_atomic_audit() -> None:
    knowledge = _Knowledge(
        KnowledgeSourceRecord(
            source=KnowledgeSource(
                source_id="ks_hybrid",
                name="Insurance Rules",
                provider="hybrid_index",
                lifecycle_state=KnowledgeSourceLifecycleState.ACTIVE,
                params={},
                created_at="2026-07-27T00:00:00Z",
                updated_at="2026-07-27T00:01:00Z",
            ),
            revision=8,
        )
    )
    unit_of_work = _UnitOfWork(knowledge)
    service = KnowledgeSourceConfigurationService(
        knowledge=knowledge,
        summaries=_Summaries(),
        capabilities=_capabilities(),
        unit_of_work_factory=lambda: unit_of_work,
    )
    context = KnowledgeSourceCommandContext(
        operator_subject="operator-1",
        permissions=(
            Permission.KNOWLEDGE_SOURCE_VIEW,
            Permission.KNOWLEDGE_SOURCE_ARCHIVE,
        ),
    )

    archived = service.change_lifecycle(
        "ks_hybrid",
        action="archive",
        expected_revision=8,
        reason="Superseded corpus",
        actor=AuditActorFacts(
            subject="operator-1",
            identity_provider="test",
            session_id="session-1",
            permissions=(
                Permission.KNOWLEDGE_SOURCE_VIEW.value,
                Permission.KNOWLEDGE_SOURCE_ARCHIVE.value,
            ),
        ),
        context=context,
    )

    assert archived.source.lifecycle_state is KnowledgeSourceLifecycleState.ARCHIVED
    assert archived.revision == 9
    assert unit_of_work.committed is True
    assert len(unit_of_work.audit.events) == 1
    event = unit_of_work.audit.events[0]
    assert getattr(event, "event_type") == "knowledge_source.archived"
    assert getattr(event, "metadata")["reason"] == "Superseded corpus"
