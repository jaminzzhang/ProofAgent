from pathlib import Path

from proof_agent.contracts import EvaluationReleaseDecisionStatus
from proof_agent.evaluation.analyzer import analyze_evaluation
from proof_agent.evaluation.errors import EvaluationInputError
from proof_agent.evaluation.frozen_bundles import (
    freeze_evaluation_subject_bundle,
    verify_evaluation_subject_bundle,
)
from proof_agent.evaluation.subjects import load_evaluation_subject_manifest


def test_frozen_subject_bundle_can_be_analyzed_without_original_run_artifacts(
    tmp_path: Path,
) -> None:
    suite_path = _write_suite(tmp_path)
    subjects_path = _write_subjects(tmp_path)

    bundle = freeze_evaluation_subject_bundle(
        suite_path=suite_path,
        subjects_path=subjects_path,
        output_dir=tmp_path / "bundles",
        bundle_id="release_2026_06_09",
        version="2026-06-09",
    )
    _remove_original_artifacts(tmp_path)

    bundled_manifest = load_evaluation_subject_manifest(bundle.subject_manifest_path)
    subject = bundled_manifest.subjects[0]
    assert bundle.artifact_count == 4
    assert bundle.suite_path.exists()
    assert bundle.bundle_manifest_path.exists()
    assert subject.trace.ref.exists()
    assert subject.trace.sha256 is not None
    assert subject.receipt.sha256 is not None
    assert subject.run_meta is not None
    assert subject.run_meta.sha256 is not None
    assert subject.response_projection.sha256 is not None

    summary = analyze_evaluation(
        suite_path=bundle.suite_path,
        subjects_path=bundle.subject_manifest_path,
        output_dir=tmp_path / "evaluations",
    )

    assert summary.release_decision.status == EvaluationReleaseDecisionStatus.PASSED


def test_frozen_subject_bundle_verification_detects_artifact_tampering(
    tmp_path: Path,
) -> None:
    suite_path = _write_suite(tmp_path)
    subjects_path = _write_subjects(tmp_path)
    bundle = freeze_evaluation_subject_bundle(
        suite_path=suite_path,
        subjects_path=subjects_path,
        output_dir=tmp_path / "bundles",
        bundle_id="release_2026_06_09",
        version="2026-06-09",
    )

    passed = verify_evaluation_subject_bundle(bundle.bundle_dir)

    assert passed.status == "passed"
    assert passed.checked_artifact_count == 4
    assert passed.mismatched_artifacts == ()

    response = bundle.bundle_dir / "artifacts" / "supported" / "evaluated_response.txt"
    response.write_text("Tampered response.", encoding="utf-8")

    failed = verify_evaluation_subject_bundle(bundle.bundle_dir)

    assert failed.status == "failed"
    assert failed.checked_artifact_count == 4
    assert failed.mismatched_artifacts == ("artifacts/supported/evaluated_response.txt",)


def test_frozen_subject_bundle_rejects_inline_response_projection(tmp_path: Path) -> None:
    suite_path = _write_suite(tmp_path)
    subjects_path = _write_inline_subjects(tmp_path)

    try:
        freeze_evaluation_subject_bundle(
            suite_path=suite_path,
            subjects_path=subjects_path,
            output_dir=tmp_path / "bundles",
            bundle_id="release_2026_06_09",
            version="2026-06-09",
        )
    except EvaluationInputError as exc:
        assert "file-backed response projections" in str(exc)
    else:
        raise AssertionError("inline response projection should not be frozen")


def _write_suite(tmp_path: Path) -> Path:
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text(
        """
suite_id: insurance_qa_bundle
version: "2026-06-09"
name: Insurance QA Bundle
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


def _write_subjects(tmp_path: Path) -> Path:
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
    (run_dir / "run_meta.json").write_text(
        '{"run_id":"run_supported","agent_id":"insurance_agent"}\n',
        encoding="utf-8",
    )
    (run_dir / "operator_response.txt").write_text("Covered by policy.", encoding="utf-8")
    subjects_path = tmp_path / "subjects.yaml"
    subjects_path.write_text(
        """
manifest_id: local_subjects
version: "2026-06-09"
suite_id: insurance_qa_bundle
agent:
  agent_id: insurance_agent
  agent_version_id: version_001
subjects:
  - case_ref:
      case_id: supported
    artifacts:
      trace_ref: runs/history/run_supported/trace.jsonl
      receipt_ref: runs/history/run_supported/governance_receipt.md
      run_meta_ref: runs/history/run_supported/run_meta.json
    projections:
      evaluated_response:
        audience: operator
        ref: runs/history/run_supported/operator_response.txt
        sensitivity: release_safe
    run_ref:
      run_id: run_supported
      source: run_store
""".lstrip(),
        encoding="utf-8",
    )
    return subjects_path


def _write_inline_subjects(tmp_path: Path) -> Path:
    run_dir = tmp_path / "runs" / "history" / "run_supported"
    run_dir.mkdir(parents=True)
    (run_dir / "trace.jsonl").write_text(
        '{"event_type":"final_output","payload":{"outcome":"ANSWERED_WITH_CITATIONS"}}\n',
        encoding="utf-8",
    )
    (run_dir / "governance_receipt.md").write_text(
        "# Governance Receipt\n\n## Final Outcome\n\nANSWERED_WITH_CITATIONS\n",
        encoding="utf-8",
    )
    subjects_path = tmp_path / "inline-subjects.yaml"
    subjects_path.write_text(
        """
manifest_id: inline_subjects
version: "2026-06-09"
suite_id: insurance_qa_bundle
subjects:
  - case_ref:
      case_id: supported
    artifacts:
      trace_ref: runs/history/run_supported/trace.jsonl
      receipt_ref: runs/history/run_supported/governance_receipt.md
    projections:
      evaluated_response:
        audience: operator
        text: Covered by policy.
        sensitivity: local_only
""".lstrip(),
        encoding="utf-8",
    )
    return subjects_path


def _remove_original_artifacts(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.rename(tmp_path / "runs_removed")
