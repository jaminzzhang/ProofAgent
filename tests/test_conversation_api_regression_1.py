from pathlib import Path
from unittest.mock import patch

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


def _append_turn(client: TestClient, conversation_id: str, question: str) -> None:
    response = client.post(
        f"/api/chat/conversations/{conversation_id}/runs",
        json={"question": question},
    )
    assert response.status_code == 200


def test_pin_and_unpin_preserve_existing_title(tmp_path: Path) -> None:
    client = _client(tmp_path)
    conversation_id = _create_conversation(client)

    renamed = client.patch(
        f"/api/chat/conversations/{conversation_id}",
        json={"title": "Travel Policy Q&A"},
    )
    assert renamed.status_code == 200

    pinned = client.patch(
        f"/api/chat/conversations/{conversation_id}",
        json={"pinned": True},
    )
    assert pinned.status_code == 200
    assert pinned.json()["title"] == "Travel Policy Q&A"
    assert pinned.json()["pinned"] is True

    unpinned = client.patch(
        f"/api/chat/conversations/{conversation_id}",
        json={"pinned": False},
    )
    assert unpinned.status_code == 200
    assert unpinned.json()["title"] == "Travel Policy Q&A"
    assert unpinned.json()["pinned"] is False

    reloaded = client.get(f"/api/chat/conversations/{conversation_id}")
    assert reloaded.status_code == 200
    assert reloaded.json()["title"] == "Travel Policy Q&A"
    assert reloaded.json()["pinned"] is False


def test_rename_and_clear_title_preserve_existing_pin(tmp_path: Path) -> None:
    client = _client(tmp_path)
    conversation_id = _create_conversation(client)

    pinned = client.patch(
        f"/api/chat/conversations/{conversation_id}",
        json={"pinned": True},
    )
    assert pinned.status_code == 200

    renamed = client.patch(
        f"/api/chat/conversations/{conversation_id}",
        json={"title": "Claims Review"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Claims Review"
    assert renamed.json()["pinned"] is True

    cleared_with_null = client.patch(
        f"/api/chat/conversations/{conversation_id}",
        json={"title": None},
    )
    assert cleared_with_null.status_code == 200
    assert cleared_with_null.json()["title"] is None
    assert cleared_with_null.json()["pinned"] is True

    client.patch(
        f"/api/chat/conversations/{conversation_id}",
        json={"title": "Temporary Title"},
    )
    cleared_with_empty_string = client.patch(
        f"/api/chat/conversations/{conversation_id}",
        json={"title": ""},
    )
    assert cleared_with_empty_string.status_code == 200
    assert cleared_with_empty_string.json()["title"] is None
    assert cleared_with_empty_string.json()["pinned"] is True

    reloaded = client.get(f"/api/chat/conversations/{conversation_id}")
    assert reloaded.status_code == 200
    assert reloaded.json()["title"] is None
    assert reloaded.json()["pinned"] is True


def test_explicit_null_pin_is_rejected_without_mutating_conversation(tmp_path: Path) -> None:
    client = _client(tmp_path)
    conversation_id = _create_conversation(client)
    before = client.get(f"/api/chat/conversations/{conversation_id}").json()

    response = client.patch(
        f"/api/chat/conversations/{conversation_id}",
        json={"pinned": None},
    )

    assert response.status_code == 422
    assert client.get(f"/api/chat/conversations/{conversation_id}").json() == before


def test_empty_patch_does_not_write_or_change_timestamp_or_list_order(tmp_path: Path) -> None:
    client = _client(tmp_path)
    older_id = _create_conversation(client)
    _append_turn(client, older_id, "What is the reimbursement rule for travel meals?")
    newer_id = _create_conversation(client)
    _append_turn(client, newer_id, "What evidence is required for reimbursement?")

    before = client.get(f"/api/chat/conversations/{older_id}").json()
    before_list = client.get("/api/chat/conversations").json()
    assert [record["conversation_id"] for record in before_list] == [newer_id, older_id]

    store = client.app.state.conversation_store
    with (
        patch.object(store, "update_conversation", wraps=store.update_conversation) as update_spy,
        patch.object(store, "_write", wraps=store._write) as write_spy,
    ):
        response = client.patch(f"/api/chat/conversations/{older_id}", json={})

    assert response.status_code == 200
    update_spy.assert_not_called()
    write_spy.assert_not_called()
    assert response.json() == before
    assert response.json()["updated_at"] == before["updated_at"]
    assert client.get(f"/api/chat/conversations/{older_id}").json() == before
    after_list = client.get("/api/chat/conversations").json()
    assert [record["conversation_id"] for record in after_list] == [newer_id, older_id]


def test_store_update_with_no_fields_is_a_write_free_no_op(tmp_path: Path) -> None:
    client = _client(tmp_path)
    conversation_id = _create_conversation(client)
    store = client.app.state.conversation_store
    before = store.get_conversation(conversation_id)
    assert before is not None

    with patch.object(store, "_write", wraps=store._write) as write_spy:
        updated = store.update_conversation(conversation_id)

    write_spy.assert_not_called()
    assert updated == before
