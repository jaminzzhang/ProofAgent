from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from proof_agent.contracts import (
    EvaluationArtifactSufficiencyStatus,
    EvaluationFailureOwner,
    EvaluationGateStatus,
    EvaluationNodeResult,
    EvaluationNodeStage,
)
from proof_agent.evaluation.artifact_reader import EvaluationArtifacts, EvaluationTraceEvent


STAGE_EVENTS: dict[EvaluationNodeStage, tuple[str, ...]] = {
    EvaluationNodeStage.PLANNING: (
        "reasoning_summary",
        "action_proposal",
        "retrieval_plan",
    ),
    EvaluationNodeStage.RETRIEVAL_EVIDENCE: (
        "retrieval_step",
        "retrieval_result",
        "evidence_evaluation",
    ),
    EvaluationNodeStage.POLICY_TOOL: (
        "policy_decision",
        "review_decision",
        "tool_request",
        "approval_requested",
        "approval_granted",
        "approval_denied",
        "tool_result",
    ),
    EvaluationNodeStage.MODEL_VALIDATION: (
        "model_request",
        "model_response",
        "model_error",
        "model_output_normalization_failed",
    ),
    EvaluationNodeStage.AUDIT_PROJECTION: (
        "final_output",
        "artifact_written",
        "redaction_applied",
    ),
}


def extract_evaluation_node_results(
    artifacts: EvaluationArtifacts,
) -> tuple[EvaluationNodeResult, ...]:
    """Extract Analyzer V1 aggregate node diagnostics from trace events."""

    return tuple(
        _node_result(stage, events, artifacts.trace_events)
        for stage, events in STAGE_EVENTS.items()
    )


def _node_result(
    stage: EvaluationNodeStage,
    stage_event_types: tuple[str, ...],
    trace_events: tuple[EvaluationTraceEvent, ...],
) -> EvaluationNodeResult:
    observed = tuple(
        event.event_type for event in trace_events if event.event_type in stage_event_types
    )
    if not observed:
        return EvaluationNodeResult(
            stage=stage,
            status=EvaluationGateStatus.FAILED,
            observed_events=(),
            key_facts={},
            sufficiency=EvaluationArtifactSufficiencyStatus.INSUFFICIENT,
            failure_owner=_failure_owner(stage),
        )
    return EvaluationNodeResult(
        stage=stage,
        status=EvaluationGateStatus.PASSED,
        observed_events=observed,
        key_facts=_key_facts(stage, trace_events),
        sufficiency=EvaluationArtifactSufficiencyStatus.SUFFICIENT,
    )


def _key_facts(stage: EvaluationNodeStage, events: Iterable[EvaluationTraceEvent]) -> dict[str, Any]:
    if stage == EvaluationNodeStage.RETRIEVAL_EVIDENCE:
        return {"accepted_count": _accepted_count(events)}
    if stage == EvaluationNodeStage.MODEL_VALIDATION:
        total_tokens = 0
        for event in events:
            usage = event.payload.get("usage")
            if isinstance(usage, dict) and isinstance(usage.get("total_tokens"), int):
                total_tokens += usage["total_tokens"]
        return {"total_tokens": total_tokens}
    if stage == EvaluationNodeStage.AUDIT_PROJECTION:
        return {"final_output_events": _event_count(events, "final_output")}
    return {}


def _accepted_count(events: Iterable[EvaluationTraceEvent]) -> int:
    accepted = 0
    for event in events:
        if event.event_type != "evidence_evaluation":
            continue
        metadata = event.payload.get("metadata")
        if isinstance(metadata, dict) and isinstance(metadata.get("accepted_count"), int):
            accepted = max(accepted, metadata["accepted_count"])
        elif isinstance(event.payload.get("accepted_count"), int):
            accepted = max(accepted, event.payload["accepted_count"])
    return accepted


def _event_count(events: Iterable[EvaluationTraceEvent], event_type: str) -> int:
    return sum(1 for event in events if event.event_type == event_type)


def _failure_owner(stage: EvaluationNodeStage) -> EvaluationFailureOwner:
    owners = {
        EvaluationNodeStage.PLANNING: EvaluationFailureOwner.PLANNING_FAILURE,
        EvaluationNodeStage.RETRIEVAL_EVIDENCE: EvaluationFailureOwner.RETRIEVAL_FAILURE,
        EvaluationNodeStage.POLICY_TOOL: EvaluationFailureOwner.POLICY_FAILURE,
        EvaluationNodeStage.MODEL_VALIDATION: EvaluationFailureOwner.ANSWER_GENERATION_FAILURE,
        EvaluationNodeStage.AUDIT_PROJECTION: EvaluationFailureOwner.AUDIT_FAILURE,
    }
    return owners[stage]
