"""Tests for resolving Published Agent Versions into governed execution."""

from pathlib import Path

from fastapi.testclient import TestClient

from proof_agent.configuration.importer import import_agent_package
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.delivery.published_agents import PublishedAgentRegistry
from proof_agent.observability.api.app import create_app


def _publish_package(
    tmp_path: Path,
    manifest_path: Path,
) -> tuple[LocalAgentConfigurationStore, str, str]:
    store = LocalAgentConfigurationStore(tmp_path / "config")
    draft = import_agent_package(manifest_path, store=store, actor="test-user")
    version = store.publish_version(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        validation_run_id="run_validation",
        actor="test-user",
    )
    return store, draft.agent_id, version.version_id


def test_registry_still_resolves_default_example_agents() -> None:
    registry = PublishedAgentRegistry()

    resolved = registry.resolve("enterprise_qa")

    assert resolved is not None
    assert resolved.agent_id == "enterprise_qa"
    assert resolved.manifest_path == Path("examples/enterprise_qa/agent.yaml")
    assert resolved.agent_version_id is None
    assert "enterprise_qa" in registry.list_agent_ids()


def test_registry_resolves_active_agent_version_from_configuration_store(
    tmp_path: Path,
) -> None:
    store, agent_id, version_id = _publish_package(
        tmp_path,
        Path("examples/enterprise_qa/agent.yaml"),
    )
    registry = PublishedAgentRegistry(agents={}, configuration_store=store)

    resolved = registry.resolve(agent_id)

    assert resolved is not None
    assert resolved.agent_id == agent_id
    assert resolved.agent_version_id == version_id
    assert resolved.manifest_path == (
        store.root_dir / "agents" / agent_id / "versions" / version_id / "agent.yaml"
    )
    assert registry.list_agent_ids() == (agent_id,)


def test_chat_production_run_records_resolved_agent_version_id(tmp_path: Path) -> None:
    store, agent_id, version_id = _publish_package(
        tmp_path,
        Path("examples/enterprise_qa/agent.yaml"),
    )
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        published_agents={},
        agent_configuration_store=store,
    )
    client = TestClient(app)

    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": agent_id,
            "question": "What is the reimbursement rule for travel meals?",
        },
    )

    assert response.status_code == 200
    run_id = response.json()["run_id"]
    detail = client.get(f"/api/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["run_purpose"] == "production"
    assert detail.json()["agent_id"] == agent_id
    assert detail.json()["agent_version_id"] == version_id


def test_customer_production_run_records_resolved_agent_version_id(tmp_path: Path) -> None:
    store, agent_id, version_id = _publish_package(
        tmp_path,
        Path("examples/insurance_customer_service/agent.yaml"),
    )
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
        published_agents={},
        agent_configuration_store=store,
    )
    client = TestClient(app)
    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": agent_id, "customer_id": "CUST-001"},
    )
    conversation_id = created.json()["conversation_id"]

    response = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "What documents are required for inpatient claim reimbursement?"},
    )

    assert response.status_code == 200
    run_id = response.json()["run_id"]
    detail = client.get(f"/api/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["agent_id"] == agent_id
    assert detail.json()["agent_version_id"] == version_id


def test_execution_api_still_rejects_arbitrary_manifest_paths(tmp_path: Path) -> None:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        published_agents={"enterprise_qa": Path("examples/enterprise_qa/agent.yaml")},
    )
    client = TestClient(app)

    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": "enterprise_qa",
            "agent_yaml": "examples/enterprise_qa/agent.yaml",
            "question": "What is the reimbursement rule for travel meals?",
        },
    )

    assert response.status_code == 422
