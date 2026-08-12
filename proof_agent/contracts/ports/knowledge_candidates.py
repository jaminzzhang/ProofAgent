"""ProofAgent port for querying Candidate Evidence from a Knowledge service."""

from __future__ import annotations

from typing import Protocol

from proof_agent.contracts.knowledge_candidates import (
    KnowledgeCandidateQuery,
    KnowledgeCandidateResult,
)


class KnowledgeCandidateService(Protocol):
    """Return typed candidates without performing Evidence Admission."""

    def query(self, request: KnowledgeCandidateQuery) -> KnowledgeCandidateResult: ...
