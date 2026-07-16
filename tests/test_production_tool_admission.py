from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from proof_agent.capabilities.tools.mcp_discovery import (
    MCPDiscoveredTool,
    discover_mcp_tools,
    import_mcp_tool_contract,
)
from proof_agent.capabilities.tools.gateway import ToolGateway
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import ContractBundle
from proof_agent.errors import ProofAgentError
from proof_agent.contracts.ports.guarded_http import GuardedHttpResponse


class NoNetworkGuardedClient:
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        timeout_seconds: float = 10.0,
    ) -> GuardedHttpResponse:
        raise AssertionError((method, url, headers, body, timeout_seconds))


def draft_with_tools(
    store: LocalAgentConfigurationStore,
    tools: list[dict[str, object]],
):
    return store.create_draft(
        agent_id="insurance_specialist",
        display_name="Insurance Specialist",
        purpose="Answer insurance rule questions with citations.",
        contract_bundle=ContractBundle(
            agent_yaml="name: insurance_specialist\n",
            policy_yaml="rules: []\n",
            tools_yaml=yaml.safe_dump({"tools": tools}, sort_keys=False),
        ),
        actor="operator",
    )


def publish(store: LocalAgentConfigurationStore, draft_id: str) -> None:
    store.publish_version(
        agent_id="insurance_specialist",
        draft_id=draft_id,
        validation_run_id="validation-1",
        actor="publisher",
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"effect": "create"}, "effect: read"),
        ({"effect": None}, "effect: read"),
        ({"read_only": False}, "read-only"),
        ({"requires_approval": True}, "approval"),
        ({"source": "local"}, "managed MCP HTTPS"),
        ({"handler": "package.module:call"}, "local handler"),
        ({"mcp_contract_snapshot": {"digest": "sha256:mutable"}}, "digest"),
    ],
)
def test_production_publication_rejects_non_read_only_tool_contracts(
    tmp_path: Path,
    changes: dict[str, object],
    message: str,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path, production_mode=True)
    tool: dict[str, object] = {
        "name": "claim_status_lookup",
        "source": "mcp",
        "tool_source_id": "tool_claims",
        "mcp_tool_name": "claim.status.lookup",
        "mcp_contract_snapshot": {"digest": "sha256:" + "a" * 64},
        "effect": "read",
        "risk_level": "medium",
        "requires_approval": False,
        "read_only": True,
        "allowed_parameters": ["claim_id"],
        "denied_parameters": ["access_token"],
        "input_schema": {"type": "object"},
        "result_schema": {"type": "object"},
        "summary_fields": [],
        "result_authority": "authoritative_read",
    }
    tool.update(changes)
    draft = draft_with_tools(store, [tool])

    with pytest.raises(ProofAgentError, match=message):
        publish(store, draft.draft_id)

    assert store.list_versions(draft.agent_id) == []


def test_production_publication_rejects_stdio_or_non_exact_https_source(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path, production_mode=True)
    source = store.create_tool_source(
        source_id="tool_claims",
        name="Claims MCP",
        source_type="mcp_server",
        provider="mcp",
        tool_contract_ids=("claim_status_lookup",),
        credential_env_ref=None,
        params={
            "transport": "stdio",
            "server_label": "claims",
            "command": "python",
        },
        actor="operator",
    )
    assert source.params["transport"] == "stdio"
    draft = draft_with_tools(
        store,
        [
            {
                "name": "claim_status_lookup",
                "source": "mcp",
                "tool_source_id": "tool_claims",
                "mcp_tool_name": "claim.status.lookup",
                "mcp_contract_snapshot": {"digest": "sha256:" + "a" * 64},
                "effect": "read",
                "risk_level": "medium",
                "requires_approval": False,
                "read_only": True,
                "allowed_parameters": ["claim_id"],
                "denied_parameters": [],
                "input_schema": {"type": "object"},
                "result_schema": {"type": "object"},
                "summary_fields": [],
                "result_authority": "authoritative_read",
            }
        ],
    )

    with pytest.raises(ProofAgentError, match="MCP stdio"):
        publish(store, draft.draft_id)


def test_production_publication_accepts_validated_read_only_https_mcp_tool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path, production_mode=True)
    store.create_tool_source(
        source_id="tool_claims",
        name="Claims MCP",
        source_type="mcp_server",
        provider="mcp",
        tool_contract_ids=("claim_status_lookup",),
        credential_env_ref=None,
        params={
            "transport": "http",
            "server_label": "claims",
            "endpoint": "https://claims.internal.example",
            "auth": {"type": "no_auth"},
        },
        actor="operator",
    )
    discovered = (
        MCPDiscoveredTool(
            name="claim.status.lookup",
            description="Lookup claim status.",
            input_schema={
                "type": "object",
                "properties": {"claim_id": {"type": "string"}},
                "required": ["claim_id"],
            },
        ),
    )
    preview = discover_mcp_tools(
        store.get_tool_source("tool_claims"),
        transport=lambda _connection: discovered,
    )
    tool = import_mcp_tool_contract(
        preview,
        mcp_tool_name="claim.status.lookup",
        contract_name="claim_status_lookup",
        tool_source_id="tool_claims",
        risk_level="medium",
        read_only=True,
        requires_approval=False,
        allowed_parameters=("claim_id",),
        denied_parameters=("access_token",),
        result_schema={
            "type": "object",
            "properties": {"status": {"type": "string"}},
            "required": ["status"],
        },
        summary_fields=("status",),
        result_authority="authoritative_read",
        imported_at="2026-07-15T00:00:00Z",
    )
    tool["effect"] = "read"
    store.validate_mcp_tool_source_publication(
        source_id="tool_claims",
        tool_contracts=(tool,),
        actor="operator",
        transport=lambda _connection: discovered,
    )
    draft = draft_with_tools(store, [tool])

    publish(store, draft.draft_id)

    assert len(store.list_versions(draft.agent_id)) == 1

    tools_path = tmp_path / "frozen-tools.yaml"
    tools_path.write_text(
        yaml.safe_dump({"tools": [tool]}, sort_keys=False),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROOF_AGENT_MODE", "production")
    gateway = ToolGateway.from_file(
        tools_path,
        configuration_store=store,
        guarded_http_client=NoNetworkGuardedClient(),
        mcp_tool_transport=lambda _request: {"status": "open"},
    )
    store.update_tool_source(
        source_id="tool_claims",
        actor="operator",
        params={
            "transport": "stdio",
            "server_label": "claims",
            "command": "python",
        },
    )

    with pytest.raises(ProofAgentError, match="MCP stdio"):
        gateway.request_tool(
            tool_name="claim_status_lookup",
            parameters={"claim_id": "CLM-1"},
            approved=False,
        )
