from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
import hashlib
import json
from typing import Any, cast
from urllib.parse import urlparse

import anyio
from pydantic import Field, field_serializer, field_validator

from proof_agent.contracts import ToolSource, ToolSourceLifecycleState
from proof_agent.contracts._base import FrozenDict, FrozenModel, freeze_value
from proof_agent.errors import ProofAgentError

MCPDiscoveryTransport = Callable[["MCPToolSourceConnection"], tuple["MCPDiscoveredTool", ...]]


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value


@dataclass(frozen=True)
class MCPToolSourceConnection:
    """Internal connection details for one short-lived MCP discovery session."""

    tool_source_id: str
    transport: str
    server_label: str
    timeout_seconds: float
    command: str | None = None
    args: tuple[str, ...] = ()
    endpoint: str | None = None
    auth_type: str = "no_auth"
    credential_header_name: str | None = None
    credential_env_ref: str | None = None
    credential_value: str | None = None

    @property
    def trace_safe_metadata(self) -> Mapping[str, str]:
        metadata = {
            "tool_source_id": self.tool_source_id,
            "provider": "mcp",
            "transport": self.transport,
            "server_label": self.server_label,
        }
        if self.endpoint is not None:
            metadata["endpoint_host"] = urlparse(self.endpoint).netloc
        if self.command is not None:
            metadata["command_digest"] = _stable_digest(
                {"command": self.command, "args": self.args}
            )
        if self.credential_env_ref is not None:
            metadata["credential_env_ref"] = self.credential_env_ref
        return metadata

    @property
    def http_headers(self) -> Mapping[str, str]:
        if self.auth_type == "bearer_env" and self.credential_value:
            return {"Authorization": f"Bearer {self.credential_value}"}
        if self.auth_type == "header_env" and self.credential_header_name and self.credential_value:
            return {self.credential_header_name: self.credential_value}
        return {}


