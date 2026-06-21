from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from typing import Any, cast

import anyio

from proof_agent.capabilities.tools.mcp_discovery import (
    MCPToolSourceConnection,
    build_mcp_tool_source_connection,
)
from proof_agent.contracts import ToolSource
from proof_agent.errors import ProofAgentError


@dataclass(frozen=True)
class MCPToolCallRequest:
    """One governed MCP tools/call request prepared by Tool Gateway."""

    connection: MCPToolSourceConnection
    mcp_tool_name: str
    arguments: Mapping[str, Any]


MCPToolCallTransport = Callable[[MCPToolCallRequest], Mapping[str, Any]]


def call_mcp_tool(
    source: ToolSource,
    *,
    mcp_tool_name: str,
    arguments: Mapping[str, Any],
    env: Mapping[str, str] | None = None,
    transport: MCPToolCallTransport | None = None,
) -> Mapping[str, Any]:
    """Call one MCP tool through a short-lived MCP session."""

    request = MCPToolCallRequest(
        connection=build_mcp_tool_source_connection(source, env=env),
        mcp_tool_name=mcp_tool_name,
        arguments=dict(arguments),
    )
    selected_transport = transport or _default_mcp_tool_call_transport
    return selected_transport(request)


def _default_mcp_tool_call_transport(
    request: MCPToolCallRequest,
) -> Mapping[str, Any]:
    try:
        return anyio.run(_call_tool_with_sdk, request)
    except ProofAgentError:
        raise
    except Exception as exc:
        raise _mcp_execution_error(
            "MCP tools/call failed.",
            "Check MCP Tool Source connectivity and server availability.",
        ) from exc


async def _call_tool_with_sdk(request: MCPToolCallRequest) -> Mapping[str, Any]:
    if request.connection.transport == "stdio":
        return await _call_stdio_tool(request)
    if request.connection.transport == "http":
        return await _call_http_tool(request)
    raise _mcp_execution_error(
        f"MCP {request.connection.transport} runtime transport is not configured.",
        "Use params.transport=stdio or params.transport=http.",
    )


async def _call_stdio_tool(request: MCPToolCallRequest) -> Mapping[str, Any]:
    from datetime import timedelta

    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    if request.connection.command is None or not request.connection.command.strip():
        raise _mcp_execution_error(
            "stdio MCP tools/call requires a command.",
            "Set params.command on the MCP Tool Source.",
        )
    server = StdioServerParameters(
        command=request.connection.command,
        args=list(request.connection.args),
    )
    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(
            read_stream,
            write_stream,
            read_timeout_seconds=timedelta(seconds=request.connection.timeout_seconds),
        ) as session:
            await session.initialize()
            result = await session.call_tool(
                request.mcp_tool_name,
                arguments=dict(request.arguments),
            )
    return _result_to_mapping(result)


async def _call_http_tool(request: MCPToolCallRequest) -> Mapping[str, Any]:
    from datetime import timedelta

    import httpx
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    if request.connection.endpoint is None or not request.connection.endpoint.strip():
        raise _mcp_execution_error(
            "HTTP MCP tools/call requires an endpoint.",
            "Set params.endpoint on the MCP Tool Source.",
        )
    async with httpx.AsyncClient(
        headers=dict(request.connection.http_headers),
        timeout=request.connection.timeout_seconds,
    ) as http_client:
        async with streamable_http_client(
            request.connection.endpoint,
            http_client=http_client,
        ) as (read_stream, write_stream, _get_session_id):
            async with ClientSession(
                read_stream,
                write_stream,
                read_timeout_seconds=timedelta(seconds=request.connection.timeout_seconds),
            ) as session:
                await session.initialize()
                result = await session.call_tool(
                    request.mcp_tool_name,
                    arguments=dict(request.arguments),
                )
    return _result_to_mapping(result)


def _result_to_mapping(result: Any) -> Mapping[str, Any]:
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, Mapping):
        return cast(Mapping[str, Any], structured)
    if isinstance(result, Mapping):
        return result
    content = getattr(result, "content", None)
    if isinstance(content, list | tuple) and content:
        first = content[0]
        text = getattr(first, "text", None)
        if isinstance(text, str):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return {"content": text}
            if isinstance(parsed, Mapping):
                return cast(Mapping[str, Any], parsed)
    raise _mcp_execution_error(
        "MCP tools/call returned an unsupported result shape.",
        "Return a structured object or JSON text object from the MCP tool.",
    )


def _mcp_execution_error(message: str, remediation: str) -> ProofAgentError:
    return ProofAgentError("PA_TOOL_SOURCE_002", message, remediation)
