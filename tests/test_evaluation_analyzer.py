import hashlib
import json
from pathlib import Path

import pytest

from proof_agent.contracts import EvaluationGateName, EvaluationGateStatus
from proof_agent.evaluation.analyzer import analyze_evaluation
from proof_agent.evaluation.errors import EvaluationInputError


def test_analyzer_marks_missing_required_subject_as_failed(tmp_path: Path) -> None:
    suite_path, subjects_path = _write_analyzer_fixture(tmp_path)

    summary = analyze_evaluation(
        suite_path=suite_path,
        subjects_path=subjects_path,
        output_dir=tmp_path / "evaluations",
    )

    results = {result.case_id: result for result in summary.case_results}
    assert summary.total_required_cases == 2
    assert summary.passed_required_cases == 1
    assert summary.governed_resolution_rate == 0.5
    assert results["missing"].status == EvaluationGateStatus.FAILED
    assert results["missing"].gates[0].gate == EvaluationGateName.SUBJECT_MAPPING
    assert results["missing"].gates[0].status == EvaluationGateStatus.FAILED
    assert not (tmp_path / "runs" / "latest").exists()


def test_analyzer_writes_report_results_and_analysis_receipt(tmp_path: Path) -> None:
    suite_path, subjects_path = _write_analyzer_fixture(tmp_path)

    summary = analyze_evaluation(
        suite_path=suite_path,
        subjects_path=subjects_path,
        output_dir=tmp_path / "evaluations",
    )

    artifact_dir = tmp_path / "evaluations" / summary.analysis_id
    assert summary.artifact_dir == artifact_dir
    assert (artifact_dir / "evaluation_report.md").exists()
    assert (artifact_dir / "evaluation_analysis_receipt.md").exists()
    result_lines = (
        (artifact_dir / "evaluation_results.jsonl").read_text(encoding="utf-8").splitlines()
    )
    first_result = json.loads(result_lines[0])
    assert first_result["case_id"] == "supported"
    assert first_result["trace"]["ref"].endswith("runs/history/run_supported/trace.jsonl")
    assert "observed_sha256" in first_result["trace"]
    assert first_result["receipt"]["ref"].endswith(
        "runs/history/run_supported/governance_receipt.md"
    )
    assert first_result["response_projection"]["audience"] == "operator"
    assert first_result["response_projection"]["text_length"] == len("Covered by policy.")
    assert "response_text" not in first_result
    receipt = (artifact_dir / "evaluation_analysis_receipt.md").read_text(encoding="utf-8")
    assert "analyzer_version: evaluation-analyzer.v1" in receipt
    assert "release_decision: blocked" in receipt
    assert "release_blocking_reasons:" in receipt
    assert "judge_mode: none" in receipt
    assert "agent_id: react_enterprise_qa" in receipt


def test_analyzer_rejects_unknown_gate_profile(tmp_path: Path) -> None:
    suite_path, subjects_path = _write_analyzer_fixture(tmp_path)
    suite_path.write_text(
        suite_path.read_text(encoding="utf-8").replace(
            "name: Insurance QA Smoke\n",
            "name: Insurance QA Smoke\ngate_profile_id: unknown\n",
        ),
        encoding="utf-8",
    )

    with pytest.raises(EvaluationInputError, match="Unknown evaluation gate profile"):
        analyze_evaluation(
            suite_path=suite_path,
            subjects_path=subjects_path,
            output_dir=tmp_path / "evaluations",
        )


def test_analyzer_warns_about_extra_subjects_without_affecting_grr(tmp_path: Path) -> None:
    suite_path, subjects_path = _write_analyzer_fixture(tmp_path)
    _write_run_artifacts(
        tmp_path,
        run_id="run_extra",
        outcome="REFUSED_NO_EVIDENCE",
        response="Extra response.",
    )
    subjects_path.write_text(
        subjects_path.read_text(encoding="utf-8")
        + """
  - case_ref:
      case_id: extra_case
    artifacts:
      trace_ref: runs/history/run_extra/trace.jsonl
      receipt_ref: runs/history/run_extra/governance_receipt.md
    projections:
      evaluated_response:
        audience: operator
        ref: runs/history/run_extra/operator_response.txt
""",
        encoding="utf-8",
    )

    summary = analyze_evaluation(
        suite_path=suite_path,
        subjects_path=subjects_path,
        output_dir=tmp_path / "evaluations",
    )

    assert summary.governed_resolution_rate == 0.5
    assert summary.warnings == ("extra subject ignored: extra_case",)


