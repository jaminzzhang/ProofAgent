from __future__ import annotations

from datetime import datetime, timedelta

from proof_agent.contracts.artifacts import ArtifactKind
from proof_agent.contracts.ports.artifact_references import ArtifactReferenceRepository


VALIDATION_CAPTURE_RETENTION = timedelta(days=7)
OPERATOR_CHAT_RETENTION = timedelta(days=90)
CASE_MEMORY_RETENTION = timedelta(days=30)
TRACE_SAFE_AUDIT_RETENTION = timedelta(days=365)
RECOVERY_COPY_WINDOW = timedelta(days=7)


def artifact_expiry_for(kind: ArtifactKind, *, created_at: datetime) -> datetime | None:
    if created_at.utcoffset() is None:
        raise ValueError("artifact retention timestamp must be timezone-aware")
    if kind is ArtifactKind.VALIDATION_CAPTURE:
        return created_at + VALIDATION_CAPTURE_RETENTION
    if kind in {
        ArtifactKind.RUN_TRACE,
        ArtifactKind.GOVERNANCE_RECEIPT,
        ArtifactKind.EVALUATION_EVIDENCE,
        ArtifactKind.HTML_REPORT,
    }:
        return created_at + TRACE_SAFE_AUDIT_RETENTION
    return None


class ArtifactRetentionService:
    def __init__(self, repository: ArtifactReferenceRepository) -> None:
        self._repository = repository

    def expire(self, *, now: datetime) -> int:
        return self._repository.expire_due(now=now)


__all__ = [
    "ArtifactRetentionService",
    "CASE_MEMORY_RETENTION",
    "OPERATOR_CHAT_RETENTION",
    "RECOVERY_COPY_WINDOW",
    "TRACE_SAFE_AUDIT_RETENTION",
    "VALIDATION_CAPTURE_RETENTION",
    "artifact_expiry_for",
]
