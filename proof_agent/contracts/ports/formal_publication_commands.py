"""Persistence port for durable Formal Production Agent publication commands."""

from __future__ import annotations

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
    ) -> FormalProductionAgentPublicationCommandReservation: ...

    def complete(
        self,
        record: FormalProductionAgentPublicationCommandRecord,
    ) -> FormalProductionAgentPublicationCommandRecord: ...


__all__ = ["FormalProductionAgentPublicationCommandRepository"]
