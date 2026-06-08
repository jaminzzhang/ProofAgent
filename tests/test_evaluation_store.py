import json
from pathlib import Path

from proof_agent.evaluation.analyzer import analyze_evaluation
from proof_agent.evaluation.store import EvaluationStore


def test_evaluation_store_indexes_analysis_artifacts_without_response_text(
    tmp_path: Path,
) -> None:
    suite_path, subjects_path = _write_fixture(tmp_path)
    summary = analyze_evaluation(
        suite_path=suite_path,
        subjects_path=subjects_path,
        output_dir=tmp_path / "evaluations",
    )

    store = EvaluationStore(tmp_path / "evaluations")
    analyses = store.list_analyses()
    case_results = store.get_case_results(summary.analysis_id)

    assert len(analyses) == 1
    assert analyses[0].analysis_id == summary.analysis_id
    assert analyses[0].suite_id == "insurance_qa_store"
    assert analyses[0].release_decision_status == summary.release_decision.status
    assert analyses[0].failed_case_count == 1
    assert analyses[0].total_case_count == 2
    assert {result.case_id for result in case_results} == {"supported", "missing"}
    result_file = tmp_path / "evaluations" / summary.analysis_id / "evaluation_results.jsonl"
    assert "response_text" not in result_file.read_text(encoding="utf-8")


def _write_fixture(tmp_path: Path) -> tuple[Path, Path]:
    suite_path = tmp_path / "suite.yaml"
    subjects_path = tmp_path / "subjects.yaml"
    run_dir = tmp_path / "runs" / "history" / "run_supported"
    run_dir.mkdir(parents=True)
    (run_dir / "trace.jsonl").write_text(
        json.dumps({"event_type": "retrieval_result", "payload": {"source_refs": ["policy"]}})
        + "\n"
        + json.dumps(
            {
                "event_type": "evidence_evaluation",
                "payload": {
                    "metadata": {"accepted_count": 1},
                    "accepted_sources": ["policy"],
                },
            }
        )
        + "\n"
        + json.dumps({"event_type": "policy_decision"})
        + "\n"
        + json.dumps(
            {
                "event_type": "final_output",
                "payload": {"outcome": "ANSWERED_WITH_CITATIONS"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "governance_receipt.md").write_text(
        "# Governance Receipt\n\n## Final Outcome\n\nANSWERED_WITH_CITATIONS\n",
        encoding="utf-8",
    )
    (run_dir / "operator_response.txt").write_text("Covered by policy.", encoding="utf-8")
    suite_path.write_text(
        """
suite_id: insurance_qa_store
version: "2026-06-09"
name: Insurance QA Store
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
manifest_id: store_subjects
version: "2026-06-09"
suite_id: insurance_qa_store
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
