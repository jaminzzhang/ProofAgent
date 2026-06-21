from __future__ import annotations

from proof_agent.capabilities.tools.mcp_discovery import (
    MCPDiscoveredTool,
    MCPToolSourceConnection,
    discover_mcp_tools,
    import_mcp_tool_contract,
    validate_mcp_tool_source_publication,
)
from proof_agent.capabilities.tools.gateway import ToolGateway
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import ToolSource, ToolSourceLifecycleState
from proof_agent.errors import ProofAgentError
from pathlib import Path
import pytest
import socket
import subprocess
import sys
import time
import yaml  # type: ignore[import-untyped]


def _mcp_source() -> ToolSource:
    return ToolSource(
        source_id="tool_mcp_claims_http",
        name="Claims MCP",
        source_type="mcp_server",
        provider="mcp",
        lifecycle_state=ToolSourceLifecycleState.ACTIVE,
        tool_contract_ids=(),
        credential_env_ref="CLAIMS_MCP_TOKEN",
        params={
            "transport": "http",
            "server_label": "claims_mcp",
            "endpoint": "https://mcp.example.internal",
            "auth": {"type": "bearer_env", "env": "CLAIMS_MCP_TOKEN"},
            "timeout_seconds": 10,
        },
        config_revision=1,
        created_at="2026-06-20T00:00:00Z",
        updated_at="2026-06-20T00:00:00Z",
    )


def _mcp_stdio_source(server_path: Path) -> ToolSource:
    return ToolSource(
        source_id="tool_mcp_claims_stdio",
        name="Claims MCP",
        source_type="mcp_server",
        provider="mcp",
        lifecycle_state=ToolSourceLifecycleState.ACTIVE,
        tool_contract_ids=(),
        credential_env_ref=None,
        params={
            "transport": "stdio",
            "server_label": "claims_mcp_stdio",
            "command": sys.executable,
            "args": [str(server_path)],
            "timeout_seconds": 10,
        },
        config_revision=1,
        created_at="2026-06-20T00:00:00Z",
        updated_at="2026-06-20T00:00:00Z",
    )


def _mcp_http_source(port: int) -> ToolSource:
    return ToolSource(
        source_id="tool_mcp_claims_http",
        name="Claims MCP",
        source_type="mcp_server",
        provider="mcp",
        lifecycle_state=ToolSourceLifecycleState.ACTIVE,
        tool_contract_ids=(),
        credential_env_ref=None,
        params={
            "transport": "http",
            "server_label": "claims_mcp_http",
            "endpoint": f"http://127.0.0.1:{port}/mcp",
            "auth": {"type": "no_auth"},
            "timeout_seconds": 10,
        },
        config_revision=1,
        created_at="2026-06-20T00:00:00Z",
        updated_at="2026-06-20T00:00:00Z",
    )


def _unused_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_discover_mcp_tools_returns_trace_safe_preview() -> None:
    seen_connections: list[MCPToolSourceConnection] = []

    def transport(connection: MCPToolSourceConnection) -> tuple[MCPDiscoveredTool, ...]:
        seen_connections.append(connection)
        return (
            MCPDiscoveredTool(
                name="claim.status.lookup",
                description="Lookup claim status",
                input_schema={
                    "type": "object",
                    "properties": {"claim_id": {"type": "string"}},
                    "required": ["claim_id"],
                },
            ),
        )

    preview = discover_mcp_tools(
        _mcp_source(),
        env={"CLAIMS_MCP_TOKEN": "secret-token"},
        transport=transport,
    )

    assert preview.tool_source_id == "tool_mcp_claims_http"
    assert preview.provider == "mcp"
    assert preview.transport == "http"
    assert preview.server_label == "claims_mcp"
    assert preview.tool_count == 1
    assert preview.tools[0].name == "claim.status.lookup"
    assert preview.tools[0].input_schema["required"] == ("claim_id",)
    assert preview.tools[0].schema_digest.startswith("sha256:")
    assert preview.trace_safe_metadata == seen_connections[0].trace_safe_metadata
    assert seen_connections[0].credential_value == "secret-token"
    assert seen_connections[0].trace_safe_metadata == {
        "tool_source_id": "tool_mcp_claims_http",
        "provider": "mcp",
        "transport": "http",
        "server_label": "claims_mcp",
        "endpoint_host": "mcp.example.internal",
        "credential_env_ref": "CLAIMS_MCP_TOKEN",
    }
    assert "secret-token" not in str(preview.model_dump(mode="json"))


