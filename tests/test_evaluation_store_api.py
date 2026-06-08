from pathlib import Path

from fastapi.testclient import TestClient

from proof_agent.evaluation.analyzer import analyze_evaluation
from proof_agent.observability.api.app import create_app


def test_dashboard_api_reads_evaluation_analysis_artifacts(tmp_path: Path) -> None:
    suite_path, subjects_path = _write_fixture(tmp_path)
    summary = analyze_evaluation(
        suite_path=suite_path,
        subjects_path=subjects_path,
        output_dir=tmp_path / "runs" / "evaluations",
    )
    app = create_app(
        history_dir=tmp_path / "runs" / "history",
        evaluations_dir=tmp_path / "runs" / "evaluations",
    )
    client = TestClient(app)

    list_response = client.get("/api/evaluation/analyses")
    cases_response = client.get(f"/api/evaluation/analyses/{summary.analysis_id}/cases")

    assert list_response.status_code == 200
    assert list_response.json()["data"][0]["analysis_id"] == summary.analysis_id
    assert list_response.json()["data"][0]["release_decision_status"] == "blocked"
    assert cases_response.status_code == 200
    assert {case["case_id"] for case in cases_response.json()["data"]} == {
        "supported",
        "missing",
    }
    assert "response_text" not in str(cases_response.json())


def _write_fixture(tmp_path: Path) -> tuple[Path, Path]:
    suite_path = tmp_path / "suite.yaml"
    subjects_path = tmp_path / "subjects.yaml"
    run_dir = tmp_path / "runs" / "history" / "run_supported"
    run_dir.mkdir(parents=True)
    (run_dir / "trace.jsonl").write_text(
        '{"event_type":"retrieval_result","payload":{"source_refs":["policy"]}}\n'
        '{"event_type":"evidence_evaluation","payload":{"metadata":{"accepted_count":1},"accepted_sources":["policy"]}}\n'
        '{"event_type":"policy_decision"}\n'
        '{"event_type":"final_output","payload":{"outcome":"ANSWERED_WITH_CITATIONS"}}\n',
        encoding="utf-8",
    )
    (run_dir / "governance_receipt.md").write_text(
        "# Governance Receipt\n\n## Final Outcome\n\nANSWERED_WITH_CITATIONS\n",
        encoding="utf-8",
    )
    (run_dir / "operator_response.txt").write_text("Covered by policy.", encoding="utf-8")
    suite_path.write_text(
        """
suite_id: insurance_qa_store_api
version: "2026-06-09"
name: Insurance QA Store API
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
manifest_id: store_api_subjects
version: "2026-06-09"
suite_id: insurance_qa_store_api
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
