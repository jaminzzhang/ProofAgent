from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from proof_agent.bootstrap.composition import HarnessInvocation
from proof_agent.contracts import (
    ApprovalPause,
    ApprovalState,
    ApprovalStatus,
    ContextAdmission,
    PolicyDecisionType,
    ReceiptOutcome,
    WorkflowTemplateExecutionInput,
    WorkflowStageResult,
    WorkflowStageStatus,
)
from proof_agent.observability.audit.trace import TraceWriter


class ReActEnterpriseQAWorkflowExecution:
    """Control Plane execution object for React Enterprise QA stages."""

    def __init__(
        self,
        *,
        invocation: HarnessInvocation,
        trace: TraceWriter,
        execution_input: WorkflowTemplateExecutionInput,
        conversation_context: ContextAdmission | None,
        allow_untrusted_web_supplement: bool,
    ) -> None:
        self.invocation = invocation
        self.trace = trace
        self.execution_input = execution_input
        from proof_agent.control.workflow.react_enterprise_qa_stage_behavior import (
            ReActEnterpriseQAStageBehavior,
            wrap_control_plane_model_providers,
        )

        wrap_control_plane_model_providers(invocation, trace)
        self._behavior = ReActEnterpriseQAStageBehavior(
            invocation=invocation,
            trace=trace,
            execution_input=execution_input,
            conversation_context=conversation_context,
            allow_untrusted_web_supplement=allow_untrusted_web_supplement,
        )

    def plan(self, state: Mapping[str, Any]) -> WorkflowStageResult:
        delta = self._behavior.plan(state)
        action = _mapping(delta.get("action"))
        outcome = _outcome(delta.get("governance_refusal"))
        return WorkflowStageResult(
            stage_id="plan",
            status=WorkflowStageStatus.BLOCKED if outcome else WorkflowStageStatus.COMPLETED,
            outcome=outcome,
            summary={
                "action_id": str(action.get("action_id", "")),
                "action_type": str(action.get("action_type", "")),
                "risk_level": str(action.get("risk_level", "")),
                "step_count": int(delta.get("step_count", state.get("step_count", 0)) or 0),
            },
            produced_fact_refs=("reasoning_summary", "action_proposal")
            if action
            else (),
            continuation=delta,
        )

    def clarify(self, state: Mapping[str, Any]) -> WorkflowStageResult:
        delta = self._behavior.clarify(state)
        action = _mapping(state.get("action"))
        parameters = _mapping(action.get("parameters"))
        missing_fields = [str(item) for item in parameters.get("missing_fields", ())]
        message = str(delta.get("governance_message", ""))
        continuation = {
            **delta,
            "clarification_need": {
                "action_id": action.get("action_id"),
                "missing_fields": missing_fields,
                "message": message,
                "summary": {"missing_field_count": len(missing_fields)},
            },
        }
        return WorkflowStageResult(
            stage_id="clarification",
            status=WorkflowStageStatus.WAITING,
            outcome=_outcome(delta.get("governance_refusal")),
            summary={
                "action_id": str(action.get("action_id", "")),
                "missing_field_count": len(missing_fields),
            },
            produced_fact_refs=("clarification_need",),
            continuation=continuation,
        )

    def intent_resolution(self, state: Mapping[str, Any]) -> WorkflowStageResult:
        delta = self._behavior.intent_resolution(state)
        resolution = _mapping(delta.get("intent_resolution"))
        outcome = _outcome(delta.get("governance_refusal"))
        return WorkflowStageResult(
            stage_id="intent_resolution",
            status=WorkflowStageStatus.BLOCKED if outcome else WorkflowStageStatus.COMPLETED,
            outcome=outcome,
            summary={
                "resolution_id": str(resolution.get("resolution_id", "")),
                "domain_intent": str(resolution.get("domain_intent", "")),
                "recommended_next_action": str(
                    resolution.get("recommended_next_action", "")
                ),
                "confidence": resolution.get("confidence", 0),
            },
            produced_fact_refs=("intent_resolution",) if resolution else (),
            continuation=delta,
        )

    def review_retrieval_plan(self, state: Mapping[str, Any]) -> WorkflowStageResult:
        delta = self._behavior.review_retrieval_plan(state)
        outcome = _outcome(delta.get("governance_refusal"))
        return WorkflowStageResult(
            stage_id="retrieval_review",
            status=WorkflowStageStatus.BLOCKED if outcome else WorkflowStageStatus.COMPLETED,
            outcome=outcome,
            summary=_review_summary(delta),
            produced_fact_refs=("review_results",),
            continuation=delta,
        )

    def tool(
        self,
        state: Mapping[str, Any],
        *,
        approval_decision: Mapping[str, Any] | None = None,
    ) -> WorkflowStageResult:
        delta = self._behavior.tool(state, approval_decision=approval_decision)
        approval_state = delta.get("tool_approval_state")
        if isinstance(approval_state, ApprovalState):
            return self._approval_waiting_result(delta, approval_state)
        return self._terminal_result("tool", delta)

    def _approval_waiting_result(
        self,
        delta: Mapping[str, Any],
        approval_state: ApprovalState,
    ) -> WorkflowStageResult:
        from proof_agent.capabilities.tools.approval import (
            create_pending_approval,
            pending_approval_payload,
        )

        parameters = dict(_mapping(delta.get("tool_approval_parameters")))
        policy_decision = _policy_decision(delta.get("tool_approval_policy_decision"))
        action_id = str(delta.get("tool_approval_action_id", ""))
        checkpoint_ref = str(
            delta.get("tool_approval_checkpoint_ref") or f"thread:{self.trace.run_id}"
        )
        tool_name = str(delta.get("tool_approval_tool_name") or approval_state.tool_name)
        pending = create_pending_approval(
            approval_state=approval_state,
            thread_id=self.trace.run_id,
            action_id=action_id,
            parameters=parameters,
            policy_decision=policy_decision,
            checkpoint_id=checkpoint_ref,
        )
        interrupt_payload = {
            "kind": "tool_approval",
            "approval_requested": {
                "approval_id": approval_state.approval_id,
                "tool_name": tool_name,
                "state": approval_state.state.value,
            },
            "pending_approval": pending_approval_payload(pending),
        }
        pause = ApprovalPause(
            approval_id=approval_state.approval_id,
            action_id=action_id,
            tool_name=tool_name,
            policy_decision=policy_decision,
            checkpoint_ref=checkpoint_ref,
            expires_at=approval_state.expires_at,
            summary={
                "state": approval_state.state.value,
                "parameter_count": len(parameters),
                "risk_level": str(delta.get("tool_approval_risk_level", "")),
            },
        )
        continuation: dict[str, Any] = {
            "approval_pause": pause,
            "approval_interrupt": interrupt_payload,
        }
        stage_context_applications = delta.get("stage_context_applications")
        if isinstance(stage_context_applications, list | tuple):
            continuation["stage_context_applications"] = [
                dict(item) for item in stage_context_applications if isinstance(item, Mapping)
            ]
        return WorkflowStageResult(
            stage_id="tool",
            status=WorkflowStageStatus.WAITING,
            outcome=ReceiptOutcome.WAITING_FOR_APPROVAL,
            summary={
                "approval_id": pause.approval_id,
                "tool_name": tool_name,
                "state": ApprovalStatus.REQUESTED.value,
                "policy_decision": policy_decision.value,
            },
            produced_fact_refs=("approval_pause",),
            continuation=continuation,
        )

    def _terminal_result(
        self,
        stage_id: str,
        delta: Mapping[str, Any],
    ) -> WorkflowStageResult:
        outcome = _outcome(delta.get("governance_refusal"))
        return WorkflowStageResult(
            stage_id=stage_id,
            status=(
                WorkflowStageStatus.COMPLETED
                if outcome == ReceiptOutcome.ANSWERED_WITH_CITATIONS
                else WorkflowStageStatus.BLOCKED
            ),
            outcome=outcome,
            summary={
                "outcome": outcome.value if outcome is not None else "",
                "final_output_length": len(str(delta.get("final_output", ""))),
            },
            continuation=delta,
        )

    def retrieval(self, state: Mapping[str, Any]) -> WorkflowStageResult:
        delta = self._behavior.retrieval(state)
        outcome = _outcome(delta.get("governance_refusal"))
        evidence = list(delta.get("evidence", ()))
        return WorkflowStageResult(
            stage_id="retrieval",
            status=WorkflowStageStatus.BLOCKED if outcome else WorkflowStageStatus.COMPLETED,
            outcome=outcome,
            summary={
                "accepted_evidence_count": len(evidence),
                "review_result_count": len(list(delta.get("review_results", ()))),
            },
            produced_fact_refs=("evidence", "review_results"),
            continuation=delta,
        )

    def model(self, state: Mapping[str, Any]) -> WorkflowStageResult:
        delta = self._behavior.model(state)
        outcome = _outcome(delta.get("governance_refusal"))
        return WorkflowStageResult(
            stage_id="model_answer",
            status=(
                WorkflowStageStatus.BLOCKED
                if outcome and outcome != ReceiptOutcome.ANSWERED_WITH_CITATIONS
                else WorkflowStageStatus.COMPLETED
            ),
            outcome=outcome,
            summary={
                "outcome": outcome.value if outcome is not None else "",
                "final_output_length": len(str(delta.get("final_output", ""))),
                "review_result_count": len(list(delta.get("review_results", ()))),
            },
            produced_fact_refs=("final_output", "review_results"),
            continuation=delta,
        )

    def review_tool(self, state: Mapping[str, Any]) -> WorkflowStageResult:
        delta = self._behavior.review_tool(state)
        outcome = _outcome(delta.get("governance_refusal"))
        return WorkflowStageResult(
            stage_id="tool_review",
            status=WorkflowStageStatus.BLOCKED if outcome else WorkflowStageStatus.COMPLETED,
            outcome=outcome,
            summary={
                **_review_summary(delta),
                "tool_policy_decision": str(delta.get("tool_policy_decision", "")),
                "tool_call_count": int(delta.get("tool_call_count", 0) or 0),
            },
            produced_fact_refs=("review_results",),
            continuation=delta,
        )

    def _stage_available(self, stage_id: str) -> bool:
        return self.execution_input.workflow_stage_availability.is_available(stage_id)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _outcome(value: Any) -> ReceiptOutcome | None:
    if isinstance(value, ReceiptOutcome):
        return value
    if isinstance(value, str) and value:
        return ReceiptOutcome(value)
    return None


def _policy_decision(value: Any) -> PolicyDecisionType:
    if isinstance(value, PolicyDecisionType):
        return value
    if isinstance(value, str) and value:
        return PolicyDecisionType(value)
    return PolicyDecisionType.REQUIRE_APPROVAL


def _review_summary(delta: Mapping[str, Any]) -> dict[str, Any]:
    review_results = list(delta.get("review_results", ()))
    first_review = _mapping(review_results[0]) if review_results else {}
    return {
        "review_result_count": len(review_results),
        "final_decision": str(first_review.get("final_decision", "")),
        "enforcement_point": str(first_review.get("enforcement_point", "")),
    }


def _tool_capability_disabled_delta() -> dict[str, Any]:
    message = "The tools capability is disabled for this Agent Contract."
    return {
        "governance_refusal": ReceiptOutcome.REFUSED_NO_EVIDENCE,
        "governance_message": message,
        "final_output": message,
    }
