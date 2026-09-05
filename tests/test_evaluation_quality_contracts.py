import pytest
from pydantic import ValidationError

from proof_agent.contracts import EvaluationCaseResult
from proof_agent.contracts.evaluation_quality import (
    EvaluationCaseQuality,
    EvaluationQualityCohort,
    EvaluationQualityMetrics,
)


def _cohort(**overrides):
    return (
        dict(
            target="answer_correctness",
            total=1,
            passed=0,
            failed=0,
            not_evaluated=1,
            verified_success_rate=0.0,
            assessment_coverage_rate=0.0,
        )
        | overrides
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"total": -1},
        {"total": True},
        {"passed": 1},
        {"not_evaluated": 0},
        {"verified_success_rate": float("nan")},
        {"assessment_coverage_rate": float("inf")},
        {"verified_success_rate": 1.0},
        {"assessment_coverage_rate": 1.0},
        {"unexpected": "ignored?"},
        {"verified_success_rate": False},
    ],
)
def test_invalid_counts_rates_and_fields_are_rejected(overrides) -> None:
    with pytest.raises(ValidationError):
        EvaluationQualityCohort.model_validate(_cohort(**overrides))


@pytest.mark.parametrize(
    "value",
    [
        {
            "target": "answer_correctness",
            "status": "passed",
            "reason": "answer_semantics_not_evaluated",
        },
        {"target": None, "status": "passed", "reason": "curated_refusal_decision_matched"},
        {
            "target": "task_completion",
            "status": "passed",
            "reason": "curated_refusal_decision_matched",
        },
        {"target": "refusal_appropriateness", "status": "failed", "reason": "missing_subject"},
        {
            "target": "refusal_appropriateness",
            "status": "not_evaluated",
            "reason": "answer_semantics_not_evaluated",
        },
        {
            "target": "answer_correctness",
            "status": "not_evaluated",
            "reason": "unclassified_expectation",
        },
    ],
)
def test_contradictory_case_quality_is_rejected(value) -> None:
    with pytest.raises(ValidationError):
        EvaluationCaseQuality.model_validate(value)


def test_quality_partition_roundtrip_immutability_and_empty_denominators() -> None:
    cohorts = [
        EvaluationQualityCohort.model_validate(
            _cohort(
                target=target,
                total=0,
                not_evaluated=0,
                verified_success_rate=None,
                assessment_coverage_rate=None,
            )
        )
        for target in ("answer_correctness", "refusal_appropriateness", "task_completion")
    ]
    metrics = EvaluationQualityMetrics(
        total_required_cases=0, unclassified_required_count=0, cohorts=tuple(cohorts)
    )
    assert EvaluationQualityMetrics.model_validate_json(metrics.model_dump_json()) == metrics
    with pytest.raises(ValidationError):
        metrics.total_required_cases = 1
    with pytest.raises(ValidationError):
        cohorts[0].total = 2
    with pytest.raises(ValidationError):
        EvaluationQualityMetrics.model_validate(metrics.model_dump() | {"total_required_cases": 1})
    with pytest.raises(ValidationError):
        EvaluationQualityMetrics.model_validate(
            metrics.model_dump() | {"cohorts": [cohorts[0]] * 3}
        )


def test_historical_result_without_quality_remains_unmeasured() -> None:
    result = EvaluationCaseResult.model_validate(
        {
            "case_id": "historical",
            "status": "passed",
            "expected_outcome": "ANSWERED_WITH_CITATIONS",
        }
    )
    assert result.quality is None
    assert EvaluationCaseResult.model_validate_json(result.model_dump_json()).quality is None
