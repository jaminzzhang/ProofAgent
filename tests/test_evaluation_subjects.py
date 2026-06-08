from pathlib import Path
from hashlib import sha256

import pytest

from proof_agent.evaluation.errors import EvaluationInputError
from proof_agent.contracts import EvaluationReleaseDecisionStatus
from proof_agent.evaluation.analyzer import analyze_evaluation
from proof_agent.evaluation.subjects import load_evaluation_subject_manifest


def test_subject_loader_reads_manifest_and_resolves_artifact_refs(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "history" / "run_123"
    run_dir.mkdir(parents=True)
    trace_path = run_dir / "trace.jsonl"
    receipt_path = run_dir / "governance_receipt.md"
    response_path = run_dir / "operator_response.txt"
    trace_path.write_text("{}", encoding="utf-8")
    receipt_path.write_text("# Receipt", encoding="utf-8")
    response_path.write_text("Travel meals are reimbursed with receipts.", encoding="utf-8")
    manifest_path = tmp_path / "subjects.yaml"
    manifest_path.write_text(
        """
manifest_id: local_subjects
version: "2026-06-07"
suite_id: insurance_qa_smoke
agent:
  agent_id: react_enterprise_qa
  agent_version_id: local
subjects:
  - case_ref:
      case_id: supported_travel_meal
    run_ref:
      run_id: run_123
      source: run_store
    artifacts:
      trace_ref: runs/history/run_123/trace.jsonl
      receipt_ref: runs/history/run_123/governance_receipt.md
    projections:
      evaluated_response:
        audience: operator
        ref: runs/history/run_123/operator_response.txt
""".lstrip(),
        encoding="utf-8",
    )

    manifest = load_evaluation_subject_manifest(manifest_path)

    subject = manifest.subjects[0]
    assert subject.case_ref.case_id == "supported_travel_meal"
    assert subject.trace.ref == trace_path
    assert subject.receipt.ref == receipt_path
    assert subject.response_projection.ref == response_path


def test_subject_loader_rejects_missing_local_artifact_ref(tmp_path: Path) -> None:
    (tmp_path / "governance_receipt.md").write_text("# Receipt", encoding="utf-8")
    manifest_path = tmp_path / "subjects.yaml"
    manifest_path.write_text(
        """
manifest_id: local_subjects
version: "2026-06-07"
suite_id: insurance_qa_smoke
subjects:
  - case_ref:
      case_id: supported_travel_meal
    artifacts:
      trace_ref: missing-trace.jsonl
      receipt_ref: governance_receipt.md
    projections:
      evaluated_response:
        audience: operator
        text: Local-only answer text.
        sensitivity: local_only
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(EvaluationInputError, match="missing local artifact ref"):
        load_evaluation_subject_manifest(manifest_path)


def test_subject_loader_accepts_matching_artifact_hashes(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    receipt_path = tmp_path / "governance_receipt.md"
    trace_path.write_text("{}", encoding="utf-8")
    receipt_path.write_text("# Receipt", encoding="utf-8")
    manifest_path = tmp_path / "subjects.yaml"
    manifest_path.write_text(
        f"""
manifest_id: local_subjects
version: "2026-06-07"
suite_id: insurance_qa_smoke
subjects:
  - case_ref:
      case_id: supported_travel_meal
    artifacts:
      trace_ref: trace.jsonl
      trace_sha256: {sha256(trace_path.read_bytes()).hexdigest()}
      receipt_ref: governance_receipt.md
      receipt_sha256: {sha256(receipt_path.read_bytes()).hexdigest()}
    projections:
      evaluated_response:
        audience: operator
        text: Local-only answer text.
        sensitivity: local_only
""".lstrip(),
        encoding="utf-8",
    )

    manifest = load_evaluation_subject_manifest(manifest_path)

    assert manifest.subjects[0].trace.sha256 == sha256(trace_path.read_bytes()).hexdigest()
    assert manifest.subjects[0].receipt.sha256 == sha256(receipt_path.read_bytes()).hexdigest()


def test_subject_loader_reads_example_fixture_manifest() -> None:
    manifest = load_evaluation_subject_manifest(
        Path("proof_agent/evaluation/subjects/examples/insurance_qa_smoke_subjects.yaml")
    )

    assert manifest.suite_id == "insurance_qa_smoke"
    assert manifest.subjects[0].case_ref.case_id == "react_supported_travel_meal"
    assert manifest.subjects[0].trace.ref.exists()


def test_release_sufficient_example_subject_manifest_passes_analyzer(tmp_path: Path) -> None:
    summary = analyze_evaluation(
        suite_path="smoke",
        subjects_path=Path(
            "proof_agent/evaluation/subjects/examples/insurance_qa_smoke_release_subjects.yaml"
        ),
        output_dir=tmp_path / "evaluations",
    )

    assert summary.release_decision.status == EvaluationReleaseDecisionStatus.PASSED


def test_subject_loader_allows_inline_response_text_only_for_local_analysis(
    tmp_path: Path,
) -> None:
    (tmp_path / "trace.jsonl").write_text("{}", encoding="utf-8")
    (tmp_path / "governance_receipt.md").write_text("# Receipt", encoding="utf-8")
    manifest_path = tmp_path / "subjects.yaml"
    manifest_path.write_text(
        """
manifest_id: local_subjects
version: "2026-06-07"
suite_id: insurance_qa_smoke
subjects:
  - case_ref:
      case_id: supported_travel_meal
    artifacts:
      trace_ref: trace.jsonl
      receipt_ref: governance_receipt.md
    projections:
      evaluated_response:
        audience: operator
        text: Local-only answer text.
        sensitivity: release_safe
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(EvaluationInputError, match="inline response text"):
        load_evaluation_subject_manifest(manifest_path)


def test_subject_loader_rejects_mutable_runs_latest_refs(tmp_path: Path) -> None:
    manifest_path = tmp_path / "subjects.yaml"
    manifest_path.write_text(
        """
manifest_id: local_subjects
version: "2026-06-07"
suite_id: insurance_qa_smoke
subjects:
  - case_ref:
      case_id: supported_travel_meal
    artifacts:
      trace_ref: runs/latest/trace.jsonl
      receipt_ref: runs/latest/governance_receipt.md
    projections:
      evaluated_response:
        audience: operator
        text: Local-only answer text.
        sensitivity: local_only
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(EvaluationInputError, match="runs/latest"):
        load_evaluation_subject_manifest(manifest_path)


def test_subject_loader_rejects_mutable_endpoint_urls(tmp_path: Path) -> None:
    manifest_path = tmp_path / "subjects.yaml"
    manifest_path.write_text(
        """
manifest_id: local_subjects
version: "2026-06-07"
suite_id: insurance_qa_smoke
subjects:
  - case_ref:
      case_id: supported_travel_meal
    artifacts:
      trace_ref: https://example.com/run/trace.jsonl
      receipt_ref: https://example.com/run/governance_receipt.md
    projections:
      evaluated_response:
        audience: operator
        text: Local-only answer text.
        sensitivity: local_only
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(EvaluationInputError, match="mutable endpoint URL"):
        load_evaluation_subject_manifest(manifest_path)
