"""PostgreSQL keyset paging tests for Knowledge Source operations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from proof_agent.capabilities.persistence.postgres.knowledge_repository import (
    PostgresKnowledgeAssetRepository,
)
from proof_agent.capabilities.persistence.postgres.knowledge_source_operation_query import (
    KnowledgeSourceCursorError,
    PostgresKnowledgeSourceOperationQuery,
)
from proof_agent.capabilities.persistence.postgres.knowledge_source_operation_repository import (
    PostgresKnowledgeSourceOperationRepository,
)
from proof_agent.contracts import (
    KnowledgeSource,
    KnowledgeSourceLifecycleState,
    KnowledgeSourceOperation,
)


pytestmark = pytest.mark.postgres_integration
pytest_plugins = ("postgres_fixtures",)


def test_pg_operation_query_uses_bounded_opaque_keyset_pages(
    postgres_engine,
) -> None:
    PostgresKnowledgeAssetRepository(postgres_engine).save_source(
        KnowledgeSource(
            source_id="ks_hybrid",
            name="Paged operations",
            provider="hybrid_index",
            lifecycle_state=KnowledgeSourceLifecycleState.ACTIVE,
            params={},
            created_at="2026-07-27T00:00:00Z",
            updated_at="2026-07-27T00:00:00Z",
        ),
        expected_revision=0,
    )
    commands = PostgresKnowledgeSourceOperationRepository(postgres_engine)
    for index, status in enumerate(("running", "succeeded", "failed"), start=1):
        terminal = status != "running"
        timestamp = f"2026-07-27T00:0{index}:00Z"
        commands.save(
            KnowledgeSourceOperation(
                operation_id=f"ksop_{index:03d}",
                source_id="ks_hybrid",
                command="upload_document",
                status=status,
                stage="done" if terminal else "ingestion",
                source_revision=index,
                poll_after_ms=1_000,
                outcome_code=f"{status}_outcome" if terminal else None,
                outcome_detail=f"{status}." if terminal else None,
                created_at=timestamp,
                updated_at=timestamp,
                completed_at=timestamp if terminal else None,
            )
        )
    now = [datetime(2026, 7, 27, 1, tzinfo=UTC)]
    query = PostgresKnowledgeSourceOperationQuery(
        postgres_engine,
        cursor_secret=b"cursor-test-secret-that-is-not-production",
        clock=lambda: now[0],
        cursor_ttl=timedelta(minutes=5),
    )

    first = query.list_page(source_id="ks_hybrid", limit=2)
    second = query.list_page(
        source_id="ks_hybrid",
        limit=2,
        cursor=first.page.next_cursor,
    )

    assert [item.operation_id for item in first.data] == ["ksop_003", "ksop_002"]
    assert first.page.has_more is True
    assert first.summary == {
        "total": 3,
        "running": 1,
        "succeeded": 1,
        "failed": 1,
    }
    assert [item.operation_id for item in second.data] == ["ksop_001"]
    assert second.page.has_more is False
    with pytest.raises(KnowledgeSourceCursorError):
        query.list_page(
            source_id="another-source",
            limit=2,
            cursor=first.page.next_cursor,
        )
    now[0] += timedelta(minutes=6)
    with pytest.raises(KnowledgeSourceCursorError):
        query.list_page(
            source_id="ks_hybrid",
            limit=2,
            cursor=first.page.next_cursor,
        )
