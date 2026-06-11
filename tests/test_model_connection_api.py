from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import ContractBundle
from proof_agent.observability.api.app import create_app
from proof_agent.observability.api.operator_identity import (
    OperatorIdentityContext,
    OperatorPermission,
)


def _client(tmp_path: Path) -> TestClient:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
        published_agents={},
        agent_configuration_dir=tmp_path / "config",
    )
    return TestClient(app)


class _StaticOperatorIdentityProvider:
    def __init__(self, permissions: set[OperatorPermission]) -> None:
        self._permissions = permissions

    def current_identity(self) -> OperatorIdentityContext:
        return OperatorIdentityContext(
            operator_id="test-operator",
            display_name="Test Operator",
            permissions=frozenset(self._permissions),
        )


def _client_with_operator_permissions(
    tmp_path: Path,
    permissions: set[OperatorPermission],
) -> TestClient:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
        published_agents={},
        agent_configuration_dir=tmp_path / "config",
    )
    app.state.operator_identity_provider = _StaticOperatorIdentityProvider(permissions)
    return TestClient(app)


def _configuration_store(client: TestClient) -> LocalAgentConfigurationStore:
    return client.app.state.agent_configuration_store


def _create_model_connection(client: TestClient) -> dict:
    response = client.post(
        "/api/config/model-connections",
        json={
            "connection_id": "model_deepseek_default",
            "display_name": "DeepSeek Default",
            "provider": "deepseek",
            "model_identifier": "deepseek-chat",
            "base_url": "https://api.deepseek.com",
            "credential_ref": {"type": "env", "name": "DEEPSEEK_API_KEY"},
            "timeout_seconds": 20,
        },
    )
    assert response.status_code == 200
    return response.json()


def test_model_connection_collection_and_detail_routes(tmp_path: Path) -> None:
    client = _client(tmp_path)

    empty = client.get("/api/config/model-connections")
    created = _create_model_connection(client)
    listed = client.get("/api/config/model-connections")
    detail = client.get("/api/config/model-connections/model_deepseek_default")
    unsupported = client.post(
        "/api/config/model-connections",
        json={
            "display_name": "Anthropic Placeholder",
            "provider": "anthropic",
            "model_identifier": "claude-placeholder",
            "credential_ref": {"type": "env", "name": "ANTHROPIC_API_KEY"},
        },
    )

    assert empty.status_code == 200
    assert empty.json() == {"data": [], "meta": {"total": 0}}
    assert created["connection_id"] == "model_deepseek_default"
    assert created["credential_ref"] == {"type": "env", "name": "DEEPSEEK_API_KEY"}
    assert created["base_url"] == "https://api.deepseek.com"
    assert listed.json()["meta"] == {"total": 1}
    assert detail.status_code == 200
    assert detail.json()["model_identifier"] == "deepseek-chat"
    assert unsupported.status_code == 400
    assert "Unsupported model provider" in unsupported.json()["detail"]


def test_model_connection_read_requires_view_permission(tmp_path: Path) -> None:
    setup_client = _client(tmp_path)
    _create_model_connection(setup_client)
    client = _client_with_operator_permissions(tmp_path, set())

    listed = client.get("/api/config/model-connections")
    detail = client.get("/api/config/model-connections/model_deepseek_default")

    assert listed.status_code == 403
    assert detail.status_code == 403


def test_model_connection_create_rejects_request_body_actor(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/config/model-connections",
        json={
            "connection_id": "model_deepseek_default",
            "display_name": "DeepSeek Default",
            "provider": "deepseek",
            "model_identifier": "deepseek-chat",
            "credential_ref": {"type": "env", "name": "DEEPSEEK_API_KEY"},
            "actor": "spoofed-operator",
        },
    )

    assert response.status_code == 422


def test_model_connection_create_requires_edit_permission(tmp_path: Path) -> None:
    client = _client_with_operator_permissions(
        tmp_path,
        {OperatorPermission.MODEL_CONNECTION_VIEW},
    )

    response = client.post(
        "/api/config/model-connections",
        json={
            "connection_id": "model_deepseek_default",
            "display_name": "DeepSeek Default",
            "provider": "deepseek",
            "model_identifier": "deepseek-chat",
            "credential_ref": {"type": "env", "name": "DEEPSEEK_API_KEY"},
        },
    )

    assert response.status_code == 403


def test_model_connection_create_accepts_operator_identity_boundary(tmp_path: Path) -> None:
    client = _client_with_operator_permissions(
        tmp_path,
        {OperatorPermission.MODEL_CONNECTION_EDIT, OperatorPermission.MODEL_CONNECTION_VIEW},
    )

    response = client.post(
        "/api/config/model-connections",
        json={
            "connection_id": "model_deepseek_default",
            "display_name": "DeepSeek Default",
            "provider": "deepseek",
            "model_identifier": "deepseek-chat",
            "credential_ref": {"type": "env", "name": "DEEPSEEK_API_KEY"},
        },
    )

    assert response.status_code == 200
    assert response.json()["connection_id"] == "model_deepseek_default"
    audit_payloads = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((tmp_path / "config" / "configuration_audit").glob("*.json"))
    ]
    assert audit_payloads[0]["operation"] == "created"
    assert audit_payloads[0]["actor"] == "test-operator"
    assert audit_payloads[0]["metadata"]["connection_id"] == "model_deepseek_default"


