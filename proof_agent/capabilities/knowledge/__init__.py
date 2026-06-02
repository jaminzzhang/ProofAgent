from __future__ import annotations

from typing import Any

from proof_agent.capabilities.knowledge.capabilities import RetrievalCapabilities
from proof_agent.capabilities.knowledge.contracts import DocumentNode, RetrievalAction
from proof_agent.capabilities.knowledge.local_provider import (
    LocalKnowledgeProvider,
    LocalMarkdownProvider,
)
from proof_agent.capabilities.knowledge.provider import (
    KnowledgeProvider,
    StructuredKnowledgeProvider,
)
from proof_agent.capabilities.knowledge.registry import resolve_knowledge_provider
from proof_agent.capabilities.knowledge.remote_search import RemoteSearchProvider


def __getattr__(name: str) -> Any:
    """Load the optional Local Index stack only when callers request it."""

    if name == "LocalIndexProvider":
        from proof_agent.capabilities.knowledge.local_index import LocalIndexProvider

        return LocalIndexProvider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "DocumentNode",
    "KnowledgeProvider",
    "LocalIndexProvider",
    "LocalKnowledgeProvider",
    "LocalMarkdownProvider",
    "RemoteSearchProvider",
    "RetrievalAction",
    "RetrievalCapabilities",
    "StructuredKnowledgeProvider",
    "resolve_knowledge_provider",
]
