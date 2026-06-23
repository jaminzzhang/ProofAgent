import json
from pathlib import Path

from fastapi.testclient import TestClient

from proof_agent.observability.api.app import create_app


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
