import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from proof_agent.evaluation.campaign_store import EvaluationCampaignStore
from proof_agent.evaluation.errors import EvaluationInputError
from proof_agent.observability.api.app import create_app


def test_dashboard_api_reads_evaluation_campaign_page_data(tmp_path: Path) -> None:
    campaigns_dir = tmp_path / "runs" / "evaluation_campaigns"
    _write_campaign_page_data(campaigns_dir)
    app = create_app(
        history_dir=tmp_path / "runs" / "history",
        evaluation_campaigns_dir=campaigns_dir,
    )
    client = TestClient(app)

    list_response = client.get("/api/evaluation/campaigns")
    detail_response = client.get("/api/evaluation/campaigns/active_agent_probe")

    assert list_response.status_code == 200
    assert list_response.json()["data"][0]["campaign_id"] == "active_agent_probe"
    assert list_response.json()["meta"] == {"total": 1}
    assert detail_response.status_code == 200
    assert detail_response.json()["campaign_id"] == "active_agent_probe"
    assert detail_response.json()["capability_coverage"][0]["capability_path"] == (
        "evidence_answer"
    )


def test_dashboard_api_reads_evaluation_campaign_case_rows(tmp_path: Path) -> None:
    campaigns_dir = tmp_path / "runs" / "evaluation_campaigns"
    _write_campaign_page_data(campaigns_dir)
    app = create_app(
        history_dir=tmp_path / "runs" / "history",
        evaluation_campaigns_dir=campaigns_dir,
    )
    client = TestClient(app)

    response = client.get("/api/evaluation/campaigns/active_agent_probe/cases")

    assert response.status_code == 200
    assert response.json()["campaign_id"] == "active_agent_probe"
    assert response.json()["data"][0]["case_id"] == "supported"
    assert response.json()["data"][0]["status"] == "passed"
    assert response.json()["meta"] == {"total": 1}


def test_dashboard_api_reads_evaluation_campaign_trends(tmp_path: Path) -> None:
    campaigns_dir = tmp_path / "runs" / "evaluation_campaigns"
    _write_campaign_page_data(campaigns_dir)
    app = create_app(
        history_dir=tmp_path / "runs" / "history",
        evaluation_campaigns_dir=campaigns_dir,
    )
    client = TestClient(app)

    response = client.get("/api/evaluation/campaigns/active_agent_probe/trends")

    assert response.status_code == 200
    assert response.json()["campaign_id"] == "active_agent_probe"
    assert response.json()["status"] == "comparable"
    assert response.json()["metric_deltas"]["governed_resolution_rate"] == 0.25


def test_dashboard_api_returns_404_for_missing_evaluation_campaign(tmp_path: Path) -> None:
    app = create_app(
        history_dir=tmp_path / "runs" / "history",
        evaluation_campaigns_dir=tmp_path / "runs" / "evaluation_campaigns",
    )
    client = TestClient(app)

    response = client.get("/api/evaluation/campaigns/missing_campaign")

    assert response.status_code == 404
    assert response.json()["detail"] == (
        "Evaluation Campaign artifacts not found: missing_campaign"
    )


def test_evaluation_campaign_store_rejects_parent_path_traversal(tmp_path: Path) -> None:
    campaigns_dir = tmp_path / "campaigns"
    campaigns_dir.mkdir()
    outside_page_data_dir = tmp_path / "page_data"
    outside_page_data_dir.mkdir()
    (outside_page_data_dir / "evaluation_lab_summary.json").write_text(
        json.dumps({"campaign_id": "outside"}) + "\n",
        encoding="utf-8",
    )
    store = EvaluationCampaignStore(campaigns_dir)

    with pytest.raises(EvaluationInputError):
        store.get_campaign("..")


def _write_campaign_page_data(campaigns_dir: Path) -> None:
    campaign_dir = campaigns_dir / "active_agent_probe"
    page_data_dir = campaign_dir / "page_data"
    page_data_dir.mkdir(parents=True)
    (page_data_dir / "evaluation_lab_summary.json").write_text(
        json.dumps(
            {
                "campaign_id": "active_agent_probe",
                "version": "2026-06-21",
                "target_agent_id": "insurance_customer_service",
                "target_agent_version_id": "published_v1",
                "readiness_status": "ready",
                "blocking_reasons": [],
                "governed_resolution_rate": 1.0,
                "artifact_sufficiency_rate": 1.0,
                "deterministic_gate_pass_rate": 1.0,
                "suite_runs": [],
                "capability_coverage": [
                    {
                        "capability_path": "evidence_answer",
                        "status": "passed",
                        "required_cases": 1,
                        "passed_required_cases": 1,
                        "failed_required_cases": 0,
                    }
                ],
                "artifact_dir": str(campaign_dir),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (page_data_dir / "evaluation_lab_cases.jsonl").write_text(
        json.dumps(
            {
                "analysis_id": "active_agent_smoke-active_agent_subjects",
                "suite_id": "active_agent_smoke",
                "suite_version": "2026-06-21",
                "case_id": "supported",
                "status": "passed",
                "expected_outcome": "ANSWERED_WITH_CITATIONS",
                "actual_outcome": "ANSWERED_WITH_CITATIONS",
                "artifact_sufficiency": "sufficient",
                "primary_failure_owner": None,
                "response_projection": {
                    "audience": "operator",
                    "text_length": 18,
                },
                "gate_failures": [],
                "diagnostic_findings": [],
                "diagnostic_blocker_candidate": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (page_data_dir / "evaluation_lab_trends.json").write_text(
        json.dumps(
            {
                "campaign_id": "active_agent_probe",
                "current_version": "2026-06-21",
                "baseline_campaign_id": "previous_probe",
                "baseline_version": "2026-06-20",
                "status": "comparable",
                "comparison_basis": {
                    "target_agent_id": "insurance_customer_service",
                    "current_target_agent_version_id": "published_v1",
                    "baseline_target_agent_version_id": "published_v0",
                    "suite_versions": [],
                },
                "metric_deltas": {
                    "governed_resolution_rate": 0.25,
                    "artifact_sufficiency_rate": 0.0,
                    "deterministic_gate_pass_rate": 0.0,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
