from pathlib import Path
import shutil

from fastapi.testclient import TestClient
import pytest
import yaml

from proof_agent.contracts import EnvironmentModelCredentialReference
from proof_agent.configuration.importer import import_agent_package
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.observability.api.app import create_app


def _client(
    tmp_path: Path, *, published_agents: dict[str, Path] | None = None
) -> TestClient:
    store = LocalAgentConfigurationStore(tmp_path / "config")
    if published_agents is None:
        published_agents = {
            "enterprise_qa": Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml"),
        }
    for manifest_path in published_agents.values():
        draft = import_agent_package(manifest_path, store=store, actor="test-user")
        store.publish_version(
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
        agent_configuration_store=store,
    )
    return TestClient(app)


def _copy_react_agent_with_response_details(tmp_path: Path) -> Path:
    agent_dir = tmp_path / "react_enterprise_qa"
    shutil.copytree(Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa"), agent_dir)
    manifest_path = agent_dir / "agent.yaml"
    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest_path.write_text(
        manifest_text.replace(
            "  include_reasoning_summary: false\n  include_review_results: false",
            "  include_reasoning_summary: true\n  include_review_results: true",
        ),
        encoding="utf-8",
    )
    return manifest_path


def _client_with_shared_model_published_agent(tmp_path: Path) -> TestClient:
    agent_dir = tmp_path / "enterprise_qa_shared_model"
    shutil.copytree(Path("proof_agent/evaluation/demo/fixtures/enterprise_qa"), agent_dir)
    manifest_path = agent_dir / "agent.yaml"
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    raw["model"] = {
        "model_source": "shared",
        "connection_id": "model_demo_shared",
        "params": {"temperature": 0},
    }
    manifest_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    store = LocalAgentConfigurationStore(tmp_path / "config")
    store.create_model_connection(
        connection_id="model_demo_shared",
        display_name="Demo Shared",
        provider="deterministic",
        model_identifier="demo",
        credential_ref=EnvironmentModelCredentialReference(name="DEMO_MODEL_KEY"),
        actor="operator",
    )
    draft = import_agent_package(manifest_path, store=store, actor="test-user")
    store.publish_version(
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
        agent_configuration_store=store,
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


def test_conversation_run_resolves_shared_model_connection_from_configuration_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEMO_MODEL_KEY", "test-key")
    client = _client_with_shared_model_published_agent(tmp_path)
    created = client.post("/api/chat/conversations", json={"agent_id": "enterprise_qa"})
    assert created.status_code == 200
    conversation_id = created.json()["conversation_id"]

    response = client.post(
        f"/api/chat/conversations/{conversation_id}/runs",
        json={"question": "What is the reimbursement rule for travel meals?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["agent_id"] == "enterprise_qa"
    assert body["outcome"] == "ANSWERED_WITH_CITATIONS"


def test_conversation_run_omits_governance_details_by_default(tmp_path: Path) -> None:
    manifest_path = _copy_react_agent_with_response_details(tmp_path)
    client = _client(tmp_path, published_agents={"react_enterprise_qa": manifest_path})
    created = client.post("/api/chat/conversations", json={"agent_id": "react_enterprise_qa"})
    assert created.status_code == 200
    conversation_id = created.json()["conversation_id"]

    response = client.post(
        f"/api/chat/conversations/{conversation_id}/runs",
        json={"question": "What is the reimbursement rule for travel meals?"},
    )

    assert response.status_code == 200
    assert "governance_details" not in response.json()

    timeline = client.get(f"/api/chat/conversations/{conversation_id}").json()
    assert "governance_details" not in timeline["turns"][0]


def test_conversation_run_returns_and_stores_governance_details_when_policy_allows(
    tmp_path: Path,
) -> None:
    manifest_path = _copy_react_agent_with_response_details(tmp_path)
    client = _client(tmp_path, published_agents={"react_enterprise_qa": manifest_path})
    created = client.post("/api/chat/conversations", json={"agent_id": "react_enterprise_qa"})
    assert created.status_code == 200
    conversation_id = created.json()["conversation_id"]

    response = client.post(
        f"/api/chat/conversations/{conversation_id}/runs",
        json={
            "question": "What is the reimbursement rule for travel meals?",
            "include_governance_details": True,
        },
    )

    assert response.status_code == 200
    details = response.json()["governance_details"]
    assert details["reasoning_summary"]
    assert details["review_results"]

    timeline = client.get(f"/api/chat/conversations/{conversation_id}").json()
    stored_details = timeline["turns"][0]["governance_details"]
    assert stored_details == details


def test_conversation_run_rejects_wrong_agent_id(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post("/api/chat/conversations", json={"agent_id": "unknown"})

    assert response.status_code == 404


def test_list_conversations_empty_when_none_exist(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/api/chat/conversations")

    assert response.status_code == 200
    assert response.json() == []


def test_list_conversations_returns_sorted_by_updated_at(tmp_path: Path) -> None:
    client = _client(tmp_path)

    a = client.post("/api/chat/conversations", json={"agent_id": "enterprise_qa"})
    assert a.status_code == 200
    a_id = a.json()["conversation_id"]

    b = client.post("/api/chat/conversations", json={"agent_id": "enterprise_qa"})
    assert b.status_code == 200
    b_id = b.json()["conversation_id"]

    # Add a turn to each conversation so they appear in listings
    client.post(
        f"/api/chat/conversations/{b_id}/runs",
        json={"question": "First question B?"},
    )
    # Add a turn to A so it becomes the most recently updated
    client.post(
        f"/api/chat/conversations/{a_id}/runs",
        json={"question": "First question A?"},
    )

    response = client.get("/api/chat/conversations")
    assert response.status_code == 200
    data = response.json()

    assert len(data) == 2
    assert data[0]["conversation_id"] == a_id  # A was updated most recently
    assert data[1]["conversation_id"] == b_id


def test_rename_conversation(tmp_path: Path) -> None:
    client = _client(tmp_path)
    created = client.post("/api/chat/conversations", json={"agent_id": "enterprise_qa"})
    assert created.status_code == 200
    conversation_id = created.json()["conversation_id"]

    response = client.patch(
        f"/api/chat/conversations/{conversation_id}",
        json={"title": "Travel Policy Q&A"},
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Travel Policy Q&A"


def test_rename_conversation_empty_string_clears_title(tmp_path: Path) -> None:
    client = _client(tmp_path)
    created = client.post("/api/chat/conversations", json={"agent_id": "enterprise_qa"})
    assert created.status_code == 200
    conversation_id = created.json()["conversation_id"]

    # Set a title first
    client.patch(
        f"/api/chat/conversations/{conversation_id}",
        json={"title": "Some Title"},
    )
    # Clear it with an empty string
    response = client.patch(
        f"/api/chat/conversations/{conversation_id}",
        json={"title": ""},
    )
    assert response.status_code == 200
    assert response.json()["title"] is None


def test_pin_conversation(tmp_path: Path) -> None:
    client = _client(tmp_path)
    a = client.post("/api/chat/conversations", json={"agent_id": "enterprise_qa"})
    assert a.status_code == 200
    a_id = a.json()["conversation_id"]

    b = client.post("/api/chat/conversations", json={"agent_id": "enterprise_qa"})
    assert b.status_code == 200
    b_id = b.json()["conversation_id"]

    # Add turns so conversations appear in listings
    client.post(f"/api/chat/conversations/{a_id}/runs", json={"question": "Q A?"})
    client.post(f"/api/chat/conversations/{b_id}/runs", json={"question": "Q B?"})

    # Pin B — it should now sort to the top
    client.patch(f"/api/chat/conversations/{b_id}", json={"pinned": True})

    response = client.get("/api/chat/conversations")
    assert response.status_code == 200
    data = response.json()
    assert data[0]["conversation_id"] == b_id  # B is pinned, sorts first
    assert data[0]["pinned"] is True
    assert data[1]["conversation_id"] == a_id


def test_unpin_conversation(tmp_path: Path) -> None:
    client = _client(tmp_path)
    a = client.post("/api/chat/conversations", json={"agent_id": "enterprise_qa"})
    assert a.status_code == 200
    a_id = a.json()["conversation_id"]

    b = client.post("/api/chat/conversations", json={"agent_id": "enterprise_qa"})
    assert b.status_code == 200
    b_id = b.json()["conversation_id"]

    # Add turns so conversations appear in listings
    client.post(f"/api/chat/conversations/{a_id}/runs", json={"question": "Q A?"})
    client.post(f"/api/chat/conversations/{b_id}/runs", json={"question": "Q B?"})

    # Pin A then unpin it
    client.patch(f"/api/chat/conversations/{a_id}", json={"pinned": True})
    client.patch(f"/api/chat/conversations/{a_id}", json={"pinned": False})

    response = client.get("/api/chat/conversations")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    # Both are unpinned; A was updated most recently (by the unpin)
    assert data[0]["pinned"] is False
    assert data[1]["pinned"] is False
    assert data[0]["conversation_id"] == a_id
    assert data[1]["conversation_id"] == b_id


def test_delete_conversation(tmp_path: Path) -> None:
    client = _client(tmp_path)
    created = client.post("/api/chat/conversations", json={"agent_id": "enterprise_qa"})
    assert created.status_code == 200
    conversation_id = created.json()["conversation_id"]

    response = client.delete(f"/api/chat/conversations/{conversation_id}")
    assert response.status_code == 204

    # Verify it's gone
    get_response = client.get(f"/api/chat/conversations/{conversation_id}")
    assert get_response.status_code == 404


def test_delete_nonexistent_conversation(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.delete("/api/chat/conversations/conv_nonexistent")
    assert response.status_code == 404


def test_patch_nonexistent_conversation(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.patch(
        "/api/chat/conversations/conv_nonexistent",
        json={"title": "Nope"},
    )
    assert response.status_code == 404