class MCPDiscoveredTool(FrozenModel):
    """Trace-safe normalized MCP tool discovery preview item."""

    name: str
    description: str = ""
    input_schema: Mapping[str, Any] = Field(default_factory=FrozenDict)
    schema_digest: str = ""

    @field_validator("input_schema", mode="after")
    @classmethod
    def freeze_input_schema(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_serializer("input_schema")
    def serialize_input_schema(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(value))


class MCPDiscoveryPreview(FrozenModel):
    """Trace-safe preview returned by MCP Tool Discovery."""

    tool_source_id: str
    provider: str
    transport: str
    server_label: str
    tool_count: int
    trace_safe_metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)
    tools: tuple[MCPDiscoveredTool, ...] = Field(default_factory=tuple)

    @field_validator("trace_safe_metadata", mode="after")
    @classmethod
    def freeze_trace_safe_metadata(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_serializer("trace_safe_metadata")
    def serialize_trace_safe_metadata(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(value))


def discover_mcp_tools(
    source: ToolSource,
    *,
    env: Mapping[str, str] | None = None,
    transport: MCPDiscoveryTransport | None = None,
) -> MCPDiscoveryPreview:
    """Initialize an MCP Tool Source, list tools, and return a trace-safe preview."""

    connection = build_mcp_tool_source_connection(source, env=env)
    selected_transport = transport or _default_mcp_discovery_transport
    tools = tuple(_normalize_discovered_tool(tool) for tool in selected_transport(connection))
    return MCPDiscoveryPreview(
        tool_source_id=source.source_id,
        provider=source.provider,
        transport=connection.transport,
        server_label=connection.server_label,
        tool_count=len(tools),
        trace_safe_metadata=connection.trace_safe_metadata,
        tools=tools,
    )


def build_mcp_tool_source_connection(
    source: ToolSource,
    *,
    env: Mapping[str, str] | None = None,
) -> MCPToolSourceConnection:
    """Build trace-safe MCP connection details from a Tool Source."""

    return _connection_from_source(source, env=env or {})


def import_mcp_tool_contract(
    preview: MCPDiscoveryPreview,
    *,
    mcp_tool_name: str,
    contract_name: str,
    tool_source_id: str,
    risk_level: str,
    read_only: bool,
    requires_approval: bool,
    allowed_parameters: tuple[str, ...],
    denied_parameters: tuple[str, ...],
    result_schema: Mapping[str, Any],
    summary_fields: tuple[str, ...],
    result_authority: str | None = None,
    side_effect_class: str | None = None,
    imported_at: str,
) -> Mapping[str, Any]:
    """Convert one discovered MCP tool into a frozen Tool Contract mapping."""

    selected_tool = _require_discovered_tool(preview, mcp_tool_name)
    input_schema = _immutable_jsonable(selected_tool.input_schema)
    frozen_result_schema = _immutable_jsonable(result_schema)
    input_schema_digest = selected_tool.schema_digest or _stable_digest(input_schema)
    result_schema_digest = _stable_digest(frozen_result_schema)
    snapshot = {
        "digest": _stable_digest(
            {
                "tool_source_id": tool_source_id,
                "mcp_tool_name": mcp_tool_name,
                "imported_at": imported_at,
                "input_schema_digest": input_schema_digest,
                "result_schema_digest": result_schema_digest,
            }
        ),
        "imported_at": imported_at,
        "input_schema_digest": input_schema_digest,
        "result_schema_digest": result_schema_digest,
    }
    contract: dict[str, Any] = {
        "name": contract_name,
        "source": "mcp",
        "tool_source_id": tool_source_id,
        "mcp_tool_name": mcp_tool_name,
        "mcp_contract_snapshot": snapshot,
        "risk_level": risk_level,
        "requires_approval": requires_approval,
        "read_only": read_only,
        "allowed_parameters": tuple(allowed_parameters),
        "denied_parameters": tuple(denied_parameters),
        "input_schema": input_schema,
        "result_schema": frozen_result_schema,
        "summary_fields": tuple(summary_fields),
    }
    if result_authority is not None:
        contract["result_authority"] = result_authority
    if side_effect_class is not None:
        contract["side_effect_class"] = side_effect_class
    return contract


def validate_mcp_tool_source_publication(
    source: ToolSource,
    *,
    tool_contracts: tuple[Mapping[str, Any], ...],
    env: Mapping[str, str] | None = None,
    transport: MCPDiscoveryTransport | None = None,
) -> MCPDiscoveryPreview:
    """Validate live MCP source/tool compatibility before Agent publication."""

    preview = discover_mcp_tools(source, env=env, transport=transport)
    discovered_by_name = {tool.name: tool for tool in preview.tools}
    for contract in tool_contracts:
        if contract.get("source") != "mcp":
            continue
        if contract.get("tool_source_id") != source.source_id:
            raise _mcp_discovery_error(
                f"MCP Tool Contract {contract.get('name', '<unknown>')} is bound "
                f"to a different Tool Source.",
                "Validate each MCP Tool Contract against its configured Tool Source.",
            )
        contract_name = _required_contract_string(contract, "name")
        if contract_name not in source.tool_contract_ids:
            raise _mcp_discovery_error(
                f"Tool Source {source.source_id} has not imported Tool Contract {contract_name}.",
                "Import the MCP tool through curated discovery before publishing the Agent.",
            )
        mcp_tool_name = _required_contract_string(contract, "mcp_tool_name")
        discovered_tool = discovered_by_name.get(mcp_tool_name)
        if discovered_tool is None:
            raise _mcp_discovery_error(
                f"MCP tool was not discovered during publication validation: {mcp_tool_name}.",
                "Refresh discovery and bind only tools still exposed by the MCP server.",
            )
        snapshot = contract.get("mcp_contract_snapshot")
        if not isinstance(snapshot, Mapping):
            raise _mcp_discovery_error(
                f"MCP Tool Contract {contract_name} is missing a contract snapshot.",
                "Import the MCP tool through curated discovery before publishing the Agent.",
            )
        expected_input_digest = snapshot.get("input_schema_digest")
        if not isinstance(expected_input_digest, str) or not expected_input_digest.strip():
            raise _mcp_discovery_error(
                f"MCP Tool Contract {contract_name} is missing input_schema_digest.",
                "Persist the imported input schema digest before publishing the Agent.",
            )
        if discovered_tool.schema_digest != expected_input_digest:
            raise _mcp_discovery_error(
                f"MCP tool input schema drift for {mcp_tool_name}.",
                "Refresh discovery and import a new Tool Contract revision before publishing.",
            )
    return preview


def _connection_from_source(
    source: ToolSource,
    *,
    env: Mapping[str, str],
) -> MCPToolSourceConnection:
    if source.provider != "mcp":
        raise _mcp_discovery_error(
            f"Tool Source {source.source_id} is not an MCP source.",
            "Use provider=mcp for MCP Tool Discovery.",
        )
    if source.lifecycle_state is ToolSourceLifecycleState.ARCHIVED:
        raise _mcp_discovery_error(
            f"Tool Source {source.source_id} is archived.",
            "Restore the Tool Source before MCP Tool Discovery.",
        )
    transport = str(source.params.get("transport", "")).strip()
    server_label = str(source.params.get("server_label", "")).strip()
    if transport == "stdio":
        return MCPToolSourceConnection(
            tool_source_id=source.source_id,
            transport=transport,
            server_label=server_label,
            timeout_seconds=_timeout_seconds(source),
            command=str(source.params.get("command", "")).strip(),
            args=tuple(str(arg) for arg in source.params.get("args", ())),
        )
    if transport == "http":
        auth = source.params.get("auth", {})
        auth_type = "no_auth"
        credential_header_name: str | None = None
        if isinstance(auth, Mapping):
            auth_type = str(auth.get("type", "no_auth"))
            raw_header = auth.get("header")
            if raw_header is not None:
                credential_header_name = str(raw_header).strip() or None
        credential_env_ref = source.credential_env_ref
        credential_value = env.get(credential_env_ref, "") if credential_env_ref else None
        if auth_type in {"bearer_env", "header_env"}:
            if credential_env_ref is None:
                raise _mcp_discovery_error(
                    "MCP credential environment variable is missing.",
                    "Configure credential_env_ref for authenticated HTTP MCP Tool Sources.",
                )
            if not credential_value:
                raise _mcp_discovery_error(
                    "MCP credential environment variable is missing.",
                    f"Set {credential_env_ref} before MCP Tool Source publication validation.",
                )
        return MCPToolSourceConnection(
            tool_source_id=source.source_id,
            transport=transport,
            server_label=server_label,
            timeout_seconds=_timeout_seconds(source),
            endpoint=str(source.params.get("endpoint", "")).strip(),
            auth_type=auth_type,
            credential_header_name=credential_header_name,
            credential_env_ref=credential_env_ref,
            credential_value=credential_value,
        )
    raise _mcp_discovery_error(
        f"Unsupported MCP transport: {transport or '<missing>'}.",
        "Use params.transport=stdio or params.transport=http.",
    )


def _normalize_discovered_tool(tool: MCPDiscoveredTool) -> MCPDiscoveredTool:
    return MCPDiscoveredTool(
        name=tool.name,
        description=tool.description,
        input_schema=tool.input_schema,
        schema_digest=_stable_digest(tool.input_schema),
    )


def _require_discovered_tool(
    preview: MCPDiscoveryPreview,
    mcp_tool_name: str,
) -> MCPDiscoveredTool:
    for tool in preview.tools:
        if tool.name == mcp_tool_name:
            return tool
    raise _mcp_discovery_error(
        f"MCP tool was not discovered: {mcp_tool_name}.",
        "Run discovery again and import only a listed MCP tool.",
    )


def _required_contract_string(contract: Mapping[str, Any], field_name: str) -> str:
    value = contract.get(field_name)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise _mcp_discovery_error(
        f"MCP Tool Contract requires {field_name}.",
        f"Persist {field_name} in the imported Tool Contract.",
    )


def _stable_digest(value: Any) -> str:
    payload = json.dumps(
        _jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _immutable_jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _immutable_jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return tuple(_immutable_jsonable(item) for item in value)
    return value


def _timeout_seconds(source: ToolSource) -> float:
    raw = source.params.get("timeout_seconds", 10)
    try:
        return max(1.0, float(raw))
    except (TypeError, ValueError):
        return 10.0


def _default_mcp_discovery_transport(
    connection: MCPToolSourceConnection,
) -> tuple[MCPDiscoveredTool, ...]:
    if connection.transport == "stdio":
        return _run_sdk_discovery(connection, _discover_stdio_tools)
    if connection.transport == "http":
        return _run_sdk_discovery(connection, _discover_http_tools)
    raise _mcp_discovery_error(
        f"MCP {connection.transport} discovery transport is not configured.",
        "Pass an MCPDiscoveryTransport or use a concrete MCP SDK adapter.",
    )


def _run_sdk_discovery(
    connection: MCPToolSourceConnection,
    discovery: Callable[[MCPToolSourceConnection], Any],
) -> tuple[MCPDiscoveredTool, ...]:
    try:
        return cast(tuple[MCPDiscoveredTool, ...], anyio.run(discovery, connection))
    except ProofAgentError:
        raise
    except Exception as exc:
        raise _mcp_discovery_error(
            f"MCP {connection.transport} discovery failed.",
            "Check MCP Tool Source connectivity and server availability.",
        ) from exc


async def _discover_stdio_tools(
    connection: MCPToolSourceConnection,
) -> tuple[MCPDiscoveredTool, ...]:
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    if connection.command is None or not connection.command.strip():
        raise _mcp_discovery_error(
            "stdio MCP discovery requires a command.",
            "Set params.command on the MCP Tool Source.",
        )
    server = StdioServerParameters(
        command=connection.command,
        args=list(connection.args),
    )
    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(
            read_stream,
            write_stream,
            read_timeout_seconds=timedelta(seconds=connection.timeout_seconds),
        ) as session:
            await session.initialize()
            result = await session.list_tools()
    return tuple(_tool_from_sdk(tool) for tool in result.tools)


async def _discover_http_tools(
    connection: MCPToolSourceConnection,
) -> tuple[MCPDiscoveredTool, ...]:
    import httpx
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    if connection.endpoint is None or not connection.endpoint.strip():
        raise _mcp_discovery_error(
            "HTTP MCP discovery requires an endpoint.",
            "Set params.endpoint on the MCP Tool Source.",
        )
    async with httpx.AsyncClient(
        headers=dict(connection.http_headers),
        timeout=connection.timeout_seconds,
        trust_env=False,
    ) as http_client:
        async with streamable_http_client(
            connection.endpoint,
            http_client=http_client,
        ) as (read_stream, write_stream, _get_session_id):
            async with ClientSession(
                read_stream,
                write_stream,
                read_timeout_seconds=timedelta(seconds=connection.timeout_seconds),
            ) as session:
                await session.initialize()
                result = await session.list_tools()
    return tuple(_tool_from_sdk(tool) for tool in result.tools)


def _tool_from_sdk(tool: Any) -> MCPDiscoveredTool:
    return MCPDiscoveredTool(
        name=str(tool.name),
        description=str(tool.description or ""),
        input_schema=cast(Mapping[str, Any], tool.inputSchema),
    )


def _mcp_discovery_error(message: str, remediation: str) -> ProofAgentError:
    return ProofAgentError("PA_TOOL_SOURCE_002", message, remediation)
