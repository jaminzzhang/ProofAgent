"""Application CAS tests for prepared Knowledge Source publication."""

from __future__ import annotations

import pytest

from proof_agent.control.knowledge.application import (
    KnowledgeSourceCommandContext,
    KnowledgeSourceRevisionConflictError,
)
from proof_agent.control.knowledge.publication_service import (
    KnowledgeSourcePublicationService,
)
from proof_agent.contracts import (
    KnowledgeSource,
    KnowledgeSourceIntakeCapability,
    KnowledgeSourceLifecycleState,
    KnowledgeSourceProviderCapability,
    KnowledgeSourceProviderReadiness,
    KnowledgeSourceRecord,
    Permission,
)


class _Operations:
    def replay(self, **_: object) -> None:
        return None


class _Knowledge:
    def get_source_record(self, source_id: str) -> KnowledgeSourceRecord:
        assert source_id == "ks_hybrid"
        return KnowledgeSourceRecord(
            source=KnowledgeSource(
                source_id=source_id,
                name="Publish CAS",
                provider="hybrid_index",
                lifecycle_state=KnowledgeSourceLifecycleState.ACTIVE,
                params={},
                source_draft_version_id="draft-8",
                created_at="2026-07-27T00:00:00Z",
                updated_at="2026-07-27T00:01:00Z",
            ),
            revision=8,
        )


class _Prepared:
    def __init__(self) -> None:
        self.consumed = False

    def consume(self, *_: object, **__: object) -> object:
        self.consumed = True
        raise AssertionError("Prepared publication was consumed before Source CAS")


class _UnitOfWork:
    def __init__(self) -> None:
        self.operations = _Operations()
        self.knowledge = _Knowledge()
        self.prepared_publications = _Prepared()

    def __enter__(self) -> "_UnitOfWork":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def commit(self) -> None:
        raise AssertionError("Revision conflict must not commit")


class _Summaries:
    def summary_for_source(self, source_id: str) -> dict[str, int]:
        return {"ready": 10, "review_required": 0}


def test_publication_checks_live_source_revision_before_consuming_preparation() -> None:
    uow = _UnitOfWork()
    service = KnowledgeSourcePublicationService(
        unit_of_work_factory=lambda: uow,
        provider_capability=KnowledgeSourceProviderCapability(
            provider="hybrid_index",
            creation_supported=True,
            intake=KnowledgeSourceIntakeCapability(
                content_types=("application/pdf",),
                max_file_bytes=50 * 1024 * 1024,
                max_batch_files=50,
                max_source_documents=10_000,
            ),
            features=("publication",),
            readiness=KnowledgeSourceProviderReadiness(state="ready"),
        ),
        summary_reader=_Summaries(),
    )

    with pytest.raises(KnowledgeSourceRevisionConflictError) as caught:
        service.publish(
            source_id="ks_hybrid",
            validation_id="kspubval_001",
            expected_revision=7,
            expected_fencing_token=3,
            change_note="Publish reviewed candidate.",
            idempotency_key="publish-key",
            request_sha256="a" * 64,
            context=KnowledgeSourceCommandContext(
                operator_subject="publisher-1",
                permissions=(Permission.KNOWLEDGE_SOURCE_PUBLISH,),
            ),
        )

    assert caught.value.current_revision == 8
    assert uow.prepared_publications.consumed is False
