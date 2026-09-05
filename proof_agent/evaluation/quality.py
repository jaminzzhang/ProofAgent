"""Conservative quality measurement, separate from governed resolution."""

from proof_agent.contracts import (
    EvaluationArtifactSufficiencyStatus,
    EvaluationCase,
    EvaluationCaseResult,
    EvaluationExpectedResolution,
    EvaluationGateName,
    EvaluationGateStatus,
)
from proof_agent.contracts.evaluation_quality import (
    EvaluationCaseQuality,
    EvaluationQualityCohort,
    EvaluationQualityMetrics,
    EvaluationQualityReason as Reason,
    EvaluationQualityStatus as Status,
    EvaluationQualityTarget as Target,
)
from proof_agent.contracts.receipt import ReceiptOutcome
from proof_agent.evaluation.artifact_reader import EvaluationArtifacts
from proof_agent.evaluation.gate_profiles import CORE_ANALYZER_GATES_V1


def summarize_quality(
    required_pairs: tuple[tuple[EvaluationCase, EvaluationCaseResult], ...],
) -> EvaluationQualityMetrics:
    qualities = tuple(
        result.quality or assess_case_quality(case, result) for case, result in required_pairs
    )
    cohorts = []
    for target in Target:
        cases = tuple(quality for quality in qualities if quality.target == target)
        total = len(cases)
        passed = sum(quality.status == Status.PASSED for quality in cases)
        failed = sum(quality.status == Status.FAILED for quality in cases)
        cohorts.append(
            EvaluationQualityCohort(
                target=target,
                total=total,
                passed=passed,
                failed=failed,
                not_evaluated=total - passed - failed,
                verified_success_rate=passed / total if total else None,
                assessment_coverage_rate=(passed + failed) / total if total else None,
            )
        )
    return EvaluationQualityMetrics(
        total_required_cases=len(qualities),
        unclassified_required_count=sum(quality.target is None for quality in qualities),
        cohorts=tuple(cohorts),
    )


def assess_case_quality(
    case: EvaluationCase,
    result: EvaluationCaseResult,
    *,
    artifacts: EvaluationArtifacts | None = None,
) -> EvaluationCaseQuality:
    target = _target(case)
    status = Status.NOT_EVALUATED
    if target is None:
        reason = Reason.UNCLASSIFIED_EXPECTATION
    elif not result.subject_present:
        reason = Reason.MISSING_SUBJECT
    elif not _verified_artifacts(result):
        reason = Reason.ARTIFACTS_NOT_VERIFIED
    else:
        gates = {gate.gate: gate for gate in result.gates}
        required = CORE_ANALYZER_GATES_V1.required_gates
        audit = gates.get(EvaluationGateName.AUDIT_ARTIFACT)
        if (
            len(gates) != len(result.gates)
            or not set(required).issubset(gates)
            or result.actual_outcome is None
            or artifacts is None
            or artifacts.trace_final_outcome is None
            or artifacts.trace_final_outcome != artifacts.actual_outcome
            or artifacts.trace_final_outcome != artifacts.receipt_outcome
            or (
                artifacts.run_meta is not None
                and "outcome" in artifacts.run_meta
                and artifacts.run_meta["outcome"] != artifacts.trace_final_outcome
            )
            or audit is None
            or audit.status != EvaluationGateStatus.PASSED
            or any(
                gate.sufficiency == EvaluationArtifactSufficiencyStatus.INSUFFICIENT
                for gate in result.gates
            )
        ):
            reason = Reason.INCOMPLETE_GOVERNANCE_RECORD
        elif any(gates[name].status == EvaluationGateStatus.FAILED for name in required):
            status, reason = Status.FAILED, Reason.GOVERNED_RESOLUTION_FAILED
        elif any(gates[name].status != EvaluationGateStatus.PASSED for name in required):
            reason = Reason.INCOMPLETE_GOVERNANCE_RECORD
        elif target == Target.ANSWER_CORRECTNESS:
            reason = Reason.ANSWER_SEMANTICS_NOT_EVALUATED
        elif target == Target.TASK_COMPLETION:
            reason = Reason.TASK_COMPLETION_NOT_EVALUATED
        elif case.expected.required_business_claims or case.expected.forbidden_claim_categories:
            reason = Reason.REFUSAL_SEMANTICS_NOT_EVALUATED
        else:
            status, reason = Status.PASSED, Reason.CURATED_REFUSAL_DECISION_MATCHED
    return EvaluationCaseQuality(target=target, status=status, reason=reason)


def _verified_artifacts(result: EvaluationCaseResult) -> bool:
    if result.artifact_sufficiency != EvaluationArtifactSufficiencyStatus.SUFFICIENT:
        return False
    refs = [result.trace, result.receipt]
    if result.run_meta is not None:
        refs.append(result.run_meta)
    if any(
        ref is None or not ref.declared_sha256 or ref.declared_sha256 != ref.observed_sha256
        for ref in refs
    ):
        return False
    projection = result.response_projection
    return bool(
        projection
        and projection.declared_sha256
        and projection.declared_sha256 == projection.observed_text_sha256
    )


def _target(case: EvaluationCase) -> Target | None:
    if case.quality_target is not None:
        return case.quality_target
    if (
        case.expected_resolution == EvaluationExpectedResolution.ANSWER_WITH_CITATIONS
        and case.expected.outcome == ReceiptOutcome.ANSWERED_WITH_CITATIONS
    ):
        return Target.ANSWER_CORRECTNESS
    if (
        case.expected_resolution == EvaluationExpectedResolution.REFUSE_NO_EVIDENCE
        and case.expected.outcome == ReceiptOutcome.REFUSED_NO_EVIDENCE
    ):
        return Target.REFUSAL_APPROPRIATENESS
    return None
