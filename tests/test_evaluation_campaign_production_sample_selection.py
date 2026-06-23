import hashlib
import json
from pathlib import Path

import pytest

from proof_agent.contracts import EvaluationResponseProjectionAudience, ReceiptOutcome, RunPurpose
from proof_agent.evaluation.campaigns import run_evaluation_campaign
from proof_agent.evaluation.errors import EvaluationInputError
from proof_agent.evaluation.production_samples import (
    ProductionSampleImportSelection,
    ProductionSamplePromotionCase,
    ProductionSampleReviewerConfirmation,
    import_curated_production_samples,
    promote_curated_production_sample,
)
from proof_agent.observability.storage.run_store import RunStore


def test_campaign_selects_promoted_curated_production_sample(
    tmp_path: Path,
) -> None:
    promotion = _promote_production_sample(tmp_path)
    campaign_path = tmp_path / "campaign.yaml"
    campaign_path.write_text(
        f"""
campaign_id: production_sample_campaign
version: "2026-06-23"
target:
  agent_id: insurance_customer_service
  agent_version_id: published_v1
suites:
  production_samples:
    enabled: true
    selections:
      - promotion_ref: {promotion.promotion_record_path.relative_to(tmp_path)}
thresholds:
  governed_resolution_rate_min: 0.95
  artifact_sufficiency_required: 1.0
  deterministic_gate_pass_required: 1.0
""".lstrip(),
        encoding="utf-8",
    )

    summary = run_evaluation_campaign(
        campaign_path=campaign_path,
        output_dir=tmp_path / "campaigns",
    )

    assert summary.readiness_status == "ready"
    assert summary.governed_resolution_rate == 1.0
    assert len(summary.suite_runs) == 1
    assert summary.suite_runs[0].source == "curated_production_sample"
    assert summary.suite_runs[0].suite_id == "production_edge_cases"


def test_campaign_auto_selects_promoted_curated_production_samples(
    tmp_path: Path,
) -> None:
    _promote_production_sample(tmp_path)
    campaign_path = tmp_path / "campaign.yaml"
    campaign_path.write_text(
        """
campaign_id: production_sample_auto_select_campaign
version: "2026-06-23"
target:
  agent_id: insurance_customer_service
  agent_version_id: published_v1
suites:
  production_samples:
    enabled: true
    auto_select:
      promotions_dir: promoted
thresholds:
  governed_resolution_rate_min: 0.95
  artifact_sufficiency_required: 1.0
  deterministic_gate_pass_required: 1.0
""".lstrip(),
        encoding="utf-8",
    )

    summary = run_evaluation_campaign(
        campaign_path=campaign_path,
        output_dir=tmp_path / "campaigns",
    )

    assert summary.readiness_status == "ready"
    assert summary.governed_resolution_rate == 1.0
    assert len(summary.suite_runs) == 1
    assert summary.suite_runs[0].source == "curated_production_sample"
    assert summary.suite_runs[0].suite_id == "production_edge_cases"


def test_campaign_rejects_diagnostic_only_curated_production_formal_suite(
    tmp_path: Path,
) -> None:
    store = RunStore(tmp_path / "runs" / "history")
    run_id = _write_run(
        store,
        run_id="run_prod_diagnostic_only",
        question="Customer asked a sensitive production question.",
        response_text="Covered by policy with production wording.",
        run_purpose=RunPurpose.PRODUCTION,
    )
    run_dir = store.history_dir / run_id
    trace_path = run_dir / "trace.jsonl"
    receipt_path = run_dir / "governance_receipt.md"
    response_path = run_dir / "operator_response.txt"
    suite_path = tmp_path / "diagnostic_suite.yaml"
    subjects_path = tmp_path / "diagnostic_subjects.yaml"
    campaign_path = tmp_path / "campaign.yaml"

    suite_path.write_text(
        """
suite_id: diagnostic_only_production
version: "2026-06-23"
name: Diagnostic-only Production Sample
cases:
  - case_id: prod_diagnostic_only_case
    question: Redacted production policy support scenario.
    intent_type: guidance
    expected_resolution: answer_with_citations
    risk_class: customer_service_fact
    capability_path: evidence_answer
    expected:
      outcome: ANSWERED_WITH_CITATIONS
      required_citation_refs:
        - policy
    metadata:
      source: curated_production_sample
      curation_status: diagnostic_only
""".lstrip(),
        encoding="utf-8",
    )
    subjects_path.write_text(
        f"""
manifest_id: diagnostic_only_subjects
version: "2026-06-23"
suite_id: diagnostic_only_production
subjects:
  - case_ref:
      case_id: prod_diagnostic_only_case
    artifacts:
      trace_ref: {trace_path.relative_to(tmp_path)}
      trace_sha256: {_sha256(trace_path)}
      receipt_ref: {receipt_path.relative_to(tmp_path)}
      receipt_sha256: {_sha256(receipt_path)}
    projections:
      evaluated_response:
        audience: operator
        ref: {response_path.relative_to(tmp_path)}
        sha256: {_sha256(response_path)}
        sensitivity: release_safe
    run_ref:
      run_id: {run_id}
      source: run_store
    metadata:
      source: curated_production_sample
      curation_status: diagnostic_only
""".lstrip(),
        encoding="utf-8",
    )
    campaign_path.write_text(
        """
campaign_id: diagnostic_only_campaign
version: "2026-06-23"
target:
  agent_id: insurance_customer_service
  agent_version_id: published_v1
suites:
  formal:
    - source: curated_production_sample
      suite_ref: diagnostic_suite.yaml
      subjects_ref: diagnostic_subjects.yaml
thresholds:
  governed_resolution_rate_min: 0.95
  artifact_sufficiency_required: 1.0
  deterministic_gate_pass_required: 1.0
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(EvaluationInputError, match="promoted curated production sample"):
        run_evaluation_campaign(
            campaign_path=campaign_path,
            output_dir=tmp_path / "campaigns",
        )


def test_campaign_auto_select_rejects_unpromoted_production_sample_record(
    tmp_path: Path,
) -> None:
    promotion_dir = tmp_path / "promoted" / "diagnostic_only"
    promotion_dir.mkdir(parents=True)
    (promotion_dir / "production_sample_promotion.json").write_text(
        json.dumps(
            {
                "sample_id": "diagnostic_only",
                "status": "diagnostic_only",
                "suite_path": "evaluation_suite.yaml",
                "subject_manifest_path": "evaluation_subjects.yaml",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    campaign_path = tmp_path / "campaign.yaml"
    campaign_path.write_text(
        """
campaign_id: production_sample_auto_select_campaign
version: "2026-06-23"
target:
  agent_id: insurance_customer_service
  agent_version_id: published_v1
suites:
  production_samples:
    enabled: true
    auto_select:
      promotions_dir: promoted
thresholds:
  governed_resolution_rate_min: 0.95
  artifact_sufficiency_required: 1.0
  deterministic_gate_pass_required: 1.0
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(EvaluationInputError, match="requires promoted status"):
        run_evaluation_campaign(
            campaign_path=campaign_path,
            output_dir=tmp_path / "campaigns",
        )


def _promote_production_sample(tmp_path: Path):
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
        version="2026-06-23",
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
    return promote_curated_production_sample(
        batch_dir=batch.batch_dir,
        sample_id="prod_supported",
        output_dir=tmp_path / "promoted",
        suite_id="production_edge_cases",
        suite_version="2026-06-23",
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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
