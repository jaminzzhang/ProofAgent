from fastapi.testclient import TestClient

from proof_agent.observability.api.app import create_app
from proof_agent.observability.storage.handoff_projection import extract_handoffs


def test_extract_handoff_projection_from_trace_events() -> None:
    events = [
        {
            "event_type": "customer_handoff_created",
            "timestamp": "2026-05-20T00:00:00Z",
            "run_id": "run_123",
            "payload": {
                "reason": "insufficient_evidence",
                "question_summary": "Can you guarantee payment?",
                "customer_ref": "CUST-001",
            },
        }
    ]

    handoffs = extract_handoffs(events)

    assert len(handoffs) == 1
    assert handoffs[0].run_id == "run_123"
    assert handoffs[0].reason.value == "insufficient_evidence"


def test_extract_handoffs_ignores_non_handoff_events() -> None:
    handoffs = extract_handoffs(
        [
            {
                "event_type": "final_output",
                "timestamp": "2026-05-20T00:00:00Z",
                "run_id": "run_123",
                "payload": {"answer": "done"},
            }
        ]
    )

    assert handoffs == ()


def test_handoff_api_lists_handoffs(tmp_path) -> None:
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
    client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "Cancel my policy now."},
    )

    response = client.get("/api/handoffs")

    assert response.status_code == 200
    assert response.json()["data"]
