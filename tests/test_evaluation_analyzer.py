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
    result_lines = (artifact_dir / "evaluation_results.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
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
        tmp_path
        / "evaluations"
        / summary.analysis_id
        / "evaluation_report.md"
    ).read_text(encoding="utf-8")


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
