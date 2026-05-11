from __future__ import annotations

from typing import Protocol

from proof_agent.contracts import EvidenceChunk


class KnowledgeProvider(Protocol):
    def retrieve(self, query: str, *, top_k: int = 3) -> tuple[EvidenceChunk, ...]:
        """Return normalized evidence chunks for a query."""
