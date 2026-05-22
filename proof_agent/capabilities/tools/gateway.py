from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5

import yaml  # type: ignore[import-untyped]

from proof_agent.contracts import ApprovalState, ApprovalStatus
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
    def from_file(cls, path: str | Path) -> ToolGateway:
        tools_path = Path(path)
        raw = yaml.safe_load(tools_path.read_text(encoding="utf-8")) or {}
        configs = {}
        for tool in raw.get("tools", []):
            config = ToolConfig(
                name=tool["name"],
                handler=_handler_from_mapping(tool.get("handler"), base_dir=tools_path.parent),
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
        tool = _load_tool_callable(config)
        return ToolGatewayResult(
            approval_state=approval_state,
            executed=True,
            result=tool(parameters),
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
    if config.handler is None:
        raise ProofAgentError(
            "PA_TOOL_001",
            f"tool has no local handler: {config.name}",
            "Add handler: ./module.py:function_name to tools.yaml.",
        )
    return _load_callable_from_file(config.handler.path, config.handler.function_name)


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
