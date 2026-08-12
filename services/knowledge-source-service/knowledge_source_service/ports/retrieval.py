"""Retrieval engine interface used by the Knowledge Query Executor."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from knowledge_source_service.contracts.knowledge_query import CreateKnowledgeQueryRequest
from knowledge_source_service.contracts.results import KnowledgeQueryResult
from knowledge_source_service.ports.authorization import KnowledgeQueryAdmission


@dataclass(frozen=True)
class AdmittedKnowledgeQuery:
    """Strict request paired with service-derived, frozen authority facts."""

    request: CreateKnowledgeQueryRequest
    admission: KnowledgeQueryAdmission


class KnowledgeRetrievalEngine(Protocol):
    """Execute one already-admitted request behind a small application seam."""

    def retrieve(self, query: AdmittedKnowledgeQuery) -> KnowledgeQueryResult: ...
