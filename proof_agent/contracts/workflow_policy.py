"""Opt-in workflow controls; preferences never grant evidence or tool authority."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, Self

from pydantic import Field, field_serializer, field_validator, model_validator

from proof_agent.contracts._base import StrictFrozenModel, freeze_value

Complexity = Literal['lite', 'standard', 'deep']
ClarificationIntensity = Literal['minimal', 'balanced', 'thorough']
InteractionStage = Literal['goal', 'plan', 'evidence', 'tool_input', 'finalization']
InteractionReason = Literal['required_context', 'material_ambiguity', 'preference',
    'retrievable', 'scope_change', 'budget_change', 'applicability_unresolved',
    'required_parameter', 'user_preference_blocking']


class WorkflowBudget(StrictFrozenModel):
    max_model_calls: int = Field(default=16, ge=2, le=128, strict=True)
    max_retrieval_calls: int = Field(default=5, ge=1, le=32, strict=True)
    max_tool_calls: int = Field(default=4, ge=0, le=8, strict=True)
    max_total_tokens: int = Field(default=64000, ge=512, le=1000000, strict=True)
    reserved_output_tokens: int = Field(default=2048, ge=64, le=32768, strict=True)
    max_active_seconds: int = Field(default=120, ge=1, le=120, strict=True)

    @model_validator(mode='after')
    def reserve_fits(self) -> Self:
        if self.reserved_output_tokens >= self.max_total_tokens:
            raise ValueError('Output reservation must leave room for model input.')
        return self


class WorkflowReasoning(StrictFrozenModel):
    effort: Literal['off', 'low', 'medium', 'high', 'xhigh', 'max'] | None = None
    unsupported: Literal['reject'] = 'reject'


class WorkflowExecutionPolicy(StrictFrozenModel):
    complexity: Complexity = 'standard'
    ceiling: Complexity = 'deep'
    auto_escalate: bool = True
    reasoning: WorkflowReasoning = Field(default_factory=WorkflowReasoning)
    budget: WorkflowBudget = Field(default_factory=WorkflowBudget)

    @model_validator(mode='after')
    def ceiling_not_lower(self) -> Self:
        order = ('lite', 'standard', 'deep')
        if order.index(self.ceiling) < order.index(self.complexity):
            raise ValueError('Complexity exceeds its execution ceiling.')
        return self


class InteractionCheckpoint(StrictFrozenModel):
    intensity: ClarificationIntensity | None = None
    ask_on: tuple[InteractionReason, ...] = Field(default_factory=tuple, max_length=10)


class InteractionPolicy(StrictFrozenModel):
    mode: Literal['autonomous', 'adaptive', 'interactive'] = 'adaptive'
    intensity: ClarificationIntensity = 'balanced'
    max_rounds: int = Field(default=2, ge=0, le=16, strict=True)
    max_questions_per_round: int = Field(default=1, ge=1, le=3, strict=True)
    unavailable: Literal['return_missing_context', 'pause'] = 'return_missing_context'
    wait_timeout_seconds: int = Field(default=86400, ge=1, le=604800, strict=True)
    checkpoints: Mapping[InteractionStage, InteractionCheckpoint] = Field(default_factory=dict)

    @field_validator('checkpoints', mode='after')
    @classmethod
    def freeze_checkpoints(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_serializer('checkpoints')
    def serialize_checkpoints(self, value: Mapping[str, InteractionCheckpoint]) -> dict[str, Any]:
        return {key: item.model_dump(mode='json') for key, item in value.items()}


class AssuranceRequirements(StrictFrozenModel):
    min_sources: int = Field(default=1, ge=1, le=8, strict=True)
    max_age_days: int | None = Field(default=None, ge=0, le=36500, strict=True)
    required_metadata: tuple[Literal['source_id', 'document_version', 'effective_date'], ...] = ()


class AssurancePolicy(StrictFrozenModel):
    level: Literal['basic', 'grounded', 'strict'] = 'grounded'
    unknown_required_claim: Literal['block'] = 'block'
    evidence_conflict: Literal['resolve_or_block'] = 'resolve_or_block'
    applicability: Literal['required'] = 'required'
    evidence: AssuranceRequirements = Field(default_factory=AssuranceRequirements)
    checkpoints: Mapping[InteractionStage, AssuranceRequirements] = Field(default_factory=dict)

    @field_validator('checkpoints', mode='after')
    @classmethod
    def freeze_checkpoints(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_serializer('checkpoints')
    def serialize_checkpoints(self, value: Mapping[str, AssuranceRequirements]) -> dict[str, Any]:
        return {key: item.model_dump(mode='json') for key, item in value.items()}


class ExecutionStagePlan(StrictFrozenModel):
    stage_id: str
    mode: Literal['execute', 'conditional', 'deterministic', 'bypass']
    reason: str
    mandatory_checks: tuple[str, ...] = ()


class ResolvedExecutionPlan(StrictFrozenModel):
    schema_version: Literal['resolved-execution-plan.v1'] = 'resolved-execution-plan.v1'
    compiler_version: Literal['adaptive-workflow.v1'] = 'adaptive-workflow.v1'
    requested_complexity: Complexity | Literal['legacy']
    effective_complexity: Complexity | Literal['legacy']
    configuration_digest: str = Field(pattern=r'^[0-9a-f]{64}$')
    stages: tuple[ExecutionStagePlan, ...]
    budget: WorkflowBudget | None = None
    reasoning_effort: Literal['off', 'low', 'medium', 'high', 'xhigh', 'max'] | None = None
    blocked_reason: str | None = None
    escalated: bool = False
