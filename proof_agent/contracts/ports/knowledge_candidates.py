"""ProofAgent port for querying Candidate Evidence from a Knowledge service."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Protocol

from proof_agent.contracts.knowledge_candidates import (
    KnowledgeCandidateQuery,
    KnowledgeCandidateResult,
)
from proof_agent.errors import ProofAgentError


class KnowledgeCandidateAdmissionFailureReason(StrEnum):
    """Stable, content-free reason for one ProofAgent Admission failure."""

    SCORER_UNAVAILABLE = "evidence_admission_scorer_unavailable"
    SCORE_INVALID = "evidence_admission_score_invalid"
    CANDIDATE_SET_EMPTY = "evidence_admission_candidate_set_empty"
    SCORE_MISSING = "evidence_admission_score_missing"
    THRESHOLD_NOT_MET = "evidence_admission_threshold_not_met"
    POLICY_DENIED = "evidence_admission_policy_denied"


class KnowledgeCandidateAdmissionError(ProofAgentError):
    """Fail closed with a bounded Admission reason and no Candidate content."""

    def __init__(
        self,
        reason: KnowledgeCandidateAdmissionFailureReason,
        message: str,
        fix: str,
    ) -> None:
        self.admission_reason_code = reason.value
        super().__init__("PA_KNOWLEDGE_001", message, fix)


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
