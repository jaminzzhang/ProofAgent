import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from proof_agent.contracts import (
    ExactArtifactRef,
    InsuranceKnowledgeEvaluationReport,
    InsuranceKnowledgeSliceMetrics,
    InsuranceRetrievalMetrics,
    ReceiptOutcome,
)
from proof_agent.delivery.cli import app
from proof_agent.evaluation.knowledge_gates import (
    KnowledgeAcceptanceAggregate,
    KnowledgeHardGateFacts,
)
from proof_agent.evaluation.sealed_knowledge_acceptance import (
    SealedKnowledgeAcceptanceEnvelope,
    SealedKnowledgeSuiteRef,
)


runner = CliRunner()


def _sealed_cli_envelope() -> SealedKnowledgeAcceptanceEnvelope:
    metrics = InsuranceRetrievalMetrics(
        retrieval_case_count=160,
        required_evidence_recall_at_20=0.94,
        required_evidence_recall_at_50=0.96,
        required_evidence_recall_at_100=0.99,
        complete_evidence_top_5_rate=0.88,
        complete_evidence_top_10_rate=0.92,
        ndcg_at_10=0.93,
        mrr_at_10=0.95,
        citation_resolvability_rate=1.0,
    )
    slices = tuple(
        InsuranceKnowledgeSliceMetrics(
            dimension="query_type",
            value=query_type,
            case_count=count,
            metrics=metrics,
        )
        for query_type, count in (
            ("clause_lookup", 60),
            ("conditional_guidance", 100),
            ("comparison", 40),
        )
    )
    return SealedKnowledgeAcceptanceEnvelope(
        candidate_digest="candidate-cli",
        suite_ref=SealedKnowledgeSuiteRef(
            suite_id="insurance-knowledge-acceptance",
            version="2026-07-14",
            artifact=ExactArtifactRef(
                artifact_uri="s3://proof-agent-private-eval/sealed/suite.yaml",
                version_id="sealed-suite-v1",
                sha256="a" * 64,
                size_bytes=4096,
                media_type="application/yaml",
            ),
        ),
        aggregate=KnowledgeAcceptanceAggregate(
            report=InsuranceKnowledgeEvaluationReport(
                case_count=200,
                overall=metrics,
                slices=slices,
            ),
            hard_facts=KnowledgeHardGateFacts(),
            human_reviewed_support_precision=0.99,
            hybrid_retrieval_p95_seconds=4.5,
        ),
    )


def test_evaluate_analyze_cli_writes_artifacts_and_returns_one_when_required_case_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "proof_agent.delivery.cli.execute_agent_package_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not create runs")),
    )
    suite_path, subjects_path = _write_cli_fixture(tmp_path)
    output_dir = tmp_path / "evaluations"

    result = runner.invoke(
        app,
        [
            "evaluate",
            "analyze",
            "--suite",
            str(suite_path),
            "--subjects",
            str(subjects_path),
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 1
    assert "evaluation_report.md" in result.output
    assert (output_dir / "insurance_qa_smoke-local_subjects" / "evaluation_report.md").exists()
    assert not (tmp_path / "runs" / "latest").exists()


def test_evaluate_analyze_cli_returns_one_when_release_decision_is_blocked(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "proof_agent.delivery.cli.execute_agent_package_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not create runs")),
    )
    suite_path, subjects_path = _write_cli_fixture(tmp_path, include_missing_case=False)

    result = runner.invoke(
        app,
        [
            "evaluate",
            "analyze",
            "--suite",
            str(suite_path),
            "--subjects",
            str(subjects_path),
            "--output-dir",
            str(tmp_path / "evaluations"),
        ],
    )

    assert result.exit_code == 1
    assert "Release Decision: blocked" in result.output


