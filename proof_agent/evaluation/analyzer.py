from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path

from proof_agent.contracts import (
    EvaluationAnalysisSummary,
    EvaluationArtifactRef,
    EvaluationArtifactSufficiencyStatus,
    EvaluationArtifactSummary,
    EvaluationCase,
    EvaluationCaseResult,
    EvaluationFailureOwner,
    EvaluationGateAutomationLevel,
    EvaluationGateName,
    EvaluationGateResult,
    EvaluationGateStatus,
    EvaluationNodeResult,
    EvaluationResponseProjectionSummary,
    EvaluationScenario,
    EvaluationScenarioResult,
    EvaluationScenarioStep,
    EvaluationSubject,
)
from proof_agent.evaluation.artifact_reader import read_evaluation_artifacts
from proof_agent.evaluation.artifacts import write_evaluation_analysis_artifacts
from proof_agent.evaluation.errors import EvaluationInputError
from proof_agent.evaluation.gate_profiles import get_gate_profile
from proof_agent.evaluation.gates import evaluate_case_gates
from proof_agent.evaluation.node_results import extract_evaluation_node_results
from proof_agent.evaluation.subjects import load_evaluation_subject_manifest
from proof_agent.evaluation.suites import load_evaluation_suite


def analyze_evaluation(
    *,
    suite_path: Path | str,
    subjects_path: Path | str,
    output_dir: Path | str | None = None,
) -> EvaluationAnalysisSummary:
    """Analyze completed governed run artifacts without creating Agent runs."""

    suite = load_evaluation_suite(suite_path)
    gate_profile = get_gate_profile(suite.gate_profile_id)
    manifest = load_evaluation_subject_manifest(subjects_path)
    if manifest.suite_id != suite.suite_id:
        raise EvaluationInputError(
            f"subject manifest suite_id {manifest.suite_id} does not match suite {suite.suite_id}"
        )

    subject_by_case_id = _unscoped_subjects_by_case_id(manifest.subjects)
    subject_by_ref = _subjects_by_ref(manifest.subjects)
    case_by_id = {case.case_id: case for case in suite.cases}
    warnings = _extra_subject_warnings(
        manifest.subjects,
        expected_keys=_expected_subject_keys(suite.cases, suite.scenarios),
    )
    case_results = tuple(
        _analyze_case(case, subject_by_case_id.get(case.case_id)) for case in suite.cases
    )
    scenario_results = tuple(
        _analyze_scenario(scenario, case_by_id=case_by_id, subject_by_ref=subject_by_ref)
        for scenario in suite.scenarios
    )
    required_results = tuple(
        result for case, result in zip(suite.cases, case_results, strict=True)
        if case.required_for_release
    )
    subject_covered = sum(1 for result in required_results if result.subject_present)
    passed_required = sum(
        1 for result in required_results if result.status == EvaluationGateStatus.PASSED
    )
    required_scenarios = tuple(
        result for scenario, result in zip(suite.scenarios, scenario_results, strict=True)
        if scenario.required_for_release
    )
    passed_required_scenarios = sum(
        1 for result in required_scenarios if result.status == EvaluationGateStatus.PASSED
    )
    artifact_sufficient = sum(
        1
        for result in case_results
        if result.artifact_sufficiency == EvaluationArtifactSufficiencyStatus.SUFFICIENT
    )
    analysis_id = f"{suite.suite_id}-{manifest.manifest_id}"
    artifact_dir = Path(output_dir) / analysis_id if output_dir is not None else None
    summary = EvaluationAnalysisSummary(
        analysis_id=analysis_id,
        suite_id=suite.suite_id,
        suite_version=suite.version,
        subject_manifest_id=manifest.manifest_id,
        subject_manifest_version=manifest.version,
        gate_profile_id=gate_profile.profile_id,
        total_required_cases=len(required_results),
        passed_required_cases=passed_required,
        governed_resolution_rate=_rate(passed_required, len(required_results)),
        subject_coverage_rate=_rate(subject_covered, len(required_results)),
        artifact_sufficiency_rate=_rate(artifact_sufficient, len(case_results)),
        deterministic_gate_pass_rate=_deterministic_gate_pass_rate(case_results),
        case_results=case_results,
        scenario_results=scenario_results,
        scenario_governed_resolution_rate=_rate(
            passed_required_scenarios,
            len(required_scenarios),
        ),
        warnings=warnings,
        agent=dict(manifest.agent),
        artifact_dir=artifact_dir,
    )
    write_evaluation_analysis_artifacts(summary)
    return summary


SubjectKey = tuple[str, str | None, str | None]


