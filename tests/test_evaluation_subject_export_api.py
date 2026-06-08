import json
from pathlib import Path

from fastapi.testclient import TestClient

from proof_agent.contracts import ReceiptOutcome, RunPurpose
from proof_agent.evaluation.analyzer import analyze_evaluation
from proof_agent.evaluation.subjects import load_evaluation_subject_manifest
from proof_agent.observability.api.app import create_app
from proof_agent.observability.storage.run_store import RunStore


def test_dashboard_api_exports_run_store_subject_manifest(tmp_path: Path) -> None:
    app = create_app(history_dir=tmp_path / "runs" / "history")
    client = TestClient(app)
    store: RunStore = app.state.store
    suite_path = _write_suite(tmp_path)
    trace_src, receipt_src = _write_sources(tmp_path)
    store.save_run_artifacts(
        "run_supported",
        trace_source=trace_src,
        receipt_source=receipt_src,
        question="Supported?",
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        run_purpose=RunPurpose.VALIDATION,
        agent_id="insurance_agent",
        agent_version_id="version_001",
    )
    response_path = store.history_dir / "run_supported" / "operator_response.txt"
    response_path.write_text("Covered by policy.", encoding="utf-8")

    response = client.post(
        "/api/evaluation/subject-manifests/export",
        json={
            "suite_id": "insurance_qa_export",
            "manifest_id": "dashboard_export",
            "version": "2026-06-09",
            "selections": [
                {
                    "case_ref": {"case_id": "supported"},
                    "run_id": "run_supported",
                    "response_projection_ref": "operator_response.txt",
                    "response_projection_audience": "operator",
                }
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["manifest_id"] == "dashboard_export"
    assert body["subject_count"] == 1
    manifest_path = Path(body["manifest_path"])
    assert manifest_path == tmp_path / "runs" / "evaluation_subject_exports" / "dashboard_export.yaml"
    loaded = load_evaluation_subject_manifest(manifest_path)
    assert loaded.subjects[0].run_ref is not None
    assert loaded.subjects[0].run_ref.run_id == "run_supported"

    summary = analyze_evaluation(
        suite_path=suite_path,
        subjects_path=manifest_path,
        output_dir=tmp_path / "evaluations",
    )

    assert summary.release_decision.status.value == "passed"


def _write_sources(tmp_path: Path) -> tuple[Path, Path]:
    trace_src = tmp_path / "trace.jsonl"
    receipt_src = tmp_path / "governance_receipt.md"
    trace_src.write_text(
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
    receipt_src.write_text(
        "# Governance Receipt\n\n## Final Outcome\n\nANSWERED_WITH_CITATIONS\n",
        encoding="utf-8",
    )
    return trace_src, receipt_src


def _write_suite(tmp_path: Path) -> Path:
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text(
        """
suite_id: insurance_qa_export
version: "2026-06-09"
name: Insurance QA Export
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
""".lstrip(),
        encoding="utf-8",
    )
    return suite_path