def test_analyzer_reports_v3_intent_execution_behavior_metrics(tmp_path: Path) -> None:
    suite_path, subjects_path = _write_v3_intent_metrics_fixture(tmp_path)

    summary = analyze_evaluation(
        suite_path=suite_path,
        subjects_path=subjects_path,
        output_dir=tmp_path / "evaluations",
    )

    assert summary.behavior_metrics == {
        "inappropriate_clarification_rate": 0.0,
        "action_constraint_rewrite_rate": 0.0,
        "repeated_identical_retrieval_rate": 0.0,
        "evidence_support_rate": 1.0,
        "citation_projection_completeness": 1.0,
    }
    report = (
        tmp_path
        / "evaluations"
        / summary.analysis_id
        / "evaluation_report.md"
    ).read_text(encoding="utf-8")
    assert "- bfsp_recommendation_accuracy:" not in report
    assert "- inappropriate_clarification_rate: 0.000" in report


def test_analyzer_reports_scenario_ordered_outcomes(tmp_path: Path) -> None:
    suite_path, subjects_path = _write_scenario_fixture(tmp_path)

    summary = analyze_evaluation(
        suite_path=suite_path,
        subjects_path=subjects_path,
        output_dir=tmp_path / "evaluations",
    )

    scenario = summary.scenario_results[0]
    assert scenario.scenario_id == "supported_then_refused"
    assert scenario.status == EvaluationGateStatus.PASSED
    assert scenario.actual_ordered_outcomes == (
        "ANSWERED_WITH_CITATIONS",
        "REFUSED_NO_EVIDENCE",
    )
    assert scenario.failed_step_ids == ()
    assert "supported_then_refused" in (
        tmp_path / "evaluations" / summary.analysis_id / "evaluation_report.md"
    ).read_text(encoding="utf-8")


def test_analyzer_fails_scenario_when_same_conversation_linkage_is_broken(
    tmp_path: Path,
) -> None:
    suite_path, subjects_path = _write_scenario_fixture(tmp_path)
    suite_path.write_text(
        suite_path.read_text(encoding="utf-8").replace(
            "    expected_ordered_outcomes:\n",
            "    linkage:\n      mode: same_conversation\n    expected_ordered_outcomes:\n",
        ),
        encoding="utf-8",
    )
    _add_scenario_run_refs(
        subjects_path, first_conversation_id="convo_a", second_conversation_id="convo_b"
    )

    summary = analyze_evaluation(
        suite_path=suite_path,
        subjects_path=subjects_path,
        output_dir=tmp_path / "evaluations",
    )

    scenario = summary.scenario_results[0]
    assert scenario.status == EvaluationGateStatus.FAILED
    assert scenario.linkage_status == EvaluationGateStatus.FAILED
    assert "same conversation" in str(scenario.linkage_reason)
    assert "scenario_pass_rate below release threshold" in summary.release_decision.blocking_reasons


def test_analyzer_passes_same_conversation_linkage_when_step_subjects_match(
    tmp_path: Path,
) -> None:
    suite_path, subjects_path = _write_scenario_fixture(tmp_path)
    suite_path.write_text(
        suite_path.read_text(encoding="utf-8").replace(
            "    expected_ordered_outcomes:\n",
            "    linkage:\n      mode: same_conversation\n    expected_ordered_outcomes:\n",
        ),
        encoding="utf-8",
    )
    _add_scenario_run_refs(
        subjects_path, first_conversation_id="convo_a", second_conversation_id="convo_a"
    )

    summary = analyze_evaluation(
        suite_path=suite_path,
        subjects_path=subjects_path,
        output_dir=tmp_path / "evaluations",
    )

    scenario = summary.scenario_results[0]
    assert scenario.status == EvaluationGateStatus.PASSED
    assert scenario.linkage_status == EvaluationGateStatus.PASSED


