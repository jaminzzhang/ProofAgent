from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any

from pydantic import Field, field_serializer, field_validator, model_validator

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
    NO_PACK = "no_pack"
    NEEDS_CLARIFICATION = "needs_clarification"
    SAFE_DEFAULT = "safe_default"
    REFUSED = "refused"
    FAILED_CLOSED = "failed_closed"


class BusinessFlowSkillPackRecommendationType(str, Enum):
    SINGLE_PACK = "single_pack"
    NO_PACK = "no_pack"
    AMBIGUOUS = "ambiguous"


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


class InsuranceConditionProposal(FrozenModel):
    """Model-proposed insurance taxonomy values without authority semantics."""

    values: Mapping[str, str] = Field(default_factory=FrozenDict)

    @field_validator("values", mode="before")
    @classmethod
    def validate_and_freeze_values(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            raise ValueError("insurance condition values must be a mapping")
        if len(value) > 32:
            raise ValueError("insurance condition values exceed the 32-field limit")
        normalized: dict[str, str] = {}
        for raw_key, raw_value in value.items():
            if not isinstance(raw_key, str) or not raw_key.strip() or len(raw_key.strip()) > 64:
                raise ValueError("insurance condition keys must be 1 through 64 characters")
            if (
                not isinstance(raw_value, str)
                or not raw_value.strip()
                or len(raw_value.strip()) > 256
            ):
                raise ValueError("insurance condition values must be 1 through 256 characters")
            key = raw_key.strip()
            if key in normalized:
                raise ValueError("insurance condition keys must be unique")
            normalized[key] = raw_value.strip()
        return freeze_value(normalized)

    @field_serializer("values")
    def serialize_values(self, value: Mapping[str, str]) -> dict[str, str]:
        return dict(value)


class InsuranceConditionAdmission(FrozenModel):
    """Deterministic Control Plane decision for proposed insurance conditions."""

    admitted: bool
    normalized_values: Mapping[str, str] = Field(default_factory=FrozenDict)
    missing_authority_fields: tuple[str, ...] = ()
    reason: str

    @field_validator("normalized_values", mode="after")
    @classmethod
    def freeze_normalized_values(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_serializer("normalized_values")
    def serialize_normalized_values(self, value: Mapping[str, str]) -> dict[str, str]:
        return dict(value)


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
    insurance_condition_proposal: InsuranceConditionProposal = Field(
        default_factory=InsuranceConditionProposal
    )

    @field_validator("retrieval_query_set", mode="after")
    @classmethod
    def freeze_retrieval_query_set(cls, value: Any) -> Any:
        return freeze_value(value)


class BusinessFlowCandidatePack(FrozenModel):
    """One candidate pack in an intent-derived business flow recommendation."""

    pack_id: str
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    reason: str

    @field_validator("pack_id", "reason", mode="after")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("field must be non-empty")
        return value


class BusinessFlowSkillPackRecommendation(FrozenModel):
    """Intent-derived recommendation from the published Business Flow Skill Pack set."""

    recommendation_id: str
    intent_resolution_id: str
    recommendation_type: BusinessFlowSkillPackRecommendationType
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    reason: str
    candidate_packs: tuple[BusinessFlowCandidatePack, ...] = Field(default_factory=tuple)
    requires_task_split: bool = False

    @field_validator("reason", mode="after")
    @classmethod
    def require_non_empty_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("field must be non-empty")
        return value

    @field_validator("candidate_packs", mode="after")
    @classmethod
    def freeze_candidate_packs(cls, value: Any) -> Any:
        return freeze_value(value)

    @model_validator(mode="after")
    def validate_candidate_cardinality(self) -> BusinessFlowSkillPackRecommendation:
        candidate_count = len(self.candidate_packs)
        if (
            self.recommendation_type is BusinessFlowSkillPackRecommendationType.SINGLE_PACK
            and candidate_count != 1
        ):
            raise ValueError("single_pack recommendations require exactly one candidate")
        if (
            self.recommendation_type is BusinessFlowSkillPackRecommendationType.NO_PACK
            and candidate_count != 0
        ):
            raise ValueError("no_pack recommendations cannot include candidates")
        if (
            self.recommendation_type is BusinessFlowSkillPackRecommendationType.AMBIGUOUS
            and candidate_count < 2
        ):
            raise ValueError("ambiguous recommendations require at least two candidates")
        if (
            self.recommendation_type is not BusinessFlowSkillPackRecommendationType.AMBIGUOUS
            and self.requires_task_split
        ):
            raise ValueError("requires_task_split is only valid for ambiguous recommendations")
        return self


class IntentResolutionResult(FrozenModel):
    """Intent Resolution model output with optional Business Flow recommendation."""

    intent_resolution: IntentResolution
    business_flow_skill_pack_recommendation: BusinessFlowSkillPackRecommendation | None = None


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
