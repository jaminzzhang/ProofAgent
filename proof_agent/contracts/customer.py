from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field

from proof_agent.contracts._base import FrozenModel


class CustomerSessionType(str, Enum):
    """Customer-facing session class admitted into a governed run."""

    ANONYMOUS = "anonymous"
    AUTHENTICATED = "authenticated"


class CustomerRunProgressState(str, Enum):
    """Customer-safe progress labels for the direct Web Chat surface."""

    AUTHENTICATING = "authenticating"
    RETRIEVING_EVIDENCE = "retrieving_evidence"
    CHECKING_ACCOUNT_DATA = "checking_account_data"
    VALIDATING_ANSWER = "validating_answer"
    PREPARING_RESPONSE = "preparing_response"
    COMPLETED = "completed"


class CustomerAuthorizationContext(FrozenModel):
    """Trace-safe customer authorization context.

    This contract intentionally stores customer references and allowed resource ids,
    not bearer tokens, raw identity claims, or provider-specific auth objects.
    """

    session_type: CustomerSessionType
    customer_ref: str | None = None
    allowed_policy_ids: tuple[str, ...] = Field(default_factory=tuple)
    allowed_claim_ids: tuple[str, ...] = Field(default_factory=tuple)
    auth_scope: tuple[str, ...] = Field(default_factory=tuple)
    locale: str | None = None


class CustomerSafeSource(FrozenModel):
    """Customer-visible source citation without internal audit links."""

    source_id: str
    label: str
    excerpt: str | None = None


class CustomerSafeResponse(FrozenModel):
    """Customer-facing response projection returned by Customer Run API."""

    progress_state: CustomerRunProgressState = CustomerRunProgressState.COMPLETED
    message: str
    safe_sources: tuple[str | CustomerSafeSource, ...] = Field(default_factory=tuple)
    suggested_next_steps: tuple[str, ...] = Field(default_factory=tuple)
    handoff_safe_message: str | None = None


class CustomerResponseSnapshot(FrozenModel):
    """Persisted customer-safe response tied to a governed Harness run."""

    snapshot_id: str
    conversation_id: str
    turn_id: str
    run_id: str
    created_at: str
    response: CustomerSafeResponse
    question: str = ""
    customer_ref: str | None = None


class CustomerDisambiguationOption(FrozenModel):
    """Short-lived mapping from a customer-safe option to one owned resource."""

    option_id: str
    resource_type: Literal["claim", "policy"]
    resource_id: str
    label: str
    origin_run_id: str | None = None
    origin_turn_id: str | None = None


class CustomerConversationRecord(FrozenModel):
    """Customer-facing conversation metadata and safe response snapshots."""

    conversation_id: str
    agent_id: str
    created_at: str
    updated_at: str
    customer_ref: str | None = None
    snapshots: tuple[CustomerResponseSnapshot, ...] = Field(default_factory=tuple)
    disambiguation_options: tuple[CustomerDisambiguationOption, ...] = Field(default_factory=tuple)


class CustomerFeedbackSignal(FrozenModel):
    """Observation-only feedback from the customer Web Chat surface."""

    rating: Literal["up", "down"]
    comment: str | None = None
    applies_to_training: bool = False
