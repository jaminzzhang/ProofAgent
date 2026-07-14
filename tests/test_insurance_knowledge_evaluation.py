from pydantic import ValidationError
import pytest
from pathlib import Path

from proof_agent.contracts.evaluation import (
    InsuranceKnowledgeCase,
    InsuranceKnowledgeGoldSuite,
    InsuranceKnowledgeObservation,
)
from proof_agent.evaluation.knowledge_metrics import (
    evaluate_insurance_knowledge,
    retrieval_metrics,
)
from proof_agent.evaluation.knowledge_cases import load_insurance_knowledge_suite


def test_comparison_case_requires_complete_gold_evidence_slots() -> None:
    with pytest.raises(
        ValidationError, match="comparison cases require at least two evidence slots"
    ):
        InsuranceKnowledgeCase(
            case_id="comparison-missing-slots",
            question="Compare Product A and Product B.",
            query_type="comparison",
            source_id="ks_insurance",
            source_publication_id="publication-7",
            source_publication_seq=7,
            required_rule_unit_revision_ids=("rule-a", "rule-b"),
            required_evidence_slots=(),
            expected_resolution="answer_with_citations",
        )


def test_required_evidence_recall_at_50() -> None:
    ranked = ("u1", *(f"noise-{index}" for index in range(49)), "u2")

    metrics = retrieval_metrics(gold=("u1", "u2"), ranked=ranked)

    assert metrics.required_evidence_recall_at_20 == 0.5
    assert metrics.required_evidence_recall_at_50 == 0.5
    assert metrics.required_evidence_recall_at_100 == 1.0


def _case(case_id: str, query_type: str) -> InsuranceKnowledgeCase:
    comparison_slots = (
        {
            "slot_id": f"slot-{case_id}-left",
            "requirement_kind": "comparison_basis",
            "subject_id": "PRODUCT-A",
        },
        {
            "slot_id": f"slot-{case_id}-right",
            "requirement_kind": "comparison_basis",
            "subject_id": "PRODUCT-B",
        },
    )
    single_slot = (
        {
            "slot_id": f"slot-{case_id}",
            "requirement_kind": "governing_rule",
            "subject_id": case_id,
        },
    )
    return InsuranceKnowledgeCase(
        case_id=case_id,
        question=f"Question {case_id}",
        query_type=query_type,
        source_id="ks_insurance",
        source_publication_id="publication-7",
        source_publication_seq=7,
        required_rule_unit_revision_ids=(f"rule-{case_id}",),
        required_evidence_slots=(comparison_slots if query_type == "comparison" else single_slot),
        expected_resolution="answer_with_citations",
    )


def test_gold_suite_rejects_query_mix_other_than_30_50_20() -> None:
    cases = (
        tuple(_case(f"clause-{index}", "clause_lookup") for index in range(4))
        + tuple(_case(f"conditional-{index}", "conditional_guidance") for index in range(4))
        + tuple(_case(f"comparison-{index}", "comparison") for index in range(2))
    )

    with pytest.raises(ValidationError, match="30/50/20"):
        InsuranceKnowledgeGoldSuite(
            suite_id="invalid-mix",
            version="1",
            cases=cases,
        )


