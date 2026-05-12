from __future__ import annotations

from typing import Protocol, Self

from proof_agent.contracts import EvidenceChunk
from proof_agent.contracts.manifest import KnowledgeConfig


class KnowledgeProvider(Protocol):
    @classmethod
    def from_config(cls, knowledge_config: KnowledgeConfig) -> Self: ...

    @property
    def provider_name(self) -> str: ...

    def retrieve(self, query: str, *, top_k: int | None = None) -> tuple[EvidenceChunk, ...]:
        """Return normalized evidence chunks for a query."""