def test_analyzer_passes_same_continuation_group_linkage_when_step_subjects_match(
    tmp_path: Path,
) -> None:
    suite_path, subjects_path = _write_scenario_fixture(tmp_path)
    suite_path.write_text(
        suite_path.read_text(encoding="utf-8").replace(
            "    expected_ordered_outcomes:\n",
            "    linkage:\n      mode: same_continuation_group\n    expected_ordered_outcomes:\n",
        ),
        encoding="utf-8",
    )
    _add_scenario_run_refs(
        subjects_path,
        first_conversation_id="convo_a",
        second_conversation_id="convo_b",
        first_turn_id="turn_1",
        second_turn_id="turn_2",
        first_continuation_group_id="continuation_1",
        second_continuation_group_id="continuation_1",
    )
    _add_context_admission_event(
        tmp_path,
        run_id="run_refused",
        included_turn_ids=("turn_1",),
    )

    summary = analyze_evaluation(
        suite_path=suite_path,
        subjects_path=subjects_path,
        output_dir=tmp_path / "evaluations",
    )

    scenario = summary.scenario_results[0]
    assert scenario.status == EvaluationGateStatus.PASSED
    assert scenario.linkage_status == EvaluationGateStatus.PASSED
    assert scenario.linkage_reason == "same continuation group linkage matched"


def test_analyzer_fails_same_continuation_group_without_context_admission_proof(
    tmp_path: Path,
) -> None:
    suite_path, subjects_path = _write_scenario_fixture(tmp_path)
    suite_path.write_text(
        suite_path.read_text(encoding="utf-8").replace(
            "    expected_ordered_outcomes:\n",
            "    linkage:\n      mode: same_continuation_group\n    expected_ordered_outcomes:\n",
        ),
        encoding="utf-8",
    )
    _add_scenario_run_refs(
        subjects_path,
        first_conversation_id="convo_a",
        second_conversation_id="convo_b",
        first_turn_id="turn_1",
        second_turn_id="turn_2",
        first_continuation_group_id="continuation_1",
        second_continuation_group_id="continuation_1",
    )

    summary = analyze_evaluation(
        suite_path=suite_path,
        subjects_path=subjects_path,
        output_dir=tmp_path / "evaluations",
    )

    scenario = summary.scenario_results[0]
    assert scenario.status == EvaluationGateStatus.FAILED
    assert scenario.linkage_status == EvaluationGateStatus.FAILED
    assert (
        "same continuation group linkage requires context_admission to include prior turn_id: turn_1"
        == scenario.linkage_reason
    )


def test_analyzer_fails_same_continuation_group_when_group_ids_differ(
    tmp_path: Path,
) -> None:
    suite_path, subjects_path = _write_scenario_fixture(tmp_path)
    suite_path.write_text(
        suite_path.read_text(encoding="utf-8").replace(
            "    expected_ordered_outcomes:\n",
            "    linkage:\n      mode: same_continuation_group\n    expected_ordered_outcomes:\n",
        ),
        encoding="utf-8",
    )
    _add_scenario_run_refs(
        subjects_path,
        first_conversation_id="convo_a",
        second_conversation_id="convo_b",
        first_turn_id="turn_1",
        second_turn_id="turn_2",
        first_continuation_group_id="continuation_1",
        second_continuation_group_id="continuation_2",
    )

    summary = analyze_evaluation(
        suite_path=suite_path,
        subjects_path=subjects_path,
        output_dir=tmp_path / "evaluations",
    )

    scenario = summary.scenario_results[0]
    assert scenario.status == EvaluationGateStatus.FAILED
    assert (
        "same continuation group linkage expected one shared continuation_group_id"
        == scenario.linkage_reason
    )


