from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from typing import Any

from proof_agent.contracts import (
    BoundToolProposal,
    ControlledReActRunState,
    EffectiveToolProposalScope,
    ReActActionProposal,
    ToolProposalInterface,
    ToolProposalParameter,
    ToolProposalParameterSource,
)
from proof_agent.errors import ProofAgentError


class ToolProposalParameterBinder:
    """Bind a valid planner tool proposal into execution-ready parameters."""

    def bind(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
        scope: EffectiveToolProposalScope,
    ) -> BoundToolProposal:
        interface = _require_interface(scope, action.target_tool_name)
        parameters: dict[str, Any] = {}
        sources: dict[str, str] = {}
        raw_parameters = dict(action.parameters)
        system_parameter_names = {
            parameter.name
            for parameter in interface.parameters
            if parameter.value_source is ToolProposalParameterSource.SYSTEM_GENERATED
        }
        spoofed_system_parameters = set(raw_parameters).intersection(system_parameter_names)
        if spoofed_system_parameters:
            raise _binding_error(
                "tool proposal includes planner-supplied system-generated parameter.",
                "Remove system-generated parameters from planner proposals.",
            )
        for parameter in interface.parameters:
            if parameter.value_source is ToolProposalParameterSource.SYSTEM_GENERATED:
                parameters[parameter.name] = _system_parameter_value(
                    state,
                    action,
                    interface,
                    parameter,
                )
                sources[parameter.name] = parameter.value_source.value
                continue
            if parameter.name not in raw_parameters:
                if parameter.required:
                    raise _binding_error(
                        "tool proposal is missing required parameter.",
                        "Ask for the missing value before proposing the tool.",
                    )
                continue
            parameters[parameter.name] = raw_parameters[parameter.name]
            sources[parameter.name] = parameter.value_source.value
        unsupported = set(raw_parameters).difference(
            parameter.name for parameter in interface.parameters
        )
        if unsupported:
            raise _binding_error(
                "tool proposal includes unsupported parameter.",
                "Use only parameters exposed by the Tool Proposal Interface.",
            )
        return BoundToolProposal(
            action_id=action.action_id,
            tool_contract_id=interface.tool_contract_id,
            parameters=parameters,
            parameter_sources=sources,
            parameter_digest=_stable_digest(parameters),
            scope_digest=scope.schema_digest,
        )


def _require_interface(
    scope: EffectiveToolProposalScope,
    tool_name: str | None,
) -> ToolProposalInterface:
    for interface in scope.tool_interfaces:
        if interface.tool_contract_id == tool_name:
            return interface
    raise _binding_error(
        "tool proposal target is outside Effective Tool Proposal Scope.",
        "Propose only tools admitted into Effective Tool Proposal Scope.",
    )


def _system_parameter_value(
    state: ControlledReActRunState,
    action: ReActActionProposal,
    interface: ToolProposalInterface,
    parameter: ToolProposalParameter,
) -> str:
    if parameter.name == "idempotency_key":
        return f"{state.run_id}:{action.action_id}:{interface.tool_contract_id}"
    return _stable_digest(
        {
            "run_id": state.run_id,
            "action_id": action.action_id,
            "tool_contract_id": interface.tool_contract_id,
            "parameter": parameter.name,
        }
    )


def _binding_error(message: str, remediation: str) -> ProofAgentError:
    return ProofAgentError("PA_TOOL_PROPOSAL_001", message, remediation)


def _stable_digest(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        _jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _jsonable(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_jsonable(item) for item in value]
    return value
