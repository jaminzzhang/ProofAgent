"""Deterministic insurance Knowledge ranking metrics."""

from __future__ import annotations

from dataclasses import dataclass
from math import log2
from typing import Literal, TypeVar

from proof_agent.contracts.evaluation import (
    InsuranceKnowledgeCase,
    InsuranceKnowledgeEvaluationReport,
    InsuranceKnowledgeObservation,
    InsuranceKnowledgeSliceMetrics,
    InsuranceRetrievalMetrics,
)


def retrieval_metrics(
    *,
    gold: tuple[str, ...],
    ranked: tuple[str, ...],
) -> InsuranceRetrievalMetrics:
    """Measure required-evidence recall at the fixed release cutoffs."""

    gold_set = set(gold)
    if not gold_set or len(gold_set) != len(gold):
        raise ValueError("gold evidence identities must be non-empty and unique")
    if len(set(ranked)) != len(ranked):
        raise ValueError("ranked evidence identities must be unique")

    def recall(cutoff: int) -> float:
        return len(gold_set.intersection(ranked[:cutoff])) / len(gold_set)

    return InsuranceRetrievalMetrics(
        retrieval_case_count=1,
        required_evidence_recall_at_20=recall(20),
        required_evidence_recall_at_50=recall(50),
        required_evidence_recall_at_100=recall(100),
    )


@dataclass(frozen=True, slots=True)
class _CaseMeasurement:
    retrieval_scored: bool
    recall_20: float
    recall_50: float
    recall_100: float
    complete_5: float
    complete_10: float
    ndcg_10: float
    mrr_10: float
    citation_resolvability: float
    authority_failures: int
    unauthorized_exposure: int


_CaseItem = TypeVar("_CaseItem", InsuranceKnowledgeCase, InsuranceKnowledgeObservation)
_SliceDimension = Literal["query_type", "document", "parser", "acl"]


def evaluate_insurance_knowledge(
    *,
    cases: tuple[InsuranceKnowledgeCase, ...],
    observations: tuple[InsuranceKnowledgeObservation, ...],
) -> InsuranceKnowledgeEvaluationReport:
    """Evaluate exact publication-bound cases and return aggregate/slice facts."""

    if not cases:
        raise ValueError("insurance Knowledge evaluation requires at least one case")
    cases_by_id = _unique_by_case_id(cases, label="case")
    observations_by_id = _unique_by_case_id(observations, label="observation")
    if set(cases_by_id) != set(observations_by_id):
        raise ValueError("observations must cover exactly the evaluation cases")

    measured: dict[str, _CaseMeasurement] = {}
    for case_id, case in cases_by_id.items():
        observation = observations_by_id[case_id]
        if (
            observation.source_id != case.source_id
            or observation.source_publication_id != case.source_publication_id
            or observation.source_publication_seq != case.source_publication_seq
        ):
            raise ValueError("observation Source publication does not match its gold case")
        measured[case_id] = _measure_case(case, observation)

    slices: list[InsuranceKnowledgeSliceMetrics] = []
    dimensions: tuple[_SliceDimension, ...] = (
        "query_type",
        "document",
        "parser",
        "acl",
    )
    for dimension in dimensions:
        values = sorted({_slice_value(case, dimension) for case in cases})
        for value in values:
            selected = tuple(
                measured[case.case_id] for case in cases if _slice_value(case, dimension) == value
            )
            slices.append(
                InsuranceKnowledgeSliceMetrics(
                    dimension=dimension,
                    value=value,
                    case_count=len(selected),
                    metrics=_aggregate(selected),
                )
            )
    return InsuranceKnowledgeEvaluationReport(
        case_count=len(cases),
        overall=_aggregate(tuple(measured.values())),
        slices=tuple(slices),
    )


def _slice_value(case: InsuranceKnowledgeCase, dimension: _SliceDimension) -> str:
    if dimension == "query_type":
        return case.query_type
    if dimension == "document":
        return case.document_slice
    if dimension == "parser":
        return case.parser_slice
    return case.acl_slice