def test_analyzer_fails_same_continuation_group_when_turn_id_is_reused(
    tmp_path: Path,
) -> None:
    suite_path, subjects_path = _write_scenario_fixture(tmp_path)
    suite_path.write_text(
        suite_path.read_text(encoding="utf-8").replace(
            "    expected_ordered_outcomes:\n",
            "    linkage:\n      mode: same_continuation_group\n    expected_ordered_outcomes:\n",
        ),
        encoding="utf-8",
    )
    _add_scenario_run_refs(
        subjects_path,
        first_conversation_id="convo_a",
        second_conversation_id="convo_b",
        first_turn_id="turn_1",
        second_turn_id="turn_1",
        first_continuation_group_id="continuation_1",
        second_continuation_group_id="continuation_1",
    )

    summary = analyze_evaluation(
        suite_path=suite_path,
        subjects_path=subjects_path,
        output_dir=tmp_path / "evaluations",
    )

    scenario = summary.scenario_results[0]
    assert scenario.status == EvaluationGateStatus.FAILED
    assert (
        "same continuation group linkage expected distinct turn_id values for scenario steps"
        == scenario.linkage_reason
    )


def test_analyzer_fails_tool_scenario_when_approval_event_reference_is_missing(
    tmp_path: Path,
) -> None:
    suite_path, subjects_path = _write_tool_approval_scenario_fixture(
        tmp_path,
        declared_approval_event_id="evt_missing",
    )

    summary = analyze_evaluation(
        suite_path=suite_path,
        subjects_path=subjects_path,
        output_dir=tmp_path / "evaluations",
    )

    scenario = summary.scenario_results[0]
    assert scenario.step_results[0].status == EvaluationGateStatus.PASSED
    assert scenario.status == EvaluationGateStatus.FAILED
    assert scenario.approval_linkage_status == EvaluationGateStatus.FAILED
    assert "missing approval event refs: evt_missing" == scenario.approval_linkage_reason


def test_analyzer_passes_tool_scenario_when_approval_event_reference_matches(
    tmp_path: Path,
) -> None:
    suite_path, subjects_path = _write_tool_approval_scenario_fixture(
        tmp_path,
        declared_approval_event_id="evt_approval_1",
    )

    summary = analyze_evaluation(
        suite_path=suite_path,
        subjects_path=subjects_path,
        output_dir=tmp_path / "evaluations",
    )

    scenario = summary.scenario_results[0]
    assert scenario.status == EvaluationGateStatus.PASSED
    assert scenario.approval_linkage_status == EvaluationGateStatus.PASSED


def test_analyzer_release_decision_blocks_local_only_required_artifacts(
    tmp_path: Path,
) -> None:
    suite_path, subjects_path = _write_single_passing_case_fixture(tmp_path)

    summary = analyze_evaluation(
        suite_path=suite_path,
        subjects_path=subjects_path,
        output_dir=tmp_path / "evaluations",
    )

    assert summary.passed_required_cases == 1
    assert summary.release_decision.status.value == "blocked"
    assert summary.release_decision.artifact_sufficiency_threshold == 1.0
    assert (
        "artifact_sufficiency_rate below release threshold"
        in summary.release_decision.blocking_reasons
    )


def test_analyzer_release_decision_passes_when_required_artifacts_are_sufficient(
    tmp_path: Path,
) -> None:
    suite_path, subjects_path = _write_single_passing_case_fixture(
        tmp_path,
        include_hashes=True,
    )

    summary = analyze_evaluation(
        suite_path=suite_path,
        subjects_path=subjects_path,
        output_dir=tmp_path / "evaluations",
    )

    assert summary.release_decision.status.value == "passed"
    assert summary.release_decision.blocking_reasons == ()
    assert summary.release_decision.required_case_pass_rate == 1.0
    assert summary.release_decision.required_artifact_sufficiency_rate == 1.0
    assert summary.release_decision.required_deterministic_gate_pass_rate == 1.0


