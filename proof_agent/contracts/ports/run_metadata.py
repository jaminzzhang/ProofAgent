from __future__ import annotations

from typing import Protocol

from proof_agent.contracts.persistence import RunAttemptMetadataRecord, RunMetadataRecord


class RunMetadataRepository(Protocol):
    """Create and read authoritative trace-safe Run metadata."""

    def append(self, record: RunMetadataRecord) -> None: ...

    def get(self, run_id: str) -> RunMetadataRecord | None: ...

    def transition(
        self,
        record: RunMetadataRecord,
        *,
        expected_state_version: int,
    ) -> RunMetadataRecord: ...

    def append_attempt(self, record: RunAttemptMetadataRecord) -> None: ...

    def get_attempt(self, attempt_id: str) -> RunAttemptMetadataRecord | None: ...

    def transition_attempt(
        self,
        record: RunAttemptMetadataRecord,
        *,
        expected_state_version: int,
        expected_fencing_token: int,
    ) -> RunAttemptMetadataRecord: ...
