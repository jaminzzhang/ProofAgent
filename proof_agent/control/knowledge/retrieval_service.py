"""KSS-only Candidate Evidence retrieval and ProofAgent Evidence Admission."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from typing import assert_never
from urllib.parse import quote

from proof_agent.contracts import (
    EvidenceChunk,
    EvidenceContribution,
    EvidenceStatus,
    EnforcementPoint,
    ModelConfig,
    PolicyDecision,
    PolicyDecisionType,
    RetrievalQueryItem,
    ValidationResult,
)
from proof_agent.contracts.knowledge_candidates import (
    KnowledgeCandidateQuery,
    KnowledgeCandidateResult,
    KnowledgeDocxParagraphCitation,
    KnowledgeDocxTableCellCitation,
    KnowledgeHtmlDomCitation,
    KnowledgeOcrRegionCitation,
    KnowledgePdfPageCitation,
    KnowledgePptxShapeCitation,
    KnowledgeRelevanceCandidate,
    KnowledgeRelevanceCandidateGroup,
    KnowledgeTextLinesCitation,
)
from proof_agent.contracts.ports.knowledge_candidates import (
    KnowledgeCandidateAdmissionError,
    KnowledgeCandidateAdmissionFailureReason,
    KnowledgeCandidateAdmissionScorer,
    KnowledgeCandidateService,
)
from proof_agent.control.policy.engine import PolicyEngine
from proof_agent.control.validators.evidence import evaluate_evidence
from proof_agent.errors import ProofAgentError
from proof_agent.observability.audit.trace import TraceEmitter


@dataclass(frozen=True)
class KnowledgeRetrievalRequest:
    """One governed retrieval action pinned to an exact KSS query."""

    question: str
    strategy: str
    top_k: int
    min_score: float
    max_steps: int | None = None
    max_rounds: int | None = None
    planner_model: ModelConfig | None = None
    evaluator_model: ModelConfig | None = None
    retrieval_query_set: tuple[RetrievalQueryItem, ...] = ()
    max_queries: int = 3
    query_concurrency: int = 3
    query_timeout_seconds: float = 10.0
    preferred_binding_ids: tuple[str, ...] = ()
    force_empty: bool = False
    knowledge_candidate_query: KnowledgeCandidateQuery | None = None


@dataclass(frozen=True)
class KnowledgeRetrievalResult:
    evidence: tuple[EvidenceChunk, ...]
    evidence_result: ValidationResult
    candidate_result: KnowledgeCandidateResult | None = None


class KnowledgeRetrievalService:
    """Consume KSS candidates, then apply ProofAgent-owned Evidence Admission."""

    def __init__(
        self,
        *,
        trace: TraceEmitter,
        policy: PolicyEngine,
        knowledge_candidate_service: KnowledgeCandidateService | None,
        knowledge_candidate_admission_scorer: (
            KnowledgeCandidateAdmissionScorer | None
        ) = None,
    ) -> None:
        self._trace = trace
        self._policy = policy
        self._knowledge_candidate_service = knowledge_candidate_service
        self._knowledge_candidate_admission_scorer = (
            knowledge_candidate_admission_scorer
        )

    def retrieve(self, request: KnowledgeRetrievalRequest) -> KnowledgeRetrievalResult:
        return self._retrieve(request, reviewed=False)

    def retrieve_reviewed(
        self,
        request: KnowledgeRetrievalRequest,
        *,
        execution_mode: str | None = None,
    ) -> KnowledgeRetrievalResult:
        del execution_mode
        return self._retrieve(request, reviewed=True)

    def _retrieve(
        self,
        request: KnowledgeRetrievalRequest,
        *,
        reviewed: bool,
    ) -> KnowledgeRetrievalResult:
        candidate_query = request.knowledge_candidate_query
        if candidate_query is None:
            if (
                self._knowledge_candidate_service is None
                and self._knowledge_candidate_admission_scorer is None
            ):
                return self._result_for_evidence(
                    (),
                    min_score=request.min_score,
                    no_evidence_reason_code="no_knowledge_source_service_binding",
                )
            raise ProofAgentError(
                "PA_KNOWLEDGE_001",
                "ProofAgent retrieval requires an exact Knowledge Source Service Candidate Query.",
                "Publish and run the Agent Version with its exact KSS release binding.",
            )
        if candidate_query.question != request.question:
            raise ProofAgentError(
                "PA_KNOWLEDGE_001",
                "Knowledge Candidate Query does not match the governed retrieval question.",
                "Rebuild the exact Candidate Query from the current retrieval action.",
            )
        expected_strategy = "agentic" if request.strategy == "agentic" else "single_pass"
        if request.strategy not in {"single_step", "agentic"}:
            raise ProofAgentError(
                "PA_CONFIG_002",
                "Published Agent retrieval strategy is not supported by Knowledge Source Service.",
                "Use single_step or agentic for the exact Knowledge Candidate binding.",
            )
        if candidate_query.strategy != expected_strategy:
            raise ProofAgentError(
                "PA_KNOWLEDGE_001",
                "Knowledge Candidate Query strategy does not match the governed retrieval action.",
                "Use single_pass for single_step or agentic for Agentic retrieval.",
            )
        if not reviewed:
            decision = self._policy.evaluate(
                EnforcementPoint.BEFORE_RETRIEVAL,
                {
                    "question": request.question,
                    "strategy": "knowledge_source_service",
                    "knowledge_base_release_id": (
                        candidate_query.knowledge_base_release_id
                    ),
                },
            )
            _emit_policy(self._trace, decision)
            if not _allowed(decision):
                return self._result_for_evidence(
                    (),
                    min_score=request.min_score,
                    no_evidence_reason_code="retrieval_policy_denied",
                )
        service = self._knowledge_candidate_service
        if service is None:
            raise ProofAgentError(
                "PA_KNOWLEDGE_001",
                "The Agent Version requires Knowledge Source Service but no client is composed.",
                "Compose the exact KnowledgeCandidateService binding before run activation.",
            )
        candidate_result = service.query(candidate_query)
        admission_scores: Mapping[str, float] = {}
        scorer = self._knowledge_candidate_admission_scorer
        if scorer is not None:
            admission_scores = _validated_candidate_admission_scores(
                scorer.score_candidates(query=candidate_query, result=candidate_result)
            )
        evidence = _project_relevance_candidates(
            candidate_result,
            admission_scores=admission_scores,
            admission_scorer=scorer,
        )
        if request.force_empty:
            evidence = ()
        structured_count = sum(
            len(group.candidate_evidence)
            for group in candidate_result.evidence_groups
            if group.group_type == "structured"
        )
        self._trace.emit(
            "knowledge_candidate_query",
            status="ok",
            payload={
                "knowledge_query_id": candidate_result.knowledge_query_id,
                "knowledge_base_release_id": (
                    candidate_result.retrieval_lineage.knowledge_base_release_id
                ),
                "strategy": candidate_result.execution_summary.strategy,
                "rounds": candidate_result.execution_summary.rounds,
                "relevance_candidate_count": len(evidence),
                "structured_candidate_count": structured_count,
                "degraded": candidate_result.execution_summary.degraded,
            },
        )
        evidence_result = self._evaluate_evidence(
            evidence,
            min_score=request.min_score,
            no_evidence_reason_code=(
                "knowledge_candidate_admission_pending"
                if evidence and scorer is None
                else (
                    "knowledge_candidate_threshold_not_met"
                    if evidence
                    else "zero_knowledge_candidates"
                )
            ),
        )
        return KnowledgeRetrievalResult(
            evidence=evidence,
            evidence_result=evidence_result,
            candidate_result=candidate_result,
        )

    def _result_for_evidence(
        self,
        evidence: tuple[EvidenceChunk, ...],
        *,
        min_score: float,
        no_evidence_reason_code: str,
    ) -> KnowledgeRetrievalResult:
        result = self._evaluate_evidence(
            evidence,
            min_score=min_score,
            no_evidence_reason_code=no_evidence_reason_code,
        )
        return KnowledgeRetrievalResult(evidence=evidence, evidence_result=result)

    def _evaluate_evidence(
        self,
        evidence: tuple[EvidenceChunk, ...],
        *,
        min_score: float,
        no_evidence_reason_code: str,
    ) -> ValidationResult:
        evidence_result = evaluate_evidence(evidence, min_count=1, min_score=min_score)
        if evidence_result.status == "failed":
            evidence_result = evidence_result.model_copy(
                update={
                    "metadata": {
                        **dict(evidence_result.metadata),
                        "no_evidence_reason_code": no_evidence_reason_code,
                    }
                }
            )
        self._trace.emit(
            "evidence_evaluation",
            status="ok" if evidence_result.status == "passed" else "blocked",
            payload={
                "validator_name": evidence_result.validator_name,
                "status": evidence_result.status.value,
                "metadata": dict(evidence_result.metadata),
            },
        )
        return evidence_result


def _project_relevance_candidates(
    result: KnowledgeCandidateResult,
    *,
    admission_scores: Mapping[str, float] | None = None,
    admission_scorer: KnowledgeCandidateAdmissionScorer | None = None,
) -> tuple[EvidenceChunk, ...]:
    resolved_scores = admission_scores or {}
    return tuple(
        _relevance_candidate_chunk(
            candidate,
            result=result,
            admission_score=resolved_scores.get(candidate.candidate_evidence_id),
            admission_scorer=admission_scorer,
        )
        for group in result.evidence_groups
        if isinstance(group, KnowledgeRelevanceCandidateGroup)
        for candidate in group.candidate_evidence
    )


def _validated_candidate_admission_scores(
    scores: Mapping[str, float],
) -> Mapping[str, float]:
    normalized: dict[str, float] = {}
    for candidate_evidence_id, score in scores.items():
        if not isfinite(score) or not 0.0 <= score <= 1.0:
            raise KnowledgeCandidateAdmissionError(
                KnowledgeCandidateAdmissionFailureReason.SCORE_INVALID,
                "Knowledge Candidate admission scorer returned a value outside the approved normalized range of 0 through 1.",
                "Use an approved calibrated scorer that returns finite normalized admission values.",
            )
        normalized[candidate_evidence_id] = float(score)
    return normalized


def _relevance_candidate_chunk(
    candidate: KnowledgeRelevanceCandidate,
    *,
    result: KnowledgeCandidateResult,
    admission_score: float | None,
    admission_scorer: KnowledgeCandidateAdmissionScorer | None,
) -> EvidenceChunk:
    citation = _candidate_citation(candidate)
    final_rank = candidate.ranking.reranked_rank or candidate.ranking.fused_rank
    contribution = EvidenceContribution(
        source_id=candidate.knowledge_source_id,
        source_version_id=candidate.knowledge_source_version_id,
        provider_name="knowledge_source_service",
        document_id=candidate.knowledge_source_id,
        revision_id=candidate.knowledge_source_version_id,
        chunk_id=candidate.evidence_unit_id,
        provider_local_rank=final_rank,
        provider_native_score=None,
        fusion_weight=None,
        citation=citation,
    )
    return EvidenceChunk(
        source=citation,
        content=candidate.content.text,
        status=EvidenceStatus.CANDIDATE,
        evidence_id=candidate.candidate_evidence_id,
        source_id=candidate.knowledge_source_id,
        source_version_id=candidate.knowledge_source_version_id,
        provider_name="knowledge_source_service",
        document_id=candidate.knowledge_source_id,
        revision_id=candidate.knowledge_source_version_id,
        chunk_id=candidate.evidence_unit_id,
        provider_native_score=None,
        fusion_rank=float(final_rank),
        admission_score=admission_score,
        citation=citation,
        metadata={
            "knowledge_candidate_group_type": "relevance_ranked",
            "knowledge_query_id": result.knowledge_query_id,
            "knowledge_space_id": candidate.knowledge_space_id,
            "knowledge_base_id": candidate.knowledge_base_id,
            "knowledge_base_version_id": candidate.knowledge_base_version_id,
            "knowledge_base_release_id": candidate.knowledge_base_release_id,
            "content_hash": candidate.content_hash,
            **(
                {
                    "admission_scorer": {
                        "scorer_id": admission_scorer.scorer_id,
                        "scorer_revision": admission_scorer.scorer_revision,
                    }
                }
                if admission_scorer is not None and admission_score is not None
                else {}
            ),
            "ranking": candidate.ranking.model_dump(mode="json"),
            "retrieval_lineage": candidate.retrieval_lineage.model_dump(mode="json"),
            "context_evidence_units": [
                context.model_dump(mode="json")
                for context in candidate.context_evidence_units
            ],
        },
        contributions=(contribution,),
    )


def _candidate_citation(candidate: KnowledgeRelevanceCandidate) -> str:
    locator = candidate.citation_locator
    identity = "/".join(
        quote(value, safe="")
        for value in (
            candidate.knowledge_space_id,
            candidate.knowledge_base_release_id,
            candidate.knowledge_source_version_id,
            candidate.evidence_unit_id,
        )
    )
    if isinstance(locator, KnowledgeTextLinesCitation):
        fragment = f"text-lines={locator.start_line}-{locator.end_line}"
    elif isinstance(locator, KnowledgePdfPageCitation):
        fragment = f"pdf-page={locator.page_number}"
    elif isinstance(locator, KnowledgeDocxParagraphCitation):
        fragment = f"docx-paragraph={locator.paragraph_number}"
    elif isinstance(locator, KnowledgeDocxTableCellCitation):
        fragment = (
            f"docx-table-cell={locator.table_number}."
            f"{locator.row_number}.{locator.column_number}"
        )
    elif isinstance(locator, KnowledgePptxShapeCitation):
        fragment = f"pptx-shape={locator.slide_number}.{locator.shape_id}"
    elif isinstance(locator, KnowledgeHtmlDomCitation):
        fragment = f"html-dom={quote(locator.dom_path, safe='')}"
    elif isinstance(locator, KnowledgeOcrRegionCitation):
        box = locator.bounding_box
        fragment = (
            f"ocr-region={locator.page_number},"
            f"{box.x_min},{box.y_min},{box.x_max},{box.y_max}"
        )
    else:
        assert_never(locator)
    return f"knowledge://{identity}#{fragment}"


def _emit_policy(trace: TraceEmitter, decision: PolicyDecision) -> None:
    trace.emit(
        "policy_decision",
        status="ok" if _allowed(decision) else "blocked",
        payload={
            "decision": decision.decision.value,
            "enforcement_point": decision.enforcement_point.value,
            "policy_rule_id": decision.policy_rule_id,
            "reason": decision.reason,
        },
    )


def _allowed(decision: PolicyDecision) -> bool:
    return decision.decision is PolicyDecisionType.ALLOW


__all__ = [
    "KnowledgeRetrievalRequest",
    "KnowledgeRetrievalResult",
    "KnowledgeRetrievalService",
]
