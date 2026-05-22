from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any, Literal

from pydantic import Field, field_validator

from proof_agent.contracts._base import FrozenDict, FrozenModel, freeze_value


class HandoffReason(str, Enum):
    """Stable internal reasons for customer-service follow-up."""

    TRANSACTIONAL_ACTION_REQUESTED = "transactional_action_requested"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CROSS_CUSTOMER_ACCESS_ATTEMPT = "cross_customer_access_attempt"
    AUTHORIZATION_REQUIRED = "authorization_required"
    TOOL_FAILURE = "tool_failure"
    RETRIEVAL_FAILURE = "retrieval_failure"
    MODEL_OUTPUT_VALIDATION_FAILED = "model_output_validation_failed"
    HIGH_RISK_COMMITMENT_REQUESTED = "high_risk_commitment_requested"
    PAYMENT_OR_COVERAGE_GUARANTEE_REQUEST = "payment_or_coverage_guarantee_request"
    LOW_CONFIDENCE = "low_confidence"
    POLICY_GAP = "policy_gap"
    CUSTOMER_REQUESTED_FOLLOW_UP = "customer_requested_follow_up"
    SYSTEM_ERROR = "system_error"


class CustomerHandoff(FrozenModel):
    """Internal handoff event recorded for monitoring, not shown as an outcome."""

    handoff_id: str
    run_id: str
    conversation_id: str
    turn_id: str
    reason: HandoffReason
    created_at: str
    summary: str
    customer_ref: str | None = None
    handoff_safe_message: str | None = None
    status: Literal["open", "reviewing", "closed"] = "open"
    metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("metadata", mode="after")
    @classmethod
    def freeze_metadata(cls, value: Any) -> Any:
        return freeze_value(value)


class HandoffProjection(FrozenModel):
    """Dashboard-ready projection of an internal customer handoff."""

    handoff_id: str
    run_id: str
    conversation_id: str
    turn_id: str
    reason: HandoffReason
    created_at: str
    question_summary: str = ""
    summary: str = ""
    customer_ref: str | None = None
    status: Literal["open", "reviewing", "closed"] = "open"