def test_discover_mcp_tools_builds_header_env_http_headers() -> None:
    source = _mcp_source().model_copy(
        update={
            "credential_env_ref": "MCP_HEADER_TOKEN",
            "params": {
                "transport": "http",
                "server_label": "claims_mcp",
                "endpoint": "https://mcp.example.internal",
                "auth": {
                    "type": "header_env",
                    "env": "MCP_HEADER_TOKEN",
                    "header": "X-MCP-Token",
                },
                "timeout_seconds": 10,
            },
        }
    )
    seen_connections: list[MCPToolSourceConnection] = []

    def transport(connection: MCPToolSourceConnection) -> tuple[MCPDiscoveredTool, ...]:
        seen_connections.append(connection)
        return ()

    preview = discover_mcp_tools(
        source,
        env={"MCP_HEADER_TOKEN": "secret-token"},
        transport=transport,
    )

    assert preview.tool_count == 0
    assert seen_connections[0].http_headers == {"X-MCP-Token": "secret-token"}
    assert seen_connections[0].trace_safe_metadata["credential_env_ref"] == "MCP_HEADER_TOKEN"
    assert "secret-token" not in str(seen_connections[0].trace_safe_metadata)


def test_discover_mcp_tools_uses_stdio_sdk_transport(tmp_path: Path) -> None:
    server_path = tmp_path / "claims_mcp_server.py"
    server_path.write_text(
        """
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Claims MCP")

@mcp.tool(name="claim.status.lookup", description="Lookup claim status")
def claim_status_lookup(claim_id: str) -> dict[str, str]:
    return {"claim_id": claim_id, "status": "open"}

if __name__ == "__main__":
    mcp.run("stdio")
""",
        encoding="utf-8",
    )

    preview = discover_mcp_tools(_mcp_stdio_source(server_path))

    assert preview.transport == "stdio"
    assert preview.server_label == "claims_mcp_stdio"
    assert preview.tool_count == 1
    assert preview.tools[0].name == "claim.status.lookup"
    assert preview.tools[0].description == "Lookup claim status"
    assert "claim_id" in preview.tools[0].input_schema["properties"]


