from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from proof_agent.bootstrap.composition import HarnessInvocation
from proof_agent.contracts import (
    ApprovalPause,
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
        from proof_agent.control.workflow.react_nodes import ReActWorkflowNodes

        self._nodes = ReActWorkflowNodes(
            invocation=invocation,
            trace=trace,
            execution_input=execution_input,
            conversation_context=conversation_context,
            allow_untrusted_web_supplement=allow_untrusted_web_supplement,
        )

    def plan(self, state: Mapping[str, Any]) -> WorkflowStageResult:
        delta = self._nodes.plan(state)
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
        delta = self._nodes.clarify(state)
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
        delta = self._nodes.intent_resolution(state)
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
        delta = self._nodes.review_retrieval_plan(state)
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
        from proof_agent.capabilities.tools.approval import (
            create_pending_approval,
            pending_approval_payload,
        )
        from proof_agent.control.workflow.react_nodes import (
            _request_tool_or_refuse,
            proposal_from_state,
        )
        from proof_agent.runtime.graph import _format_untrusted_web_supplement

        proposal = proposal_from_state(state)
        if not self._stage_available("tool"):
            return self._terminal_result("tool", _tool_capability_disabled_delta())
        tool_name = proposal.target_tool_name or ""
        parameters = dict(proposal.parameters)
        tool_policy_decision = PolicyDecisionType(
            state.get("tool_policy_decision")
            or PolicyDecisionType.REQUIRE_APPROVAL.value
        )

        if (
            tool_policy_decision == PolicyDecisionType.REQUIRE_APPROVAL
            and approval_decision is None
        ):
            gateway_result = _request_tool_or_refuse(
                invocation=self.invocation,
                trace=self.trace,
                proposal=proposal,
                tool_name=tool_name,
                parameters=parameters,
                approved=False,
            )
            if isinstance(gateway_result, dict):
                return self._terminal_result("tool", gateway_result)
            pending = create_pending_approval(
                approval_state=gateway_result.approval_state,
                thread_id=self.trace.run_id,
                action_id=proposal.action_id,
                parameters=parameters,
                policy_decision=tool_policy_decision,
                checkpoint_id=f"thread:{self.trace.run_id}",
            )
            interrupt_payload = {
                "kind": "tool_approval",
                "approval_requested": {
                    "approval_id": gateway_result.approval_state.approval_id,
                    "tool_name": tool_name,
                    "state": gateway_result.approval_state.state.value,
                },
                "pending_approval": pending_approval_payload(pending),
            }
            pause = ApprovalPause(
                approval_id=gateway_result.approval_state.approval_id,
                action_id=proposal.action_id,
                tool_name=tool_name,
                policy_decision=tool_policy_decision,
                checkpoint_ref=f"thread:{self.trace.run_id}",
                expires_at=gateway_result.approval_state.expires_at,
                summary={
                    "state": gateway_result.approval_state.state.value,
                    "parameter_count": len(parameters),
                    "risk_level": proposal.risk_level,
                },
            )
            return WorkflowStageResult(
                stage_id="tool",
                status=WorkflowStageStatus.WAITING,
                outcome=ReceiptOutcome.WAITING_FOR_APPROVAL,
                summary={
                    "approval_id": pause.approval_id,
                    "tool_name": tool_name,
                    "state": ApprovalStatus.REQUESTED.value,
                    "policy_decision": tool_policy_decision.value,
                },
                produced_fact_refs=("approval_pause",),
                continuation={
                    "approval_pause": pause,
                    "approval_interrupt": interrupt_payload,
                },
            )

        if approval_decision is not None and not approval_decision.get("approved"):
            actor = approval_decision.get("actor", "local-user")
            self.trace.emit(
                "approval_denied",
                status="blocked",
                payload={
                    "approval_id": approval_decision.get("approval_id", "appr_unknown"),
                    "tool_name": tool_name,
                    "state": ApprovalStatus.DENIED.value,
                    "actor": actor,
                },
            )
            return self._terminal_result(
                "tool",
                {
                    "governance_refusal": ReceiptOutcome.TOOL_APPROVAL_DENIED,
                    "governance_message": (
                        f"The {tool_name} tool was not run because approval was denied."
                    ),
                },
            )

        gateway_result = _request_tool_or_refuse(
            invocation=self.invocation,
            trace=self.trace,
            proposal=proposal,
            tool_name=tool_name,
            parameters=parameters,
            approved=True,
        )
        if isinstance(gateway_result, dict):
            return self._terminal_result("tool", gateway_result)
        if approval_decision is not None:
            self.trace.emit(
                "approval_granted",
                status="ok",
                payload={
                    "approval_id": approval_decision.get(
                        "approval_id",
                        gateway_result.approval_state.approval_id,
                    ),
                    "tool_name": tool_name,
                    "state": ApprovalStatus.GRANTED.value,
                    "actor": approval_decision.get("actor", "local-user"),
                },
            )
        self.trace.emit("tool_result", status="ok", payload=dict(gateway_result.result or {}))
        if tool_name == "untrusted_web_search":
            supplement = _format_untrusted_web_supplement(
                dict(gateway_result.result or {}).get("results", ())
            )
            message = (
                "I cannot answer because the available evidence is insufficient."
                if not supplement
                else f"I cannot answer because the available evidence is insufficient.\n\n{supplement}"
            )
            self.trace.emit(
                "final_output_disclosure",
                status="ok",
                payload={
                    "used_untrusted_web_context": bool(supplement),
                    "untrusted_web_disclaimer_present": bool(supplement),
                },
            )
            return self._terminal_result(
                "tool",
                {
                    "final_output": message,
                    "governance_refusal": ReceiptOutcome.REFUSED_NO_EVIDENCE,
                    "governance_message": message,
                },
            )
        message = "Customer policy status is active according to the approved mock lookup."
        return self._terminal_result(
            "tool",
            {
                "final_output": message,
                "governance_refusal": ReceiptOutcome.ANSWERED_WITH_CITATIONS,
                "governance_message": message,
            },
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
        delta = self._nodes.retrieval(state)
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
        delta = self._nodes.model(state)
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
        delta = self._nodes.review_tool(state)
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