def _unique_by_case_id(items: tuple[_CaseItem, ...], *, label: str) -> dict[str, _CaseItem]:
    result: dict[str, _CaseItem] = {}
    for item in items:
        case_id = getattr(item, "case_id", None)
        if not isinstance(case_id, str) or not case_id:
            raise ValueError(f"{label} requires a case_id")
        if case_id in result:
            raise ValueError(f"duplicate {label} case_id: {case_id}")
        result[case_id] = item
    return result


def _measure_case(
    case: InsuranceKnowledgeCase,
    observation: InsuranceKnowledgeObservation,
) -> _CaseMeasurement:
    ranked = observation.ranked_rule_unit_revision_ids
    gold = case.required_rule_unit_revision_ids
    rank_by_id = {item: rank for rank, item in enumerate(ranked, start=1)}

    if not gold:
        return _CaseMeasurement(
            retrieval_scored=False,
            recall_20=0.0,
            recall_50=0.0,
            recall_100=0.0,
            complete_5=0.0,
            complete_10=0.0,
            ndcg_10=0.0,
            mrr_10=0.0,
            citation_resolvability=0.0,
            authority_failures=observation.authority_failure_count,
            unauthorized_exposure=len(
                set(ranked).intersection(case.acl_hard_negative_rule_unit_revision_ids)
            ),
        )

    recalls = retrieval_metrics(gold=gold, ranked=ranked)

    def complete(cutoff: int) -> float:
        rules_complete = all(rank_by_id.get(item, cutoff + 1) <= cutoff for item in gold)
        slots_complete = all(
            observation.evidence_slot_ranks.get(slot.slot_id, cutoff + 1) <= cutoff
            for slot in case.required_evidence_slots
        )
        return float(rules_complete and slots_complete)

    relevant_ranks = tuple(
        rank for item, rank in rank_by_id.items() if item in set(gold) and rank <= 10
    )
    dcg = sum(1.0 / log2(rank + 1) for rank in relevant_ranks)
    ideal_dcg = sum(1.0 / log2(rank + 1) for rank in range(1, min(len(gold), 10) + 1))
    resolvable = set(observation.resolvable_citation_rule_unit_revision_ids)
    return _CaseMeasurement(
        retrieval_scored=True,
        recall_20=recalls.required_evidence_recall_at_20,
        recall_50=recalls.required_evidence_recall_at_50,
        recall_100=recalls.required_evidence_recall_at_100,
        complete_5=complete(5),
        complete_10=complete(10),
        ndcg_10=dcg / ideal_dcg,
        mrr_10=(1.0 / min(relevant_ranks) if relevant_ranks else 0.0),
        citation_resolvability=len(set(gold).intersection(resolvable)) / len(set(gold)),
        authority_failures=observation.authority_failure_count,
        unauthorized_exposure=len(
            set(ranked).intersection(case.acl_hard_negative_rule_unit_revision_ids)
        ),
    )


def _aggregate(measurements: tuple[_CaseMeasurement, ...]) -> InsuranceRetrievalMetrics:
    if not measurements:
        raise ValueError("metric aggregation requires at least one case")
    scored = tuple(item for item in measurements if item.retrieval_scored)
    count = len(scored)
    denominator = count or 1

    return InsuranceRetrievalMetrics(
        retrieval_case_count=count,
        required_evidence_recall_at_20=(sum(item.recall_20 for item in scored) / denominator),
        required_evidence_recall_at_50=(sum(item.recall_50 for item in scored) / denominator),
        required_evidence_recall_at_100=(sum(item.recall_100 for item in scored) / denominator),
        complete_evidence_top_5_rate=(sum(item.complete_5 for item in scored) / denominator),
        complete_evidence_top_10_rate=(sum(item.complete_10 for item in scored) / denominator),
        ndcg_at_10=sum(item.ndcg_10 for item in scored) / denominator,
        mrr_at_10=sum(item.mrr_10 for item in scored) / denominator,
        citation_resolvability_rate=(
            sum(item.citation_resolvability for item in scored) / denominator
        ),
        authority_failure_count=sum(item.authority_failures for item in measurements),
        unauthorized_candidate_exposure=sum(item.unauthorized_exposure for item in measurements),
    )


__all__ = ["evaluate_insurance_knowledge", "retrieval_metrics"]
