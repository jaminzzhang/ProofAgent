from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from proof_agent.contracts import ApprovalState, ApprovalStatus
from proof_agent.errors import ProofAgentError
from proof_agent.tools.approval import create_approval_state
from proof_agent.tools.registry import get_tool_callable


@dataclass(frozen=True)
class ToolConfig:
    name: str
    risk_level: str
    requires_approval: bool
    allowed_parameters: frozenset[str]
    denied_parameters: frozenset[str]


@dataclass(frozen=True)
class ToolGatewayResult:
    approval_state: ApprovalState
    executed: bool
    result: Mapping[str, Any] | None = None


class ToolGateway:
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
                risk_level=tool["risk_level"],
                requires_approval=bool(tool.get("requires_approval", False)),
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
        config = self._require_tool(tool_name)
        self._validate_parameters(config, parameters)
        approval_state = create_approval_state(
            run_id=run_id,
            approval_id=f"appr_{tool_name}",
            state=ApprovalStatus.GRANTED if approved else ApprovalStatus.REQUESTED,
            tool_name=tool_name,
            reason="Human approval required." if config.requires_approval else "Tool allowed.",
        )
        if config.requires_approval and not approved:
            return ToolGatewayResult(approval_state=approval_state, executed=False)
        tool = get_tool_callable(tool_name)
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
