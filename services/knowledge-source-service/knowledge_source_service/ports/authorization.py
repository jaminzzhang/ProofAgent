"""Authorization boundary for admitting exact-Release Knowledge Queries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from knowledge_source_service.contracts.knowledge_query import CreateKnowledgeQueryRequest


@dataclass(frozen=True)
class KnowledgeQueryAdmission:
    """Service-derived authority facts frozen for one admitted Query."""

    knowledge_space_id: str
    client_grant_id: str
    effective_access_scope_digest: str


class KnowledgeQueryAuthorizer(Protocol):
    """Resolve a client grant and exact Release without caller-supplied Space ids."""

    def authorize(
        self,
        *,
        client_id: str,
        request: CreateKnowledgeQueryRequest,
    ) -> KnowledgeQueryAdmission | None: ...
