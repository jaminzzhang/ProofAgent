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


def test_anonymous_customer_policy_status_requires_authentication(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            history_dir=tmp_path / "history",
            runs_dir=tmp_path / "latest",
            conversations_dir=tmp_path / "conversations",
        )
    )
    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_customer_service"},
    )
    conversation_id = created.json()["conversation_id"]

    response = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "What is my policy status?"},
    )

    assert response.status_code == 200
    message = response.json()["message"].lower()
    assert "sign in" in message or "authenticate" in message


def test_authenticated_customer_policy_status_uses_authorized_read_tool(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_app(
            history_dir=tmp_path / "history",
            runs_dir=tmp_path / "latest",
            conversations_dir=tmp_path / "conversations",
        )
    )
    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_customer_service", "customer_id": "CUST-001"},
    )
    conversation_id = created.json()["conversation_id"]

    response = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "What is the status of policy POL-001?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "active" in body["message"].lower()
    assert "approval_state" not in body


def test_cross_customer_policy_status_does_not_execute_tool(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            history_dir=tmp_path / "history",
            runs_dir=tmp_path / "latest",
            conversations_dir=tmp_path / "conversations",
        )
    )
    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_customer_service", "customer_id": "CUST-001"},
    )
    conversation_id = created.json()["conversation_id"]

    response = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "What is the status of policy POL-002?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "POL-002" not in body["message"]
    assert "can't access" in body["message"].lower()


def test_customer_response_snapshot_is_stored(tmp_path: Path) -> None:
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
    conversation_id = created.json()["conversation_id"]
    run = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "What documents are required for inpatient claim reimbursement?"},
    ).json()

    conversation = client.get(f"/api/customer/conversations/{conversation_id}").json()

    assert conversation["turns"][0]["response_snapshot"]["message"] == run["message"]
    assert conversation["turns"][0]["run_id"] == run["run_id"]


def test_customer_feedback_is_observation_only(tmp_path: Path) -> None:
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
    conversation_id = created.json()["conversation_id"]
    run = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "What documents are required for inpatient claim reimbursement?"},
    ).json()

    feedback = client.post(
        f"/api/customer/conversations/{conversation_id}/turns/{run['turn_id']}/feedback",
        json={"rating": "down", "comment": "Need more detail."},
    )

    assert feedback.status_code == 200
    assert feedback.json()["feedback"]["applies_to_training"] is False
