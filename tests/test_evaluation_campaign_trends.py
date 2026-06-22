import hashlib
import json
from pathlib import Path

from proof_agent.evaluation.campaigns import run_evaluation_campaign


def test_campaign_run_writes_version_aware_trend_against_comparable_baseline(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "campaigns"
    _write_baseline_campaign_summary(output_dir)
    campaign_path = _write_campaign_fixture(tmp_path)

    summary = run_evaluation_campaign(
        campaign_path=campaign_path,
        output_dir=output_dir,
    )

    trends_path = summary.artifact_dir / "page_data" / "evaluation_lab_trends.json"
    trend = json.loads(trends_path.read_text(encoding="utf-8"))

    assert trend["campaign_id"] == "active_agent_probe"
    assert trend["status"] == "comparable"
    assert trend["baseline_campaign_id"] == "active_agent_probe_previous"
    assert trend["current_version"] == "2026-06-22"
    assert trend["baseline_version"] == "2026-06-21"
    assert trend["metric_deltas"]["governed_resolution_rate"] == 0.5
    assert trend["metric_deltas"]["artifact_sufficiency_rate"] == 0.0
    assert trend["metric_deltas"]["deterministic_gate_pass_rate"] == 0.0
    assert trend["comparison_basis"]["suite_versions"] == [
        {
            "source": "core_regression",
            "suite_id": "active_agent_smoke",
            "current_suite_version": "2026-06-21",
            "baseline_suite_version": "2026-06-21",
            "comparable": True,
        }
    ]


def test_campaign_trend_marks_suite_version_change_as_benchmark_migration(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "campaigns"
    _write_baseline_campaign_summary(output_dir, suite_version="2026-06-20")
    campaign_path = _write_campaign_fixture(tmp_path)

    summary = run_evaluation_campaign(
        campaign_path=campaign_path,
        output_dir=output_dir,
    )

    trend = json.loads(
        (summary.artifact_dir / "page_data" / "evaluation_lab_trends.json").read_text(
            encoding="utf-8"
        )
    )

    assert trend["status"] == "benchmark_migration"
    assert trend["metric_deltas"] == {}
    assert trend["comparison_basis"]["suite_versions"][0]["comparable"] is False
    assert trend["comparison_basis"]["suite_versions"][0]["baseline_suite_version"] == (
        "2026-06-20"
    )


def _write_baseline_campaign_summary(
    output_dir: Path,
    *,
    suite_version: str = "2026-06-21",
) -> None:
    page_data_dir = output_dir / "active_agent_probe_previous" / "page_data"
    page_data_dir.mkdir(parents=True)
    (page_data_dir / "evaluation_lab_summary.json").write_text(
        json.dumps(
            {
                "campaign_id": "active_agent_probe_previous",
                "version": "2026-06-21",
                "target_agent_id": "insurance_customer_service",
                "target_agent_version_id": "published_v1",
                "readiness_status": "blocked",
                "blocking_reasons": ["required_case_pass_rate below release threshold"],
                "governed_resolution_rate": 0.5,
                "artifact_sufficiency_rate": 1.0,
                "deterministic_gate_pass_rate": 1.0,
                "suite_runs": [
                    {
                        "source": "core_regression",
                        "suite_id": "active_agent_smoke",
                        "suite_version": suite_version,
                        "analysis_id": "baseline",
                        "release_decision_status": "blocked",
                        "total_required_cases": 2,
                        "passed_required_cases": 1,
                        "governed_resolution_rate": 0.5,
                        "artifact_dir": "baseline/analyzer",
                    }
                ],
                "capability_coverage": [],
                "artifact_dir": str(output_dir / "active_agent_probe_previous"),
            }
        )
        + "\n",
        encoding="utf-8",
    )


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
version: "2026-06-22"
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
