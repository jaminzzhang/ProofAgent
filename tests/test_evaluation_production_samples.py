import json
from pathlib import Path

from proof_agent.contracts import EvaluationResponseProjectionAudience, ReceiptOutcome, RunPurpose
from proof_agent.evaluation.production_samples import (
    ProductionSampleImportSelection,
    ProductionSamplePromotionCase,
    ProductionSampleReviewerConfirmation,
    import_curated_production_samples,
    promote_curated_production_sample,
)
from proof_agent.evaluation.analyzer import analyze_evaluation
from proof_agent.evaluation.errors import EvaluationInputError
from proof_agent.evaluation.subjects import load_evaluation_subject_manifest
from proof_agent.evaluation.suites import load_evaluation_suite
from proof_agent.observability.storage.run_store import RunStore


def test_import_curated_production_sample_writes_diagnostic_candidate(
    tmp_path: Path,
) -> None:
    store = RunStore(tmp_path / "runs" / "history")
    run_id = _write_run(
        store,
        run_id="run_prod_supported",
        question="Customer asked a sensitive production question.",
        response_text="Covered by policy with production wording.",
        run_purpose=RunPurpose.PRODUCTION,
    )

    batch = import_curated_production_samples(
        store=store,
        output_dir=tmp_path / "curation",
        batch_id="prod_edge_cases",
        version="2026-06-22",
        selections=(
            ProductionSampleImportSelection(
                sample_id="prod_supported",
                run_id=run_id,
                response_projection_ref=Path("operator_response.txt"),
                response_projection_audience=EvaluationResponseProjectionAudience.OPERATOR,
                redaction_reviewer="redaction-reviewer",
                redaction_confirmed=True,
            ),
        ),
    )

    candidates_path = batch.batch_dir / "production_sample_candidates.jsonl"
    rows = [
        json.loads(line)
        for line in candidates_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    serialized = candidates_path.read_text(encoding="utf-8")

    assert batch.candidate_count == 1
    assert rows[0]["sample_id"] == "prod_supported"
    assert rows[0]["source_run_id"] == "run_prod_supported"
    assert rows[0]["curation_status"] == "diagnostic_only"
    assert rows[0]["formal_scoring_allowed"] is False
    assert rows[0]["run_purpose"] == "production"
    assert rows[0]["safe_summary"]["question_text_length"] == len(
        "Customer asked a sensitive production question."
    )
    assert rows[0]["safe_summary"]["response_text_length"] == len(
        "Covered by policy with production wording."
    )
    assert rows[0]["artifacts"]["trace_sha256"]
    assert rows[0]["artifacts"]["response_projection_sha256"]
    assert "Customer asked a sensitive production question." not in serialized
    assert "Covered by policy with production wording." not in serialized


def test_import_curated_production_sample_rejects_non_production_run(
    tmp_path: Path,
) -> None:
    store = RunStore(tmp_path / "runs" / "history")
    run_id = _write_run(
        store,
        run_id="run_eval_sample",
        question="Evaluation sample question.",
        response_text="Evaluation sample answer.",
        run_purpose=RunPurpose.EVALUATION_SAMPLE,
    )

    try:
        import_curated_production_samples(
            store=store,
            output_dir=tmp_path / "curation",
            batch_id="prod_edge_cases",
            version="2026-06-22",
            selections=(
                ProductionSampleImportSelection(
                    sample_id="not_production",
                    run_id=run_id,
                    response_projection_ref=Path("operator_response.txt"),
                    response_projection_audience=EvaluationResponseProjectionAudience.OPERATOR,
                    redaction_reviewer="redaction-reviewer",
                    redaction_confirmed=True,
                ),
            ),
        )
    except EvaluationInputError as exc:
        assert "run_purpose production" in str(exc)
    else:
        raise AssertionError("non-production runs must not import as production samples")

    assert not (tmp_path / "curation" / "prod_edge_cases").exists()


def test_import_curated_production_sample_requires_redaction_confirmation(
    tmp_path: Path,
) -> None:
    store = RunStore(tmp_path / "runs" / "history")
    run_id = _write_run(
        store,
        run_id="run_prod_supported",
        question="Customer asked a sensitive production question.",
        response_text="Covered by policy with production wording.",
        run_purpose=RunPurpose.PRODUCTION,
    )

    try:
        import_curated_production_samples(
            store=store,
            output_dir=tmp_path / "curation",
            batch_id="prod_edge_cases",
            version="2026-06-22",
            selections=(
                ProductionSampleImportSelection(
                    sample_id="prod_supported",
                    run_id=run_id,
                    response_projection_ref=Path("operator_response.txt"),
                    response_projection_audience=EvaluationResponseProjectionAudience.OPERATOR,
                    redaction_reviewer="redaction-reviewer",
                    redaction_confirmed=False,
                ),
            ),
        )
    except EvaluationInputError as exc:
        assert "Redaction reviewer confirmation is required" in str(exc)
    else:
        raise AssertionError("production sample import must require redaction confirmation")

    assert not (tmp_path / "curation" / "prod_edge_cases").exists()


def test_promote_curated_production_sample_requires_dual_reviewer_confirmation(
    tmp_path: Path,
) -> None:
    store = RunStore(tmp_path / "runs" / "history")
    run_id = _write_run(
        store,
        run_id="run_prod_supported",
        question="Customer asked a sensitive production question.",
        response_text="Covered by policy with production wording.",
        run_purpose=RunPurpose.PRODUCTION,
    )
    batch = import_curated_production_samples(
        store=store,
        output_dir=tmp_path / "curation",
        batch_id="prod_edge_cases",
        version="2026-06-22",
        selections=(
            ProductionSampleImportSelection(
                sample_id="prod_supported",
                run_id=run_id,
                response_projection_ref=Path("operator_response.txt"),
                response_projection_audience=EvaluationResponseProjectionAudience.OPERATOR,
                redaction_reviewer="redaction-reviewer",
                redaction_confirmed=True,
            ),
        ),
    )

    promotion = promote_curated_production_sample(
        batch_dir=batch.batch_dir,
        sample_id="prod_supported",
        output_dir=tmp_path / "promoted",
        suite_id="production_edge_cases",
        suite_version="2026-06-22",
        manifest_id="production_edge_subjects",
        case=ProductionSamplePromotionCase(
            case_id="prod_supported_case",
            question="Redacted production policy support scenario.",
            intent_type="guidance",
            expected_resolution="answer_with_citations",
            risk_class="customer_service_fact",
            capability_path="evidence_answer",
            expected_outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            required_citation_refs=("policy",),
        ),
        domain_review=ProductionSampleReviewerConfirmation(
            reviewer="domain-reviewer",
            confirmed=True,
        ),
        harness_review=ProductionSampleReviewerConfirmation(
            reviewer="harness-reviewer",
            confirmed=True,
        ),
    )

    suite = load_evaluation_suite(promotion.suite_path)
    manifest = load_evaluation_subject_manifest(promotion.subject_manifest_path)
    promotion_record = json.loads(promotion.promotion_record_path.read_text(encoding="utf-8"))

    assert promotion.status == "promoted"
    assert suite.cases[0].case_id == "prod_supported_case"
    assert suite.cases[0].metadata["curation_status"] == "promoted"
    assert suite.cases[0].metadata["source_sample_id"] == "prod_supported"
    assert manifest.subjects[0].run_ref is not None
    assert manifest.subjects[0].run_ref.run_id == "run_prod_supported"
    assert manifest.subjects[0].metadata["curation_status"] == "promoted"
    assert promotion_record["domain_review"]["reviewer"] == "domain-reviewer"
    assert promotion_record["harness_review"]["reviewer"] == "harness-reviewer"

    summary = analyze_evaluation(
        suite_path=promotion.suite_path,
        subjects_path=promotion.subject_manifest_path,
        output_dir=tmp_path / "evaluations",
    )

    assert summary.release_decision.status.value == "passed"


def test_promote_curated_production_sample_rejects_missing_reviewer_confirmation(
    tmp_path: Path,
) -> None:
    store = RunStore(tmp_path / "runs" / "history")
    run_id = _write_run(
        store,
        run_id="run_prod_supported",
        question="Customer asked a sensitive production question.",
        response_text="Covered by policy with production wording.",
        run_purpose=RunPurpose.PRODUCTION,
    )
    batch = import_curated_production_samples(
        store=store,
        output_dir=tmp_path / "curation",
        batch_id="prod_edge_cases",
        version="2026-06-22",
        selections=(
            ProductionSampleImportSelection(
                sample_id="prod_supported",
                run_id=run_id,
                response_projection_ref=Path("operator_response.txt"),
                response_projection_audience=EvaluationResponseProjectionAudience.OPERATOR,
                redaction_reviewer="redaction-reviewer",
                redaction_confirmed=True,
            ),
        ),
    )

    try:
        promote_curated_production_sample(
            batch_dir=batch.batch_dir,
            sample_id="prod_supported",
            output_dir=tmp_path / "promoted",
            suite_id="production_edge_cases",
            suite_version="2026-06-22",
            manifest_id="production_edge_subjects",
            case=ProductionSamplePromotionCase(
                case_id="prod_supported_case",
                question="Redacted production policy support scenario.",
                intent_type="guidance",
                expected_resolution="answer_with_citations",
                risk_class="customer_service_fact",
                capability_path="evidence_answer",
                expected_outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
                required_citation_refs=("policy",),
            ),
            domain_review=ProductionSampleReviewerConfirmation(
                reviewer="domain-reviewer",
                confirmed=True,
            ),
            harness_review=ProductionSampleReviewerConfirmation(
                reviewer="harness-reviewer",
                confirmed=False,
            ),
        )
    except EvaluationInputError as exc:
        assert "Harness Evaluation Reviewer confirmation is required" in str(exc)
    else:
        raise AssertionError("promotion must require Harness reviewer confirmation")

    assert not (tmp_path / "promoted" / "prod_supported").exists()


def _write_run(
    store: RunStore,
    *,
    run_id: str,
    question: str,
    response_text: str,
    run_purpose: RunPurpose,
) -> str:
    source_dir = store.history_dir.parent / "sources" / run_id
    source_dir.mkdir(parents=True)
    trace_src = source_dir / "trace.jsonl"
    receipt_src = source_dir / "governance_receipt.md"
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
    store.save_run_artifacts(
        run_id,
        trace_source=trace_src,
        receipt_source=receipt_src,
        question=question,
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        run_purpose=run_purpose,
        agent_id="insurance_customer_service",
        agent_version_id="published_v1",
    )
    (store.history_dir / run_id / "operator_response.txt").write_text(
        response_text,
        encoding="utf-8",
    )
    return run_id
