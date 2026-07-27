"""Application ordering tests for Knowledge Source ingestion commands."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from proof_agent.capabilities.persistence.postgres.bundle import PostgresPersistenceBundle
from proof_agent.control.knowledge.application import KnowledgeSourceCommandContext
from proof_agent.control.knowledge.ingestion_service import (
    KnowledgeSourceIngestionService,
)
from proof_agent.contracts import (
    KnowledgeSource,
    KnowledgeSourceIntakeCapability,
    KnowledgeSourceLifecycleState,
    KnowledgeSourceOperation,
    KnowledgeSourceProviderCapability,
    KnowledgeSourceProviderReadiness,
    Permission,
)


pytest_plugins = ("postgres_fixtures",)


class _ReplayOperations:
    def __init__(self, replay: KnowledgeSourceOperation) -> None:
        self._replay = replay

    def replay(self, **_: object) -> KnowledgeSourceOperation:
        return self._replay


class _ForbiddenKnowledgeRead:
    def get_source_record(self, source_id: str) -> object:
        raise AssertionError(f"Source CAS was evaluated before replay: {source_id}")


class _ReplayUnitOfWork:
    def __init__(self, replay: KnowledgeSourceOperation) -> None:
        self.operations = _ReplayOperations(replay)
        self.knowledge = _ForbiddenKnowledgeRead()
        self.committed = False

    def __enter__(self) -> "_ReplayUnitOfWork":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def commit(self) -> None:
        self.committed = True


def test_ingestion_exact_replay_returns_before_source_cas() -> None:
    replay = KnowledgeSourceOperation(
        operation_id="ksop_upload_original",
        source_id="ks_hybrid",
        command="upload_document",
        status="queued",
        stage="quarantine",
        source_revision=8,
        poll_after_ms=1_000,
        created_at="2026-07-27T00:00:00Z",
        updated_at="2026-07-27T00:00:00Z",
    )
    uow = _ReplayUnitOfWork(replay)
    service = KnowledgeSourceIngestionService(
        unit_of_work_factory=lambda: uow,
        provider_capability=None,
        summary_reader=None,
    )

    operation, created = service.admit_async_command(
        source_id="ks_hybrid",
        action="upload_document",
        command="upload_document",
        expected_revision=1,
        idempotency_key="stable-upload",
        request_sha256="a" * 64,
        context=KnowledgeSourceCommandContext(
            operator_subject="operator-1",
            permissions=(
                Permission.KNOWLEDGE_SOURCE_VIEW,
                Permission.KNOWLEDGE_SOURCE_EDIT,
            ),
        ),
    )

    assert created is False
    assert operation == replay
    assert uow.committed is False


class _EmptySummaries:
    def summary_for_source(self, source_id: str) -> dict[str, int]:
        return {"documents": 0, "ready": 0, "review_required": 0}


@pytest.mark.postgres_integration
def test_ingestion_admission_commits_source_revision_operation_and_replay_atomically(
    postgres_dsn: str,
) -> None:
    from proof_agent.capabilities.persistence.postgres.database import upgrade_database

    upgrade_database(postgres_dsn)
    bundle = PostgresPersistenceBundle.create(postgres_dsn)
    try:
        bundle.knowledge.save_source(
            KnowledgeSource(
                source_id="ks_hybrid_atomic",
                name="Atomic admission",
                provider="hybrid_index",
                lifecycle_state=KnowledgeSourceLifecycleState.ACTIVE,
                params={},
                created_at="2026-07-27T00:00:00Z",
                updated_at="2026-07-27T00:00:00Z",
            ),
            expected_revision=0,
        )
        service = KnowledgeSourceIngestionService(
            unit_of_work_factory=bundle.configuration_uow,
            provider_capability=KnowledgeSourceProviderCapability(
                provider="hybrid_index",
                creation_supported=True,
                intake=KnowledgeSourceIntakeCapability(
                    content_types=("application/pdf",),
                    max_file_bytes=50 * 1024 * 1024,
                    max_batch_files=50,
                    max_source_documents=10_000,
                ),
                features=("documents",),
                readiness=KnowledgeSourceProviderReadiness(state="ready"),
            ),
            summary_reader=_EmptySummaries(),
            clock=lambda: datetime(2026, 7, 27, 1, tzinfo=UTC),
            operation_id_factory=lambda: "ksop_atomic_001",
        )
        context = KnowledgeSourceCommandContext(
            operator_subject="operator-1",
            permissions=(Permission.KNOWLEDGE_SOURCE_EDIT,),
        )

        admitted, created = service.admit_async_command(
            source_id="ks_hybrid_atomic",
            action="upload_document",
            command="upload_document",
            expected_revision=1,
            idempotency_key="atomic-upload",
            request_sha256="a" * 64,
            context=context,
        )
        replayed, replay_created = service.admit_async_command(
            source_id="ks_hybrid_atomic",
            action="upload_document",
            command="upload_document",
            expected_revision=1,
            idempotency_key="atomic-upload",
            request_sha256="a" * 64,
            context=context,
        )

        assert created is True
        assert admitted.source_revision == 2
        assert replay_created is False
        assert replayed == admitted
        assert bundle.knowledge.get_source_record("ks_hybrid_atomic").revision == 2
    finally:
        bundle.close()