def _write_analyzer_fixture(tmp_path: Path) -> tuple[Path, Path]:
    suite_path = tmp_path / "suite.yaml"
    subjects_path = tmp_path / "subjects.yaml"
    run_dir = tmp_path / "runs" / "history" / "run_supported"
    run_dir.mkdir(parents=True)
    (run_dir / "trace.jsonl").write_text(
        '{"event_type":"retrieval_result","status":"ok","payload":{"source_refs":["policy"]}}\n'
        '{"event_type":"evidence_evaluation","status":"ok",'
        '"payload":{"metadata":{"accepted_count":1},"accepted_sources":["policy"]}}\n'
        '{"event_type":"policy_decision","status":"ok"}\n'
        '{"event_type":"final_output","status":"ok",'
        '"payload":{"outcome":"ANSWERED_WITH_CITATIONS"}}\n',
        encoding="utf-8",
    )
    (run_dir / "governance_receipt.md").write_text(
        "# Governance Receipt\n\n## Final Outcome\n\nANSWERED_WITH_CITATIONS\n",
        encoding="utf-8",
    )
    (run_dir / "operator_response.txt").write_text("Covered by policy.", encoding="utf-8")
    suite_path.write_text(
        """
suite_id: insurance_qa_smoke
version: "2026-06-07"
name: Insurance QA Smoke
cases:
  - case_id: supported
    question: Supported?
    intent_type: guidance
    expected_resolution: answer_with_citations
    risk_class: low
    capability_path: retrieval_only
    expected:
      outcome: ANSWERED_WITH_CITATIONS
      required_citation_refs:
        - policy
  - case_id: missing
    question: Missing?
    intent_type: guidance
    expected_resolution: refuse_no_evidence
    risk_class: low
    capability_path: retrieval_only
    expected:
      outcome: REFUSED_NO_EVIDENCE
""".lstrip(),
        encoding="utf-8",
    )
    subjects_path.write_text(
        """
manifest_id: local_subjects
version: "2026-06-07"
suite_id: insurance_qa_smoke
agent:
  agent_id: react_enterprise_qa
  agent_version_id: local
subjects:
  - case_ref:
      case_id: supported
    artifacts:
      trace_ref: runs/history/run_supported/trace.jsonl
      receipt_ref: runs/history/run_supported/governance_receipt.md
    projections:
      evaluated_response:
        audience: operator
        ref: runs/history/run_supported/operator_response.txt
""".lstrip(),
        encoding="utf-8",
    )
    return suite_path, subjects_path


def _write_single_passing_case_fixture(
    tmp_path: Path,
    *,
    include_hashes: bool = False,
) -> tuple[Path, Path]:
    suite_path = tmp_path / "release-suite.yaml"
    subjects_path = tmp_path / "release-subjects.yaml"
    _write_run_artifacts(
        tmp_path,
        run_id="run_supported",
        outcome="ANSWERED_WITH_CITATIONS",
        response="Covered by policy.",
    )
    run_dir = tmp_path / "runs" / "history" / "run_supported"
    trace_sha = _sha256(run_dir / "trace.jsonl")
    receipt_sha = _sha256(run_dir / "governance_receipt.md")
    response_sha = _sha256(run_dir / "operator_response.txt")
    artifact_hashes = (
        f"""
      trace_sha256: {trace_sha}
      receipt_sha256: {receipt_sha}
"""
        if include_hashes
        else ""
    )
    response_hash = f"        sha256: {response_sha}\n" if include_hashes else ""
    suite_path.write_text(
        """
suite_id: insurance_qa_release
version: "2026-06-07"
name: Insurance QA Release
cases:
  - case_id: supported
    question: Supported?
    intent_type: guidance
    expected_resolution: answer_with_citations
    risk_class: low
    capability_path: retrieval_only
    expected:
      outcome: ANSWERED_WITH_CITATIONS
      required_citation_refs:
        - policy
""".lstrip(),
        encoding="utf-8",
    )
    subjects_path.write_text(
        f"""
manifest_id: release_subjects
version: "2026-06-07"
suite_id: insurance_qa_release
subjects:
  - case_ref:
      case_id: supported
    artifacts:
      trace_ref: runs/history/run_supported/trace.jsonl
      receipt_ref: runs/history/run_supported/governance_receipt.md
{artifact_hashes.rstrip()}
    projections:
      evaluated_response:
        audience: operator
        ref: runs/history/run_supported/operator_response.txt
{response_hash.rstrip()}
""".lstrip(),
        encoding="utf-8",
    )
    return suite_path, subjects_path


