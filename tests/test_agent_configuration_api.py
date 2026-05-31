"""Integration tests for the Agent Configuration API."""

import base64
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
import yaml

from proof_agent.observability.api.app import create_app


def _client(tmp_path: Path) -> TestClient:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
        published_agents={},
        agent_configuration_dir=tmp_path / "config",
    )
    return TestClient(app)


def _import_enterprise_qa(client: TestClient) -> dict:
    response = client.post(
        "/api/config/agents/import",
        json={
            "manifest_path": "proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml",
            "actor": "test-user",
        },
    )
    assert response.status_code == 200
    return response.json()


def test_list_config_agents_empty(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/api/config/agents")

    assert response.status_code == 200
    assert response.json() == {"data": [], "meta": {"total": 0}}


def test_create_pageindex_knowledge_source_and_upload_document(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = _client(tmp_path)
    ingestion_calls: list[dict[str, Any]] = []

    def fake_ingest_pageindex_document(**kwargs: Any) -> dict[str, Any]:
        ingestion_calls.append(kwargs)
        return {
            "provider_document_id": "pi_travel_policy",
            "state": "ready",
            "message": "indexed",
        }

    monkeypatch.setattr(
        "proof_agent.delivery.configuration_api.ingest_pageindex_document",
        fake_ingest_pageindex_document,
    )

    created = client.post(
        "/api/config/knowledge-sources",
        json={
            "source_id": "ks_pageindex",
            "name": "PageIndex Policies",
            "provider": "pageindex",
            "params": {
                "endpoint_env": "PAGEINDEX_BASE_URL",
                "document_id": "policies",
            },
            "actor": "operator",
        },
    )
    uploaded = client.post(
        "/api/config/knowledge-sources/ks_pageindex/documents",
        json={
            "filename": "travel-policy.pdf",
            "content_type": "application/pdf",
            "content_base64": base64.b64encode(b"%PDF-1.4\nsample").decode("ascii"),
            "actor": "operator",
        },
    )
    listed = client.get("/api/config/knowledge-sources")
    documents = client.get("/api/config/knowledge-sources/ks_pageindex/documents")

    assert created.status_code == 200
    assert created.json()["source_id"] == "ks_pageindex"
    assert uploaded.status_code == 200
    assert uploaded.json()["state"] == "ready"
    assert uploaded.json()["provider_document_id"] == "pi_travel_policy"
    assert listed.json()["data"][0]["source_id"] == "ks_pageindex"
    assert listed.json()["data"][0]["document_count"] == 1
    assert listed.json()["data"][0]["ready_document_count"] == 1
    assert documents.json()["data"][0]["filename"] == "travel-policy.pdf"
    assert ingestion_calls[0]["source"].source_id == "ks_pageindex"
    assert ingestion_calls[0]["content"] == b"%PDF-1.4\nsample"


def test_bind_shared_knowledge_source_to_agent_draft(tmp_path: Path) -> None:
    client = _client(tmp_path)
    draft = _import_enterprise_qa(client)
    created = client.post(
        "/api/config/knowledge-sources",
        json={
            "source_id": "ks_pageindex",
            "name": "PageIndex Policies",
            "provider": "pageindex",
            "params": {
                "endpoint_env": "PAGEINDEX_BASE_URL",
                "document_id": "policies",
            },
            "actor": "operator",
        },
    )
    assert created.status_code == 200

    bound = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/knowledge-bindings",
        json={
            "source_id": "ks_pageindex",
            "alias": "policies",
            "failure_mode": "advisory",
            "fusion_weight": 0.75,
            "top_k": 3,
            "actor": "operator",
        },
    )
    loaded = client.get(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/contract"
    )

    assert bound.status_code == 200
    parsed = yaml.safe_load(bound.json()["agent_yaml"])
    assert any(
        source["source_id"] == "ks_pageindex"
        and source["provider"] == "pageindex"
        for source in parsed["knowledge_sources"]
    )
    assert any(
        binding["source_id"] == "ks_pageindex"
        and binding["alias"] == "policies"
        and binding["failure_mode"] == "advisory"
        and binding["fusion_weight"] == 0.75
        and binding["top_k"] == 3
        for binding in parsed["knowledge_bindings"]
    )
    assert loaded.json()["agent_yaml"] == bound.json()["agent_yaml"]


def test_import_agent_package_creates_draft_and_list_entry(tmp_path: Path) -> None:
    client = _client(tmp_path)

    draft = _import_enterprise_qa(client)
    listed = client.get("/api/config/agents")

    assert draft["agent_id"] == "enterprise_qa"
    assert draft["draft_id"].startswith("draft_")
    assert draft["display_name"] == "enterprise_qa"
    assert listed.status_code == 200
    assert listed.json()["data"][0]["agent_id"] == "enterprise_qa"
    assert listed.json()["data"][0]["draft_count"] == 1
    assert listed.json()["data"][0]["active_version_id"] is None


def test_read_update_draft_and_contract_view(tmp_path: Path) -> None:
    client = _client(tmp_path)
    draft = _import_enterprise_qa(client)

    updated = client.patch(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}",
        json={
            "display_name": "Enterprise QA Workspace",
            "purpose": "Answer support policy questions with governed evidence.",
            "actor": "editor",
        },
    )
    loaded = client.get(f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}")
    contract = client.get(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/contract"
    )

    assert updated.status_code == 200
    assert updated.json()["display_name"] == "Enterprise QA Workspace"
    assert loaded.status_code == 200
    assert loaded.json()["purpose"] == "Answer support policy questions with governed evidence."
    assert contract.status_code == 200
    assert contract.json()["agent_yaml"].startswith("name: enterprise_qa")
    assert contract.json()["policy_yaml"].startswith("rules:")
    assert "knowledge/customer-support-policy.md" in contract.json()["extra_files"]


