from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from proof_agent.configuration.importer import import_agent_package
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.observability.api.app import create_app


def _client(tmp_path: Path) -> TestClient:
    configuration_store = LocalAgentConfigurationStore(tmp_path / "config")
    draft = import_agent_package(
        Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml"),
        store=configuration_store,
        actor="test-user",
    )
    configuration_store.publish_version(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        validation_run_id="run_validation",
        actor="test-user",
    )
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
        published_agents={},
        agent_configuration_store=configuration_store,
    )
    return TestClient(app)


def _create_conversation(client: TestClient) -> str:
    response = client.post(
        "/api/chat/conversations",
        json={"agent_id": "enterprise_qa"},
    )
    assert response.status_code == 200
    return str(response.json()["conversation_id"])


def _append_turn(client: TestClient, conversation_id: str, question: str) -> dict[str, Any]:
    response = client.post(
        f"/api/chat/conversations/{conversation_id}/runs",
        json={"question": question},
    )
    assert response.status_code == 200
    return response.json()


def test_append_preserves_metadata_turns_and_pinned_first_order(tmp_path: Path) -> None:
    client = _client(tmp_path)
    conversation_id = _create_conversation(client)
    first_question = "What is the reimbursement rule for travel meals?"
    second_question = "What evidence is required for reimbursement?"

    first_run = _append_turn(client, conversation_id, first_question)
    patched = client.patch(
        f"/api/chat/conversations/{conversation_id}",
        json={"title": "Travel Policy Q&A", "pinned": True},
    )
    assert patched.status_code == 200
    assert (patched.json()["title"], patched.json()["pinned"]) == (
        "Travel Policy Q&A",
        True,
    )
    second_run = _append_turn(client, conversation_id, second_question)

    reloaded_response = client.get(f"/api/chat/conversations/{conversation_id}")
    assert reloaded_response.status_code == 200
    reloaded = reloaded_response.json()
    assert (reloaded["title"], reloaded["pinned"]) == ("Travel Policy Q&A", True)
    assert [turn["turn_id"] for turn in reloaded["turns"]] == [
        first_run["turn_id"],
        second_run["turn_id"],
    ]
    assert [turn["question"] for turn in reloaded["turns"]] == [
        first_question,
        second_question,
    ]
    assert [turn["final_output"] for turn in reloaded["turns"]] == [
        first_run["final_output"],
        second_run["final_output"],
    ]

    newer_unpinned_id = _create_conversation(client)
    _append_turn(
        client,
        newer_unpinned_id,
        "What documents are required for inpatient claim reimbursement?",
    )

    listed_response = client.get("/api/chat/conversations")
    assert listed_response.status_code == 200
    listed = listed_response.json()
    assert [record["conversation_id"] for record in listed] == [
        conversation_id,
        newer_unpinned_id,
    ]
    assert listed[1]["updated_at"] > listed[0]["updated_at"]
    assert (listed[0]["title"], listed[0]["pinned"]) == ("Travel Policy Q&A", True)
    assert listed[0]["turns"] == reloaded["turns"]
