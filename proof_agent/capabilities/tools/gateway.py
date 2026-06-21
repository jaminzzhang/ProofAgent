from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5

import yaml  # type: ignore[import-untyped]

from proof_agent.capabilities.tools.brave_search import (
    BraveSearchTransport,
    create_brave_untrusted_web_search_handler,
)
from proof_agent.capabilities.tools.mcp_runtime import MCPToolCallTransport, call_mcp_tool
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import ApprovalState, ApprovalStatus
from proof_agent.control.tools.untrusted_web import sanitize_web_search_query
from proof_agent.errors import ProofAgentError
from proof_agent.capabilities.tools.approval import create_approval_state
from proof_agent.contracts._base import freeze_value

ToolCallable = Callable[[Mapping[str, Any]], Mapping[str, Any]]


@dataclass(frozen=True)
class LocalToolHandler:
    path: Path
    function_name: str


@dataclass(frozen=True)
class ToolConfig:
    """Static allowlist entry loaded from tools.yaml."""

    name: str
    handler: LocalToolHandler | None
    built_in_handler: ToolCallable | None
    tool_source_id: str | None
    risk_level: str
    requires_approval: bool
    read_only: bool
    allowed_parameters: frozenset[str]
    denied_parameters: frozenset[str]
    source: str = "local"
    mcp_tool_name: str | None = None
    mcp_contract_snapshot: Mapping[str, Any] = field(default_factory=dict)
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    result_schema: Mapping[str, Any] = field(default_factory=dict)
    summary_fields: tuple[str, ...] = field(default_factory=tuple)
    result_authority: str | None = None
    side_effect_class: str | None = None


@dataclass(frozen=True)
class ToolGatewayResult:
    """Result envelope returned whether a tool executed or is waiting for approval."""

    approval_state: ApprovalState
    executed: bool
    result: Mapping[str, Any] | None = None


