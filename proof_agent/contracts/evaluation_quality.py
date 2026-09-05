"""Quality projections over completed evaluations, never execution authority."""

from enum import Enum
from typing import Literal, Self

from pydantic import Field, model_validator

from proof_agent.contracts._base import StrictFrozenModel


class EvaluationQualityTarget(str, Enum):
    ANSWER_CORRECTNESS = "answer_correctness"
    REFUSAL_APPROPRIATENESS = "refusal_appropriateness"
    TASK_COMPLETION = "task_completion"


class EvaluationQualityStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_EVALUATED = "not_evaluated"


class EvaluationQualityReason(str, Enum):
    UNCLASSIFIED_EXPECTATION = "unclassified_expectation"
    MISSING_SUBJECT = "missing_subject"
    ARTIFACTS_NOT_VERIFIED = "artifacts_not_verified"
    INCOMPLETE_GOVERNANCE_RECORD = "incomplete_governance_record"
    GOVERNED_RESOLUTION_FAILED = "governed_resolution_failed"
    ANSWER_SEMANTICS_NOT_EVALUATED = "answer_semantics_not_evaluated"
    REFUSAL_SEMANTICS_NOT_EVALUATED = "refusal_semantics_not_evaluated"
    TASK_COMPLETION_NOT_EVALUATED = "task_completion_not_evaluated"
    CURATED_REFUSAL_DECISION_MATCHED = "curated_refusal_decision_matched"


class EvaluationCaseQuality(StrictFrozenModel):
    target: EvaluationQualityTarget | None
    status: EvaluationQualityStatus
    reason: EvaluationQualityReason

    @model_validator(mode="after")
    def require_consistent_judgment(self) -> Self:
        reason = EvaluationQualityReason
        status = EvaluationQualityStatus
        target = EvaluationQualityTarget
        expected_status = {
            reason.CURATED_REFUSAL_DECISION_MATCHED: status.PASSED,
            reason.GOVERNED_RESOLUTION_FAILED: status.FAILED,
        }.get(self.reason, status.NOT_EVALUATED)
        if self.status != expected_status:
            raise ValueError("quality status must agree with its reason")
        if (self.target is None) != (self.reason == reason.UNCLASSIFIED_EXPECTATION):
            raise ValueError("only unclassified expectations may omit a quality target")
        reason_targets = {
            reason.ANSWER_SEMANTICS_NOT_EVALUATED: target.ANSWER_CORRECTNESS,
            reason.REFUSAL_SEMANTICS_NOT_EVALUATED: target.REFUSAL_APPROPRIATENESS,
            reason.CURATED_REFUSAL_DECISION_MATCHED: target.REFUSAL_APPROPRIATENESS,
            reason.TASK_COMPLETION_NOT_EVALUATED: target.TASK_COMPLETION,
        }
        if self.reason in reason_targets and self.target != reason_targets[self.reason]:
            raise ValueError("quality reason must agree with its target")
        return self


class EvaluationQualityCohort(StrictFrozenModel):
    target: EvaluationQualityTarget
    total: int = Field(ge=0, strict=True)
    passed: int = Field(ge=0, strict=True)
    failed: int = Field(ge=0, strict=True)
    not_evaluated: int = Field(ge=0, strict=True)
    verified_success_rate: float | None = Field(ge=0, le=1, allow_inf_nan=False, strict=True)
    assessment_coverage_rate: float | None = Field(ge=0, le=1, allow_inf_nan=False, strict=True)

    @model_validator(mode="after")
    def require_consistent_counts_and_rates(self) -> Self:
        if self.total != self.passed + self.failed + self.not_evaluated:
            raise ValueError("quality cohort counts must sum to total")
        success = self.passed / self.total if self.total else None
        coverage = (self.passed + self.failed) / self.total if self.total else None
        if self.verified_success_rate != success or self.assessment_coverage_rate != coverage:
            raise ValueError("quality cohort rates must use all required cases")
        return self


class EvaluationQualityMetrics(StrictFrozenModel):
    schema_version: Literal["evaluation-quality.v1"] = "evaluation-quality.v1"
    cohort_scope: Literal["required_standalone_cases"] = "required_standalone_cases"
    total_required_cases: int = Field(ge=0, strict=True)
    unclassified_required_count: int = Field(ge=0, strict=True)
    cohorts: tuple[EvaluationQualityCohort, ...] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def require_complete_cohort_partition(self) -> Self:
        if {cohort.target for cohort in self.cohorts} != set(EvaluationQualityTarget):
            raise ValueError("quality metrics require each target exactly once")
        if self.total_required_cases != (
            self.unclassified_required_count + sum(cohort.total for cohort in self.cohorts)
        ):
            raise ValueError("quality metrics must include every required case")
        return self
