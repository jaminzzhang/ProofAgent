import json
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from proof_agent.contracts import (
    EvaluationResponseProjectionAudience,
    ReceiptOutcome,
    RunPurpose,
)
from proof_agent.evaluation.campaigns import run_evaluation_campaign
from proof_agent.evaluation.errors import EvaluationInputError
from proof_agent.evaluation.sample_production import EvaluationSampleRequest, EvaluationSampleRun
from proof_agent.observability.storage.run_store import RunStore


def test_campaign_run_produces_evaluation_samples_and_exports_subject_manifest(
    tmp_path: Path,
) -> None:
    campaign_path = _write_sampled_campaign_fixture(tmp_path)
    store = RunStore(tmp_path / "runs" / "history")
    captured_requests: list[EvaluationSampleRequest] = []

    def sample_runner(request: EvaluationSampleRequest) -> EvaluationSampleRun:
        captured_requests.append(request)
        run_id = "run_supported"
        _write_sample_run(store, run_id=run_id, question=request.question)
        return EvaluationSampleRun(
            case_ref=request.case_ref,
            run_id=run_id,
            response_projection_ref=Path("operator_response.txt"),
            response_projection_audience=EvaluationResponseProjectionAudience.OPERATOR,
        )

    summary = run_evaluation_campaign(
        campaign_path=campaign_path,
        output_dir=tmp_path / "campaigns",
        run_store=store,
        sample_runner=sample_runner,
    )

    assert summary.readiness_status == "ready"
    assert [request.question for request in captured_requests] == ["Supported?"]
    subject_manifest_path = summary.artifact_dir / "subject_manifest.yaml"
    assert subject_manifest_path.exists()
    assert (summary.suite_runs[0].artifact_dir / "evaluation_results.jsonl").exists()
    subject_manifest = yaml.safe_load(subject_manifest_path.read_text(encoding="utf-8"))
    assert subject_manifest["subjects"][0]["run_ref"]["run_id"] == "run_supported"
    assert subject_manifest["subjects"][0]["execution_surface"] == "run_execution_api"
    assert subject_manifest["subjects"][0]["artifacts"]["run_meta_sha256"]


def test_campaign_sample_production_rejects_production_runs(tmp_path: Path) -> None:
    campaign_path = _write_sampled_campaign_fixture(tmp_path)
    store = RunStore(tmp_path / "runs" / "history")

    def sample_runner(request: EvaluationSampleRequest) -> EvaluationSampleRun:
        run_id = "run_production"
        _write_sample_run(
            store,
            run_id=run_id,
            question=request.question,
            run_purpose=RunPurpose.PRODUCTION,
        )
        return EvaluationSampleRun(
            case_ref=request.case_ref,
            run_id=run_id,
            response_projection_ref=Path("operator_response.txt"),
        )

    with pytest.raises(EvaluationInputError, match="run_purpose evaluation_sample"):
        run_evaluation_campaign(
            campaign_path=campaign_path,
            output_dir=tmp_path / "campaigns",
            run_store=store,
            sample_runner=sample_runner,
        )


def _write_sampled_campaign_fixture(tmp_path: Path) -> Path:
    suite_path = tmp_path / "suite.yaml"
    campaign_path = tmp_path / "campaign.yaml"
    suite_path.write_text(
        """
suite_id: active_agent_sample_smoke
version: "2026-06-22"
name: Active Agent Sample Smoke
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
    campaign_path.write_text(
        """
campaign_id: active_agent_sample_probe
version: "2026-06-22"
target:
  agent_id: insurance_customer_service
  agent_version_id: published_v1
suites:
  formal:
    - source: core_regression
      suite_ref: suite.yaml
      produce_samples: true
      subject_manifest_id: active_agent_sample_subjects
thresholds:
  governed_resolution_rate_min: 0.95
  artifact_sufficiency_required: 1.0
  deterministic_gate_pass_required: 1.0
""".lstrip(),
        encoding="utf-8",
    )
    return campaign_path


def _write_sample_run(
    store: RunStore,
    *,
    run_id: str,
    question: str,
    run_purpose: RunPurpose = RunPurpose.EVALUATION_SAMPLE,
) -> None:
    run_dir = store.create_run_dir(run_id)
    trace_path = run_dir / "trace.jsonl"
    receipt_path = run_dir / "governance_receipt.md"
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
    (run_dir / "operator_response.txt").write_text("Covered by policy.", encoding="utf-8")
    store.save_run_artifacts(
        run_id,
        trace_source=trace_path,
        receipt_source=receipt_path,
        question=question,
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        run_purpose=run_purpose,
        agent_id="insurance_customer_service",
        agent_version_id="published_v1",
    )
