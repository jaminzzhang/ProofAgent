from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from proof_agent.capabilities.persistence.postgres.bundle import PostgresPersistenceBundle
from proof_agent.capabilities.persistence.postgres.database import upgrade_database
from proof_agent.control.knowledge.publication_preparation_service import (
    KnowledgeSourcePublicationPreparationService,
)
from proof_agent.contracts import (
    AuditActorFacts,
    KnowledgeSource,
    KnowledgeSourceIntakeCapability,
    KnowledgeSourceLifecycleState,
    KnowledgeSourceProviderCapability,
    KnowledgeSourceProviderReadiness,
)


pytestmark = pytest.mark.postgres_integration
pytest_plugins = ("postgres_fixtures",)


class _Summary:
    def summary_for_source(self, source_id: str) -> dict[str, int]:
        return {"ready": 1, "review_required": 0}


def test_prepare_publication_is_durable_async_and_idempotent(
    postgres_dsn: str,
) -> None:
    upgrade_database(postgres_dsn)
    bundle = PostgresPersistenceBundle.create(postgres_dsn)
    source_id = f"ks_{uuid4().hex}"
    draft_id = str(uuid4())
    now = datetime(2026, 7, 27, 13, tzinfo=UTC)
    bundle.knowledge.save_source(
        KnowledgeSource(
            source_id=source_id,
            name="Publish source",
            provider="hybrid_index",
            lifecycle_state=KnowledgeSourceLifecycleState.ACTIVE,
            params={},
            source_draft_version_id=draft_id,
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
        ),
        expected_revision=0,
    )
    service = KnowledgeSourcePublicationPreparationService(
        unit_of_work_factory=bundle.configuration_uow,
        provider_capability=KnowledgeSourceProviderCapability(
            provider="hybrid_index",
            creation_supported=True,
            intake=KnowledgeSourceIntakeCapability(
                content_types=("application/pdf",),
                max_file_bytes=1024,
                max_batch_files=1,
                max_source_documents=100,
            ),
            features=("publication",),
            readiness=KnowledgeSourceProviderReadiness(state="ready"),
        ),
        summary_reader=_Summary(),
        clock=lambda: now,
    )
    actor = AuditActorFacts(
        subject="publisher-1",
        identity_provider="enterprise-oidc",
        session_id=str(uuid4()),
        permissions=("knowledge_source.publish",),
    )
    try:
        operation = service.prepare_publication(
            source_id=source_id,
            smoke_query="What policy term is covered?",
            expected_revision=1,
            idempotency_key="prepare-1",
            actor=actor,
        )
        replay = service.prepare_publication(
            source_id=source_id,
            smoke_query="What policy term is covered?",
            expected_revision=1,
            idempotency_key="prepare-1",
            actor=actor,
        )

        assert replay == operation
        assert operation.status == "queued"
        assert operation.stage == "publication_preparation_queued"
        with bundle.engine.connect() as connection:
            row = connection.exec_driver_sql(
                "SELECT count(*), min(source_draft_version_id) "
                "FROM hybrid_publication_preparation_jobs "
                "WHERE operation_id = %s",
                (operation.operation_id,),
            ).one()
        assert row == (1, draft_id)
    finally:
        bundle.close()
