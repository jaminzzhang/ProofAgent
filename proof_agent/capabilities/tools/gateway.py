from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5

import yaml  # type: ignore[import-untyped]

from proof_agent.capabilities.tools.brave_search import (
    BraveSearchTransport,
    create_brave_untrusted_web_search_handler,
)
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import ApprovalState, ApprovalStatus
from proof_agent.control.tools.untrusted_web import sanitize_web_search_query
from proof_agent.errors import ProofAgentError
from proof_agent.capabilities.tools.approval import create_approval_state

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


@dataclass(frozen=True)
class ToolGatewayResult:
    """Result envelope returned whether a tool executed or is waiting for approval."""

    approval_state: ApprovalState
    executed: bool
    result: Mapping[str, Any] | None = None


class ToolGateway:
    """Approval and parameter boundary in front of configured local tool handlers."""

    def __init__(self, tools: Mapping[str, ToolConfig]) -> None:
        self.tools = dict(tools)

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        *,
        configuration_store: LocalAgentConfigurationStore | None = None,
        tool_source_env: Mapping[str, str] | None = None,
        brave_search_transport: BraveSearchTransport | None = None,
    ) -> ToolGateway:
        tools_path = Path(path)
        raw = yaml.safe_load(tools_path.read_text(encoding="utf-8")) or {}
        configs = {}
        for tool in raw.get("tools", []):
            tool_source_id = _optional_tool_source_id(tool)
            config = ToolConfig(
                name=tool["name"],
                handler=_handler_from_mapping(tool.get("handler"), base_dir=tools_path.parent),
                built_in_handler=_built_in_handler_from_tool_source(
                    tool_name=tool["name"],
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
            )
            configs[config.name] = config
        return cls(configs)

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


def _built_in_handler_from_tool_source(
    *,
    tool_name: str,
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
    if tool_name == "untrusted_web_search" and source.provider == "brave_search":
        return create_brave_untrusted_web_search_handler(
            source,
            env=tool_source_env or {},
            transport=brave_search_transport,
        )
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
