"""Dashboard-facing read-only contracts for run history, detail, and aggregation.

These models compose existing audit contracts (TraceEvent, EvidenceChunk,
PolicyDecision, etc.) into shapes suited for the REST API and frontend
without leaking framework or runtime internals.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field

from proof_agent.contracts._base import FrozenModel
from proof_agent.contracts.approval import ApprovalStatus
from proof_agent.contracts.receipt import ReceiptOutcome


class RunPurpose(str, Enum):
    """Operational purpose for a persisted run."""

    PRODUCTION = "production"
    VALIDATION = "validation"
    EVALUATION_SAMPLE = "evaluation_sample"


class RunSummary(FrozenModel):
    """Row-level data for the Runs List and Overview pages."""

    run_id: str
    question: str
    outcome: ReceiptOutcome
    run_purpose: RunPurpose = RunPurpose.PRODUCTION
    agent_id: str | None = None
    agent_version_id: str | None = None
    draft_id: str | None = None
    validation_capture_id: str | None = None
    created_at: str
    updated_at: str
    approval_status: ApprovalStatus | None = None
    error_code: str | None = None


class RunDetail(FrozenModel):
    """Full run data for the Run Detail page.

    Composes the summary with all nested artifacts needed by the
    timeline, evidence, model usage, and receipt tabs.
    """

    run_id: str
    question: str
    outcome: ReceiptOutcome
    run_purpose: RunPurpose = RunPurpose.PRODUCTION
    agent_id: str | None = None
    agent_version_id: str | None = None
    draft_id: str | None = None
    validation_capture_id: str | None = None
    created_at: str
    updated_at: str
    approval_status: ApprovalStatus | None = None
    error_code: str | None = None
    trace_events: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    receipt_markdown: str = ""
    evidence_chunks: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    policy_decisions: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    model_usage: dict[str, Any] = Field(default_factory=dict)
    approval_state: dict[str, Any] | None = None
    pending_approvals: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    governance_details: dict[str, Any] = Field(default_factory=dict)


class RunIndex(FrozenModel):
    """Persisted run_meta.json entry for querying without parsing trace."""

    run_id: str
    question: str
    outcome: ReceiptOutcome
    run_purpose: RunPurpose = RunPurpose.PRODUCTION
    agent_id: str | None = None
    agent_version_id: str | None = None
    draft_id: str | None = None
    validation_capture_id: str | None = None
    created_at: str
    updated_at: str
    approval_status: ApprovalStatus | None = None
    error_code: str | None = None