def _write_v3_intent_metrics_fixture(tmp_path: Path) -> tuple[Path, Path]:
    suite_path = tmp_path / "v3-intent-suite.yaml"
    subjects_path = tmp_path / "v3-intent-subjects.yaml"
    run_dir = tmp_path / "runs" / "history" / "run_v3_policy"
    run_dir.mkdir(parents=True)
    run_dir.joinpath("trace.jsonl").write_text(
        '{"event_type":"business_flow_skill_pack_recommendation","status":"ok",'
        '"payload":{"recommendation_type":"single_pack",'
        '"candidate_packs":[{"pack_id":"enterprise_policy_qa","confidence":0.9}]}}\n'
        '{"event_type":"business_flow_skill_pack_admission","status":"ok",'
        '"payload":{"decision":"admitted","selected_pack_id":"enterprise_policy_qa"}}\n'
        '{"event_type":"retrieval_step","status":"ok",'
        '"payload":{"query":"travel meal reimbursement"}}\n'
        '{"event_type":"retrieval_result","status":"ok",'
        '"payload":{"source_refs":["customer-support-policy"]}}\n'
        '{"event_type":"evidence_evaluation","status":"ok",'
        '"payload":{"metadata":{"accepted_count":1},'
        '"accepted_sources":["customer-support-policy"]}}\n'
        '{"event_type":"policy_decision","status":"ok"}\n'
        '{"event_type":"final_output","status":"ok",'
        '"payload":{"outcome":"ANSWERED_WITH_CITATIONS"}}\n',
        encoding="utf-8",
    )
    run_dir.joinpath("governance_receipt.md").write_text(
        "# Governance Receipt\n\n## Final Outcome\n\nANSWERED_WITH_CITATIONS\n",
        encoding="utf-8",
    )
    run_dir.joinpath("operator_response.txt").write_text(
        "Travel meals are reimbursed. citation_refs: customer-support-policy",
        encoding="utf-8",
    )
    suite_path.write_text(
        """
suite_id: v3_intent_execution
version: "2026-06-21"
name: V3 Intent Execution
cases:
  - case_id: v3_policy_answer
    question: What is the reimbursement rule for travel meals?
    intent_type: enterprise_policy_question
    expected_resolution: answer_with_citations
    risk_class: low_business_fact
    capability_path: retrieval_only
    expected:
      outcome: ANSWERED_WITH_CITATIONS
      required_citation_refs:
        - customer-support-policy
      forbid_clarification: true
      max_action_constraint_rewrites: 0
      forbid_repeated_retrieval_queries: true
      require_response_citation_refs: true
""".lstrip(),
        encoding="utf-8",
    )
    subjects_path.write_text(
        """
manifest_id: v3_intent_subjects
version: "2026-06-21"
suite_id: v3_intent_execution
subjects:
  - case_ref:
      case_id: v3_policy_answer
    artifacts:
      trace_ref: runs/history/run_v3_policy/trace.jsonl
      receipt_ref: runs/history/run_v3_policy/governance_receipt.md
    projections:
      evaluated_response:
        audience: operator
        ref: runs/history/run_v3_policy/operator_response.txt
""".lstrip(),
        encoding="utf-8",
    )
    return suite_path, subjects_path


