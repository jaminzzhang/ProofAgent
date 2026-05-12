from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any

from pydantic import Field, field_validator

from proof_agent.contracts._base import FrozenDict, FrozenModel, freeze_value


class PolicyDecisionType(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"
    ESCALATE = "escalate"


class EnforcementPoint(str, Enum):
    BEFORE_RETRIEVAL = "before_retrieval"
    BEFORE_RETRIEVAL_PLAN = "before_retrieval_plan"
    BEFORE_RETRIEVAL_STEP = "before_retrieval_step"
    BEFORE_ANSWER = "before_answer"
    BEFORE_TOOL_CALL = "before_tool_call"
    BEFORE_MEMORY_WRITE = "before_memory_write"
    BEFORE_MODEL_CALL = "before_model_call"


class PolicyRule(FrozenModel):
    """Declarative rule loaded from policy.yaml before runtime evaluation."""

    rule_id: str
    enforcement_point: EnforcementPoint
    condition: Mapping[str, Any]
    decision: Mapping[str, Any]
    reason_template: str

    @field_validator("condition", "decision", mode="after")
    @classmethod
    def freeze_mappings(cls, value: Any) -> Any:
        return freeze_value(value)


class PolicyDecision(FrozenModel):
    """Auditable policy verdict produced at a named enforcement point."""

    decision: PolicyDecisionType
    enforcement_point: EnforcementPoint
    reason: str
    policy_rule_id: str
    metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)
    trace_event_id: str

    @field_validator("metadata", mode="after")
    @classmethod
    def freeze_metadata(cls, value: Any) -> Any:
        return freeze_value(value)