class ToolGateway:
    """Approval and parameter boundary in front of configured local tool handlers."""

    def __init__(
        self,
        tools: Mapping[str, ToolConfig],
        *,
        configuration_store: LocalAgentConfigurationStore | None = None,
        tool_source_env: Mapping[str, str] | None = None,
        mcp_tool_transport: MCPToolCallTransport | None = None,
    ) -> None:
        self.tools = dict(tools)
        self._configuration_store = configuration_store
        self._tool_source_env = dict(tool_source_env or {})
        self._mcp_tool_transport = mcp_tool_transport

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        *,
        configuration_store: LocalAgentConfigurationStore | None = None,
        tool_source_env: Mapping[str, str] | None = None,
        brave_search_transport: BraveSearchTransport | None = None,
        mcp_tool_transport: MCPToolCallTransport | None = None,
    ) -> ToolGateway:
        tools_path = Path(path)
        raw = yaml.safe_load(tools_path.read_text(encoding="utf-8")) or {}
        configs = {}
        for tool in raw.get("tools", []):
            tool_source_id = _optional_tool_source_id(tool)
            source = str(tool.get("source", "local"))
            config = ToolConfig(
                name=tool["name"],
                handler=_handler_from_mapping(tool.get("handler"), base_dir=tools_path.parent),
                built_in_handler=_built_in_handler_from_tool_source(
                    tool_name=tool["name"],
                    configured_source=source,
                    tool_source_id=tool_source_id,
                    configuration_store=configuration_store,
                    tool_source_env=tool_source_env,
                    brave_search_transport=brave_search_transport,
                ),
                tool_source_id=tool_source_id,
                risk_level=tool["risk_level"],
                requires_approval=bool(tool.get("requires_approval", False)),
                read_only=bool(tool.get("read_only", False)),
                allowed_parameters=frozenset(tool.get("allowed_parameters", [])),
                denied_parameters=frozenset(tool.get("denied_parameters", [])),
                source=source,
                mcp_tool_name=_optional_string(tool.get("mcp_tool_name")),
                mcp_contract_snapshot=_frozen_mapping(tool.get("mcp_contract_snapshot")),
                input_schema=_frozen_mapping(tool.get("input_schema")),
                result_schema=_frozen_mapping(tool.get("result_schema")),
                summary_fields=_string_tuple(
                    tool.get("summary_fields"),
                    field_name="summary_fields",
                ),
                result_authority=_optional_string(tool.get("result_authority")),
                side_effect_class=_optional_string(tool.get("side_effect_class")),
            )
            _validate_tool_contract(config)
            configs[config.name] = config
        return cls(
            configs,
            configuration_store=configuration_store,
            tool_source_env=tool_source_env,
            mcp_tool_transport=mcp_tool_transport,
        )

    def request_tool(
        self,
        *,
        tool_name: str,
        parameters: Mapping[str, Any],
        approved: bool,
        run_id: str = "run_test",
    ) -> ToolGatewayResult:
        """Validate the request, enforce approval, and execute only if permitted."""

        config = self._require_tool(tool_name)
        self._validate_parameters(config, parameters)
        approval_status = ApprovalStatus.GRANTED
        if config.requires_approval and not approved:
            approval_status = ApprovalStatus.REQUESTED
        approval_state = create_approval_state(
            run_id=run_id,
            approval_id=f"appr_{tool_name}",
            state=approval_status,
            tool_name=tool_name,
            reason=_approval_reason(config),
        )
        if config.requires_approval and not approved:
            return ToolGatewayResult(approval_state=approval_state, executed=False)
        execution_parameters, gateway_metadata = _prepare_parameters_for_execution(
            config,
            parameters,
        )
        if config.source == "mcp":
            tool_result = dict(self._call_mcp_tool(config, execution_parameters))
        else:
            tool = _load_tool_callable(config)
            tool_result = dict(tool(execution_parameters))
        tool_result.update(gateway_metadata)
        return ToolGatewayResult(
            approval_state=approval_state,
            executed=True,
            result=tool_result,
        )

    def _require_tool(self, tool_name: str) -> ToolConfig:
        if tool_name not in self.tools:
            raise ProofAgentError(
                "PA_TOOL_001",
                f"tool is not registered: {tool_name}",
                "Add the tool to tools.yaml before requesting it.",
            )
        return self.tools[tool_name]

    def _validate_parameters(self, config: ToolConfig, parameters: Mapping[str, Any]) -> None:
        parameter_names = set(parameters)
        # Denied parameters win even if a future config accidentally allowlists them.
        denied = parameter_names.intersection(config.denied_parameters)
        if denied:
            raise ProofAgentError(
                "PA_TOOL_001",
                f"tool request includes denied parameter(s): {', '.join(sorted(denied))}",
                "Remove denied parameters before calling the tool.",
            )
        unsupported = parameter_names.difference(config.allowed_parameters)
        if unsupported:
            raise ProofAgentError(
                "PA_TOOL_001",
                f"tool request includes unsupported parameter(s): {', '.join(sorted(unsupported))}",
                "Use only parameters declared in tools.yaml.",
            )
        if config.source == "mcp":
            missing = set(_required_schema_fields(config.input_schema)).difference(parameter_names)
            if missing:
                raise ProofAgentError(
                    "PA_TOOL_001",
                    f"tool request is missing required parameter(s): "
                    f"{', '.join(sorted(missing))}",
                    "Provide all parameters required by the MCP Tool Contract input_schema.",
                )

    def _call_mcp_tool(
        self,
        config: ToolConfig,
        parameters: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if config.tool_source_id is None:
            raise ProofAgentError(
                "PA_TOOL_SOURCE_002",
                "MCP tool execution requires tool_source_id.",
                "Bind the MCP Tool Contract to a Tool Source before execution.",
            )
        if config.mcp_tool_name is None:
            raise ProofAgentError(
                "PA_TOOL_SOURCE_002",
                "MCP tool execution requires mcp_tool_name.",
                "Persist the imported MCP server tool name before execution.",
            )
        if self._configuration_store is None:
            raise ProofAgentError(
                "PA_TOOL_SOURCE_002",
                "MCP tool execution requires a configuration store.",
                "Run with a LocalAgentConfigurationStore containing the Tool Source.",
            )
        source = self._configuration_store.get_tool_source(config.tool_source_id)
        if source is None:
            raise ProofAgentError(
                "PA_TOOL_SOURCE_002",
                f"Tool Source not found: {config.tool_source_id}",
                "Create the Tool Source in Dashboard configuration before execution.",
            )
        raw_result = call_mcp_tool(
            source,
            mcp_tool_name=config.mcp_tool_name,
            arguments=parameters,
            env=self._tool_source_env,
            transport=self._mcp_tool_transport,
        )
        _validate_mcp_result_schema(config, raw_result)
        summary = _mcp_summary_projection(config, raw_result)
        result = {
            "provider": "mcp",
            "tool_source_id": config.tool_source_id,
            "tool_contract_id": config.name,
            "mcp_tool_name": config.mcp_tool_name,
            "contract_snapshot_digest": config.mcp_contract_snapshot["digest"],
            "result_schema_validation": "passed",
            "result_classification": _mcp_result_classification(config),
            "summary_fields": config.summary_fields,
            "summary": summary,
        }
        if not config.read_only:
            result.update(
                {
                    "side_effect_class": config.side_effect_class,
                    "idempotency_key_digest": _stable_digest(
                        {"idempotency_key": parameters.get("idempotency_key")}
                    ),
                }
            )
        return result


def _approval_reason(config: ToolConfig) -> str:
    if config.requires_approval:
        return "Human approval required."
    if config.read_only:
        return "Policy-authorized read-only tool allowed."
    return "Tool allowed."


def _handler_from_mapping(raw: Any, *, base_dir: Path) -> LocalToolHandler | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ProofAgentError(
            "PA_TOOL_001",
            "tool handler must be a string.",
            "Use handler: ./module.py:function_name in tools.yaml.",
            artifact_path=base_dir,
        )
    if ":" not in raw:
        raise ProofAgentError(
            "PA_TOOL_001",
            f"tool handler is missing a function name: {raw}",
            "Use handler: ./module.py:function_name in tools.yaml.",
            artifact_path=base_dir,
        )
    raw_path, function_name = raw.rsplit(":", 1)
    path = Path(raw_path)
    if not path.is_absolute():
        path = base_dir / path
    return LocalToolHandler(path=path.resolve(), function_name=function_name)


def _load_tool_callable(config: ToolConfig) -> ToolCallable:
    if config.built_in_handler is not None:
        return config.built_in_handler
    if config.handler is None:
        raise ProofAgentError(
            "PA_TOOL_001",
            f"tool has no local handler: {config.name}",
            "Add handler: ./module.py:function_name or tool_source_id to tools.yaml.",
        )
    return _load_callable_from_file(config.handler.path, config.handler.function_name)


def _optional_tool_source_id(raw: Mapping[str, Any]) -> str | None:
    value = raw.get("tool_source_id")
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ProofAgentError(
            "PA_TOOL_001",
            "tool_source_id must be a non-empty string.",
            "Use a Dashboard-managed Tool Source id, such as tool_brave_default.",
        )
    return value.strip()


def _optional_string(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return str(raw)


def _frozen_mapping(raw: Any) -> Mapping[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ProofAgentError(
            "PA_TOOL_001",
            "tool contract metadata must be a mapping.",
            "Use YAML mappings for schema and snapshot metadata.",
        )
    return cast(Mapping[str, Any], freeze_value(raw))


def _string_tuple(raw: Any, *, field_name: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list | tuple):
        raise ProofAgentError(
            "PA_TOOL_001",
            f"{field_name} must be a list.",
            f"Use YAML list syntax for {field_name}.",
        )
    return tuple(str(item) for item in raw)


def _validate_tool_contract(config: ToolConfig) -> None:
    if config.source != "mcp":
        return
    if config.mcp_tool_name is None:
        raise ProofAgentError(
            "PA_TOOL_001",
            "MCP tools require mcp_tool_name.",
            "Persist the imported server tool name in the Tool Contract.",
        )
    if not config.mcp_contract_snapshot:
        raise ProofAgentError(
            "PA_TOOL_001",
            "MCP tools require mcp_contract_snapshot.",
            "Import the MCP tool through curated discovery before binding it.",
        )
    snapshot_digest = config.mcp_contract_snapshot.get("digest")
    if not isinstance(snapshot_digest, str) or not snapshot_digest.strip():
        raise ProofAgentError(
            "PA_TOOL_001",
            "MCP contract snapshot requires digest.",
            "Persist the imported MCP contract digest in mcp_contract_snapshot.",
        )
    if not config.input_schema:
        raise ProofAgentError(
            "PA_TOOL_001",
            "MCP tools require input_schema.",
            "Persist the imported MCP input schema in the Tool Contract.",
        )
    if not config.result_schema:
        raise ProofAgentError(
            "PA_TOOL_001",
            "MCP tools require result_schema.",
            "Persist the imported MCP result schema in the Tool Contract.",
        )
    if not config.summary_fields:
        raise ProofAgentError(
            "PA_TOOL_001",
            "MCP tools require summary_fields.",
            "Declare the planner-visible result projection in the Tool Contract.",
        )
    if config.read_only:
        if config.result_authority is None:
            raise ProofAgentError(
                "PA_TOOL_001",
                "MCP read tools require result_authority.",
                "Declare whether the read result is authoritative or advisory.",
            )
        return
    if not config.requires_approval:
        raise ProofAgentError(
            "PA_TOOL_001",
            "MCP action tools require approval.",
            "Set requires_approval: true for state-changing MCP tools.",
        )
    if "idempotency_key" not in config.allowed_parameters:
        raise ProofAgentError(
            "PA_TOOL_001",
            "MCP action tools require idempotency_key in allowed_parameters.",
            "Add idempotency_key to the Tool Contract parameter schema and allowlist.",
        )
    if not config.side_effect_class:
        raise ProofAgentError(
            "PA_TOOL_001",
            "MCP action tools require side_effect_class.",
            "Declare the action side effect class for audit and retry governance.",
        )


def _validate_mcp_result_schema(
    config: ToolConfig,
    result: Mapping[str, Any],
) -> None:
    missing = [
        field
        for field in _required_schema_fields(config.result_schema)
        if field not in result
    ]
    if missing:
        raise ProofAgentError(
            "PA_TOOL_SOURCE_002",
            "MCP tool result failed result_schema validation.",
            "Return all fields required by the Tool Contract result_schema.",
        )
    type_errors = [
        field
        for field, expected_type in _schema_property_types(config.result_schema).items()
        if field in result and not _json_schema_type_matches(result[field], expected_type)
    ]
    if type_errors:
        raise ProofAgentError(
            "PA_TOOL_SOURCE_002",
            "MCP tool result failed result_schema validation.",
            "Return values matching the Tool Contract result_schema types.",
        )


def _required_schema_fields(schema: Mapping[str, Any]) -> tuple[str, ...]:
    required = schema.get("required", ())
    if not isinstance(required, list | tuple):
        return ()
    return tuple(str(field) for field in required)


def _schema_property_types(schema: Mapping[str, Any]) -> Mapping[str, str]:
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return {}
    types: dict[str, str] = {}
    for property_name, raw_schema in properties.items():
        if not isinstance(raw_schema, Mapping):
            continue
        raw_type = raw_schema.get("type")
        if isinstance(raw_type, str):
            types[str(property_name)] = raw_type
    return types


def _json_schema_type_matches(value: Any, expected_type: str) -> bool:
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "object":
        return isinstance(value, Mapping)
    if expected_type == "array":
        return isinstance(value, list | tuple)
    if expected_type == "null":
        return value is None
    return True


def _mcp_summary_projection(
    config: ToolConfig,
    result: Mapping[str, Any],
) -> Mapping[str, Any]:
    missing = [field for field in config.summary_fields if field not in result]
    if missing:
        raise ProofAgentError(
            "PA_TOOL_SOURCE_002",
            "MCP tool result is missing summary_fields.",
            "Return all Tool Contract summary_fields from the MCP tool.",
        )
    return {field: result[field] for field in config.summary_fields}


def _mcp_result_classification(config: ToolConfig) -> str:
    if config.read_only and config.result_authority == "authoritative_read":
        return "authorized_tool_result"
    if not config.read_only:
        return "action_confirmation"
    return "observation"


def _stable_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _built_in_handler_from_tool_source(
    *,
    tool_name: str,
    configured_source: str,
    tool_source_id: str | None,
    configuration_store: LocalAgentConfigurationStore | None,
    tool_source_env: Mapping[str, str] | None,
    brave_search_transport: BraveSearchTransport | None,
) -> ToolCallable | None:
    if tool_source_id is None:
        return None
    if configuration_store is None:
        raise ProofAgentError(
            "PA_TOOL_001",
            f"tool_source_id requires a configuration store: {tool_source_id}",
            "Run with a LocalAgentConfigurationStore or use a local handler.",
        )
    source = configuration_store.get_tool_source(tool_source_id)
    if source is None:
        raise ProofAgentError(
            "PA_TOOL_SOURCE_002",
            f"Tool Source not found: {tool_source_id}",
            "Create the Tool Source in Dashboard configuration before binding it.",
        )
    if configured_source == "mcp" and source.provider != "mcp":
        raise ProofAgentError(
            "PA_TOOL_SOURCE_001",
            "MCP tools require an MCP Tool Source.",
            "Bind source: mcp tools only to Tool Sources with provider: mcp.",
        )
    if tool_name == "untrusted_web_search" and source.provider == "brave_search":
        return create_brave_untrusted_web_search_handler(
            source,
            env=tool_source_env or {},
            transport=brave_search_transport,
        )
    if source.provider == "mcp":
        return None
    raise ProofAgentError(
        "PA_TOOL_SOURCE_001",
        f"Unsupported Tool Source binding: {tool_name} -> {source.provider}",
        "Use a built-in descriptor that exposes the requested tool contract.",
    )


def _prepare_parameters_for_execution(
    config: ToolConfig,
    parameters: Mapping[str, Any],
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    if config.name != "untrusted_web_search":
        return parameters, {}
    raw_query = str(parameters.get("query", ""))
    context = sanitize_web_search_query(raw_query)
    if not context.searchable:
        raise ProofAgentError(
            "PA_TOOL_001",
            "untrusted_web_search query is not safe to search after sanitization.",
            "Ask a less identifying question or use controlled knowledge instead.",
        )
    execution_parameters = dict(parameters)
    execution_parameters["query"] = context.sanitized_query
    return execution_parameters, {
        "sanitized_query": context.sanitized_query,
        "sanitization_applied": context.sanitization_applied,
        "sanitization_categories": context.sanitization_categories,
    }


def _load_callable_from_file(path: Path, function_name: str) -> ToolCallable:
    if not path.exists():
        raise ProofAgentError(
            "PA_TOOL_001",
            f"tool handler file does not exist: {path}",
            "Create the handler file or update tools.yaml.",
            artifact_path=path,
        )
    module_name = f"_proof_agent_tool_handler_{uuid5(NAMESPACE_URL, str(path)).hex}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ProofAgentError(
            "PA_TOOL_001",
            f"tool handler file cannot be loaded: {path}",
            "Use a Python file that exports the configured tool function.",
            artifact_path=path,
        )
    module = importlib.util.module_from_spec(spec)
    _exec_module(spec.loader, module)
    handler = getattr(module, function_name, None)
    if not callable(handler):
        raise ProofAgentError(
            "PA_TOOL_001",
            f"tool handler function not found: {function_name}",
            "Export the configured tool function or update tools.yaml.",
            artifact_path=path,
        )
    return cast(ToolCallable, handler)


def _exec_module(loader: Any, module: ModuleType) -> None:
    loader.exec_module(module)
