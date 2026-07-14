"""Control Plane entry point for governed Hybrid retrieval execution."""

from __future__ import annotations

from proof_agent.capabilities.knowledge.hybrid.model_clients import (
    KnowledgeModelCancellation,
)
from proof_agent.capabilities.knowledge.hybrid.provider import (
    HybridIndexProvider,
    HybridQueryEmbeddingClient,
    HybridQueryRerankerClient,
    HybridRetrievalAuthority,
    HybridRetrievalCandidates,
)
from proof_agent.capabilities.knowledge.hybrid.ports import HybridSearchIndex
from proof_agent.control.knowledge.hybrid_request import GovernedHybridRetrievalRequest


def execute_hybrid_retrieval(
    request: GovernedHybridRetrievalRequest,
    *,
    authority: HybridRetrievalAuthority,
    search: HybridSearchIndex,
    embedding: HybridQueryEmbeddingClient,
    reranker: HybridQueryRerankerClient,
    cancellation: KnowledgeModelCancellation | None = None,
) -> HybridRetrievalCandidates:
    """Execute one admitted request through the narrow Hybrid provider boundary."""

    return HybridIndexProvider(
        authority=authority,
        search=search,
        embedding=embedding,
        reranker=reranker,
    ).retrieve_governed(request, cancellation=cancellation)


__all__ = [
    "HybridRetrievalAuthority",
    "HybridRetrievalCandidates",
    "execute_hybrid_retrieval",
]
