import json
import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from proof_agent.observability.api.operator_identity import (
    OperatorIdentityContext,
    OperatorPermission,
)
from proof_agent.observability.api.app import create_app


class _StaticOperatorIdentityProvider:
    def __init__(self, permissions: set[OperatorPermission]) -> None:
        self._permissions = permissions

    def current_identity(self) -> OperatorIdentityContext:
        return OperatorIdentityContext(
            operator_id="test-operator",
            display_name="Test Operator",
            permissions=frozenset(self._permissions),
        )


def _client_with_operator_permissions(
    tmp_path: Path,
    *,
    curation_dir: Path,
    permissions: set[OperatorPermission],
) -> TestClient:
    app = create_app(
        history_dir=tmp_path / "runs" / "history",
        evaluation_curation_dir=curation_dir,
    )
    app.state.operator_identity_provider = _StaticOperatorIdentityProvider(permissions)
    return TestClient(app)


def test_dashboard_api_lists_production_sample_curation_candidates(
    tmp_path: Path,
) -> None:
    curation_dir = tmp_path / "runs" / "evaluation_curation"
    batch_dir = curation_dir / "prod_edge_cases"
    batch_dir.mkdir(parents=True)
    (batch_dir / "production_sample_candidates.jsonl").write_text(
        json.dumps(
            {
                "sample_id": "prod_supported",
                "source_run_id": "run_prod_supported",
                "curation_status": "diagnostic_only",
                "formal_scoring_allowed": False,
                "run_purpose": "production",
                "safe_summary": {
                    "question_sha256": "question-hash",
                    "question_text_length": 42,
                    "response_text_sha256": "response-hash",
                    "response_text_length": 28,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    app = create_app(
        history_dir=tmp_path / "runs" / "history",
        evaluation_curation_dir=curation_dir,
    )
    client = TestClient(app)

    response = client.get("/api/evaluation/production-samples/candidates")

    assert response.status_code == 200
    assert response.json()["meta"] == {"total": 1}
    assert response.json()["data"][0]["batch_id"] == "prod_edge_cases"
    assert response.json()["data"][0]["sample_id"] == "prod_supported"
    assert response.json()["data"][0]["curation_status"] == "diagnostic_only"
    assert response.json()["data"][0]["safe_summary"]["question_text_length"] == 42


def test_dashboard_api_lists_promoted_production_sample_records(
    tmp_path: Path,
) -> None:
    curation_dir = tmp_path / "runs" / "evaluation_curation"
    promotion_dir = curation_dir / "promoted" / "prod_supported"
    promotion_dir.mkdir(parents=True)
    (promotion_dir / "production_sample_promotion.json").write_text(
        json.dumps(
            {
                "sample_id": "prod_supported",
                "status": "promoted",
                "source_run_id": "run_prod_supported",
                "suite_path": "evaluation_suite.yaml",
                "subject_manifest_path": "evaluation_subjects.yaml",
                "domain_review": {
                    "reviewer": "domain-reviewer",
                    "confirmed": True,
                },
                "harness_review": {
                    "reviewer": "harness-reviewer",
                    "confirmed": True,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    app = create_app(
        history_dir=tmp_path / "runs" / "history",
        evaluation_curation_dir=curation_dir,
    )
    client = TestClient(app)

    response = client.get("/api/evaluation/production-samples/promotions")

    assert response.status_code == 200
    assert response.json()["meta"] == {"total": 1}
    assert response.json()["data"][0]["sample_id"] == "prod_supported"
    assert response.json()["data"][0]["status"] == "promoted"
    assert response.json()["data"][0]["promotion_dir"] == str(promotion_dir)
    assert response.json()["data"][0]["domain_review"]["reviewer"] == "domain-reviewer"


def test_dashboard_api_promotes_production_sample_with_reviewer_permission(
    tmp_path: Path,
) -> None:
    curation_dir = tmp_path / "runs" / "evaluation_curation"
    batch_dir = curation_dir / "prod_edge_cases"
    batch_dir.mkdir(parents=True)
    _write_candidate_artifacts(batch_dir)
    client = _client_with_operator_permissions(
        tmp_path,
        curation_dir=curation_dir,
        permissions={OperatorPermission.EVALUATION_CURATION_REVIEW},
    )

    response = client.post(
        "/api/evaluation/production-samples/promotions",
        json={
            "batch_id": "prod_edge_cases",
            "sample_id": "prod_supported",
            "suite_id": "production_edge_cases",
            "suite_version": "2026-06-23",
            "manifest_id": "production_edge_subjects",
            "case": {
                "case_id": "prod_supported_case",
                "question": "Redacted production policy support scenario.",
                "intent_type": "guidance",
                "expected_resolution": "answer_with_citations",
                "risk_class": "customer_service_fact",
                "capability_path": "evidence_answer",
                "expected_outcome": "ANSWERED_WITH_CITATIONS",
                "required_citation_refs": ["policy"],
            },
            "domain_review": {
                "reviewer": "domain-reviewer",
                "confirmed": True,
            },
            "harness_review": {
                "reviewer": "harness-reviewer",
                "confirmed": True,
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["sample_id"] == "prod_supported"
    assert body["status"] == "promoted"
    assert body["promotion_record_path"].endswith(
        "promoted/prod_supported/production_sample_promotion.json"
    )
    promotion_record = json.loads(
        (curation_dir / "promoted" / "prod_supported" / "production_sample_promotion.json")
        .read_text(encoding="utf-8")
    )
    assert promotion_record["domain_review"]["reviewer"] == "domain-reviewer"
    assert promotion_record["harness_review"]["reviewer"] == "harness-reviewer"
    promotion_audit = json.loads(
        (curation_dir / "promoted" / "prod_supported" / "production_sample_promotion_audit.json")
        .read_text(encoding="utf-8")
    )
    assert promotion_audit["operation"] == "promoted"
    assert promotion_audit["actor"] == "test-operator"
    assert promotion_audit["permission"] == "evaluation_curation.review"


def test_dashboard_api_production_sample_promotion_requires_reviewer_permission(
    tmp_path: Path,
) -> None:
    curation_dir = tmp_path / "runs" / "evaluation_curation"
    batch_dir = curation_dir / "prod_edge_cases"
    batch_dir.mkdir(parents=True)
    _write_candidate_artifacts(batch_dir)
    client = _client_with_operator_permissions(
        tmp_path,
        curation_dir=curation_dir,
        permissions=set(),
    )

    response = client.post(
        "/api/evaluation/production-samples/promotions",
        json={
            "batch_id": "prod_edge_cases",
            "sample_id": "prod_supported",
            "suite_id": "production_edge_cases",
            "suite_version": "2026-06-23",
            "manifest_id": "production_edge_subjects",
            "case": {
                "case_id": "prod_supported_case",
                "question": "Redacted production policy support scenario.",
                "intent_type": "guidance",
                "expected_resolution": "answer_with_citations",
                "risk_class": "customer_service_fact",
                "capability_path": "evidence_answer",
                "expected_outcome": "ANSWERED_WITH_CITATIONS",
            },
            "domain_review": {
                "reviewer": "domain-reviewer",
                "confirmed": True,
            },
            "harness_review": {
                "reviewer": "harness-reviewer",
                "confirmed": True,
            },
        },
    )

    assert response.status_code == 403
    assert (
        response.json()["detail"]
        == "Operator lacks required permission: evaluation_curation.review"
    )
    assert not (curation_dir / "promoted" / "prod_supported").exists()


def _write_candidate_artifacts(batch_dir: Path) -> None:
    run_dir = batch_dir / "artifacts" / "run_prod_supported"
    run_dir.mkdir(parents=True)
    trace_path = run_dir / "trace.jsonl"
    receipt_path = run_dir / "governance_receipt.md"
    run_meta_path = run_dir / "run_meta.json"
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
    run_meta_path.write_text(
        json.dumps(
            {
                "run_id": "run_prod_supported",
                "run_purpose": "production",
                "question": "redacted",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    response_path.write_text("Covered by policy with production wording.", encoding="utf-8")
    (batch_dir / "production_sample_candidates.jsonl").write_text(
        json.dumps(
            {
                "sample_id": "prod_supported",
                "source_run_id": "run_prod_supported",
                "curation_status": "diagnostic_only",
                "formal_scoring_allowed": False,
                "run_purpose": "production",
                "artifacts": {
                    "trace_ref": _relative_ref(trace_path, batch_dir),
                    "trace_sha256": _sha256(trace_path),
                    "receipt_ref": _relative_ref(receipt_path, batch_dir),
                    "receipt_sha256": _sha256(receipt_path),
                    "run_meta_ref": _relative_ref(run_meta_path, batch_dir),
                    "run_meta_sha256": _sha256(run_meta_path),
                    "response_projection_ref": _relative_ref(response_path, batch_dir),
                    "response_projection_audience": "operator",
                    "response_projection_sha256": _sha256(response_path),
                },
                "execution_surface": "run_execution_api_conversation",
                "safe_summary": {
                    "question_sha256": "question-hash",
                    "question_text_length": 42,
                    "response_text_sha256": "response-hash",
                    "response_text_length": 28,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _relative_ref(path: Path, base_dir: Path) -> str:
    return str(path.relative_to(base_dir))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