def _write_scenario_fixture(tmp_path: Path) -> tuple[Path, Path]:
    suite_path = tmp_path / "scenario-suite.yaml"
    subjects_path = tmp_path / "scenario-subjects.yaml"
    _write_run_artifacts(
        tmp_path,
        run_id="run_supported",
        outcome="ANSWERED_WITH_CITATIONS",
        response="Covered by policy.",
    )
    _write_run_artifacts(
        tmp_path,
        run_id="run_refused",
        outcome="REFUSED_NO_EVIDENCE",
        response="No evidence supports that.",
    )
    suite_path.write_text(
        """
suite_id: insurance_qa_scenario
version: "2026-06-07"
name: Insurance QA Scenario
cases:
  - case_id: supported
    question: Supported?
    intent_type: guidance
    expected_resolution: answer_with_citations
    risk_class: low
    capability_path: retrieval_only
    expected:
      outcome: ANSWERED_WITH_CITATIONS
      required_citation_refs:
        - policy
  - case_id: refused
    question: Refused?
    intent_type: unsupported_advice
    expected_resolution: refuse_no_evidence
    risk_class: low
    capability_path: retrieval_only
    expected:
      outcome: REFUSED_NO_EVIDENCE
scenarios:
  - scenario_id: supported_then_refused
    steps:
      - step_id: first
        case_id: supported
      - step_id: second
        case_id: refused
    expected_ordered_outcomes:
      - ANSWERED_WITH_CITATIONS
      - REFUSED_NO_EVIDENCE
""".lstrip(),
        encoding="utf-8",
    )
    subjects_path.write_text(
        """
manifest_id: scenario_subjects
version: "2026-06-07"
suite_id: insurance_qa_scenario
subjects:
  - case_ref:
      case_id: supported
      scenario_id: supported_then_refused
      scenario_step_id: first
    artifacts:
      trace_ref: runs/history/run_supported/trace.jsonl
      receipt_ref: runs/history/run_supported/governance_receipt.md
    projections:
      evaluated_response:
        audience: operator
        ref: runs/history/run_supported/operator_response.txt
  - case_ref:
      case_id: refused
      scenario_id: supported_then_refused
      scenario_step_id: second
    artifacts:
      trace_ref: runs/history/run_refused/trace.jsonl
      receipt_ref: runs/history/run_refused/governance_receipt.md
    projections:
      evaluated_response:
        audience: operator
        ref: runs/history/run_refused/operator_response.txt
""".lstrip(),
        encoding="utf-8",
    )
    return suite_path, subjects_path


def _add_scenario_run_refs(
    subjects_path: Path,
    *,
    first_conversation_id: str,
    second_conversation_id: str,
    first_turn_id: str | None = None,
    second_turn_id: str | None = None,
    first_continuation_group_id: str | None = None,
    second_continuation_group_id: str | None = None,
) -> None:
    first_turn_ref = f"      turn_id: {first_turn_id}\n" if first_turn_id is not None else ""
    second_turn_ref = f"      turn_id: {second_turn_id}\n" if second_turn_id is not None else ""
    first_continuation_group_ref = (
        f"      continuation_group_id: {first_continuation_group_id}\n"
        if first_continuation_group_id is not None
        else ""
    )
    second_continuation_group_ref = (
        f"      continuation_group_id: {second_continuation_group_id}\n"
        if second_continuation_group_id is not None
        else ""
    )
    subjects_path.write_text(
        subjects_path.read_text(encoding="utf-8")
        .replace(
            """    artifacts:
      trace_ref: runs/history/run_supported/trace.jsonl
      receipt_ref: runs/history/run_supported/governance_receipt.md
    projections:
""",
            f"""    artifacts:
      trace_ref: runs/history/run_supported/trace.jsonl
      receipt_ref: runs/history/run_supported/governance_receipt.md
    run_ref:
      run_id: run_supported
      source: run_store
      conversation_id: {first_conversation_id}
{first_turn_ref}{first_continuation_group_ref.rstrip()}
    projections:
""",
        )
        .replace(
            """    artifacts:
      trace_ref: runs/history/run_refused/trace.jsonl
      receipt_ref: runs/history/run_refused/governance_receipt.md
    projections:
""",
            f"""    artifacts:
      trace_ref: runs/history/run_refused/trace.jsonl
      receipt_ref: runs/history/run_refused/governance_receipt.md
    run_ref:
      run_id: run_refused
      source: run_store
      conversation_id: {second_conversation_id}
{second_turn_ref}{second_continuation_group_ref.rstrip()}
    projections:
""",
        ),
        encoding="utf-8",
    )


