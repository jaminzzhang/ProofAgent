from pathlib import Path
from typing import Any

import yaml
from fastapi.testclient import TestClient

from proof_agent.observability.api.app import create_app


def test_customer_journey_acceptance_suite(tmp_path: Path) -> None:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
    )
    client = TestClient(app)
    raw = yaml.safe_load(
        Path("examples/insurance_customer_service/journeys.yaml").read_text(encoding="utf-8")
    )

    for journey in raw["journeys"]:
        created = client.post(
            "/api/customer/conversations",
            json={
                "agent_id": "insurance_customer_service",
                "customer_id": journey.get("customer_id"),
            },
        )
        assert created.status_code == 200, journey["id"]
        conversation_id = created.json()["conversation_id"]

        response = client.post(
            f"/api/customer/conversations/{conversation_id}/runs",
            json={"question": journey["question"]},
        )

        assert response.status_code == 200, journey["id"]
        body = response.json()
        _assert_customer_safe(body, journey["id"])
        _assert_expected(client, body, journey)


def _assert_customer_safe(body: dict[str, Any], journey_id: str) -> None:
    assert "message" in body, journey_id
    assert "links" not in body, journey_id
    assert "governance_details" not in body, journey_id
    assert "approval_state" not in body, journey_id
    assert "safe_sources" in body, journey_id


def _assert_expected(
    client: TestClient,
    body: dict[str, Any],
    journey: dict[str, Any],
) -> None:
    expected = journey["expected"]
    journey_id = journey["id"]
    if expected.get("requires_authentication"):
        message = str(body["message"]).lower()
        assert "sign in" in message or "authenticate" in message, journey_id
    if expected.get("has_safe_sources"):
        assert body["safe_sources"], journey_id
    if expected.get("tool"):
        assert expected["tool"] in body["safe_sources"], journey_id
    if expected.get("handoff_reason"):
        response = client.get("/api/handoffs")
        assert response.status_code == 200, journey_id
        reasons = [item["reason"] for item in response.json()["data"]]
        assert expected["handoff_reason"] in reasons, journey_id
