"""PostgreSQL authority tests for durable Knowledge Source operations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from proof_agent.capabilities.persistence.postgres.knowledge_repository import (
    PostgresKnowledgeAssetRepository,
)
from proof_agent.capabilities.persistence.postgres.knowledge_source_operation_repository import (
    KnowledgeSourceIdempotencyConflictError,
    PostgresKnowledgeSourceOperationRepository,
)
from proof_agent.contracts import (
    KnowledgeSource,
    KnowledgeSourceLifecycleState,
    KnowledgeSourceOperation,
    KnowledgeSourceOperationProgress,
)


pytest_plugins = ("postgres_fixtures",)


def _seed_source(postgres_engine) -> None:
    source_repository = PostgresKnowledgeAssetRepository(postgres_engine)
    source_repository.save_source(
        KnowledgeSource(
            source_id="ks_hybrid",
            name="Insurance Rules",
            provider="hybrid_index",
            lifecycle_state=KnowledgeSourceLifecycleState.ACTIVE,
            params={},
            created_at="2026-07-27T00:00:00Z",
            updated_at="2026-07-27T00:00:00Z",
        ),
        expected_revision=0,
    )


def _operation(operation_id: str = "ksop_upload_001") -> KnowledgeSourceOperation:
    return KnowledgeSourceOperation(
        operation_id=operation_id,
        source_id="ks_hybrid",
        command="upload_document",
        status="running",
        stage="ingestion",
        source_revision=1,
        poll_after_ms=1_000,
        progress=KnowledgeSourceOperationProgress(
            current=3,
            total=10,
            unit="pages",
        ),
        created_at="2026-07-27T00:00:00Z",
        updated_at="2026-07-27T00:00:01Z",
    )


def test_pg_operation_repository_persists_and_reads_durable_operation(
    postgres_engine,
) -> None:
    _seed_source(postgres_engine)
    repository = PostgresKnowledgeSourceOperationRepository(postgres_engine)
    operation = _operation()

    assert repository.save(operation) == operation
    assert repository.get(operation.operation_id) == operation


def test_pg_command_admission_replays_exact_request_and_rejects_key_mismatch(
    postgres_engine,
) -> None:
    _seed_source(postgres_engine)
    repository = PostgresKnowledgeSourceOperationRepository(postgres_engine)
    operation = _operation()
    expires_at = datetime(2026, 7, 28, tzinfo=UTC)

    admitted, created = repository.admit(
        operation,
        operator_subject="operator-1",
        idempotency_key="stable-upload-key",
        request_sha256="a" * 64,
        expires_at=expires_at,
    )
    replayed, replay_created = repository.admit(
        _operation("ksop_upload_response_lost"),
        operator_subject="operator-1",
        idempotency_key="stable-upload-key",
        request_sha256="a" * 64,
        expires_at=expires_at + timedelta(minutes=1),
    )

    assert created is True
    assert replay_created is False
    assert replayed == admitted
    with pytest.raises(KnowledgeSourceIdempotencyConflictError):
        repository.admit(
            _operation("ksop_upload_mismatch"),
            operator_subject="operator-1",
            idempotency_key="stable-upload-key",
            request_sha256="b" * 64,
            expires_at=expires_at,
        )
