"""Configuration-to-runtime authorization without policy files or restarts."""

import json

import pytest
from fastapi.testclient import TestClient

from proof_agent.capabilities.egress.guarded_http import (
    SystemAddressResolver,
    StdlibPinnedHttpsTransport,
)
from proof_agent.contracts.ports.guarded_http import GuardedHttpResponse
from proof_agent.contracts import Permission
from proof_agent.observability.api.app import create_app
from proof_agent.observability.api.operator_identity import OperatorIdentityContext


def binding():
    return {
        "binding_id": "manuals",
        "provider": "agentset",
        "endpoint": "https://api.agentset.ai/v1",
        "namespace_id": "ns_manuals",
        "credential_ref": {
            "protocol_id": "local-environment-v1",
            "handle_id": "SYNTHETIC_KEY",
            "purpose": "knowledge_credential",
            "version_id": "env",
        },
    }


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("PROOF_AGENT_MODE", "development")
    monkeypatch.delenv("PROOF_AGENT_EXTERNAL_KNOWLEDGE_EGRESS_POLICY", raising=False)
    monkeypatch.setenv("SYNTHETIC_KEY", "synthetic-test-token")
    addresses = ["8.8.8.8"]
    sent = []
    monkeypatch.setattr(SystemAddressResolver, "resolve", lambda *a, **k: tuple(addresses))

    def send(self, method, url, **kwargs):
        sent.append((url, kwargs["connect_address"]))
        return GuardedHttpResponse(
            status_code=200,
            headers={"content-type": "application/json"},
            body=b'{"success":true,"data":[]}',
        )

    monkeypatch.setattr(StdlibPinnedHttpsTransport, "send", send)
    kwargs = dict(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "runs",
        conversations_dir=tmp_path / "conversations",
        agent_configuration_dir=tmp_path / "config",
    )
    app = create_app(**kwargs)
    client = TestClient(app)
    draft = client.post(
        "/api/config/agents/import",
        json={
            "manifest_path": "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"
        },
    ).json()
    base = f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/external-knowledge"
    return client, app, base, addresses, sent, kwargs


def save(client, base, **extra):
    revision = client.get(base).json()["revision"]
    return client.patch(
        base, json={"expected_revision": revision, "bindings": [binding()], **extra}
    )


def check(client, base):
    return client.post(
        base + "/check", json={"expected_revision": client.get(base).json()["revision"]}
    )


def test_authorize_persists_and_hot_applies_with_public_dns_rotation(setup):
    client, app, base, addresses, sent, kwargs = setup
    saved = save(client, base, authorize={"allow_local_proxy": False})
    assert saved.status_code == 200, saved.text
    assert saved.json()["connections"][0]["authorized"] is True
    assert check(client, base).json()["connections"][0]["status"] == "ready"
    addresses[:] = ["1.1.1.1"]
    restarted = TestClient(create_app(**kwargs))
    assert check(restarted, base).json()["connections"][0]["status"] == "ready"
    assert sent[-1][1] == "1.1.1.1"
    assert "synthetic-test-token" not in json.dumps(saved.json())
    validation = restarted.post(
        base.removesuffix("/external-knowledge") + "/validate",
        json={"question": "What is the limit?"},
    )
    assert validation.status_code == 200, validation.text


def test_cas_and_plain_binding_changes_revoke_without_new_permission(setup):
    client, app, base, addresses, sent, _ = setup
    revision = client.get(base).json()["revision"]
    assert save(client, base, authorize={"allow_local_proxy": False}).status_code == 200
    stale = client.patch(
        base,
        json={
            "expected_revision": revision,
            "bindings": [],
            "authorize": {"allow_local_proxy": False},
        },
    )
    assert stale.status_code == 409
    assert client.get(base).json()["connections"][0]["authorized"]
    changed = binding()
    changed["namespace_id"] = "ns_other"
    updated = client.patch(base, json={"expected_revision": revision + 1, "bindings": [changed]})
    assert updated.status_code == 200
    assert not updated.json()["connections"][0]["authorized"]
    assert check(client, base).json()["connections"][0]["status"] == "authorization_required"


def test_plain_save_does_not_authorize_and_credential_check_is_actionable(setup, monkeypatch):
    client, app, base, addresses, sent, _ = setup
    assert save(client, base).status_code == 200
    assert check(client, base).json()["connections"][0]["status"] == "authorization_required"
    assert not sent
    assert save(client, base, authorize={"allow_local_proxy": False}).status_code == 200
    monkeypatch.delenv("SYNTHETIC_KEY")
    result = check(client, base)
    assert result.json()["connections"][0]["status"] == "credential_unavailable"
    assert not sent


def test_egress_permission_and_cas_prevent_grants(setup):
    client, app, base, addresses, sent, _ = setup

    class Editor:
        def current_identity(self):
            return OperatorIdentityContext(
                operator_id="editor",
                display_name="Editor",
                permissions=frozenset(Permission) - {Permission.EGRESS_POLICY_EDIT},
            )

    app.state.operator_identity_provider = Editor()
    before = client.get(base).json()["revision"]
    assert save(client, base, authorize={"allow_local_proxy": False}).status_code == 403
    assert client.get(base).json()["revision"] == before
    assert not sent


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "::1",
        "::ffff:127.0.0.1",
        "::ffff:0:7f00:1",
        "224.0.0.1",
    ],
)
def test_private_and_special_dns_answers_never_granted(setup, address):
    client, app, base, addresses, sent, _ = setup
    addresses[:] = ["8.8.8.8", address]
    response = save(client, base, authorize={"allow_local_proxy": True})
    assert response.status_code == 400
    assert not sent