def test_discover_mcp_tools_uses_http_sdk_transport(tmp_path: Path) -> None:
    port = _unused_port()
    server_path = tmp_path / "claims_mcp_http_server.py"
    server_path.write_text(
        f"""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Claims MCP", host="127.0.0.1", port={port})

@mcp.tool(name="claim.status.lookup", description="Lookup claim status")
def claim_status_lookup(claim_id: str) -> dict[str, str]:
    return {{"claim_id": claim_id, "status": "open"}}

if __name__ == "__main__":
    mcp.run("streamable-http")
""",
        encoding="utf-8",
    )
    process = subprocess.Popen(
        [sys.executable, str(server_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        last_error: ProofAgentError | None = None
        while time.monotonic() < deadline:
            try:
                preview = discover_mcp_tools(_mcp_http_source(port))
                break
            except ProofAgentError as exc:
                if "transport is not configured" in exc.message:
                    raise
                last_error = exc
                time.sleep(0.2)
        else:
            raise AssertionError(f"HTTP MCP server did not become ready: {last_error}")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    assert preview.transport == "http"
    assert preview.server_label == "claims_mcp_http"
    assert preview.tool_count == 1
    assert preview.tools[0].name == "claim.status.lookup"
    assert "claim_id" in preview.tools[0].input_schema["properties"]


def test_import_mcp_tool_contract_freezes_selected_discovery_snapshot(tmp_path) -> None:
    preview = discover_mcp_tools(
        _mcp_source(),
        env={"CLAIMS_MCP_TOKEN": "secret-token"},
        transport=lambda _connection: (
            MCPDiscoveredTool(
                name="claim.status.lookup",
                description="Lookup claim status",
                input_schema={
                    "type": "object",
                    "properties": {"claim_id": {"type": "string"}},
                    "required": ["claim_id"],
                },
            ),
        ),
    )

    tool_contract = import_mcp_tool_contract(
        preview,
        mcp_tool_name="claim.status.lookup",
        contract_name="claim_status_lookup",
        tool_source_id="tool_mcp_claims_http",
        risk_level="medium",
        read_only=True,
        requires_approval=False,
        allowed_parameters=("claim_id",),
        denied_parameters=("access_token",),
        result_schema={
            "type": "object",
            "properties": {
                "claim_id": {"type": "string"},
                "status": {"type": "string"},
            },
            "required": ["claim_id", "status"],
        },
        summary_fields=("claim_id", "status"),
        result_authority="authoritative_read",
        imported_at="2026-06-20T00:00:00Z",
    )

    assert tool_contract["source"] == "mcp"
    assert tool_contract["mcp_tool_name"] == "claim.status.lookup"
    assert tool_contract["mcp_contract_snapshot"]["digest"].startswith("sha256:")
    assert (
        tool_contract["mcp_contract_snapshot"]["input_schema_digest"]
        == preview.tools[0].schema_digest
    )
    assert tool_contract["mcp_contract_snapshot"]["result_schema_digest"].startswith("sha256:")
    assert tool_contract["input_schema"]["required"] == ("claim_id",)
    assert tool_contract["result_schema"]["required"] == ("claim_id", "status")
    assert tool_contract["summary_fields"] == ("claim_id", "status")
    assert "secret-token" not in str(tool_contract)

    tools_yaml = tmp_path / "tools.yaml"
    tools_yaml.write_text(
        yaml.safe_dump({"tools": [tool_contract]}, sort_keys=False),
        encoding="utf-8",
    )
    store = LocalAgentConfigurationStore(tmp_path / "config")
    store.create_tool_source(
        source_id="tool_mcp_claims_http",
        name="Claims MCP",
        source_type="mcp_server",
        provider="mcp",
        tool_contract_ids=("claim_status_lookup",),
        credential_env_ref="CLAIMS_MCP_TOKEN",
        params={
            "transport": "http",
            "server_label": "claims_mcp",
            "endpoint": "https://mcp.example.internal",
            "auth": {"type": "bearer_env", "env": "CLAIMS_MCP_TOKEN"},
        },
        actor="operator",
    )
    gateway = ToolGateway.from_file(tools_yaml, configuration_store=store)

    assert (
        gateway.tools["claim_status_lookup"].mcp_contract_snapshot["digest"]
        == tool_contract["mcp_contract_snapshot"]["digest"]
    )


def test_validate_mcp_tool_source_publication_rejects_schema_drift() -> None:
    imported_preview = discover_mcp_tools(
        _mcp_source(),
        env={"CLAIMS_MCP_TOKEN": "secret-token"},
        transport=lambda _connection: (
            MCPDiscoveredTool(
                name="claim.status.lookup",
                description="Lookup claim status",
                input_schema={
                    "type": "object",
                    "properties": {"claim_id": {"type": "string"}},
                    "required": ["claim_id"],
                },
            ),
        ),
    )
    tool_contract = import_mcp_tool_contract(
        imported_preview,
        mcp_tool_name="claim.status.lookup",
        contract_name="claim_status_lookup",
        tool_source_id="tool_mcp_claims_http",
        risk_level="medium",
        read_only=True,
        requires_approval=False,
        allowed_parameters=("claim_id",),
        denied_parameters=("access_token",),
        result_schema={
            "type": "object",
            "properties": {
                "claim_id": {"type": "string"},
                "status": {"type": "string"},
            },
            "required": ["claim_id", "status"],
        },
        summary_fields=("claim_id", "status"),
        result_authority="authoritative_read",
        imported_at="2026-06-20T00:00:00Z",
    )
    source = _mcp_source().model_copy(
        update={"tool_contract_ids": ("claim_status_lookup",)}
    )

    with pytest.raises(ProofAgentError) as blocked:
        validate_mcp_tool_source_publication(
            source,
            tool_contracts=(tool_contract,),
            env={"CLAIMS_MCP_TOKEN": "secret-token"},
            transport=lambda _connection: (
                MCPDiscoveredTool(
                    name="claim.status.lookup",
                    description="Lookup claim status",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "claim_id": {"type": "string"},
                            "customer_id": {"type": "string"},
                        },
                        "required": ["claim_id", "customer_id"],
                    },
                ),
            ),
        )

    assert blocked.value.code == "PA_TOOL_SOURCE_002"
    assert "input schema drift" in blocked.value.message


def test_validate_mcp_tool_source_publication_requires_env_ref_secret() -> None:
    imported_preview = discover_mcp_tools(
        _mcp_source(),
        env={"CLAIMS_MCP_TOKEN": "secret-token"},
        transport=lambda _connection: (
            MCPDiscoveredTool(
                name="claim.status.lookup",
                description="Lookup claim status",
                input_schema={
                    "type": "object",
                    "properties": {"claim_id": {"type": "string"}},
                    "required": ["claim_id"],
                },
            ),
        ),
    )
    tool_contract = import_mcp_tool_contract(
        imported_preview,
        mcp_tool_name="claim.status.lookup",
        contract_name="claim_status_lookup",
        tool_source_id="tool_mcp_claims_http",
        risk_level="medium",
        read_only=True,
        requires_approval=False,
        allowed_parameters=("claim_id",),
        denied_parameters=("access_token",),
        result_schema={
            "type": "object",
            "properties": {
                "claim_id": {"type": "string"},
                "status": {"type": "string"},
            },
            "required": ["claim_id", "status"],
        },
        summary_fields=("claim_id", "status"),
        result_authority="authoritative_read",
        imported_at="2026-06-20T00:00:00Z",
    )
    source = _mcp_source().model_copy(
        update={"tool_contract_ids": ("claim_status_lookup",)}
    )

    with pytest.raises(ProofAgentError) as blocked:
        validate_mcp_tool_source_publication(
            source,
            tool_contracts=(tool_contract,),
            env={},
            transport=lambda _connection: (
                MCPDiscoveredTool(
                    name="claim.status.lookup",
                    description="Lookup claim status",
                    input_schema={
                        "type": "object",
                        "properties": {"claim_id": {"type": "string"}},
                        "required": ["claim_id"],
                    },
                ),
            ),
        )

    assert blocked.value.code == "PA_TOOL_SOURCE_002"
    assert "credential environment variable is missing" in blocked.value.message
