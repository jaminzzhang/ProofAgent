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
    EvaluationReleaseDecision,
    EvaluationReleaseDecisionStatus,
    EvaluationResponseProjectionSummary,
    EvaluationScenario,
    EvaluationScenarioLinkageMode,
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
        result
        for case, result in zip(suite.cases, case_results, strict=True)
        if case.required_for_release
    )
    subject_covered = sum(1 for result in required_results if result.subject_present)
    passed_required = sum(
        1 for result in required_results if result.status == EvaluationGateStatus.PASSED
    )
    required_scenarios = tuple(
        result
        for scenario, result in zip(suite.scenarios, scenario_results, strict=True)
        if scenario.required_for_release
    )
    passed_required_scenarios = sum(
        1 for result in required_scenarios if result.status == EvaluationGateStatus.PASSED
    )
    required_scenario_rate = (
        _rate(passed_required_scenarios, len(required_scenarios)) if required_scenarios else None
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
        scenario_governed_resolution_rate=required_scenario_rate or 0.0,
        release_decision=_release_decision(
            required_results=required_results,
            required_scenario_results=required_scenarios,
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
        result.actual_outcome.value for result in step_results if result.actual_outcome is not None
    )
    expected_ordered_outcomes = tuple(
        outcome.value for outcome in scenario.expected_ordered_outcomes
    )
    failed_step_ids = tuple(
        step.step_id
        for step, result in zip(scenario.steps, step_results, strict=True)
        if result.status == EvaluationGateStatus.FAILED
    )
    linkage_status, linkage_reason = _scenario_linkage_status(
        scenario,
        subject_by_ref=subject_by_ref,
    )
    approval_linkage_status, approval_linkage_reason = _scenario_approval_linkage_status(
        scenario,
        subject_by_ref=subject_by_ref,
    )
    order_matches = (
        not expected_ordered_outcomes or expected_ordered_outcomes == actual_ordered_outcomes
    )
    status = (
        EvaluationGateStatus.PASSED
        if (
            not failed_step_ids
            and order_matches
            and linkage_status == EvaluationGateStatus.PASSED
            and approval_linkage_status == EvaluationGateStatus.PASSED
        )
        else EvaluationGateStatus.FAILED
    )
    return EvaluationScenarioResult(
        scenario_id=scenario.scenario_id,
        status=status,
        expected_ordered_outcomes=expected_ordered_outcomes,
        actual_ordered_outcomes=actual_ordered_outcomes,
        step_results=step_results,
        failed_step_ids=failed_step_ids,
        linkage_status=linkage_status,
        linkage_reason=linkage_reason,
        approval_linkage_status=approval_linkage_status,
        approval_linkage_reason=approval_linkage_reason,
    )


def _scenario_linkage_status(
    scenario: EvaluationScenario,
    *,
    subject_by_ref: dict[SubjectKey, EvaluationSubject],
) -> tuple[EvaluationGateStatus, str | None]:
    if scenario.linkage.mode == EvaluationScenarioLinkageMode.NONE:
        return EvaluationGateStatus.PASSED, None
    subjects = tuple(subject_by_ref.get(_step_key(scenario, step)) for step in scenario.steps)
    if any(subject is None for subject in subjects):
        return (
            EvaluationGateStatus.FAILED,
            "scenario linkage could not be evaluated because one or more step subjects were missing",
        )
    resolved_subjects = tuple(subject for subject in subjects if subject is not None)
    if scenario.linkage.mode == EvaluationScenarioLinkageMode.SAME_CONVERSATION:
        conversation_ids = tuple(
            subject.run_ref.conversation_id
            for subject in resolved_subjects
            if subject.run_ref is not None
        )
        if len(conversation_ids) != len(subjects) or any(
            conversation_id is None for conversation_id in conversation_ids
        ):
            return (
                EvaluationGateStatus.FAILED,
                "same conversation linkage requires every scenario step subject to declare run_ref.conversation_id",
            )
        if len(set(conversation_ids)) != 1:
            return (
                EvaluationGateStatus.FAILED,
                "same conversation linkage expected one shared conversation_id",
            )
        return EvaluationGateStatus.PASSED, "same conversation linkage matched"
    if scenario.linkage.mode == EvaluationScenarioLinkageMode.SAME_CONTINUATION_GROUP:
        continuation_group_ids = tuple(
            subject.run_ref.continuation_group_id
            for subject in resolved_subjects
            if subject.run_ref is not None
        )
        turn_ids = tuple(
            subject.run_ref.turn_id for subject in resolved_subjects if subject.run_ref is not None
        )
        if (
            len(continuation_group_ids) != len(subjects)
            or len(turn_ids) != len(subjects)
            or any(group_id is None for group_id in continuation_group_ids)
            or any(turn_id is None for turn_id in turn_ids)
        ):
            return (
                EvaluationGateStatus.FAILED,
                "same continuation group linkage requires every scenario step subject to declare "
                "run_ref.continuation_group_id and run_ref.turn_id",
            )
        if len(set(continuation_group_ids)) != 1:
            return (
                EvaluationGateStatus.FAILED,
                "same continuation group linkage expected one shared continuation_group_id",
            )
        if len(set(turn_ids)) != len(turn_ids):
            return (
                EvaluationGateStatus.FAILED,
                "same continuation group linkage expected distinct turn_id values for scenario steps",
            )
        turn_id_values = tuple(str(turn_id) for turn_id in turn_ids)
        for index, subject in enumerate(resolved_subjects[1:], start=1):
            prior_turn_id = turn_id_values[index - 1]
            if not _trace_context_admission_includes(subject, prior_turn_id):
                return (
                    EvaluationGateStatus.FAILED,
                    "same continuation group linkage requires context_admission to include "
                    f"prior turn_id: {prior_turn_id}",
                )
        return EvaluationGateStatus.PASSED, "same continuation group linkage matched"
    return (
        EvaluationGateStatus.FAILED,
        f"scenario linkage mode is not implemented: {scenario.linkage.mode.value}",
    )


def _scenario_approval_linkage_status(
    scenario: EvaluationScenario,
    *,
    subject_by_ref: dict[SubjectKey, EvaluationSubject],
) -> tuple[EvaluationGateStatus, str | None]:
    expected_by_step = {
        step.step_id: step.approval_event_ids for step in scenario.steps if step.approval_event_ids
    }
    if not expected_by_step:
        return EvaluationGateStatus.PASSED, None
    missing_refs: list[str] = []
    for step in scenario.steps:
        expected = expected_by_step.get(step.step_id)
        if not expected:
            continue
        subject = subject_by_ref.get(_step_key(scenario, step))
        if subject is None:
            missing_refs.extend(expected)
            continue
        artifacts = read_evaluation_artifacts(subject)
        observed = {
            event.event_id
            for event in artifacts.trace_events
            if event.event_type
            in {
                "approval_requested",
                "approval_granted",
                "approval_denied",
                "approval_timeout",
            }
            and event.event_id is not None
        }
        missing_refs.extend(ref for ref in expected if ref not in observed)
    if missing_refs:
        return (
            EvaluationGateStatus.FAILED,
            "missing approval event refs: " + ", ".join(sorted(missing_refs)),
        )
    return EvaluationGateStatus.PASSED, "approval event references matched"


def _trace_context_admission_includes(subject: EvaluationSubject, turn_id: str) -> bool:
    artifacts = read_evaluation_artifacts(subject)
    for event in artifacts.trace_events:
        if event.event_type != "context_admission":
            continue
        if event.payload.get("admitted") is not True:
            continue
        included_turn_ids = event.payload.get("included_turn_ids")
        if isinstance(included_turn_ids, list | tuple) and turn_id in included_turn_ids:
            return True
    return False


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


def _release_decision(
    *,
    required_results: tuple[EvaluationCaseResult, ...],
    required_scenario_results: tuple[EvaluationScenarioResult, ...],
) -> EvaluationReleaseDecision:
    required_case_pass_rate = _rate(
        sum(1 for result in required_results if result.status == EvaluationGateStatus.PASSED),
        len(required_results),
    )
    required_artifact_sufficiency_rate = _rate(
        sum(
            1
            for result in required_results
            if result.artifact_sufficiency == EvaluationArtifactSufficiencyStatus.SUFFICIENT
        ),
        len(required_results),
    )
    required_deterministic_gate_pass_rate = _deterministic_gate_pass_rate(required_results)
    required_scenario_pass_rate = (
        _rate(
            sum(
                1
                for result in required_scenario_results
                if result.status == EvaluationGateStatus.PASSED
            ),
            len(required_scenario_results),
        )
        if required_scenario_results
        else None
    )

    blocking_reasons: list[str] = []
    if not required_results:
        blocking_reasons.append("no required release cases declared")
    else:
        if required_case_pass_rate < 1.0:
            blocking_reasons.append("required_case_pass_rate below release threshold")
        if required_artifact_sufficiency_rate < 1.0:
            blocking_reasons.append("artifact_sufficiency_rate below release threshold")
        if required_deterministic_gate_pass_rate < 1.0:
            blocking_reasons.append("deterministic_gate_pass_rate below release threshold")
    if required_scenario_pass_rate is not None and required_scenario_pass_rate < 1.0:
        blocking_reasons.append("scenario_pass_rate below release threshold")

    return EvaluationReleaseDecision(
        status=(
            EvaluationReleaseDecisionStatus.BLOCKED
            if blocking_reasons
            else EvaluationReleaseDecisionStatus.PASSED
        ),
        required_case_pass_rate=required_case_pass_rate,
        required_artifact_sufficiency_rate=required_artifact_sufficiency_rate,
        required_deterministic_gate_pass_rate=required_deterministic_gate_pass_rate,
        required_scenario_pass_rate=required_scenario_pass_rate,
        scenario_pass_threshold=1.0 if required_scenario_results else None,
        blocking_reasons=tuple(blocking_reasons),
    )


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
