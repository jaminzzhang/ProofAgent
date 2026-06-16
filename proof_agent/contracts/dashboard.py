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


class WorkflowRunStageProjection(FrozenModel):
    """Trace-safe Workflow Template Stage projection for Dashboard run detail."""

    stage_id: str
    label: str | None = None
    status: str | None = None
    outcome: ReceiptOutcome | None = None
    safe_summary: dict[str, Any] = Field(default_factory=dict)
    context_application_summary: dict[str, Any] = Field(default_factory=dict)
    produced_fact_refs: tuple[str, ...] = Field(default_factory=tuple)
    related_event_ids: tuple[str, ...] = Field(default_factory=tuple)
    approval_pause_summary: dict[str, Any] | None = None
    clarification_need_summary: dict[str, Any] | None = None


class WorkflowRunProjection(FrozenModel):
    """Stage-organized, runtime-neutral projection for Dashboard run detail."""

    template_name: str | None = None
    template_descriptor_version: str | None = None
    stage_configuration_source: dict[str, Any] = Field(default_factory=dict)
    stages: tuple[WorkflowRunStageProjection, ...] = Field(default_factory=tuple)


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
    workflow_projection: WorkflowRunProjection = Field(
        default_factory=WorkflowRunProjection
    )


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
