import hashlib
import json
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


def test_evaluate_analyze_cli_returns_one_when_release_decision_is_blocked(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "proof_agent.delivery.cli.run_with_langgraph",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not create runs")),
    )
    suite_path, subjects_path = _write_cli_fixture(tmp_path, include_missing_case=False)

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
            str(tmp_path / "evaluations"),
        ],
    )

    assert result.exit_code == 1
    assert "Release Decision: blocked" in result.output


def test_evaluate_freeze_bundle_cli_writes_portable_bundle(tmp_path: Path) -> None:
    suite_path, subjects_path = _write_cli_fixture(tmp_path, include_missing_case=False)
    output_dir = tmp_path / "bundles"

    result = runner.invoke(
        app,
        [
            "evaluate",
            "freeze-bundle",
            "--suite",
            str(suite_path),
            "--subjects",
            str(subjects_path),
            "--output-dir",
            str(output_dir),
            "--bundle-id",
            "release_bundle",
            "--version",
            "2026-06-09",
        ],
    )

    assert result.exit_code == 0
    assert "evaluation_subjects.yaml" in result.output
    assert (output_dir / "release_bundle" / "evaluation_suite.yaml").exists()
    assert (output_dir / "release_bundle" / "evaluation_subjects.yaml").exists()
    assert (output_dir / "release_bundle" / "bundle_manifest.yaml").exists()


def test_evaluate_verify_bundle_cli_reports_integrity_status(tmp_path: Path) -> None:
    suite_path, subjects_path = _write_cli_fixture(tmp_path, include_missing_case=False)
    output_dir = tmp_path / "bundles"
    runner.invoke(
        app,
        [
            "evaluate",
            "freeze-bundle",
            "--suite",
            str(suite_path),
            "--subjects",
            str(subjects_path),
            "--output-dir",
            str(output_dir),
            "--bundle-id",
            "release_bundle",
            "--version",
            "2026-06-09",
        ],
    )

    passed = runner.invoke(
        app,
        [
            "evaluate",
            "verify-bundle",
            str(output_dir / "release_bundle"),
        ],
    )

    assert passed.exit_code == 0
    assert "Bundle Integrity: passed" in passed.output

    response = output_dir / "release_bundle" / "artifacts" / "supported" / "evaluated_response.txt"
    response.write_text("tampered", encoding="utf-8")
    failed = runner.invoke(
        app,
        [
            "evaluate",
            "verify-bundle",
            str(output_dir / "release_bundle"),
        ],
    )

    assert failed.exit_code == 1
    assert "Bundle Integrity: failed" in failed.output
    assert "artifacts/supported/evaluated_response.txt" in failed.output


def test_evaluate_campaign_run_cli_writes_campaign_artifacts(tmp_path: Path) -> None:
    campaign_path = _write_campaign_cli_fixture(tmp_path)

    result = runner.invoke(
        app,
        [
            "evaluate",
            "campaign",
            "run",
            "--campaign",
            str(campaign_path),
            "--output-dir",
            str(tmp_path / "campaigns"),
        ],
    )

    assert result.exit_code == 0
    assert "Campaign: active_agent_probe" in result.output
    assert "Readiness: ready" in result.output
    assert (tmp_path / "campaigns" / "active_agent_probe" / "campaign_summary.json").exists()


def _write_cli_fixture(
    tmp_path: Path,
    *,
    include_missing_case: bool = True,
) -> tuple[Path, Path]:
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
    missing_case = (
        """
  - case_id: missing
    question: Missing?
    intent_type: guidance
    expected_resolution: refuse_no_evidence
    risk_class: low
    capability_path: retrieval_only
    expected:
      outcome: REFUSED_NO_EVIDENCE
"""
        if include_missing_case
        else ""
    )
    suite_path.write_text(
        f"""
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
{missing_case.rstrip()}
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


def _write_campaign_cli_fixture(tmp_path: Path) -> Path:
    suite_path = tmp_path / "campaign_suite.yaml"
    subjects_path = tmp_path / "campaign_subjects.yaml"
    campaign_path = tmp_path / "campaign.yaml"
    run_dir = tmp_path / "runs" / "history" / "run_campaign_supported"
    run_dir.mkdir(parents=True)
    trace_path = run_dir / "trace.jsonl"
    receipt_path = run_dir / "governance_receipt.md"
    response_path = run_dir / "operator_response.txt"
    trace_path.write_text(
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
    receipt_path.write_text(
        "# Governance Receipt\n\n## Final Outcome\n\nANSWERED_WITH_CITATIONS\n",
        encoding="utf-8",
    )
    response_path.write_text("Covered by policy.", encoding="utf-8")
    suite_path.write_text(
        """
suite_id: campaign_smoke
version: "2026-06-21"
name: Campaign Smoke
cases:
  - case_id: supported
    question: Supported?
    intent_type: guidance
    expected_resolution: answer_with_citations
    risk_class: low
    capability_path: evidence_answer
    expected:
      outcome: ANSWERED_WITH_CITATIONS
      required_citation_refs:
        - policy
""".lstrip(),
        encoding="utf-8",
    )
    subjects_path.write_text(
        f"""
manifest_id: campaign_subjects
version: "2026-06-21"
suite_id: campaign_smoke
subjects:
  - case_ref:
      case_id: supported
    artifacts:
      trace_ref: runs/history/run_campaign_supported/trace.jsonl
      trace_sha256: {_file_sha256(trace_path)}
      receipt_ref: runs/history/run_campaign_supported/governance_receipt.md
      receipt_sha256: {_file_sha256(receipt_path)}
    projections:
      evaluated_response:
        audience: operator
        ref: runs/history/run_campaign_supported/operator_response.txt
        sha256: {_file_sha256(response_path)}
        sensitivity: release_safe
""".lstrip(),
        encoding="utf-8",
    )
    campaign_path.write_text(
        """
campaign_id: active_agent_probe
version: "2026-06-21"
target:
  agent_id: insurance_customer_service
  agent_version_id: published_v1
suites:
  formal:
    - source: core_regression
      suite_ref: campaign_suite.yaml
      subjects_ref: campaign_subjects.yaml
thresholds:
  governed_resolution_rate_min: 0.95
  artifact_sufficiency_required: 1.0
  deterministic_gate_pass_required: 1.0
""".lstrip(),
        encoding="utf-8",
    )
    return campaign_path


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
