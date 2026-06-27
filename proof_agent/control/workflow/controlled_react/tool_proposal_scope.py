from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from typing import Any

from proof_agent.contracts import (
    ControlledReActRunState,
    EffectiveToolProposalScope,
    ToolProposalInterface,
    ToolProposalParameter,
    ToolProposalParameterSource,
)


class ToolProposalScopeResolver:
    """Derive planner-visible tool proposal scope for one ReAct plan round."""

    def resolve(
        self,
        state: ControlledReActRunState,
        *,
        tools: Mapping[str, Any],
        remaining_call_budget: int | None = None,
    ) -> EffectiveToolProposalScope:
        interfaces = tuple(
            self._interface_from_tool(
                tool,
                remaining_call_budget=remaining_call_budget,
            )
            for _, tool in sorted(tools.items(), key=lambda item: item[0])
        )
        return EffectiveToolProposalScope(
            run_id=state.run_id,
            plan_round=state.plan_round,
            tool_interfaces=interfaces,
            excluded={},
            schema_digest=_stable_digest(
                [_interface_digest_payload(interface) for interface in interfaces]
            ),
        )

    def _interface_from_tool(
        self,
        tool: Any,
        *,
        remaining_call_budget: int | None,
    ) -> ToolProposalInterface:
        input_schema = _mapping_field(tool, "input_schema")
        required = set(_required_schema_fields(input_schema))
        denied = set(_iterable_field(tool, "denied_parameters"))
        parameters = tuple(
            ToolProposalParameter(
                name=name,
                required=name in required,
                value_type=_schema_property_type(input_schema, name),
                value_source=_parameter_source(name),
                description=_schema_property_description(input_schema, name),
            )
            for name in sorted(set(_iterable_field(tool, "allowed_parameters")) - denied)
        )
        return ToolProposalInterface(
            tool_contract_id=str(_field(tool, "name")),
            purpose=_tool_purpose(tool),
            risk_level=str(_field(tool, "risk_level")),
            read_only=bool(_field(tool, "read_only")),
            requires_approval=bool(_field(tool, "requires_approval")),
            semantic_result_summary=_semantic_result_summary(
                _iterable_field(tool, "summary_fields")
            ),
            parameters=parameters,
            source=str(_field(tool, "source")),
            remaining_call_budget=remaining_call_budget,
        )


def _field(tool: Any, name: str) -> Any:
    if isinstance(tool, Mapping):
        return tool.get(name)
    return getattr(tool, name)


def _mapping_field(tool: Any, name: str) -> Mapping[str, Any]:
    value = _field(tool, name)
    if isinstance(value, Mapping):
        return value
    return {}


def _iterable_field(tool: Any, name: str) -> tuple[str, ...]:
    value = _field(tool, name)
    if isinstance(value, str) or value is None:
        return ()
    return tuple(str(item) for item in value)


def _required_schema_fields(schema: Mapping[str, Any]) -> tuple[str, ...]:
    required = schema.get("required")
    if not isinstance(required, list | tuple):
        return ()
    return tuple(str(field) for field in required)


def _schema_property_type(schema: Mapping[str, Any], name: str) -> str:
    property_schema = _schema_property(schema, name)
    raw_type = property_schema.get("type")
    return str(raw_type) if isinstance(raw_type, str) else "string"


def _schema_property_description(schema: Mapping[str, Any], name: str) -> str | None:
    property_schema = _schema_property(schema, name)
    description = property_schema.get("description")
    if isinstance(description, str) and description.strip():
        return description.strip()
    return None


def _schema_property(schema: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return {}
    property_schema = properties.get(name)
    if isinstance(property_schema, Mapping):
        return property_schema
    return {}


def _parameter_source(name: str) -> ToolProposalParameterSource:
    if name == "idempotency_key":
        return ToolProposalParameterSource.SYSTEM_GENERATED
    return ToolProposalParameterSource.USER_SUPPLIED


def _semantic_result_summary(summary_fields: tuple[str, ...]) -> str | None:
    if not summary_fields:
        return None
    return "Returns " + ", ".join(summary_fields) + "."


def _tool_purpose(tool: Any) -> str:
    name = str(_field(tool, "name"))
    return name.replace("_", " ")


def _stable_digest(value: Any) -> str:
    payload = json.dumps(
        _jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _interface_digest_payload(interface: ToolProposalInterface) -> Mapping[str, Any]:
    return {
        "tool_contract_id": interface.tool_contract_id,
        "purpose": interface.purpose,
        "risk_level": interface.risk_level,
        "read_only": interface.read_only,
        "requires_approval": interface.requires_approval,
        "semantic_result_summary": interface.semantic_result_summary,
        "parameters": [
            {
                "name": parameter.name,
                "required": parameter.required,
                "value_type": parameter.value_type,
                "value_source": parameter.value_source.value,
                "description": parameter.description,
                "enum_values": parameter.enum_values,
            }
            for parameter in interface.parameters
        ],
        "source": interface.source,
        "remaining_call_budget": interface.remaining_call_budget,
    }


def _jsonable(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | frozenset | set):
        return [_jsonable(item) for item in value]
    return value
