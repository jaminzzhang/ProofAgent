from pathlib import Path

from fastapi.testclient import TestClient

from proof_agent.observability.api.app import create_app


def _client(tmp_path: Path) -> TestClient:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
        published_agents={
            "enterprise_qa": Path("examples/enterprise_qa/agent.yaml"),
        },
    )
    return TestClient(app)


def test_conversation_run_admits_prior_turn_context(tmp_path: Path) -> None:
    client = _client(tmp_path)
    created = client.post("/api/chat/conversations", json={"agent_id": "enterprise_qa"})
    assert created.status_code == 200
    conversation_id = created.json()["conversation_id"]

    first = client.post(
        f"/api/chat/conversations/{conversation_id}/runs",
        json={"question": "What is the reimbursement rule for travel meals?"},
    )
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["context_admission"]["admitted"] is False
    assert first_body["context_admission"]["turn_count"] == 0

    second = client.post(
        f"/api/chat/conversations/{conversation_id}/runs",
        json={"question": "What about travel meals again?"},
    )
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["conversation_id"] == conversation_id
    assert second_body["context_admission"]["admitted"] is True
    assert second_body["context_admission"]["turn_count"] == 1
    assert second_body["context_admission"]["included_turn_ids"] == [first_body["turn_id"]]
    assert "prior turn" in second_body["context_admission"]["summary"]

    trace = client.get(second_body["links"]["trace"]).json()["events"]
    context_event = next(event for event in trace if event["event_type"] == "context_admission")
    assert context_event["payload"]["admitted"] is True
    assert context_event["payload"]["turn_count"] == 1

    conversation = client.get(f"/api/chat/conversations/{conversation_id}")
    assert conversation.status_code == 200
    timeline = conversation.json()
    assert len(timeline["turns"]) == 2
    assert timeline["turns"][0]["run_id"] == first_body["run_id"]
    assert timeline["turns"][1]["run_id"] == second_body["run_id"]


def test_conversation_run_rejects_wrong_agent_id(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post("/api/chat/conversations", json={"agent_id": "unknown"})

    assert response.status_code == 404
