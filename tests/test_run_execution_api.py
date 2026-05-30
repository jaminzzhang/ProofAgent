from pathlib import Path
import shutil

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from proof_agent.configuration.importer import import_agent_package
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.observability.api.app import create_app
from proof_agent.runtime import langgraph_runner


def _app_with_published_agent(tmp_path: Path, manifest_path: Path):
    store = LocalAgentConfigurationStore(tmp_path / "config")
    draft = import_agent_package(manifest_path, store=store, actor="test-user")
    store.publish_version(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        validation_run_id="run_validation",
        actor="test-user",
    )
    return create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        published_agents={},
        agent_configuration_store=store,
    )


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


def test_chat_run_execution_starts_published_agent_and_persists_run(tmp_path: Path) -> None:
    app = _app_with_published_agent(tmp_path, Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml"))
    client = TestClient(app)

    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": "enterprise_qa",
            "question": "What is the reimbursement rule for travel meals?",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["agent_id"] == "enterprise_qa"
    assert body["run_id"].startswith("run_")
    assert body["outcome"] == "ANSWERED_WITH_CITATIONS"
    assert "Travel meals are reimbursed" in body["final_output"]
    assert body["links"]["run_detail"] == f"/api/runs/{body['run_id']}"
    assert body["links"]["trace"] == f"/api/runs/{body['run_id']}/trace"
    assert body["links"]["receipt"] == f"/api/runs/{body['run_id']}/receipt"
    assert body["evidence"]

    detail = client.get(f"/api/runs/{body['run_id']}")
    assert detail.status_code == 200
    assert detail.json()["question"] == "What is the reimbursement rule for travel meals?"


def test_chat_run_execution_rejects_unknown_agent_id(tmp_path: Path) -> None:
    app = _app_with_published_agent(tmp_path, Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml"))
    client = TestClient(app)

    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": "unknown",
            "question": "What is the reimbursement rule for travel meals?",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"]["available_agent_ids"] == ["enterprise_qa"]


def test_chat_run_execution_rejects_arbitrary_manifest_path(tmp_path: Path) -> None:
    app = _app_with_published_agent(tmp_path, Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml"))
    client = TestClient(app)

    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": "enterprise_qa",
            "agent_yaml": "proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml",
            "question": "What is the reimbursement rule for travel meals?",
        },
    )

    assert response.status_code == 422


def test_chat_run_execution_registers_react_enterprise_qa(
    tmp_path: Path,
) -> None:
    app = _app_with_published_agent(tmp_path, Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa/agent.yaml"))
    client = TestClient(app)

    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": "react_enterprise_qa",
            "question": "What is the reimbursement rule for travel meals?",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["agent_id"] == "react_enterprise_qa"
    assert body["outcome"] == "ANSWERED_WITH_CITATIONS"


def test_chat_run_omits_governance_details_by_default(tmp_path: Path) -> None:
    app = _app_with_published_agent(tmp_path, Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa/agent.yaml"))
    client = TestClient(app)

    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": "react_enterprise_qa",
            "question": "What is the reimbursement rule for travel meals?",
        },
    )

    assert response.status_code == 200
    assert "governance_details" not in response.json()


def test_chat_run_omits_governance_details_when_agent_policy_denies(
    tmp_path: Path,
) -> None:
    app = _app_with_published_agent(tmp_path, Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa/agent.yaml"))
    client = TestClient(app)

    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": "react_enterprise_qa",
            "question": "What is the reimbursement rule for travel meals?",
            "include_governance_details": True,
        },
    )

    assert response.status_code == 200
    assert "governance_details" not in response.json()


def test_chat_run_returns_governance_details_when_agent_policy_allows(
    tmp_path: Path,
) -> None:
    manifest_path = _copy_react_agent_with_response_details(tmp_path)
    app = _app_with_published_agent(tmp_path, manifest_path)
    client = TestClient(app)

    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": "react_enterprise_qa",
            "question": "What is the reimbursement rule for travel meals?",
            "include_governance_details": True,
        },
    )

    assert response.status_code == 200
    details = response.json()["governance_details"]
    assert details["reasoning_summary"]
    assert details["review_results"]


def test_chat_run_executes_with_same_manifest_used_for_projection(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    manifest_path = _copy_react_agent_with_response_details(tmp_path)
    app = _app_with_published_agent(tmp_path, manifest_path)
    client = TestClient(app)

    def fail_on_runtime_reload(path: Path | str) -> None:
        raise AssertionError(f"runtime reloaded manifest: {path}")

    monkeypatch.setattr(langgraph_runner, "load_agent_manifest", fail_on_runtime_reload)

    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": "react_enterprise_qa",
            "question": "What is the reimbursement rule for travel meals?",
            "include_governance_details": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["governance_details"]["reasoning_summary"]


def test_chat_run_execution_returns_approval_state_for_tool_question(tmp_path: Path) -> None:
    app = _app_with_published_agent(tmp_path, Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml"))
    client = TestClient(app)

    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": "enterprise_qa",
            "question": "Look up customer policy status before answering.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "WAITING_FOR_APPROVAL"
    assert body["approval_state"]["state"] == "requested"
    assert body["approval_state"]["tool_name"] == "customer_lookup"
