"""Retrieval capabilities for knowledge providers."""
from __future__ import annotations

from proof_agent.contracts._base import FrozenModel


class RetrievalCapabilities(FrozenModel):
    """Declares what structured retrieval operations a KnowledgeProvider supports.

    Used by RetrievalPlanner to determine whether a provider supports
    advanced retrieval operations like document structure listing and
    scoped retrieval.
    """

    supports_structure_listing: bool = False
    supports_scoped_retrieval: bool = False
    supports_parallel_retrieval: bool = False
