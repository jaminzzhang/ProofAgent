"""ProofAgent port for querying Candidate Evidence from a Knowledge service."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from proof_agent.contracts.knowledge_candidates import (
    KnowledgeCandidateQuery,
    KnowledgeCandidateResult,
)


class KnowledgeCandidateService(Protocol):
    """Return typed candidates without performing Evidence Admission."""

    def query(self, request: KnowledgeCandidateQuery) -> KnowledgeCandidateResult: ...


class KnowledgeCandidateAdmissionScorer(Protocol):
    """Assign Control Plane admission inputs to remote Candidate Evidence."""

    scorer_id: str
    scorer_revision: str

    def score_candidates(
        self,
        *,
        query: KnowledgeCandidateQuery,
        result: KnowledgeCandidateResult,
    ) -> Mapping[str, float]: ...
