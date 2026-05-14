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


class ReasoningSummary(FrozenModel):
    """Audit-safe summary of controlled reasoning without raw chain-of-thought."""

    goal: str
    observations: tuple[str, ...]
    candidate_actions: tuple[ReActActionType, ...]
    selected_action: ReActActionType
    rationale_summary: str
    risk_flags: tuple[str, ...]
    required_evidence: tuple[str, ...]


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
    confidence: float
    risk_flags: tuple[str, ...]
    subject_action_id: str
    metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("metadata", mode="after")
    @classmethod
    def freeze_metadata(cls, value: Any) -> Any:
        return freeze_value(value)


class GovernanceDetails(FrozenModel):
    """Supplemental governance projection for ReAct workflow audit views."""

    reasoning_summary: Mapping[str, Any] | None = None
    review_results: tuple[Mapping[str, Any], ...] = ()

    @field_validator("reasoning_summary", "review_results", mode="after")
    @classmethod
    def freeze_nested_values(cls, value: Any) -> Any:
        return freeze_value(value)
