"""Persistence port for durable Formal Production Agent publication commands."""

from __future__ import annotations

from datetime import timedelta
from typing import Protocol

from proof_agent.contracts.persistence import (
    FormalProductionAgentPublicationCommandRecord,
    FormalProductionAgentPublicationCommandReservation,
)


class FormalProductionAgentPublicationCommandRepository(Protocol):
    """Reserve idempotency and complete one command with terminal state."""

    def reserve(
        self,
        record: FormalProductionAgentPublicationCommandRecord,
        *,
        lease_duration: timedelta,
    ) -> FormalProductionAgentPublicationCommandReservation: ...

    def find_owned(
        self,
        *,
        command_id: str,
        actor_subject: str,
    ) -> FormalProductionAgentPublicationCommandRecord | None: ...

    def checkpoint_candidate(
        self,
        record: FormalProductionAgentPublicationCommandRecord,
        *,
        formal_candidate_sha256: str,
        knowledge_release_candidate_sha256: str,
    ) -> FormalProductionAgentPublicationCommandRecord: ...

    def complete(
        self,
        record: FormalProductionAgentPublicationCommandRecord,
    ) -> FormalProductionAgentPublicationCommandRecord: ...


__all__ = ["FormalProductionAgentPublicationCommandRepository"]
