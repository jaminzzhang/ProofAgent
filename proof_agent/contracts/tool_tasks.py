"""Package-bound read-only task requirements; never model-granted authority."""
from collections.abc import Mapping
from typing import Any, Literal, Self
import json
import math

from pydantic import BaseModel, Field, field_serializer, field_validator, model_validator
from proof_agent.contracts._base import StrictFrozenModel, freeze_value


class ToolResultBinding(StrictFrozenModel):
    step_id: str = Field(pattern=r'^[a-z][a-z0-9_]{0,63}$')
    path: tuple[str, ...] = Field(min_length=1, max_length=8)


class ExactCalculation(StrictFrozenModel):
    operation: Literal['sum']
    operand_parameter: str = Field(min_length=1, max_length=64)
    result_field: str = Field(min_length=1, max_length=64)


class ToolTaskStep(StrictFrozenModel):
    step_id: str = Field(pattern=r'^[a-z][a-z0-9_]{0,63}$')
    tool_name: str = Field(min_length=1, max_length=128)
    parameters: Mapping[str, Any] = Field(default_factory=dict)
    bindings: Mapping[str, ToolResultBinding] = Field(default_factory=dict)
    calculation: ExactCalculation | None = None
    report_fields: tuple[str, ...] = Field(default_factory=tuple, max_length=32)

    @field_validator('parameters', mode='before')
    @classmethod
    def bounded_json_parameters(cls, value: Any) -> Any:
        nodes = 0
        def check(item: Any, depth: int = 0) -> None:
            nonlocal nodes
            nodes += 1
            if depth > 16 or nodes > 4096:
                raise ValueError('task parameter limit exceeded')
            if isinstance(item, Mapping):
                for key, child in item.items():
                    if not isinstance(key, str):
                        raise ValueError('task parameter key must be a string')
                    check(child, depth + 1)
            elif isinstance(item, (tuple, list)):
                for child in item:
                    check(child, depth + 1)
            elif item is not None and not isinstance(item, (str, bool, int, float)):
                raise ValueError('task parameter must be JSON')
            elif isinstance(item, float) and not math.isfinite(item):
                raise ValueError('task parameter must be finite')
        check(value)
        if len(json.dumps(_json_value(value), ensure_ascii=False, allow_nan=False).encode()) > 65536:
            raise ValueError('task parameter limit exceeded')
        return value

    @field_validator('parameters', 'bindings', mode='after')
    @classmethod
    def freeze(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_serializer('parameters', 'bindings')
    def serialize_mappings(self, value: Any) -> Any:
        return _json_value(value)

    @model_validator(mode='after')
    def validate_parameters(self) -> Self:
        if set(self.parameters) & set(self.bindings):
            raise ValueError('literal and bound parameters overlap')
        if len(self.parameters) + len(self.bindings) > 32:
            raise ValueError('too many task parameters')
        return self


class ToolTaskPlan(StrictFrozenModel):
    schema_version: Literal['tool-task-plan.v1'] = 'tool-task-plan.v1'
    steps: tuple[ToolTaskStep, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode='after')
    def validate_dependencies(self) -> Self:
        # Canonical topological order makes execution and recovery unambiguous.
        seen: set[str] = set()
        for step in self.steps:
            if step.step_id in seen or any(b.step_id not in seen for b in step.bindings.values()):
                raise ValueError('duplicate, cyclic or forward task dependency')
            seen.add(step.step_id)
        return self


def _json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


class ToolTaskReportRow(StrictFrozenModel):
    step_id: str
    tool_name: str
    truth_ref: str
    input_digest: str
    values: Mapping[str, Any]

    @field_validator('values', mode='after')
    @classmethod
    def freeze_values(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_serializer('values')
    def serialize_values(self, value: Any) -> Any:
        return _json_value(value)


class ToolTaskReport(StrictFrozenModel):
    schema_version: Literal['tool-task-report.v1'] = 'tool-task-report.v1'
    run_id: str
    plan_digest: str = Field(pattern=r'^[0-9a-f]{64}$')
    rows: tuple[ToolTaskReportRow, ...] = Field(min_length=1, max_length=8)