def test_evaluate_knowledge_acceptance_writes_aggregate_only_result(
    monkeypatch,
    tmp_path: Path,
) -> None:
    envelope = _sealed_cli_envelope()
    monkeypatch.setattr(
        "proof_agent.delivery.cli.load_sealed_knowledge_acceptance_envelope",
        lambda _path: envelope,
    )
    output = tmp_path / "acceptance-result.json"

    result = runner.invoke(
        app,
        [
            "evaluate",
            "knowledge-acceptance",
            "--suite",
            str(tmp_path / "private-suite.yaml"),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert "Knowledge Acceptance: passed" in result.output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["case_count"] == 200
    assert "case_results" not in payload

    repeated = runner.invoke(
        app,
        [
            "evaluate",
            "knowledge-acceptance",
            "--suite",
            str(tmp_path / "private-suite.yaml"),
            "--output",
            str(output),
        ],
    )
    assert repeated.exit_code == 2
    assert "one acceptance attempt" in repeated.output


def test_evaluate_run_suite_cli_creates_subjects_and_analysis(
    monkeypatch,
    tmp_path: Path,
) -> None:
    suite_path = tmp_path / "suite.yaml"
    agent_path = tmp_path / "agent.yaml"
    output_dir = tmp_path / "evaluations"
    agent_path.write_text("name: fake_agent\n", encoding="utf-8")
    suite_path.write_text(
        """
suite_id: v3_intent_execution
version: "2026-06-21"
name: V3 Intent Execution
cases:
  - case_id: v3_policy_answer
    question: What is the reimbursement rule for travel meals?
    intent_type: enterprise_policy_question
    expected_resolution: answer_with_citations
    risk_class: low_business_fact
    capability_path: retrieval_only
    expected:
      outcome: ANSWERED_WITH_CITATIONS
      required_citation_refs:
        - customer-support-policy
      forbid_clarification: true
      max_action_constraint_rewrites: 0
      forbid_repeated_retrieval_queries: true
      require_response_citation_refs: true
""".lstrip(),
        encoding="utf-8",
    )

    def fake_execute_agent_package_run(request):
        assert Path(request.agent_yaml) == agent_path
        assert request.question == "What is the reimbursement rule for travel meals?"
        Path(request.runs_dir).mkdir(parents=True, exist_ok=True)
        trace_path = Path(request.runs_dir) / "trace.jsonl"
        receipt_path = Path(request.runs_dir) / "governance_receipt.md"
        trace_path.write_text(
            '{"event_type":"retrieval_step","status":"ok",'
            '"payload":{"query":"travel meal reimbursement"}}\n'
            '{"event_type":"retrieval_result","status":"ok",'
            '"payload":{"source_refs":["customer-support-policy"]}}\n'
            '{"event_type":"evidence_evaluation","status":"ok",'
            '"payload":{"metadata":{"accepted_count":1},'
            '"accepted_sources":["customer-support-policy"]}}\n'
            '{"event_type":"policy_decision","status":"ok"}\n'
            '{"event_type":"final_output","status":"ok",'
            '"payload":{"outcome":"ANSWERED_WITH_CITATIONS"}}\n',
            encoding="utf-8",
        )
        receipt_path.write_text(
            "# Governance Receipt\n\n## Final Outcome\n\nANSWERED_WITH_CITATIONS\n",
            encoding="utf-8",
        )
        return SimpleNamespace(
            final_output=(
                "Travel meals are reimbursed. citation_refs: customer-support-policy"
            ),
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            trace_path=trace_path,
            receipt_path=receipt_path,
        )

    monkeypatch.setattr(
        "proof_agent.delivery.cli.execute_agent_package_run",
        fake_execute_agent_package_run,
    )

    result = runner.invoke(
        app,
        [
            "evaluate",
            "run-suite",
            "--suite",
            str(suite_path),
            "--agent",
            str(agent_path),
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0
    assert "Subjects:" in result.output
    assert "Release Decision: passed" in result.output
    subject_manifest = (
        output_dir
        / "v3_intent_execution"
        / "evaluation_subjects.yaml"
    )
    assert subject_manifest.exists()
    assert "v3_policy_answer" in subject_manifest.read_text(encoding="utf-8")
    assert (
        output_dir
        / "v3_intent_execution-v3_intent_execution_run_subjects"
        / "evaluation_report.md"
    ).exists()


def test_evaluate_freeze_bundle_cli_writes_portable_bundle(tmp_path: Path) -> None:
    suite_path, subjects_path = _write_cli_fixture(tmp_path, include_missing_case=False)
    output_dir = tmp_path / "bundles"

    result = runner.invoke(
        app,
        [
            "evaluate",
            "freeze-bundle",
            "--suite",
            str(suite_path),
            "--subjects",
            str(subjects_path),
            "--output-dir",
            str(output_dir),
            "--bundle-id",
            "release_bundle",
            "--version",
            "2026-06-09",
        ],
    )

    assert result.exit_code == 0
    assert "evaluation_subjects.yaml" in result.output
    assert (output_dir / "release_bundle" / "evaluation_suite.yaml").exists()
    assert (output_dir / "release_bundle" / "evaluation_subjects.yaml").exists()
    assert (output_dir / "release_bundle" / "bundle_manifest.yaml").exists()


def test_evaluate_verify_bundle_cli_reports_integrity_status(tmp_path: Path) -> None:
    suite_path, subjects_path = _write_cli_fixture(tmp_path, include_missing_case=False)
    output_dir = tmp_path / "bundles"
    runner.invoke(
        app,
        [
            "evaluate",
            "freeze-bundle",
            "--suite",
            str(suite_path),
            "--subjects",
            str(subjects_path),
            "--output-dir",
            str(output_dir),
            "--bundle-id",
            "release_bundle",
            "--version",
            "2026-06-09",
        ],
    )

    passed = runner.invoke(
        app,
        [
            "evaluate",
            "verify-bundle",
            str(output_dir / "release_bundle"),
        ],
    )

    assert passed.exit_code == 0
    assert "Bundle Integrity: passed" in passed.output

    response = output_dir / "release_bundle" / "artifacts" / "supported" / "evaluated_response.txt"
    response.write_text("tampered", encoding="utf-8")
    failed = runner.invoke(
        app,
        [
            "evaluate",
            "verify-bundle",
            str(output_dir / "release_bundle"),
        ],
    )

    assert failed.exit_code == 1
    assert "Bundle Integrity: failed" in failed.output
    assert "artifacts/supported/evaluated_response.txt" in failed.output


def test_evaluate_campaign_run_cli_writes_campaign_artifacts(tmp_path: Path) -> None:
    campaign_path = _write_campaign_cli_fixture(tmp_path)

    result = runner.invoke(
        app,
        [
            "evaluate",
            "campaign",
            "run",
            "--campaign",
            str(campaign_path),
            "--output-dir",
            str(tmp_path / "campaigns"),
        ],
    )

    assert result.exit_code == 0
    assert "Campaign: active_agent_probe" in result.output
    assert "Readiness: ready" in result.output
    assert (tmp_path / "campaigns" / "active_agent_probe" / "campaign_summary.json").exists()


def _write_cli_fixture(
    tmp_path: Path,
    *,
    include_missing_case: bool = True,
) -> tuple[Path, Path]:
    suite_path = tmp_path / "suite.yaml"
    subjects_path = tmp_path / "subjects.yaml"
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
    (run_dir / "operator_response.txt").write_text("Covered by policy.", encoding="utf-8")
    missing_case = (
        """
  - case_id: missing
    question: Missing?
    intent_type: guidance
    expected_resolution: refuse_no_evidence
    risk_class: low
    capability_path: retrieval_only
    expected:
      outcome: REFUSED_NO_EVIDENCE
"""
        if include_missing_case
        else ""
    )
    suite_path.write_text(
        f"""
suite_id: insurance_qa_smoke
version: "2026-06-07"
name: Insurance QA Smoke
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
{missing_case.rstrip()}
""".lstrip(),
        encoding="utf-8",
    )
    subjects_path.write_text(
        """
manifest_id: local_subjects
version: "2026-06-07"
suite_id: insurance_qa_smoke
subjects:
  - case_ref:
      case_id: supported
    artifacts:
      trace_ref: runs/history/run_supported/trace.jsonl
      receipt_ref: runs/history/run_supported/governance_receipt.md
    projections:
      evaluated_response:
        audience: operator
        ref: runs/history/run_supported/operator_response.txt
""".lstrip(),
        encoding="utf-8",
    )
    return suite_path, subjects_path


def _write_campaign_cli_fixture(tmp_path: Path) -> Path:
    suite_path = tmp_path / "campaign_suite.yaml"
    subjects_path = tmp_path / "campaign_subjects.yaml"
    campaign_path = tmp_path / "campaign.yaml"
    run_dir = tmp_path / "runs" / "history" / "run_campaign_supported"
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
suite_id: campaign_smoke
version: "2026-06-21"
name: Campaign Smoke
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
manifest_id: campaign_subjects
version: "2026-06-21"
suite_id: campaign_smoke
subjects:
  - case_ref:
      case_id: supported
    artifacts:
      trace_ref: runs/history/run_campaign_supported/trace.jsonl
      trace_sha256: {_file_sha256(trace_path)}
      receipt_ref: runs/history/run_campaign_supported/governance_receipt.md
      receipt_sha256: {_file_sha256(receipt_path)}
    projections:
      evaluated_response:
        audience: operator
        ref: runs/history/run_campaign_supported/operator_response.txt
        sha256: {_file_sha256(response_path)}
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
      suite_ref: campaign_suite.yaml
      subjects_ref: campaign_subjects.yaml
thresholds:
  governed_resolution_rate_min: 0.95
  artifact_sufficiency_required: 1.0
  deterministic_gate_pass_required: 1.0
""".lstrip(),
        encoding="utf-8",
    )
    return campaign_path


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
