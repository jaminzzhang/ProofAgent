import hashlib
from pathlib import Path

from proof_agent.contracts import (
    EvaluationCaseRef,
    EvaluationReleaseDecisionStatus,
    EvaluationResponseProjectionAudience,
    EvaluationSubjectExportSelection,
    ReceiptOutcome,
    RunPurpose,
)
from proof_agent.evaluation.analyzer import analyze_evaluation
from proof_agent.evaluation.errors import EvaluationInputError
from proof_agent.evaluation.subject_exports import (
    export_evaluation_subject_manifest_from_run_store,
)
from proof_agent.evaluation.subjects import load_evaluation_subject_manifest
from proof_agent.observability.storage.run_store import RunStore


def test_export_from_run_store_writes_release_sufficient_subject_manifest(
    tmp_path: Path,
) -> None:
    store = RunStore(tmp_path / "runs" / "history")
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

    output_path = tmp_path / "exports" / "subjects.yaml"
    manifest = export_evaluation_subject_manifest_from_run_store(
        store=store,
        suite_id="insurance_qa_export",
        manifest_id="dashboard_export",
        version="2026-06-09",
        selections=(
            EvaluationSubjectExportSelection(
                case_ref=EvaluationCaseRef(case_id="supported"),
                run_id="run_supported",
                response_projection_ref=Path("operator_response.txt"),
                response_projection_audience=EvaluationResponseProjectionAudience.OPERATOR,
            ),
        ),
        output_path=output_path,
    )

    loaded = load_evaluation_subject_manifest(output_path)
    subject = loaded.subjects[0]
    assert manifest.manifest_id == "dashboard_export"
    assert loaded.agent["agent_id"] == "insurance_agent"
    assert loaded.agent["agent_version_id"] == "version_001"
    assert subject.trace.sha256 == _sha256(store.history_dir / "run_supported" / "trace.jsonl")
    assert subject.receipt.sha256 == _sha256(
        store.history_dir / "run_supported" / "governance_receipt.md"
    )
    assert subject.run_meta is not None
    assert subject.run_meta.sha256 == _sha256(
        store.history_dir / "run_supported" / "run_meta.json"
    )
    assert subject.response_projection.sha256 == _sha256(response_path)
    assert subject.response_projection.sensitivity == "release_safe"
    assert subject.run_ref is not None
    assert subject.run_ref.run_id == "run_supported"
    assert subject.run_ref.source == "run_store"

    summary = analyze_evaluation(
        suite_path=suite_path,
        subjects_path=output_path,
        output_dir=tmp_path / "evaluations",
    )

    assert summary.release_decision.status == EvaluationReleaseDecisionStatus.PASSED


def test_export_from_run_store_requires_explicit_response_projection_file(
    tmp_path: Path,
) -> None:
    store = RunStore(tmp_path / "runs" / "history")
    trace_src, receipt_src = _write_sources(tmp_path)
    store.save_run_artifacts(
        "run_supported",
        trace_source=trace_src,
        receipt_source=receipt_src,
        question="Supported?",
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
    )

    output_path = tmp_path / "exports" / "subjects.yaml"
    try:
        export_evaluation_subject_manifest_from_run_store(
            store=store,
            suite_id="insurance_qa_export",
            manifest_id="dashboard_export",
            version="2026-06-09",
            selections=(
                EvaluationSubjectExportSelection(
                    case_ref=EvaluationCaseRef(case_id="supported"),
                    run_id="run_supported",
                    response_projection_ref=Path("operator_response.txt"),
                    response_projection_audience=EvaluationResponseProjectionAudience.OPERATOR,
                ),
            ),
            output_path=output_path,
        )
    except EvaluationInputError as exc:
        assert "cannot export missing run artifact refs" in str(exc)
    else:
        raise AssertionError("missing response projection should block export")

    assert not output_path.exists()


def _write_sources(tmp_path: Path) -> tuple[Path, Path]:
    trace_src = tmp_path / "trace.jsonl"
    receipt_src = tmp_path / "governance_receipt.md"
    trace_src.write_text(
        '{"event_type":"retrieval_result","status":"ok","payload":{"source_refs":["policy"]}}\n'
        '{"event_type":"evidence_evaluation","status":"ok",'
        '"payload":{"metadata":{"accepted_count":1},"accepted_sources":["policy"]}}\n'
        '{"event_type":"policy_decision","status":"ok"}\n'
        '{"event_type":"final_output","status":"ok",'
        '"payload":{"outcome":"ANSWERED_WITH_CITATIONS"}}\n',
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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