def _add_context_admission_event(
    tmp_path: Path,
    *,
    run_id: str,
    included_turn_ids: tuple[str, ...],
) -> None:
    trace_path = tmp_path / "runs" / "history" / run_id / "trace.jsonl"
    existing = trace_path.read_text(encoding="utf-8")
    trace_path.write_text(
        json.dumps(
            {
                "event_type": "context_admission",
                "status": "ok",
                "payload": {
                    "admitted": True,
                    "included_turn_ids": list(included_turn_ids),
                },
            }
        )
        + "\n"
        + existing,
        encoding="utf-8",
    )


def _write_tool_approval_scenario_fixture(
    tmp_path: Path,
    *,
    declared_approval_event_id: str,
) -> tuple[Path, Path]:
    suite_path = tmp_path / "tool-scenario-suite.yaml"
    subjects_path = tmp_path / "tool-scenario-subjects.yaml"
    run_dir = tmp_path / "runs" / "history" / "run_tool"
    run_dir.mkdir(parents=True)
    (run_dir / "trace.jsonl").write_text(
        '{"event_id":"evt_policy_1","event_type":"policy_decision","status":"ok"}\n'
        '{"event_id":"evt_tool_1","event_type":"tool_request","status":"ok"}\n'
        '{"event_id":"evt_approval_1","event_type":"approval_requested","status":"waiting"}\n'
        '{"event_id":"evt_final_1","event_type":"final_output","status":"ok",'
        '"payload":{"outcome":"WAITING_FOR_APPROVAL"}}\n',
        encoding="utf-8",
    )
    (run_dir / "governance_receipt.md").write_text(
        "# Governance Receipt\n\n## Final Outcome\n\nWAITING_FOR_APPROVAL\n",
        encoding="utf-8",
    )
    (run_dir / "operator_response.txt").write_text(
        "Waiting for approval before customer lookup can execute.",
        encoding="utf-8",
    )
    suite_path.write_text(
        f"""
suite_id: insurance_qa_tool_scenario
version: "2026-06-09"
name: Insurance QA Tool Scenario
cases:
  - case_id: tool_step
    question: Check claim status?
    intent_type: tool_required
    expected_resolution: wait_for_approval
    risk_class: tool_governed
    capability_path: retrieval_plus_tool
    expected:
      outcome: WAITING_FOR_APPROVAL
scenarios:
  - scenario_id: approval_required
    steps:
      - step_id: first
        case_id: tool_step
        approval_event_ids:
          - {declared_approval_event_id}
    expected_ordered_outcomes:
      - WAITING_FOR_APPROVAL
""".lstrip(),
        encoding="utf-8",
    )
    subjects_path.write_text(
        """
manifest_id: tool_scenario_subjects
version: "2026-06-09"
suite_id: insurance_qa_tool_scenario
subjects:
  - case_ref:
      case_id: tool_step
      scenario_id: approval_required
      scenario_step_id: first
    artifacts:
      trace_ref: runs/history/run_tool/trace.jsonl
      receipt_ref: runs/history/run_tool/governance_receipt.md
    projections:
      evaluated_response:
        audience: operator
        ref: runs/history/run_tool/operator_response.txt
""".lstrip(),
        encoding="utf-8",
    )
    return suite_path, subjects_path


def _write_run_artifacts(
    tmp_path: Path,
    *,
    run_id: str,
    outcome: str,
    response: str,
) -> None:
    run_dir = tmp_path / "runs" / "history" / run_id
    run_dir.mkdir(parents=True)
    run_dir.joinpath("trace.jsonl").write_text(
        '{"event_type":"retrieval_result","status":"ok","payload":{"source_refs":["policy"]}}\n'
        '{"event_type":"evidence_evaluation","status":"ok",'
        '"payload":{"metadata":{"accepted_count":1},"accepted_sources":["policy"]}}\n'
        '{"event_type":"policy_decision","status":"ok"}\n'
        '{"event_type":"final_output","status":"ok",'
        f'"payload":{{"outcome":"{outcome}"}}}}\n',
        encoding="utf-8",
    )
    run_dir.joinpath("governance_receipt.md").write_text(
        f"# Governance Receipt\n\n## Final Outcome\n\n{outcome}\n",
        encoding="utf-8",
    )
    run_dir.joinpath("operator_response.txt").write_text(response, encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