def test_proxy_requires_explicit_option_and_supports_address_rotation(setup):
    client, app, base, addresses, sent, _ = setup
    addresses[:] = ["198.18.0.32", "::ffff:198.18.0.32"]
    assert save(client, base, authorize={"allow_local_proxy": False}).status_code == 400
    assert save(client, base, authorize={"allow_local_proxy": True}).status_code == 200
    assert client.get(base).json()["connections"][0]["address_mode"] == "local_proxy_dns"
    addresses[:] = ["198.18.0.69", "::ffff:0:c612:45"]
    assert check(client, base).json()["connections"][0]["status"] == "ready"
    addresses[:] = ["127.0.0.1"]
    assert check(client, base).json()["connections"][0]["status"] != "ready"
    assert len(sent) == 1


def test_proxy_cannot_authorize_arbitrary_hosts_or_client_supplied_grants(setup):
    client, app, base, addresses, sent, _ = setup
    addresses[:] = ["198.18.0.69"]
    changed = binding()
    changed["endpoint"] = "https://untrusted.example/v1"
    revision = client.get(base).json()["revision"]
    response = client.patch(
        base,
        json={
            "expected_revision": revision,
            "bindings": [changed],
            "authorize": {"allow_local_proxy": True},
        },
    )
    assert response.status_code == 400
    assert client.get(base).json()["revision"] == revision
    response = client.patch(
        base,
        json={
            "expected_revision": revision,
            "bindings": [binding()],
            "knowledge_connection_authorizations": [{"origin": "forged"}],
        },
    )
    assert response.status_code == 400


def test_managed_and_production_policies_cannot_be_overridden(setup, monkeypatch):
    client, app, base, addresses, sent, _ = setup
    monkeypatch.setenv(
        "PROOF_AGENT_EXTERNAL_KNOWLEDGE_EGRESS_POLICY", "/not-read/server-policy.json"
    )
    assert client.get(base).json()["can_authorize"] is False
    assert save(client, base, authorize={"allow_local_proxy": False}).status_code == 409
    monkeypatch.delenv("PROOF_AGENT_EXTERNAL_KNOWLEDGE_EGRESS_POLICY")
    app.state.proof_agent_mode = "production"
    from proof_agent.observability.api.dependencies import get_operator_identity
    from proof_agent.observability.api.operator_identity import LocalOperatorIdentityProvider

    app.dependency_overrides[get_operator_identity] = (
        LocalOperatorIdentityProvider().current_identity
    )
    assert client.get(base).json()["can_authorize"] is False
    versioned = binding()
    versioned["credential_ref"].update(protocol_id="hashicorp-vault-2.0-kv-v2", version_id="1")
    response = client.patch(
        base,
        json={
            "expected_revision": client.get(base).json()["revision"],
            "bindings": [versioned],
            "authorize": {"allow_local_proxy": False},
        },
    )
    assert response.status_code == 409
    assert not sent


def test_live_client_observes_revocation_and_audit_commits_with_grant(setup):
    from proof_agent.bootstrap.external_knowledge import development_knowledge_dependencies
    from proof_agent.contracts.external_knowledge import ExternalKnowledgeBinding
    from proof_agent.control.security.egress import EgressDeniedError

    client, app, base, addresses, sent, _ = setup
    saved = save(client, base, authorize={"allow_local_proxy": False})
    agent_id = base.split("/")[4]
    store = app.state.agent_configuration_store
    draft = store.list_drafts(agent_id)[0]
    assert draft.operation_audit[-1].metadata["knowledge_connection_authorizations"]
    http, _ = development_knowledge_dependencies(
        None,
        None,
        configuration_store=store,
        agent_id=agent_id,
        bindings=(ExternalKnowledgeBinding.model_validate(binding()),),
    )
    assert http is not None
    client.patch(base, json={"expected_revision": saved.json()["revision"], "bindings": []})
    with pytest.raises(EgressDeniedError):
        http.request("POST", "https://api.agentset.ai/v1/namespace/ns_manuals/search")
    assert not sent


def test_failed_contract_validation_does_not_grant_access(setup, monkeypatch):
    client, app, base, addresses, sent, _ = setup
    revision = client.get(base).json()["revision"]

    def fail(**kwargs):
        raise ValueError("synthetic-contract-failure")

    monkeypatch.setattr(
        app.state.agent_configuration_workspace._contract_validator, "validate", fail
    )
    assert save(client, base, authorize={"allow_local_proxy": False}).status_code == 400
    assert client.get(base).json()["revision"] == revision
    assert client.get(base).json()["connections"] == []


def test_probe_checks_permission_revision_and_never_returns_provider_payload(setup, monkeypatch):
    client, app, base, addresses, sent, _ = setup
    saved = save(client, base, authorize={"allow_local_proxy": False})
    assert (
        client.post(
            base + "/check", json={"expected_revision": saved.json()["revision"] - 1}
        ).status_code
        == 409
    )

    def reject(*args, **kwargs):
        return GuardedHttpResponse(
            status_code=401, headers={}, body=b"private provider error and token"
        )

    monkeypatch.setattr(StdlibPinnedHttpsTransport, "send", reject)
    response = check(client, base)
    assert response.json()["connections"][0]["status"] == "provider_rejected"
    assert "private provider" not in response.text

    class Viewer:
        def current_identity(self):
            return OperatorIdentityContext(
                operator_id="viewer",
                display_name="Viewer",
                permissions=frozenset(Permission) - {Permission.SECRET_HANDLE_USE},
            )

    app.state.operator_identity_provider = Viewer()
    assert check(client, base).status_code == 403