def _unscoped_subjects_by_case_id(
    subjects: Iterable[EvaluationSubject],
) -> dict[str, EvaluationSubject]:
    subject_by_case_id: dict[str, EvaluationSubject] = {}
    for subject in subjects:
        if subject.case_ref.scenario_id is None and subject.case_ref.scenario_step_id is None:
            subject_by_case_id.setdefault(subject.case_ref.case_id, subject)
    return subject_by_case_id


def _subjects_by_ref(subjects: Iterable[EvaluationSubject]) -> dict[SubjectKey, EvaluationSubject]:
    subject_by_ref: dict[SubjectKey, EvaluationSubject] = {}
    for subject in subjects:
        subject_by_ref.setdefault(_subject_key(subject), subject)
    return subject_by_ref


def _subject_key(subject: EvaluationSubject) -> SubjectKey:
    return (
        subject.case_ref.case_id,
        subject.case_ref.scenario_id,
        subject.case_ref.scenario_step_id,
    )


def _step_key(scenario: EvaluationScenario, step: EvaluationScenarioStep) -> SubjectKey:
    return (step.case_id, scenario.scenario_id, step.step_id)


def _expected_subject_keys(
    cases: Iterable[EvaluationCase],
    scenarios: Iterable[EvaluationScenario],
) -> set[SubjectKey]:
    keys: set[SubjectKey] = {(case.case_id, None, None) for case in cases}
    for scenario in scenarios:
        for step in scenario.steps:
            keys.add(_step_key(scenario, step))
    return keys


def _extra_subject_warnings(
    subjects: Iterable[EvaluationSubject],
    *,
    expected_keys: set[SubjectKey],
) -> tuple[str, ...]:
    warnings: list[str] = []
    for subject in subjects:
        key = _subject_key(subject)
        if key in expected_keys:
            continue
        label = subject.case_ref.case_id
        if subject.case_ref.scenario_id is not None:
            label = f"{subject.case_ref.scenario_id}/{subject.case_ref.scenario_step_id}/{label}"
        warnings.append(f"extra subject ignored: {label}")
    return tuple(warnings)


def _analyze_scenario(
    scenario: EvaluationScenario,
    *,
    case_by_id: dict[str, EvaluationCase],
    subject_by_ref: dict[SubjectKey, EvaluationSubject],
) -> EvaluationScenarioResult:
    step_results = tuple(
        _analyze_scenario_step(scenario, step, case_by_id=case_by_id, subject_by_ref=subject_by_ref)
        for step in scenario.steps
    )
    actual_ordered_outcomes = tuple(
        result.actual_outcome.value
        for result in step_results
        if result.actual_outcome is not None
    )
    expected_ordered_outcomes = tuple(
        outcome.value for outcome in scenario.expected_ordered_outcomes
    )
    failed_step_ids = tuple(
        step.step_id
        for step, result in zip(scenario.steps, step_results, strict=True)
        if result.status == EvaluationGateStatus.FAILED
    )
    order_matches = (
        not expected_ordered_outcomes or expected_ordered_outcomes == actual_ordered_outcomes
    )
    status = (
        EvaluationGateStatus.PASSED
        if not failed_step_ids and order_matches
        else EvaluationGateStatus.FAILED
    )
    return EvaluationScenarioResult(
        scenario_id=scenario.scenario_id,
        status=status,
        expected_ordered_outcomes=expected_ordered_outcomes,
        actual_ordered_outcomes=actual_ordered_outcomes,
        step_results=step_results,
        failed_step_ids=failed_step_ids,
    )


def _analyze_scenario_step(
    scenario: EvaluationScenario,
    step: EvaluationScenarioStep,
    *,
    case_by_id: dict[str, EvaluationCase],
    subject_by_ref: dict[SubjectKey, EvaluationSubject],
) -> EvaluationCaseResult:
    case = case_by_id.get(step.case_id)
    if case is None:
        gate = EvaluationGateResult(
            gate=EvaluationGateName.SUBJECT_MAPPING,
            status=EvaluationGateStatus.FAILED,
            reason=f"scenario step referenced unknown case_id: {step.case_id}",
            failure_owner=EvaluationFailureOwner.LABEL_OR_CURATION_ISSUE,
        )
        return EvaluationCaseResult(
            case_id=step.case_id,
            scenario_id=scenario.scenario_id,
            scenario_step_id=step.step_id,
            status=EvaluationGateStatus.FAILED,
            expected_outcome=scenario.expected_ordered_outcomes[0],
            subject_present=False,
            gates=(gate,),
            primary_failure_owner=EvaluationFailureOwner.LABEL_OR_CURATION_ISSUE,
        )
    subject = subject_by_ref.get(_step_key(scenario, step))
    return _analyze_case(
        case,
        subject,
        scenario_id=scenario.scenario_id,
        scenario_step_id=step.step_id,
    )


