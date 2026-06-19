from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any

from pydantic import Field, field_validator

from proof_agent.contracts._base import FrozenDict, FrozenModel, freeze_value
from proof_agent.contracts.policy import EnforcementPoint, PolicyDecisionType


class ReActActionType(str, Enum):
    ASK_CLARIFICATION = "ask_clarification"
    PLAN_RETRIEVAL = "plan_retrieval"
    RUN_RETRIEVAL_STEP = "run_retrieval_step"
    PROPOSE_TOOL_CALL = "propose_tool_call"
    GENERATE_FINAL_ANSWER = "generate_final_answer"
    ESCALATE = "escalate"
    STOP = "stop"
    REFUSE = "refuse"


class BusinessFlowSkillPackAdmissionDecision(str, Enum):
    ADMITTED = "admitted"
    NEEDS_CLARIFICATION = "needs_clarification"
    SAFE_DEFAULT = "safe_default"
    REFUSED = "refused"
    FAILED_CLOSED = "failed_closed"


class ReasoningSummary(FrozenModel):
    """Audit-safe summary of controlled reasoning without raw chain-of-thought."""

    goal: str
    observations: tuple[str, ...]
    candidate_actions: tuple[ReActActionType, ...]
    selected_action: ReActActionType
    rationale_summary: str
    risk_flags: tuple[str, ...]
    required_evidence: tuple[str, ...]


class RetrievalQueryItem(FrozenModel):
    """Audit-safe candidate Knowledge retrieval query emitted by Intent Resolution."""

    query: str
    intent_angle: str
    required: bool
    reason: str

    @field_validator("query", "intent_angle", "reason", mode="after")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("field must be non-empty")
        return value


class IntentResolution(FrozenModel):
    """Audit-safe user intent understanding before ReAct action planning."""

    resolution_id: str
    user_goal: str
    domain_intent: str
    known_facts: tuple[str, ...]
    missing_fields: tuple[str, ...]
    ambiguities: tuple[str, ...]
    risk_flags: tuple[str, ...]
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    recommended_next_action: ReActActionType
    retrieval_query_set: tuple[RetrievalQueryItem, ...] = Field(default_factory=tuple)

    @field_validator("retrieval_query_set", mode="after")
    @classmethod
    def freeze_retrieval_query_set(cls, value: Any) -> Any:
        return freeze_value(value)


class BusinessFlowSkillPackRecommendation(FrozenModel):
    """Intent-derived recommendation from the published Business Flow Skill Pack set."""

    recommendation_id: str
    intent_resolution_id: str
    recommended_pack_id: str | None
    candidate_pack_ids: tuple[str, ...]
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    reason: str


class BusinessFlowSkillPackAdmission(FrozenModel):
    """Control Plane admission fact for the Primary Business Flow Skill Pack."""

    admission_id: str
    recommendation_id: str
    decision: BusinessFlowSkillPackAdmissionDecision
    selected_pack_id: str | None = None
    reason: str
    failure_reason: str | None = None
    trace_summary: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("trace_summary", mode="after")
    @classmethod
    def freeze_trace_summary(cls, value: Any) -> Any:
        return freeze_value(value)


class BusinessFlowSkillPackAdmissionResult(FrozenModel):
    """Recommendation plus admission facts kept separate from IntentResolution."""

    recommendation: BusinessFlowSkillPackRecommendation
    admission: BusinessFlowSkillPackAdmission


class ReActActionProposal(FrozenModel):
    """Planner-proposed action for Harness and PolicyEngine evaluation."""

    action_id: str
    action_type: ReActActionType
    reasoning_summary: ReasoningSummary
    parameters: Mapping[str, Any] = Field(default_factory=FrozenDict)
    target_tool_name: str | None = None
    risk_level: str

    @field_validator("parameters", mode="after")
    @classmethod
    def freeze_parameters(cls, value: Any) -> Any:
        return freeze_value(value)


class ReviewDecision(FrozenModel):
    """Advisory review output; final authority remains with Harness policy."""

    review_id: str
    enforcement_point: EnforcementPoint
    suggested_decision: PolicyDecisionType
    reason: str
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    risk_flags: tuple[str, ...]
    subject_action_id: str
    metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("metadata", mode="after")
    @classmethod
    def freeze_metadata(cls, value: Any) -> Any:
        return freeze_value(value)


class GovernanceDetails(FrozenModel):
    """Supplemental governance projection for ReAct workflow audit views."""

    intent_resolution: Mapping[str, Any] | None = None
    reasoning_summary: Mapping[str, Any] | None = None
    review_results: tuple[Mapping[str, Any], ...] = ()

    @field_validator("intent_resolution", "reasoning_summary", "review_results", mode="after")
    @classmethod
    def freeze_nested_values(cls, value: Any) -> Any:
        return freeze_value(value)
