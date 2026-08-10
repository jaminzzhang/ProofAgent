"""PostgreSQL bounded query tests for unified Source workspace resources."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa

from proof_agent.capabilities.persistence.postgres.knowledge_source_workspace_query import (
    PostgresKnowledgeSourceWorkspaceQuery,
)
from proof_agent.capabilities.persistence.postgres.knowledge_repository import (
    PostgresKnowledgeAssetRepository,
)
from proof_agent.capabilities.persistence.postgres.knowledge_source_operation_repository import (
    PostgresKnowledgeSourceOperationRepository,
)
from proof_agent.capabilities.persistence.postgres.schema import (
    hybrid_document_candidates,
    hybrid_ingestion_jobs,
    hybrid_publication_preparation_jobs,
)
from proof_agent.contracts import (
    KnowledgeSource,
    KnowledgeSourceCursorError,
    KnowledgeSourceLifecycleState,
    KnowledgeSourceOperation,
)


pytestmark = pytest.mark.postgres_integration
pytest_plugins = ("postgres_fixtures",)


def _seed_source(postgres_engine: Any, *, now: datetime) -> None:
    PostgresKnowledgeAssetRepository(postgres_engine).save_source(
        KnowledgeSource(
            source_id="ks_hybrid",
            name="Insurance Rules",
            provider="hybrid_index",
            lifecycle_state=KnowledgeSourceLifecycleState.ACTIVE,
            params={},
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
        ),
        expected_revision=0,
    )


def test_documents_are_keyset_bounded_and_strip_private_result_artifacts(
    postgres_engine: Any,
) -> None:
    now = datetime(2026, 7, 27, 4, 0, tzinfo=UTC)
    _seed_source(postgres_engine, now=now)
    rows: list[dict[str, object]] = []
    candidates: list[dict[str, object]] = []
    for index in range(3):
        job_id = uuid4()
        document_id = uuid4()
        revision_id = uuid4()
        at = now + timedelta(seconds=index)
        rows.append(
            {
                "job_id": job_id,
                "idempotency_key": f"key-{index}",
                "source_id": "ks_hybrid",
                "document_id": document_id,
                "revision_id": revision_id,
                "request_identity": f"request-{index}",
                "request_sha256": f"{index + 1:064x}",
                "request_json": {
                    "content_type": "application/pdf",
                    "private_locator": "s3://must-not-leak",
                },
                "filename": f"policy-{index}.pdf",
                "uploaded_by": "operator-1",
                "state": "COMPLETED" if index != 1 else "FAILED",
                "fencing_token": 1,
                "worker_id": None,
                "auto_retry_count": 0,
                "max_auto_retries": 2,
                "next_attempt_initiation": "automatic",
                "next_attempt_at": None,
                "claimed_at": None,
                "lease_expires_at": None,
                "safe_reason": "safe failure" if index == 1 else None,
                "failure_code": "PARSER_FAILURE" if index == 1 else None,
                "failure_classification": "retryable" if index == 1 else None,
                "result_json": (
                    {"artifact_ref": "s3://must-not-leak"}
                    if index != 1
                    else None
                ),
                "created_at": at,
                "updated_at": at,
                "completed_at": at,
                "cancel_requested_at": None,
                "cancel_requested_by": None,
                "cancelled_at": None,
            }
        )
        candidates.append(
            {
                "source_id": "ks_hybrid",
                "document_id": document_id,
                "candidate_revision_id": revision_id if index != 1 else None,
                "pending_revision_id": revision_id if index == 1 else None,
                "updated_at": at,
            }
        )
    with postgres_engine.begin() as connection:
        for row in rows:
            statement = hybrid_ingestion_jobs.insert().values(**row)
            if row["state"] == "FAILED":
                statement = statement.values(result_json=sa.null())
            connection.execute(statement)
        connection.execute(hybrid_document_candidates.insert(), candidates)

    query = PostgresKnowledgeSourceWorkspaceQuery(
        postgres_engine,
        cursor_secret=b"w" * 32,
        clock=lambda: now + timedelta(minutes=1),
    )
    first = query.list_documents(source_id="ks_hybrid", limit=1)
    second = query.list_documents(
        source_id="ks_hybrid",
        limit=1,
        cursor=first.page.next_cursor,
    )

    assert [item.filename for item in first.data] == ["policy-2.pdf"]
    assert [item.filename for item in second.data] == ["policy-1.pdf"]
    assert second.data[0].candidate_state == "pending"
    assert first.summary == {"total": 3, "completed": 2, "failed": 1}
    assert "artifact" not in str(first.model_dump(mode="json")).casefold()
    with pytest.raises(KnowledgeSourceCursorError):
        query.list_documents(
            source_id="ks_other",
            limit=1,
            cursor=first.page.next_cursor,
        )


def test_failed_revision_that_was_never_selected_is_not_superseded(
    postgres_engine: Any,
) -> None:
    now = datetime(2026, 7, 28, 4, 0, tzinfo=UTC)
    _seed_source(postgres_engine, now=now)
    with postgres_engine.begin() as connection:
        connection.execute(
            hybrid_ingestion_jobs.insert().values(
                job_id=uuid4(),
                idempotency_key="failed-upload",
                source_id="ks_hybrid",
                document_id=uuid4(),
                revision_id=uuid4(),
                request_identity="failed-request",
                request_sha256="f" * 64,
                request_json={"content_type": "application/pdf"},
                filename="failed.pdf",
                uploaded_by="operator-1",
                state="FAILED",
                fencing_token=1,
                worker_id=None,
                auto_retry_count=0,
                max_auto_retries=2,
                next_attempt_initiation="automatic",
                next_attempt_at=None,
                claimed_at=None,
                lease_expires_at=None,
                safe_reason="safe failure",
                failure_code="PA_HYBRID_WORKER_INTEGRITY",
                failure_classification="non_recoverable",
                created_at=now,
                updated_at=now,
                completed_at=now,
                cancel_requested_at=None,
                cancel_requested_by=None,
                cancelled_at=None,
            ).values(result_json=sa.null())
        )

    page = PostgresKnowledgeSourceWorkspaceQuery(
        postgres_engine,
        cursor_secret=b"w" * 32,
        clock=lambda: now + timedelta(minutes=1),
    ).list_documents(source_id="ks_hybrid")

    assert page.data[0].candidate_state == "unselected"


def test_publication_preparation_page_exposes_only_final_cas_authority(
    postgres_engine: Any,
) -> None:
    now = datetime(2026, 7, 27, 5, 0, tzinfo=UTC)
    _seed_source(postgres_engine, now=now)
    PostgresKnowledgeSourceOperationRepository(postgres_engine).save(
        KnowledgeSourceOperation(
            operation_id="op_prepare",
            source_id="ks_hybrid",
            command="prepare_publication",
            status="succeeded",
            stage="publication_prepared",
            source_revision=8,
            poll_after_ms=1_000,
            created_at=now.isoformat(),
            updated_at=(now + timedelta(seconds=1)).isoformat(),
            completed_at=(now + timedelta(seconds=1)).isoformat(),
        )
    )
    preparation_job_id = uuid4()
    with postgres_engine.begin() as connection:
        connection.execute(
            hybrid_publication_preparation_jobs.insert().values(
                preparation_job_id=preparation_job_id,
                operation_id="op_prepare",
                validation_id="validation_1",
                source_id="ks_hybrid",
                source_revision=8,
                source_draft_version_id="draft_1",
                smoke_query="What is covered?",
                state="PREPARED",
                fencing_token=3,
                worker_id=None,
                claimed_at=None,
                lease_expires_at=None,
                prepared_commit_json={"private_locator": "s3://must-not-leak"},
                failure_code=None,
                safe_reason=None,
                created_by="operator-1",
                created_at=now,
                updated_at=now + timedelta(seconds=1),
                completed_at=now + timedelta(seconds=1),
            )
        )

    query = PostgresKnowledgeSourceWorkspaceQuery(
        postgres_engine,
        cursor_secret=b"w" * 32,
        clock=lambda: now + timedelta(minutes=1),
    )
    page = query.list_publication_validations(source_id="ks_hybrid")

    assert page.data[0].model_dump(mode="json") == {
        "validation_id": "validation_1",
        "state": "prepared",
        "source_revision": 8,
        "fencing_token": 3,
        "source_draft_version_id": "draft_1",
        "generation_id": None,
        "safe_reason": None,
        "created_at": "2026-07-27T05:00:00Z",
        "updated_at": "2026-07-27T05:00:01Z",
    }
    assert "private_locator" not in str(page.model_dump(mode="json"))
