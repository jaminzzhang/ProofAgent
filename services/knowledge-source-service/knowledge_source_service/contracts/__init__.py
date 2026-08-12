"""Public contracts exposed by Knowledge Source Service."""

from knowledge_source_service.contracts.knowledge_query import (
    CreateKnowledgeQueryRequest,
    KnowledgeQuery,
    KnowledgeServiceProblem,
)
from knowledge_source_service.contracts.results import KnowledgeQueryResult

__all__ = [
    "CreateKnowledgeQueryRequest",
    "KnowledgeQuery",
    "KnowledgeQueryResult",
    "KnowledgeServiceProblem",
]
