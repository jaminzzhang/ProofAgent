from __future__ import annotations

from datetime import UTC, datetime, timedelta

from proof_agent.contracts.artifacts import ArtifactKind
from proof_agent.observability.retention import (
    CASE_MEMORY_RETENTION,
    OPERATOR_CHAT_RETENTION,
    RECOVERY_COPY_WINDOW,
    TRACE_SAFE_AUDIT_RETENTION,
    VALIDATION_CAPTURE_RETENTION,
    artifact_expiry_for,
)


def test_approved_retention_windows_are_exact() -> None:
    assert VALIDATION_CAPTURE_RETENTION == timedelta(days=7)
    assert CASE_MEMORY_RETENTION == timedelta(days=30)
    assert OPERATOR_CHAT_RETENTION == timedelta(days=90)
    assert TRACE_SAFE_AUDIT_RETENTION == timedelta(days=365)
    assert RECOVERY_COPY_WINDOW == timedelta(days=7)


def test_artifact_retention_keeps_reference_governed_knowledge_unbounded() -> None:
    now = datetime(2026, 7, 15, tzinfo=UTC)

    assert artifact_expiry_for(ArtifactKind.VALIDATION_CAPTURE, created_at=now) == now + timedelta(days=7)
    assert artifact_expiry_for(ArtifactKind.RUN_TRACE, created_at=now) == now + timedelta(days=365)
    assert artifact_expiry_for(ArtifactKind.KNOWLEDGE_SOURCE, created_at=now) is None
