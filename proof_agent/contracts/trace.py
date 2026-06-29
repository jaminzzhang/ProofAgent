from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any, Literal

from pydantic import field_validator

from proof_agent.contracts._base import FrozenModel, freeze_value


class TraceEventType(str, Enum):
    """Closed set of audit event names for trace.v1."""

    RUN_STARTED = "run_started"
    MANIFEST_LOADED = "manifest_loaded"
    WORKFLOW_STAGE_CONFIGURATION_TRACE_SUMMARY = "workflow_stage_configuration_trace_summary"
    WORKFLOW_STAGE_CONTEXT_APPLIED = "workflow_stage_context_applied"
    WORKFLOW_STAGE_RESULT = "workflow_stage_result"
    INTENT_RESOLUTION = "intent_resolution"
    RETRIEVAL_QUERY_SET = "retrieval_query_set"
    BUSINESS_FLOW_SKILL_PACK_RECOMMENDATION = "business_flow_skill_pack_recommendation"
    BUSINESS_FLOW_SKILL_PACK_ADMISSION = "business_flow_skill_pack_admission"
    REASONING_SUMMARY = "reasoning_summary"
    ACTION_PROPOSAL = "action_proposal"
    ACTION_CONSTRAINED = "action_constrained"
    ANSWER_READY_FINALIZATION_FORCED = "answer_ready_finalization_forced"
    TOOL_PROPOSAL_SCOPE = "tool_proposal_scope"
    REVIEW_REQUESTED = "review_requested"
    REVIEW_DECISION = "review_decision"
    REVIEW_ERROR = "review_error"
    REVIEW_OVERRIDDEN = "review_overridden"
    CLARIFICATION_REQUESTED = "clarification_requested"
    POLICY_DECISION = "policy_decision"
    RETRIEVAL_STARTED = "retrieval_started"
    RETRIEVAL_PLAN = "retrieval_plan"
    RETRIEVAL_STEP = "retrieval_step"
    RETRIEVAL_RESULT = "retrieval_result"
    EVIDENCE_EVALUATION = "evidence_evaluation"
    CONTEXT_ADMISSION = "context_admission"
    CONTEXT_ASSEMBLY_SUMMARY = "context_assembly_summary"
    APPROVAL_REQUESTED = "approval_requested"
    PENDING_APPROVAL_CREATED = "pending_approval_created"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_DENIED = "approval_denied"
    APPROVAL_TIMEOUT = "approval_timeout"
    CUSTOMER_HANDOFF_CREATED = "customer_handoff_created"
    TOOL_REQUEST = "tool_request"
    TOOL_RESULT = "tool_result"
    MEMORY_READ = "memory_read"
    MEMORY_PROMOTION_DECISION = "memory_promotion_decision"
    MEMORY_CANDIDATE_GENERATED = "memory_candidate_generated"
    MEMORY_WRITE_REQUESTED = "memory_write_requested"
    MEMORY_WRITE_DECISION = "memory_write_decision"
    MEMORY_ADMISSION = "memory_admission"
    MEMORY_EXPORT_DECISION = "memory_export_decision"
    MEMORY_DELETE_DECISION = "memory_delete_decision"
    MODEL_REQUEST = "model_request"
    MODEL_CONNECTION_RESOLUTION = "model_connection_resolution"
    MODEL_RESPONSE = "model_response"
    MODEL_ERROR = "model_error"
    MODEL_OUTPUT_NORMALIZATION_FAILED = "model_output_normalization_failed"
    FINAL_ANSWER_VALIDATION_FAILED = "final_answer_validation_failed"
    FINAL_OUTPUT = "final_output"
    FINAL_OUTPUT_DISCLOSURE = "final_output_disclosure"
    REDACTION_APPLIED = "redaction_applied"
    ARTIFACT_WRITTEN = "artifact_written"
    RUN_FAILED = "run_failed"


class TraceEvent(FrozenModel):
    """Append-only audit event persisted as one JSON object per trace line."""

    schema_version: Literal["trace.v1"] = "trace.v1"
    run_id: str
    event_id: str
    sequence: int
    timestamp: str
    event_type: TraceEventType
    span_id: str
    parent_span_id: str | None = None
    status: Literal["ok", "blocked", "waiting", "error"]
    payload: Mapping[str, Any]
    redaction: Mapping[str, Any]

    @field_validator("payload", "redaction", mode="after")
    @classmethod
    def freeze_mappings(cls, value: Any) -> Any:
        return freeze_value(value)
