from pathlib import Path

from fastapi.testclient import TestClient

from proof_agent.observability.api.app import create_app


def test_customer_run_returns_customer_safe_projection(tmp_path: Path) -> None:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
    )
    client = TestClient(app)

    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_customer_service", "customer_id": "CUST-001"},
    )
    assert created.status_code == 200
    conversation_id = created.json()["conversation_id"]

    response = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "What documents are required for inpatient claim reimbursement?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "message" in body
    assert "safe_sources" in body
    assert "links" not in body
    assert "governance_details" not in body
    assert "approval_state" not in body


def test_customer_conversation_rejects_unknown_agent(tmp_path: Path) -> None:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
    )
    client = TestClient(app)

    response = client.post(
        "/api/customer/conversations",
        json={"agent_id": "unknown", "customer_id": "CUST-001"},
    )

    assert response.status_code == 404
