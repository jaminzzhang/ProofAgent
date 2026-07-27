"""PostgreSQL keyset query tests for the unified Source collection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from proof_agent.capabilities.persistence.postgres.knowledge_source_query import (
    KnowledgeSourceCursorError,
    PostgresKnowledgeSourceQuery,
)
from proof_agent.capabilities.persistence.postgres.knowledge_repository import (
    PostgresKnowledgeAssetRepository,
)
from proof_agent.contracts import (
    KnowledgeSource,
    KnowledgeSourceLifecycleState,
)


pytestmark = pytest.mark.postgres_integration
pytest_plugins = ("postgres_fixtures",)


def test_source_query_limits_before_materialization_and_binds_cursor_to_filter(
    postgres_engine: Any,
) -> None:
    now = datetime(2026, 7, 27, 3, 0, tzinfo=UTC)
    repository = PostgresKnowledgeAssetRepository(postgres_engine)
    for index in range(3):
        timestamp = (now + timedelta(seconds=index)).isoformat()
        repository.save_source(
            KnowledgeSource(
                source_id=f"ks_{index}",
                name=f"Source {index}",
                provider="hybrid_index",
                lifecycle_state=(
                    KnowledgeSourceLifecycleState.ARCHIVED
                    if index == 0
                    else KnowledgeSourceLifecycleState.ACTIVE
                ),
                params={},
                created_at=timestamp,
                updated_at=timestamp,
            ),
            expected_revision=0,
        )
    query = PostgresKnowledgeSourceQuery(
        postgres_engine,
        cursor_secret=b"s" * 32,
        clock=lambda: now,
    )

    first = query.list_page(limit=1, cursor=None, lifecycle_state="active")
    second = query.list_page(
        limit=1,
        cursor=first.page.next_cursor,
        lifecycle_state="active",
    )

    assert [item.source.source_id for item in first.data] == ["ks_2"]
    assert [item.source.source_id for item in second.data] == ["ks_1"]
    assert first.summary == {"total": 2, "active": 2, "archived": 1}
    assert first.page.has_more is True
    assert second.page.has_more is False
    with pytest.raises(KnowledgeSourceCursorError):
        query.list_page(
            limit=1,
            cursor=first.page.next_cursor,
            lifecycle_state=None,
        )
