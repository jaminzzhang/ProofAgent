import hashlib
import json
from pathlib import Path

from proof_agent.evaluation.campaigns import run_evaluation_campaign


def test_campaign_run_writes_evaluation_lab_case_rows(tmp_path: Path) -> None:
    campaign_path = _write_campaign_fixture(tmp_path)

    summary = run_evaluation_campaign(
        campaign_path=campaign_path,
        output_dir=tmp_path / "campaigns",
    )

    cases_path = summary.artifact_dir / "page_data" / "evaluation_lab_cases.jsonl"
    rows = [json.loads(line) for line in cases_path.read_text(encoding="utf-8").splitlines()]

    assert len(rows) == 1
    row = rows[0]
    assert row["analysis_id"] == "active_agent_smoke-active_agent_subjects"
    assert row["suite_id"] == "active_agent_smoke"
    assert row["suite_version"] == "2026-06-21"
    assert row["case_id"] == "supported"
    assert row["status"] == "passed"
    assert row["expected_outcome"] == "ANSWERED_WITH_CITATIONS"
    assert row["actual_outcome"] == "ANSWERED_WITH_CITATIONS"
    assert row["artifact_sufficiency"] == "sufficient"
    assert row["primary_failure_owner"] is None
    assert row["response_projection"]["audience"] == "operator"
    assert row["response_projection"]["ref"] == "runs/history/run_supported/operator_response.txt"
    assert row["response_projection"]["text_length"] == len("Covered by policy.")
    assert row["response_projection"]["source"] == "file"
    assert row["response_projection"]["sensitivity"] == "release_safe"
    assert row["response_projection"]["declared_sha256"]
    assert row["response_projection"]["observed_text_sha256"]
    assert row["gate_failures"] == []
    assert row["diagnostic_findings"] == []
    assert row["diagnostic_blocker_candidate"] is False


def _write_campaign_fixture(tmp_path: Path) -> Path:
    suite_path = tmp_path / "suite.yaml"
    subjects_path = tmp_path / "subjects.yaml"
    campaign_path = tmp_path / "campaign.yaml"
    run_dir = tmp_path / "runs" / "history" / "run_supported"
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
suite_id: active_agent_smoke
version: "2026-06-21"
name: Active Agent Smoke
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
manifest_id: active_agent_subjects
version: "2026-06-21"
suite_id: active_agent_smoke
subjects:
  - case_ref:
      case_id: supported
    artifacts:
      trace_ref: runs/history/run_supported/trace.jsonl
      trace_sha256: {_sha256(trace_path)}
      receipt_ref: runs/history/run_supported/governance_receipt.md
      receipt_sha256: {_sha256(receipt_path)}
    projections:
      evaluated_response:
        audience: operator
        ref: runs/history/run_supported/operator_response.txt
        sha256: {_sha256(response_path)}
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
      suite_ref: suite.yaml
      subjects_ref: subjects.yaml
thresholds:
  governed_resolution_rate_min: 0.95
  artifact_sufficiency_required: 1.0
  deterministic_gate_pass_required: 1.0
""".lstrip(),
        encoding="utf-8",
    )
    return campaign_path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