def test_evaluation_computes_complete_evidence_ranking_citation_and_hard_facts() -> None:
    case = InsuranceKnowledgeCase(
        case_id="comparison-a-b",
        question="Compare Product A and Product B.",
        query_type="comparison",
        source_id="ks_insurance",
        source_publication_id="publication-7",
        source_publication_seq=7,
        required_rule_unit_revision_ids=("rule-a", "rule-b"),
        required_evidence_slots=(
            {
                "slot_id": "product-a",
                "requirement_kind": "comparison_basis",
                "subject_id": "PRODUCT-A",
                "required_rule_unit_revision_ids": ("rule-a",),
            },
            {
                "slot_id": "product-b",
                "requirement_kind": "comparison_basis",
                "subject_id": "PRODUCT-B",
                "required_rule_unit_revision_ids": ("rule-b",),
            },
        ),
        expected_resolution="answer_with_citations",
        acl_hard_negative_rule_unit_revision_ids=("rule-restricted",),
        document_slice="product-terms",
        parser_slice="docling",
        acl_slice="restricted-mixed",
    )
    observation = InsuranceKnowledgeObservation(
        case_id=case.case_id,
        source_id="ks_insurance",
        source_publication_id="publication-7",
        source_publication_seq=7,
        ranked_rule_unit_revision_ids=(
            "rule-a",
            "rule-restricted",
            "noise-1",
            "noise-2",
            "noise-3",
            "rule-b",
        ),
        evidence_slot_ranks={"product-a": 1, "product-b": 6},
        resolvable_citation_rule_unit_revision_ids=("rule-a",),
        authority_failure_count=1,
    )

    report = evaluate_insurance_knowledge(cases=(case,), observations=(observation,))

    assert report.overall.complete_evidence_top_5_rate == 0.0
    assert report.overall.complete_evidence_top_10_rate == 1.0
    assert report.overall.mrr_at_10 == 1.0
    assert 0.0 < report.overall.ndcg_at_10 < 1.0
    assert report.overall.citation_resolvability_rate == 0.5
    assert report.overall.authority_failure_count == 1
    assert report.overall.unauthorized_candidate_exposure == 1
    assert {(item.dimension, item.value) for item in report.slices} == {
        ("query_type", "comparison"),
        ("document", "product-terms"),
        ("parser", "docling"),
        ("acl", "restricted-mixed"),
    }


def test_sample_suite_loads_exact_publication_authority_and_query_labels() -> None:
    suite = load_insurance_knowledge_suite(
        Path("proof_agent/evaluation/suites/insurance_knowledge_tuning.sample.yaml")
    )

    assert len(suite.cases) == 10
    assert [case.query_type for case in suite.cases].count("clause_lookup") == 3
    assert [case.query_type for case in suite.cases].count("conditional_guidance") == 5
    assert [case.query_type for case in suite.cases].count("comparison") == 2
    assert all(case.source_publication_id and case.source_publication_seq for case in suite.cases)
    assert all(case.required_evidence_slots for case in suite.cases)
    assert any(case.acl_hard_negative_rule_unit_revision_ids for case in suite.cases)
    assert {case.expected_knowledge_outcome for case in suite.cases} >= {
        "answer_with_citations",
        "ask_clarification",
        "conflict",
        "refuse_no_evidence",
    }


def test_clarification_case_requires_explicit_missing_fields() -> None:
    with pytest.raises(ValidationError, match="clarification fields"):
        InsuranceKnowledgeCase(
            case_id="missing-authority-condition",
            question="Can Product A be sold?",
            query_type="conditional_guidance",
            source_id="ks_insurance",
            source_publication_id="publication-7",
            source_publication_seq=7,
            required_evidence_slots=(
                {
                    "slot_id": "applicable-condition",
                    "requirement_kind": "applicable_condition",
                    "subject_id": "PRODUCT-A",
                },
            ),
            expected_resolution="ask_clarification",
            expected_knowledge_outcome="ask_clarification",
            expected_authority_outcome="FAIL",
            expected_clarification_fields=(),
        )


def test_non_answer_case_contributes_hard_facts_without_fabricated_ranking_gold() -> None:
    case = InsuranceKnowledgeCase(
        case_id="restricted-refusal",
        question="What does another institution's exception say?",
        query_type="conditional_guidance",
        source_id="ks_insurance",
        source_publication_id="publication-7",
        source_publication_seq=7,
        required_evidence_slots=(
            {
                "slot_id": "governing-rule",
                "requirement_kind": "governing_rule",
                "subject_id": "PRODUCT-A",
            },
        ),
        expected_resolution="refuse_no_evidence",
        expected_knowledge_outcome="refuse_no_evidence",
        expected_authority_outcome="FAIL",
        acl_hard_negative_rule_unit_revision_ids=("rule-other-institution",),
        acl_slice="restricted-hidden",
    )
    observation = InsuranceKnowledgeObservation(
        case_id=case.case_id,
        source_id=case.source_id,
        source_publication_id=case.source_publication_id,
        source_publication_seq=case.source_publication_seq,
        ranked_rule_unit_revision_ids=("rule-other-institution",),
    )

    report = evaluate_insurance_knowledge(cases=(case,), observations=(observation,))

    assert report.overall.retrieval_case_count == 0
    assert report.overall.required_evidence_recall_at_50 == 0.0
    assert report.overall.unauthorized_candidate_exposure == 1