def test_model_connection_lifecycle_references_and_delete_routes(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    _create_model_connection(client)
    store = _configuration_store(client)
    store.create_draft(
        agent_id="enterprise_qa",
        display_name="Enterprise QA",
        purpose="Answer enterprise questions.",
        contract_bundle=ContractBundle(
            agent_yaml="""
name: enterprise_qa
model:
  model_source: shared
  connection_id: model_deepseek_default
""",
            policy_yaml="rules: []\n",
            tools_yaml="tools: {}\n",
        ),
        actor="operator",
    )

    references = client.get("/api/config/model-connections/model_deepseek_default/references")
    unconfirmed_update = client.patch(
        "/api/config/model-connections/model_deepseek_default",
        json={"model_identifier": "deepseek-reasoner"},
    )
    confirmed_update = client.patch(
        "/api/config/model-connections/model_deepseek_default",
        json={
            "model_identifier": "deepseek-reasoner",
            "confirm_impact": True,
        },
    )
    active_delete = client.request(
        "DELETE",
        "/api/config/model-connections/model_deepseek_default",
        json={"reason": "Cleanup."},
    )
    archived = client.post(
        "/api/config/model-connections/model_deepseek_default/archive",
        json={"reason": "No longer preferred."},
    )
    eligibility = client.get(
        "/api/config/model-connections/model_deepseek_default/deletion-eligibility"
    )
    restored = client.post(
        "/api/config/model-connections/model_deepseek_default/restore",
        json={},
    )

    assert references.status_code == 200
    assert references.json()["draft_agent_reference_count"] == 1
    assert unconfirmed_update.status_code == 409
    assert unconfirmed_update.json()["detail"]["requires_impact_review"] is True
    assert confirmed_update.status_code == 200
    assert confirmed_update.json()["model_identifier"] == "deepseek-reasoner"
    assert active_delete.status_code == 400
    assert active_delete.json()["detail"]["code"] == "PA_CONFIG_002"
    assert archived.status_code == 200
    assert archived.json()["lifecycle_state"] == "ARCHIVED"
    assert eligibility.status_code == 200
    assert eligibility.json()["blockers"] == ["draft_agent_references"]
    assert restored.status_code == 200
    assert restored.json()["lifecycle_state"] == "ACTIVE"


def test_model_connection_delete_empty_archived_connection(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _create_model_connection(client)
    client.post(
        "/api/config/model-connections/model_deepseek_default/archive",
        json={"reason": "Cleanup."},
    )

    deleted = client.request(
        "DELETE",
        "/api/config/model-connections/model_deepseek_default",
        json={"reason": "Cleanup."},
    )

    assert deleted.status_code == 200
    assert deleted.json()["eligible"] is True
    assert client.get("/api/config/model-connections/model_deepseek_default").status_code == 404


def test_model_connection_validation_and_smoke_test_do_not_expose_missing_secret(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    client = _client(tmp_path)
    _create_model_connection(client)

    validation = client.post(
        "/api/config/model-connections/model_deepseek_default/validate",
        json={},
    )
    smoke_test = client.post(
        "/api/config/model-connections/model_deepseek_default/smoke-test",
        json={},
    )

    assert validation.status_code == 200
    assert validation.json()["status"] == "failed"
    assert validation.json()["missing_env_vars"] == ["DEEPSEEK_API_KEY"]
    assert "secret" not in str(validation.json()).lower()
    assert smoke_test.status_code == 200
    assert smoke_test.json()["status"] == "failed"
    assert smoke_test.json()["request_sent"] is False
    assert smoke_test.json()["credential_ref"] == {
        "type": "env",
        "name": "DEEPSEEK_API_KEY",
    }


def test_model_connection_validation_uses_operator_identity_for_audit(
    tmp_path: Path,
) -> None:
    setup_client = _client(tmp_path)
    _create_model_connection(setup_client)
    client = _client_with_operator_permissions(
        tmp_path,
        {OperatorPermission.MODEL_CONNECTION_VALIDATE},
    )

    response = client.post(
        "/api/config/model-connections/model_deepseek_default/validate",
        json={},
    )

    assert response.status_code == 200
    assert response.json()["created_by"] == "test-operator"


def test_model_connection_validate_requires_validate_permission(tmp_path: Path) -> None:
    setup_client = _client(tmp_path)
    _create_model_connection(setup_client)
    client = _client_with_operator_permissions(
        tmp_path,
        {OperatorPermission.MODEL_CONNECTION_VIEW},
    )

    response = client.post(
        "/api/config/model-connections/model_deepseek_default/validate",
        json={},
    )

    assert response.status_code == 403
