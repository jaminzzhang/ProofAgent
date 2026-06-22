import hashlib
import json
from pathlib import Path

from proof_agent.contracts import (
    EvaluationCampaignDiagnostics,
    EvaluationCaseDiagnostic,
    EvaluationDiagnosticFinding,
    EvaluationDiagnosticInputBundle,
)
from proof_agent.evaluation.campaigns import run_evaluation_campaign


def test_campaign_run_writes_coding_agent_diagnostics_and_page_data(
    tmp_path: Path,
) -> None:
    campaign_path = _write_campaign_fixture(tmp_path)
    captured_bundles: list[EvaluationDiagnosticInputBundle] = []

    def reviewer(bundle: EvaluationDiagnosticInputBundle) -> EvaluationCampaignDiagnostics:
        captured_bundles.append(bundle)
        return EvaluationCampaignDiagnostics(
            case_diagnostics=(
                EvaluationCaseDiagnostic(
                    case_id="supported",
                    status="passed_with_diagnostics",
                    quality_score=0.82,
                    findings=(
                        EvaluationDiagnosticFinding(
                            severity="medium",
                            category="clarity",
                            summary=(
                                "Answer is correct but could front-load the policy condition."
                            ),
                        ),
                    ),
                    diagnostic_blocker_candidate=False,
                ),
            )
        )

    summary = run_evaluation_campaign(
        campaign_path=campaign_path,
        output_dir=tmp_path / "campaigns",
        diagnostic_reviewer=reviewer,
    )

    assert captured_bundles[0].campaign_id == "active_agent_probe"
    assert captured_bundles[0].cases[0].case_id == "supported"
    assert summary.coding_agent_diagnostics is not None
    assert summary.coding_agent_diagnostics.mean_quality_score == 0.82

    diagnostics_path = summary.artifact_dir / "diagnostics" / "coding_agent_diagnostics.json"
    input_path = summary.artifact_dir / "diagnostics" / "coding_agent_input_bundle.json"
    assert diagnostics_path.exists()
    assert input_path.exists()

    page_data = json.loads(
        (summary.artifact_dir / "page_data" / "evaluation_lab_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert page_data["coding_agent_diagnostics"]["mean_quality_score"] == 0.82
    assert (
        page_data["coding_agent_diagnostics"]["case_diagnostics"][0]["findings"][0]["category"]
        == "clarity"
    )


def test_coding_agent_diagnostic_input_bundle_excludes_raw_artifacts(
    tmp_path: Path,
) -> None:
    campaign_path = _write_campaign_fixture(
        tmp_path,
        trace_secret="raw trace should not enter diagnostics",
        receipt_secret="raw receipt should not enter diagnostics",
        response_text="Covered by policy.",
    )
    captured_bundles: list[EvaluationDiagnosticInputBundle] = []

    def reviewer(bundle: EvaluationDiagnosticInputBundle) -> EvaluationCampaignDiagnostics:
        captured_bundles.append(bundle)
        return EvaluationCampaignDiagnostics()

    run_evaluation_campaign(
        campaign_path=campaign_path,
        output_dir=tmp_path / "campaigns",
        diagnostic_reviewer=reviewer,
    )

    bundle = captured_bundles[0]
    case = bundle.cases[0]
    assert case.response_projection is not None
    assert case.response_projection.text_length == len("Covered by policy.")
    serialized = json.dumps(bundle.model_dump(mode="json"), sort_keys=True)
    assert "raw trace should not enter diagnostics" not in serialized
    assert "raw receipt should not enter diagnostics" not in serialized
    assert "Covered by policy." not in serialized


def _write_campaign_fixture(
    tmp_path: Path,
    *,
    trace_secret: str = "",
    receipt_secret: str = "",
    response_text: str = "Covered by policy.",
) -> Path:
    suite_path = tmp_path / "suite.yaml"
    subjects_path = tmp_path / "subjects.yaml"
    campaign_path = tmp_path / "campaign.yaml"
    run_dir = tmp_path / "runs" / "history" / "run_supported"
    run_dir.mkdir(parents=True)
    trace_path = run_dir / "trace.jsonl"
    receipt_path = run_dir / "governance_receipt.md"
    response_path = run_dir / "operator_response.txt"
    trace_path.write_text(
        json.dumps(
            {
                "event_type": "retrieval_result",
                "payload": {"source_refs": ["policy"], "debug": trace_secret},
            }
        )
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
        "# Governance Receipt\n\n## Final Outcome\n\nANSWERED_WITH_CITATIONS\n" + receipt_secret,
        encoding="utf-8",
    )
    response_path.write_text(response_text, encoding="utf-8")
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
