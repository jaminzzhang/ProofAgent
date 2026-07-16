from __future__ import annotations

from typing import Protocol

from proof_agent.contracts.persistence import AuditMetadataRecord


class AuditRepository(Protocol):
    """Append and read immutable trace-safe audit metadata."""

    def append(self, event: AuditMetadataRecord) -> None: ...

    def get(self, audit_id: str) -> AuditMetadataRecord | None: ...
