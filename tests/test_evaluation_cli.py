from pathlib import Path

from typer.testing import CliRunner

from proof_agent.delivery.cli import app


runner = CliRunner()


def test_evaluate_analyze_cli_writes_artifacts_and_returns_one_when_required_case_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "proof_agent.delivery.cli.run_with_langgraph",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not create runs")),
    )
    suite_path, subjects_path = _write_cli_fixture(tmp_path)
    output_dir = tmp_path / "evaluations"

    result = runner.invoke(
        app,
        [
            "evaluate",
            "analyze",
            "--suite",
            str(suite_path),
            "--subjects",
            str(subjects_path),
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 1
    assert "evaluation_report.md" in result.output
    assert (output_dir / "insurance_qa_smoke-local_subjects" / "evaluation_report.md").exists()
    assert not (tmp_path / "runs" / "latest").exists()


def _write_cli_fixture(tmp_path: Path) -> tuple[Path, Path]:
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
