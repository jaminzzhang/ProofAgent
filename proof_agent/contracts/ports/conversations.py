from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from proof_agent.contracts.conversation import ConversationRecord, ConversationTurn


class ConversationRepository(Protocol):
    """Persist raw Operator Chat timelines separately from trace-safe Run metadata."""

    def create(self, record: ConversationRecord) -> None: ...

    def get(self, conversation_id: str) -> ConversationRecord | None: ...

    def list(self, *, limit: int = 200) -> Sequence[ConversationRecord]: ...

    def update(self, record: ConversationRecord) -> None: ...

    def delete(self, conversation_id: str) -> bool: ...

    def append_turn(
        self,
        conversation_id: str,
        turn: ConversationTurn,
        *,
        expected_turn_count: int,
    ) -> ConversationRecord: ...
