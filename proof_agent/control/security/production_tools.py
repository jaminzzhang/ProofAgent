from __future__ import annotations

from collections.abc import Mapping
import json
import re
from typing import Any
from urllib.parse import urlsplit

import yaml  # type: ignore[import-untyped]

from proof_agent.contracts import ToolSource
from proof_agent.errors import ProofAgentError


_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_MAX_TOOLS_YAML_BYTES = 1024 * 1024
_MAX_SCHEMA_NODES = 4_096
_MAX_SCHEMA_DEPTH = 16
_MAX_SCHEMA_BYTES = 256 * 1024


def require_production_tool_contracts(tools_yaml: str) -> tuple[Mapping[str, Any], ...]:
    """Validate the complete initial-release production Tool Contract boundary."""

    if len(tools_yaml.encode("utf-8")) > _MAX_TOOLS_YAML_BYTES:
        raise _denied("production Tool Contract bundle exceeds its byte limit")
    try:
        raw = yaml.safe_load(tools_yaml) or {}
    except yaml.YAMLError as exc:
        raise _denied("production Tool Contract bundle is invalid YAML") from exc
    if not isinstance(raw, Mapping):
        raise _denied("production tools.yaml root must be a mapping")
    raw_tools = raw.get("tools", ())
    if raw_tools in ({}, None):
        return ()
    if not isinstance(raw_tools, list | tuple):
        raise _denied("production tools must be a list")
    contracts: list[Mapping[str, Any]] = []
    for raw_tool in raw_tools:
        if not isinstance(raw_tool, Mapping):
            raise _denied("production Tool Contract must be a mapping")
        tool = dict(raw_tool)
        name = tool.get("name")
        if not isinstance(name, str) or not name.strip():
            raise _denied("production Tool Contract requires a name")
        if "handler" in tool:
            raise _denied("production tools forbid every local handler")
        if tool.get("source") != "mcp":
            raise _denied("production tools require a managed MCP HTTPS source")
        if tool.get("effect") != "read":
            raise _denied("production tools require explicit effect: read")
        if tool.get("read_only") is not True:
            raise _denied("production tools must be read-only")
        if tool.get("requires_approval") is not False:
            raise _denied("production tools cannot require workflow approval")
        source_id = tool.get("tool_source_id")
        if not isinstance(source_id, str) or not source_id.strip():
            raise _denied("production tools require a managed Tool Source binding")
        snapshot = tool.get("mcp_contract_snapshot")
        digest = snapshot.get("digest") if isinstance(snapshot, Mapping) else None
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            raise _denied("production Tool Contract requires an immutable SHA-256 digest")
        _require_bounded_schema(tool.get("input_schema"), field_name="input_schema")
        _require_bounded_schema(tool.get("result_schema"), field_name="result_schema")
        for field_name in ("allowed_parameters", "denied_parameters", "summary_fields"):
            values = tool.get(field_name)
            if (
                not isinstance(values, list | tuple)
                or len(values) > 128
                or any(not isinstance(value, str) or not value for value in values)
            ):
                raise _denied(f"production Tool Contract {field_name} is invalid")
        contracts.append(tool)
    return tuple(contracts)


def require_production_mcp_source(source: ToolSource) -> None:
    """Require one active, exact-origin, environment-secret-free MCP source."""

    if source.provider != "mcp" or source.source_type != "mcp_server":
        raise _denied("production tools require a managed MCP HTTPS source")
    if source.params.get("transport") != "http":
        raise _denied("production tools forbid MCP stdio")
    endpoint = source.params.get("endpoint")
    if not isinstance(endpoint, str):
        raise _denied("production MCP Tool Source requires one exact HTTPS origin")
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except ValueError as exc:
        raise _denied("production MCP Tool Source origin is malformed") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.hostname.endswith(".")
        or "*" in parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise _denied("production MCP Tool Source requires one exact HTTPS origin")
    if source.credential_env_ref is not None:
        raise _denied("production Tool Source cannot reference an environment credential")
    auth = source.params.get("auth")
    if not isinstance(auth, Mapping) or auth.get("type") != "no_auth":
        raise _denied(
            "initial production MCP Tool Source supports no_auth until Secret Handle binding "
            "is configured"
        )


def _require_bounded_schema(value: object, *, field_name: str) -> None:
    if not isinstance(value, Mapping):
        raise _denied(f"production Tool Contract {field_name} must be a mapping")
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    except (TypeError, ValueError, RecursionError) as exc:
        raise _denied(f"production Tool Contract {field_name} is invalid") from exc
    if len(encoded) > _MAX_SCHEMA_BYTES:
        raise _denied(f"production Tool Contract {field_name} exceeds its byte limit")
    pending: list[tuple[object, int]] = [(value, 1)]
    nodes = 0
    while pending:
        current, depth = pending.pop()
        nodes += 1
        if nodes > _MAX_SCHEMA_NODES or depth > _MAX_SCHEMA_DEPTH:
            raise _denied(f"production Tool Contract {field_name} exceeds structural limits")
        if isinstance(current, Mapping):
            pending.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list | tuple):
            pending.extend((item, depth + 1) for item in current)


def _denied(message: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_TOOL_001",
        message,
        "Publish only a validated, immutable, read-only MCP HTTPS Tool Contract.",
    )


__all__ = ["require_production_mcp_source", "require_production_tool_contracts"]
