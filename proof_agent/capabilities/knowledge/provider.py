from __future__ import annotations

from typing import Protocol, Self

from proof_agent.capabilities.knowledge.capabilities import RetrievalCapabilities
from proof_agent.capabilities.knowledge.contracts import DocumentNode
from proof_agent.contracts import EvidenceChunk
from proof_agent.contracts.manifest import KnowledgeConfig


class KnowledgeProvider(Protocol):
    @classmethod
    def from_config(cls, knowledge_config: KnowledgeConfig) -> Self: ...

    @property
    def provider_name(self) -> str: ...

    @property
    def capabilities(self) -> RetrievalCapabilities: ...

    def retrieve(self, query: str, *, top_k: int | None = None) -> tuple[EvidenceChunk, ...]:
        """Return normalized evidence chunks for a query."""


class StructuredKnowledgeProvider(KnowledgeProvider, Protocol):
    """Extended protocol for providers supporting structured retrieval operations.

    Providers implementing this protocol support document structure listing
    and scoped retrieval, enabling more sophisticated retrieval planning.
    """

    def list_structure(self) -> tuple[DocumentNode, ...]: ...

    def retrieve_at_scope(
        self, scope_id: str, *, top_k: int | None = None
    ) -> tuple[EvidenceChunk, ...]: ...
