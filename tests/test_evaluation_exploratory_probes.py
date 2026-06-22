import hashlib
import json
from pathlib import Path

from proof_agent.evaluation.campaigns import run_evaluation_campaign
from proof_agent.evaluation.errors import EvaluationInputError
from proof_agent.evaluation.exploratory_probes import (
    ExploratoryProbeResult,
    ExploratoryProbeRunRequest,
)


def test_campaign_run_writes_exploratory_probe_results_artifact(tmp_path: Path) -> None:
    campaign_path = _write_campaign_fixture(tmp_path, exploratory_enabled=True)
    captured_requests: list[ExploratoryProbeRunRequest] = []

    def probe_runner(request: ExploratoryProbeRunRequest) -> tuple[ExploratoryProbeResult, ...]:
        captured_requests.append(request)
        return (
            ExploratoryProbeResult(
                probe_id="ambiguous_coverage_wording",
                status="needs_review",
                surface_ref="operator_chat",
                intent_boundary="evidence_answer_vs_clarification",
                finding_summary="Ambiguous wording should ask for clarification.",
                diagnostic_blocker_candidate=True,
            ),
        )

    summary = run_evaluation_campaign(
        campaign_path=campaign_path,
        output_dir=tmp_path / "campaigns",
        exploratory_probe_runner=probe_runner,
    )

    assert captured_requests[0].campaign_id == "active_agent_probe"
    assert captured_requests[0].target_agent_id == "insurance_customer_service"
    assert captured_requests[0].max_cases == 3
    assert summary.readiness_status == "ready"
    assert summary.governed_resolution_rate == 1.0

    result_path = summary.artifact_dir / "diagnostics" / "exploratory_probe_results.jsonl"
    rows = [
        json.loads(line)
        for line in result_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert rows == [
        {
            "diagnostic_blocker_candidate": True,
            "finding_summary": "Ambiguous wording should ask for clarification.",
            "intent_boundary": "evidence_answer_vs_clarification",
            "probe_id": "ambiguous_coverage_wording",
            "source": "exploratory",
            "status": "needs_review",
            "surface_ref": "operator_chat",
        }
    ]


def test_campaign_run_rejects_enabled_exploratory_probes_without_runner(
    tmp_path: Path,
) -> None:
    campaign_path = _write_campaign_fixture(tmp_path, exploratory_enabled=True)

    try:
        run_evaluation_campaign(
            campaign_path=campaign_path,
            output_dir=tmp_path / "campaigns",
        )
    except EvaluationInputError as exc:
        assert "exploratory probe runner" in str(exc)
    else:
        raise AssertionError("enabled exploratory probes must require a probe runner")

    assert not (
        tmp_path
        / "campaigns"
        / "active_agent_probe"
        / "diagnostics"
        / "exploratory_probe_results.jsonl"
    ).exists()


def _write_campaign_fixture(tmp_path: Path, *, exploratory_enabled: bool) -> Path:
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
version: "2026-06-22"
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
version: "2026-06-22"
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
    exploratory_config = (
        """
diagnostics:
  exploratory_probes:
    enabled: true
    max_cases: 3
"""
        if exploratory_enabled
        else ""
    )
    campaign_path.write_text(
        f"""
campaign_id: active_agent_probe
version: "2026-06-22"
target:
  agent_id: insurance_customer_service
  agent_version_id: published_v1
surfaces:
  - id: operator_chat
    kind: run_execution_api_conversation
    audience: operator
suites:
  formal:
    - source: core_regression
      suite_ref: suite.yaml
      subjects_ref: subjects.yaml
thresholds:
  governed_resolution_rate_min: 0.95
  artifact_sufficiency_required: 1.0
  deterministic_gate_pass_required: 1.0
{exploratory_config.rstrip()}
""".lstrip(),
        encoding="utf-8",
    )
    return campaign_path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
