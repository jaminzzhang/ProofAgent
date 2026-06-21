from __future__ import annotations

import json
from pathlib import Path

import pytest

from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import ToolSourceLifecycleState
from proof_agent.errors import ProofAgentError


def _configuration_audit_payloads(root: Path) -> list[dict[str, object]]:
    audit_root = root / "configuration_audit"
    return [
        json.loads(path.read_text(encoding="utf-8")) for path in sorted(audit_root.glob("*.json"))
    ]


def _create_brave_source(
    store: LocalAgentConfigurationStore,
    *,
    source_id: str = "tool_brave_default",
) -> None:
    store.create_tool_source(
        source_id=source_id,
        name="Brave Search Default",
        source_type="search_vendor",
        provider="brave_search",
        tool_contract_ids=("untrusted_web_search",),
        credential_env_ref="BRAVE_SEARCH_API_KEY",
        params={"timeout_seconds": 8, "default_max_results": 3},
        actor="operator",
    )


def test_create_list_get_and_persist_tool_source(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)

    _create_brave_source(store)
    store.create_tool_source(
        source_id="tool_brave_backup",
        name="Brave Search Backup",
        source_type="search_vendor",
        provider="brave_search",
        tool_contract_ids=("untrusted_web_search",),
        credential_env_ref="BRAVE_SEARCH_BACKUP_API_KEY",
        params={"timeout_seconds": 5, "default_max_results": 2},
        actor="operator",
    )

    loaded = store.get_tool_source("tool_brave_default")
    listed = store.list_tool_sources()

    assert loaded is not None
    assert loaded.lifecycle_state is ToolSourceLifecycleState.ACTIVE
    assert loaded.config_revision == 1
    assert loaded.provider == "brave_search"
    assert loaded.credential_env_ref == "BRAVE_SEARCH_API_KEY"
    assert loaded.tool_contract_ids == ("untrusted_web_search",)
    assert [source.source_id for source in listed] == [
        "tool_brave_default",
        "tool_brave_backup",
    ]
    payload = json.loads(
        (tmp_path / "tool_sources" / "tool_brave_default" / "source.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["credential_env_ref"] == "BRAVE_SEARCH_API_KEY"
    assert "api_key" not in payload
    audits = _configuration_audit_payloads(tmp_path)
    created_audits = [payload for payload in audits if payload["operation"] == "created"]
    assert [payload["actor"] for payload in created_audits] == ["operator", "operator"]
    created_by_source = {payload["metadata"]["source_id"]: payload for payload in created_audits}
    assert created_by_source["tool_brave_default"]["metadata"]["tool_contract_ids"] == [
        "untrusted_web_search"
    ]


def test_mcp_stdio_tool_source_requires_command(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)

    created = store.create_tool_source(
        source_id="tool_mcp_policy_ops",
        name="Policy Ops MCP",
        source_type="mcp_server",
        provider="mcp",
        tool_contract_ids=(),
        credential_env_ref=None,
        params={
            "transport": "stdio",
            "server_label": "policy_ops_local",
            "command": "python",
            "args": ["-m", "examples.mcp.policy_ops_server"],
            "timeout_seconds": 10,
        },
        actor="operator",
    )

    assert created.provider == "mcp"
    assert created.source_type == "mcp_server"
    assert created.params["transport"] == "stdio"
    assert created.params["command"] == "python"

    with pytest.raises(ProofAgentError) as missing_command:
        store.create_tool_source(
            source_id="tool_mcp_missing_command",
            name="Broken MCP",
            source_type="mcp_server",
            provider="mcp",
            tool_contract_ids=(),
            credential_env_ref=None,
            params={"transport": "stdio", "server_label": "broken"},
            actor="operator",
        )

    assert missing_command.value.code == "PA_TOOL_SOURCE_001"
    assert "stdio MCP Tool Source requires params.command" in missing_command.value.message


def test_mcp_tool_source_requires_mcp_server_source_type(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)

    with pytest.raises(ProofAgentError) as exc:
        store.create_tool_source(
            source_id="tool_mcp_wrong_type",
            name="Wrong Type MCP",
            source_type="search_vendor",
            provider="mcp",
            tool_contract_ids=(),
            credential_env_ref=None,
            params={
                "transport": "stdio",
                "server_label": "wrong_type",
                "command": "python",
            },
            actor="operator",
        )

    assert exc.value.code == "PA_TOOL_SOURCE_001"
    assert "MCP Tool Source requires source_type=mcp_server" in exc.value.message


def test_mcp_http_tool_source_requires_endpoint_and_uses_env_ref(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)

    created = store.create_tool_source(
        source_id="tool_mcp_claims_http",
        name="Claims MCP",
        source_type="mcp_server",
        provider="mcp",
        tool_contract_ids=(),
        credential_env_ref="CLAIMS_MCP_TOKEN",
        params={
            "transport": "http",
            "server_label": "claims_mcp",
            "endpoint": "https://mcp.example.internal",
            "auth": {"type": "bearer_env", "env": "CLAIMS_MCP_TOKEN"},
            "timeout_seconds": 10,
        },
        actor="operator",
    )

    assert created.provider == "mcp"
    assert created.credential_env_ref == "CLAIMS_MCP_TOKEN"
    assert created.params["auth"] == {
        "type": "bearer_env",
        "env": "CLAIMS_MCP_TOKEN",
    }
    persisted = json.loads(
        (tmp_path / "tool_sources" / "tool_mcp_claims_http" / "source.json").read_text(
            encoding="utf-8"
        )
    )
    assert persisted["credential_env_ref"] == "CLAIMS_MCP_TOKEN"
    assert "secret-token" not in str(persisted)

    with pytest.raises(ProofAgentError) as missing_endpoint:
        store.create_tool_source(
            source_id="tool_mcp_missing_endpoint",
            name="Broken Claims MCP",
            source_type="mcp_server",
            provider="mcp",
            tool_contract_ids=(),
            credential_env_ref="CLAIMS_MCP_TOKEN",
            params={
                "transport": "http",
                "server_label": "broken_claims_mcp",
                "auth": {"type": "bearer_env", "env": "CLAIMS_MCP_TOKEN"},
            },
            actor="operator",
        )

    assert missing_endpoint.value.code == "PA_TOOL_SOURCE_001"
    assert "HTTP MCP Tool Source requires params.endpoint" in missing_endpoint.value.message


def test_mcp_http_tool_source_rejects_oauth_auth(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)

    with pytest.raises(ProofAgentError) as exc:
        store.create_tool_source(
            source_id="tool_mcp_oauth",
            name="OAuth MCP",
            source_type="mcp_server",
            provider="mcp",
            tool_contract_ids=(),
            credential_env_ref="MCP_CLIENT_ID",
            params={
                "transport": "http",
                "server_label": "oauth_mcp",
                "endpoint": "https://mcp.example.internal",
                "auth": {
                    "type": "oauth_device",
                    "client_id_env": "MCP_CLIENT_ID",
                },
            },
            actor="operator",
        )

    assert exc.value.code == "PA_TOOL_SOURCE_001"
    assert "HTTP MCP auth.type is not supported in V1" in exc.value.message


def test_mcp_http_tool_source_rejects_non_mapping_auth(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)

    with pytest.raises(ProofAgentError) as exc:
        store.create_tool_source(
            source_id="tool_mcp_scalar_auth",
            name="Scalar Auth MCP",
            source_type="mcp_server",
            provider="mcp",
            tool_contract_ids=(),
            credential_env_ref="CLAIMS_MCP_TOKEN",
            params={
                "transport": "http",
                "server_label": "scalar_auth_mcp",
                "endpoint": "https://mcp.example.internal",
                "auth": "Bearer secret-token",
            },
            actor="operator",
        )

    assert exc.value.code == "PA_TOOL_SOURCE_001"
    assert "HTTP MCP auth must be a mapping" in exc.value.message


def test_tool_source_create_rejects_duplicate_and_unsafe_ids(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_brave_source(store)

    with pytest.raises(ValueError):
        _create_brave_source(store)

    with pytest.raises(ProofAgentError) as invalid_id:
        store.create_tool_source(
            source_id="../escape",
            name="Escape",
            source_type="search_vendor",
            provider="brave_search",
            tool_contract_ids=("untrusted_web_search",),
            credential_env_ref="BRAVE_SEARCH_API_KEY",
            params={},
            actor="operator",
        )

    assert invalid_id.value.code == "PA_CONFIG_001"


def test_update_tool_source_increments_live_config_revision(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_brave_source(store)

    updated = store.update_tool_source(
        source_id="tool_brave_default",
        actor="operator",
        name="Brave Search Production",
        params={"timeout_seconds": 12, "default_max_results": 4},
    )

    assert updated.name == "Brave Search Production"
    assert updated.config_revision == 2
    assert updated.params["timeout_seconds"] == 12
    assert updated.lifecycle_state is ToolSourceLifecycleState.ACTIVE
    audits = _configuration_audit_payloads(tmp_path)
    updated_audit = [payload for payload in audits if payload["operation"] == "updated"][0]
    assert updated_audit["actor"] == "operator"
    assert updated_audit["metadata"]["source_id"] == "tool_brave_default"
    assert updated_audit["metadata"]["changed_fields"] == ["name", "params"]
    assert updated_audit["metadata"]["previous_config_revision"] == 1
    assert updated_audit["metadata"]["config_revision"] == 2


def test_archive_and_restore_tool_source_records_audit(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_brave_source(store)

    archived = store.archive_tool_source(
        source_id="tool_brave_default",
        actor="operator",
        reason="Rotate search vendor.",
    )
    restored = store.restore_tool_source(
        source_id="tool_brave_default",
        actor="operator",
        reason="Rollback vendor change.",
    )

    assert archived.lifecycle_state is ToolSourceLifecycleState.ARCHIVED
    assert restored.lifecycle_state is ToolSourceLifecycleState.ACTIVE
    audits = _configuration_audit_payloads(tmp_path)
    audit_by_operation = {payload["operation"]: payload for payload in audits}
    assert set(audit_by_operation) == {"created", "archived", "restored"}
    assert audit_by_operation["archived"]["metadata"]["source_id"] == "tool_brave_default"