def test_update_contract_view_revalidates_and_persists_agent_yaml(tmp_path: Path) -> None:
    client = _client(tmp_path)
    draft = _import_enterprise_qa(client)
    contract = client.get(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/contract"
    ).json()
    updated_yaml = contract["agent_yaml"].replace("  top_k: 2", "  top_k: 1")

    updated = client.patch(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/contract",
        json={"agent_yaml": updated_yaml, "actor": "workflow-editor"},
    )

    assert updated.status_code == 200
    assert "  top_k: 1" in updated.json()["agent_yaml"]
    loaded = client.get(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/contract"
    )
    assert "  top_k: 1" in loaded.json()["agent_yaml"]


def test_validate_draft_runs_harness_as_validation_run(tmp_path: Path) -> None:
    client = _client(tmp_path)
    draft = _import_enterprise_qa(client)

    validation = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/validate",
        json={
            "question": "What is the reimbursement rule for travel meals?",
            "actor": "validator",
        },
    )

    assert validation.status_code == 200
    body = validation.json()
    assert body["run_id"].startswith("run_")
    assert body["run_purpose"] == "validation"
    assert body["agent_id"] == draft["agent_id"]
    assert body["draft_id"] == draft["draft_id"]

    detail = client.get(f"/api/runs/{body['run_id']}")
    assert detail.status_code == 200
    assert detail.json()["run_purpose"] == "validation"
    assert detail.json()["agent_id"] == draft["agent_id"]
    assert detail.json()["draft_id"] == draft["draft_id"]

    loaded = client.get(f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}")
    assert loaded.json()["validation_records"][0]["run_id"] == body["run_id"]


def test_publish_requires_validation_and_activates_version(tmp_path: Path) -> None:
    client = _client(tmp_path)
    draft = _import_enterprise_qa(client)

    blocked = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/publish",
        json={"actor": "publisher"},
    )
    validation = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/validate",
        json={
            "question": "What is the reimbursement rule for travel meals?",
            "actor": "validator",
        },
    )
    published = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/publish",
        json={"validation_run_id": validation.json()["run_id"], "actor": "publisher"},
    )

    assert blocked.status_code == 400
    assert published.status_code == 200
    assert published.json()["version_id"].startswith("version_")
    assert published.json()["validation_run_id"] == validation.json()["run_id"]

    listed = client.get("/api/config/agents")
    assert listed.json()["data"][0]["active_version_id"] == published.json()["version_id"]


def test_rollback_switches_active_version(tmp_path: Path) -> None:
    client = _client(tmp_path)
    draft = _import_enterprise_qa(client)
    validation_one = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/validate",
        json={
            "question": "What is the reimbursement rule for travel meals?",
            "actor": "validator",
        },
    )
    version_one = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/publish",
        json={"validation_run_id": validation_one.json()["run_id"], "actor": "publisher"},
    ).json()["version_id"]
    client.patch(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}",
        json={"display_name": "Enterprise QA v2", "actor": "editor"},
    )
    validation_two = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/validate",
        json={
            "question": "What is the reimbursement rule for travel meals?",
            "actor": "validator",
        },
    )
    version_two = client.post(
        f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/publish",
        json={"validation_run_id": validation_two.json()["run_id"], "actor": "publisher"},
    ).json()["version_id"]

    rollback = client.post(
        f"/api/config/agents/{draft['agent_id']}/versions/{version_one}/rollback",
        json={"actor": "publisher"},
    )

    assert rollback.status_code == 200
    assert rollback.json()["version_id"] == version_one
    assert rollback.json()["rollback_from_version_id"] == version_two
    assert client.get("/api/config/agents").json()["data"][0]["active_version_id"] == version_one