def _analyze_case(
    case: EvaluationCase,
    subject: EvaluationSubject | None,
    *,
    scenario_id: str | None = None,
    scenario_step_id: str | None = None,
) -> EvaluationCaseResult:
    if subject is None:
        gate = EvaluationGateResult(
            gate=EvaluationGateName.SUBJECT_MAPPING,
            status=EvaluationGateStatus.FAILED,
            reason="required case did not have an explicit evaluation subject",
            failure_owner=EvaluationFailureOwner.LABEL_OR_CURATION_ISSUE,
        )
        return EvaluationCaseResult(
            case_id=case.case_id,
            scenario_id=scenario_id,
            scenario_step_id=scenario_step_id,
            status=EvaluationGateStatus.FAILED,
            expected_outcome=case.expected.outcome,
            subject_present=False,
            gates=(gate,),
            primary_failure_owner=EvaluationFailureOwner.LABEL_OR_CURATION_ISSUE,
        )

    artifacts = read_evaluation_artifacts(subject)
    gates = evaluate_case_gates(case, subject, artifacts)
    node_results = extract_evaluation_node_results(artifacts)
    status = _case_status(gates)
    return EvaluationCaseResult(
        case_id=case.case_id,
        scenario_id=scenario_id,
        scenario_step_id=scenario_step_id,
        status=status,
        expected_outcome=case.expected.outcome,
        actual_outcome=artifacts.actual_outcome,
        subject_present=True,
        gates=gates,
        node_results=node_results,
        trace=_artifact_summary(subject.trace),
        receipt=_artifact_summary(subject.receipt),
        run_meta=_artifact_summary(subject.run_meta) if subject.run_meta is not None else None,
        response_projection=_response_projection_summary(subject, artifacts.response_text),
        artifact_sufficiency=_artifact_sufficiency(gates),
        primary_failure_owner=(
            _primary_failure_owner(gates, node_results)
            if status == EvaluationGateStatus.FAILED
            else None
        ),
    )


def _case_status(gates: tuple[EvaluationGateResult, ...]) -> EvaluationGateStatus:
    for gate in gates:
        if gate.automation_level == EvaluationGateAutomationLevel.DIAGNOSTIC:
            continue
        if gate.status != EvaluationGateStatus.PASSED:
            return EvaluationGateStatus.FAILED
    return EvaluationGateStatus.PASSED


def _artifact_sufficiency(
    gates: tuple[EvaluationGateResult, ...],
) -> EvaluationArtifactSufficiencyStatus | None:
    for gate in gates:
        if gate.gate == EvaluationGateName.ARTIFACT_SUFFICIENCY:
            return gate.sufficiency
    return None


def _primary_failure_owner(
    gates: tuple[EvaluationGateResult, ...],
    node_results: tuple[EvaluationNodeResult, ...],
) -> EvaluationFailureOwner | None:
    for gate in gates:
        if gate.status == EvaluationGateStatus.FAILED and gate.failure_owner is not None:
            return gate.failure_owner
    for node_result in node_results:
        if (
            node_result.status == EvaluationGateStatus.FAILED
            and node_result.failure_owner is not None
        ):
            return node_result.failure_owner
    return None


def _deterministic_gate_pass_rate(case_results: tuple[EvaluationCaseResult, ...]) -> float:
    deterministic_gates = [
        gate
        for result in case_results
        for gate in result.gates
        if gate.automation_level != EvaluationGateAutomationLevel.DIAGNOSTIC
    ]
    passed = sum(1 for gate in deterministic_gates if gate.status == EvaluationGateStatus.PASSED)
    return _rate(passed, len(deterministic_gates))


def _rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _artifact_summary(ref: EvaluationArtifactRef) -> EvaluationArtifactSummary:
    return EvaluationArtifactSummary(
        ref=ref.ref,
        declared_sha256=ref.sha256,
        observed_sha256=_file_sha256(ref.ref) if ref.ref.exists() else None,
    )


def _response_projection_summary(
    subject: EvaluationSubject,
    response_text: str,
) -> EvaluationResponseProjectionSummary:
    projection = subject.response_projection
    return EvaluationResponseProjectionSummary(
        audience=projection.audience,
        ref=projection.ref,
        declared_sha256=projection.sha256,
        observed_text_sha256=hashlib.sha256(response_text.encode("utf-8")).hexdigest(),
        text_length=len(response_text),
        source="file" if projection.ref is not None else "inline",
        sensitivity=projection.sensitivity,
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
