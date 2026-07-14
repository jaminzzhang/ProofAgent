"""Non-compensating release authority for insurance Knowledge candidates."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from proof_agent.contracts._base import FrozenModel
from proof_agent.contracts.evaluation import InsuranceKnowledgeEvaluationReport
from proof_agent.evaluation.gate_profiles import (
    INSURANCE_KNOWLEDGE_ACCEPTANCE_GATES_V1,
    KnowledgeAcceptanceGateProfile,
)


HARD_ZERO_FIELDS = (
    "unauthorized_candidate_exposure",
    "wrong_version_or_precedence",
    "unresolvable_formal_citation",
    "advice_under_authority_uncertainty",
    "high_severity_unsupported_claim",
)


class KnowledgeHardGateFacts(FrozenModel):
    """Zero-tolerance security, authority, citation, and support counts."""

    unauthorized_candidate_exposure: int = Field(default=0, ge=0)
    wrong_version_or_precedence: int = Field(default=0, ge=0)
    unresolvable_formal_citation: int = Field(default=0, ge=0)
    advice_under_authority_uncertainty: int = Field(default=0, ge=0)
    high_severity_unsupported_claim: int = Field(default=0, ge=0)


class KnowledgeAcceptanceAggregate(FrozenModel):
    """Aggregate-only result returned by the access-controlled evaluator."""

    report: InsuranceKnowledgeEvaluationReport
    hard_facts: KnowledgeHardGateFacts
    human_reviewed_support_precision: float = Field(ge=0.0, le=1.0)
    hybrid_retrieval_p95_seconds: float = Field(ge=0.0)


class KnowledgeReleaseGateResult(FrozenModel):
    """Ordered hard, quality, and performance gate decision."""

    status: Literal["passed", "blocked"]
    profile_id: str
    hard_gate_failures: int = Field(ge=0)
    quality_evaluated: bool
    quality_gate_failures: int = Field(ge=0)
    performance_evaluated: bool
    performance_gate_failures: int = Field(ge=0)
    blocking_reasons: tuple[str, ...] = ()


def evaluate_knowledge_release(
    aggregate: KnowledgeAcceptanceAggregate,
    *,
    profile: KnowledgeAcceptanceGateProfile = INSURANCE_KNOWLEDGE_ACCEPTANCE_GATES_V1,
) -> KnowledgeReleaseGateResult:
    """Apply hard-zero facts before any quality or latency threshold."""

    hard_facts = _effective_hard_facts(aggregate)
    hard_reasons = _hard_gate_reasons(hard_facts)
    if hard_reasons:
        return KnowledgeReleaseGateResult(
            status="blocked",
            profile_id=profile.profile_id,
            hard_gate_failures=sum(int(getattr(hard_facts, field)) for field in HARD_ZERO_FIELDS),
            quality_evaluated=False,
            quality_gate_failures=0,
            performance_evaluated=False,
            performance_gate_failures=0,
            blocking_reasons=hard_reasons,
        )

    quality_reasons = _quality_gate_reasons(aggregate, profile)
    performance_reasons = _performance_gate_reasons(aggregate, profile)
    blocking_reasons = (*quality_reasons, *performance_reasons)
    return KnowledgeReleaseGateResult(
        status="blocked" if blocking_reasons else "passed",
        profile_id=profile.profile_id,
        hard_gate_failures=0,
        quality_evaluated=True,
        quality_gate_failures=len(quality_reasons),
        performance_evaluated=True,
        performance_gate_failures=len(performance_reasons),
        blocking_reasons=blocking_reasons,
    )


def _effective_hard_facts(
    aggregate: KnowledgeAcceptanceAggregate,
) -> KnowledgeHardGateFacts:
    """Fail closed when aggregate retrieval facts are stricter than supplied counts."""

    declared = aggregate.hard_facts
    retrieval = aggregate.report.overall
    return declared.model_copy(
        update={
            "unauthorized_candidate_exposure": max(
                declared.unauthorized_candidate_exposure,
                retrieval.unauthorized_candidate_exposure,
            ),
            "unresolvable_formal_citation": max(
                declared.unresolvable_formal_citation,
                int(retrieval.citation_resolvability_rate < 1.0),
            ),
            "advice_under_authority_uncertainty": max(
                declared.advice_under_authority_uncertainty,
                retrieval.authority_failure_count,
            ),
        }
    )


def _hard_gate_reasons(facts: KnowledgeHardGateFacts) -> tuple[str, ...]:
    return tuple(
        f"hard-zero gate {field} observed {getattr(facts, field)}"
        for field in HARD_ZERO_FIELDS
        if getattr(facts, field) != 0
    )


def _quality_gate_reasons(
    aggregate: KnowledgeAcceptanceAggregate,
    profile: KnowledgeAcceptanceGateProfile,
) -> tuple[str, ...]:
    reasons: list[str] = []
    overall = aggregate.report.overall
    if overall.retrieval_case_count == 0:
        reasons.append("overall retrieval cohort is empty")
    if overall.required_evidence_recall_at_50 < profile.overall_recall_at_50_minimum:
        reasons.append(f"overall Recall@50 below {profile.overall_recall_at_50_minimum:.3f}")

    query_slice_items = tuple(
        item for item in aggregate.report.slices if item.dimension == "query_type"
    )
    query_slices = {item.value: item for item in query_slice_items}
    if len(query_slices) != len(query_slice_items):
        reasons.append("duplicate query-type slices")
    expected_case_counts = {
        "clause_lookup": 60,
        "conditional_guidance": 100,
        "comparison": 40,
    }
    for query_type, expected_case_count in expected_case_counts.items():
        item = query_slices.get(query_type)
        if item is None:
            reasons.append(f"missing query-type slice {query_type}")
            continue
        if item.case_count != expected_case_count:
            reasons.append(f"{query_type} slice case count must be {expected_case_count}")
        if item.metrics.retrieval_case_count == 0:
            reasons.append(f"{query_type} retrieval cohort is empty")
        if item.metrics.required_evidence_recall_at_50 < profile.query_slice_recall_at_50_minimum:
            reasons.append(
                f"{query_type} Recall@50 below {profile.query_slice_recall_at_50_minimum:.3f}"
            )
        if query_type in {"conditional_guidance", "comparison"} and (
            item.metrics.complete_evidence_top_10_rate < profile.complete_evidence_top_10_minimum
        ):
            reasons.append(
                f"{query_type} complete-evidence Top-10 below "
                f"{profile.complete_evidence_top_10_minimum:.3f}"
            )
    if (
        aggregate.human_reviewed_support_precision
        < profile.human_reviewed_support_precision_minimum
    ):
        reasons.append(
            "human-reviewed support precision below "
            f"{profile.human_reviewed_support_precision_minimum:.3f}"
        )
    return tuple(reasons)


def _performance_gate_reasons(
    aggregate: KnowledgeAcceptanceAggregate,
    profile: KnowledgeAcceptanceGateProfile,
) -> tuple[str, ...]:
    if aggregate.hybrid_retrieval_p95_seconds <= profile.hybrid_retrieval_p95_seconds_maximum:
        return ()
    return (f"retrieval P95 exceeds {profile.hybrid_retrieval_p95_seconds_maximum:.3f}s",)


__all__ = [
    "HARD_ZERO_FIELDS",
    "KnowledgeAcceptanceAggregate",
    "KnowledgeHardGateFacts",
    "KnowledgeReleaseGateResult",
    "evaluate_knowledge_release",
]
