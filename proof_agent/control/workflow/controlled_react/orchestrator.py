from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from proof_agent.contracts import (
    ApprovalPause,
    ControlledReActRunPhase,
    ControlledReActRunState,
    ControlledReActRunStateSnapshot,
    ObservationRecord,
    PolicyDecisionType,
    ReActActionProposal,
    ReActActionType,
    ReceiptOutcome,
    WorkflowStageResult,
    WorkflowStageStatus,
    WorkflowTemplateExecutionResult,
)
from proof_agent.control.workflow.controlled_react.ports import ControlledReActPorts
from proof_agent.control.workflow.controlled_react.state_machine import (
    ControlledReActStateMachine,
    EffectResult,
    TransitionCommand,
    TransitionCommandType,
)
from proof_agent.control.workflow.react_enterprise_qa import (
    compute_eligible_action_set,
    constrain_action,
)


@dataclass(frozen=True)
class ControlledReActStartRequest:
    run_id: str
    template_name: str
    template_descriptor_version: str
    question: str
    max_plan_rounds: int = 4


@dataclass(frozen=True)
class ControlledReActResumeRequest:
    snapshot_ref: str
    approval_id: str
    approved: bool
    actor: str


class ControlledReActOrchestrator:
    """Run-scoped V3 Controlled ReAct execution interface."""

    def __init__(self, *, ports: ControlledReActPorts) -> None:
        self._ports = ports
        self._state_machine = ControlledReActStateMachine()

    def start(
        self,
        request: ControlledReActStartRequest,
    ) -> WorkflowTemplateExecutionResult:
        state = ControlledReActRunState(
            run_id=request.run_id,
            template_name=request.template_name,
            template_descriptor_version=request.template_descriptor_version,
            question=request.question,
            phase=ControlledReActRunPhase.PLANNING,
        )
        action = self._ports.planner.plan(state)
        if action.action_type is ReActActionType.PLAN_RETRIEVAL:
            if self._review_denies(state, action):
                return self._deny_retrieval_review(request, action)
            state = self._observe_knowledge(state, action)
            action = self._ports.planner.plan(state)
            action = self._constrain_next_action(
                state,
                action,
                max_plan_rounds=request.max_plan_rounds,
            )
        if action.action_type is ReActActionType.REFUSE:
            return self._refuse_plan_budget_exhausted(request, action)
        if action.action_type is ReActActionType.PROPOSE_TOOL_CALL:
            policy_decision = self._policy_decision(state, action)
            if policy_decision is PolicyDecisionType.DENY:
                return self._deny_tool_policy(request, action)
            if policy_decision is PolicyDecisionType.ALLOW:
                state = self._observe_tool(state, action)
                action = self._ports.planner.plan(state)
                if action.action_type is not ReActActionType.GENERATE_FINAL_ANSWER:
                    raise ValueError(f"unsupported tool follow-up action: {action.action_type}")
                answer = self._ports.answer_synthesis.synthesize(state, action)
                return WorkflowTemplateExecutionResult(
                    run_id=request.run_id,
                    template_name=request.template_name,
                    template_descriptor_version=request.template_descriptor_version,
                    outcome=answer.outcome,
                    final_output=answer.final_output,
                    message=answer.message,
                    evidence=answer.evidence,
                    stage_results=_stage_results_from_state(state),
                    reasoning_summary=answer.reasoning_summary,
                    model_usage_summary=answer.model_usage_summary,
                )
            return self._pause_for_tool_approval(request, state, action)
        if action.action_type is not ReActActionType.GENERATE_FINAL_ANSWER:
            raise ValueError(f"unsupported start action: {action.action_type}")
        answer = self._ports.answer_synthesis.synthesize(state, action)
        return WorkflowTemplateExecutionResult(
            run_id=request.run_id,
            template_name=request.template_name,
            template_descriptor_version=request.template_descriptor_version,
            outcome=answer.outcome,
            final_output=answer.final_output,
            message=answer.message,
            evidence=answer.evidence,
            stage_results=_stage_results_from_state(state),
            reasoning_summary=answer.reasoning_summary,
            model_usage_summary=answer.model_usage_summary,
        )

    def _refuse_plan_budget_exhausted(
        self,
        request: ControlledReActStartRequest,
        action: ReActActionProposal,
    ) -> WorkflowTemplateExecutionResult:
        message = "Unable to continue gathering evidence within the plan budget."
        return WorkflowTemplateExecutionResult(
            run_id=request.run_id,
            template_name=request.template_name,
            template_descriptor_version=request.template_descriptor_version,
            outcome=ReceiptOutcome.REFUSED_NO_EVIDENCE,
            final_output=message,
            message=message,
            reasoning_summary=action.reasoning_summary.model_dump(mode="json"),
        )

    def _review_denies(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> bool:
        if self._ports.review is None:
            return False
        decision = self._ports.review.review(state, action)
        return decision.suggested_decision is PolicyDecisionType.DENY

    def _deny_retrieval_review(
        self,
        request: ControlledReActStartRequest,
        action: ReActActionProposal,
    ) -> WorkflowTemplateExecutionResult:
        message = "The retrieval action was not run because review denied it."
        return WorkflowTemplateExecutionResult(
            run_id=request.run_id,
            template_name=request.template_name,
            template_descriptor_version=request.template_descriptor_version,
            outcome=ReceiptOutcome.REFUSED_NO_EVIDENCE,
            final_output=message,
            message=message,
            reasoning_summary=action.reasoning_summary.model_dump(mode="json"),
        )

    def _policy_decision(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> PolicyDecisionType:
        if self._ports.policy is None:
            return PolicyDecisionType.REQUIRE_APPROVAL
        decision = self._ports.policy.evaluate(state, action)
        return decision.decision

    def _deny_tool_policy(
        self,
        request: ControlledReActStartRequest,
        action: ReActActionProposal,
    ) -> WorkflowTemplateExecutionResult:
        tool_name = action.target_tool_name or "unknown_tool"
        message = f"The {tool_name} tool was not run because policy denied it."
        return WorkflowTemplateExecutionResult(
            run_id=request.run_id,
            template_name=request.template_name,
            template_descriptor_version=request.template_descriptor_version,
            outcome=ReceiptOutcome.TOOL_APPROVAL_DENIED,
            final_output=message,
            message=message,
            reasoning_summary=action.reasoning_summary.model_dump(mode="json"),
        )

    def resume(
        self,
        request: ControlledReActResumeRequest,
    ) -> WorkflowTemplateExecutionResult:
        if self._ports.snapshot_store is None:
            raise ValueError("snapshot store port is required for approval resume")
        snapshot = self._ports.snapshot_store.load(request.snapshot_ref)
        state = snapshot.state
        if not state.action_history:
            raise ValueError("approval resume snapshot is missing pending action")
        action = state.action_history[-1]
        if not request.approved:
            return self._deny_tool_approval(state, action)
        if self._ports.tool_observation is None:
            raise ValueError("tool observation port is required for approval resume")
        observing_state = state.model_copy(
            update={
                "phase": ControlledReActRunPhase.OBSERVING,
                "plan_round": state.plan_round + 1,
            }
        )
        observation = self._ports.tool_observation.observe(observing_state, action)
        planning_state = self._commit_observation(observing_state, action, observation)
        next_action = self._ports.planner.plan(planning_state)
        if next_action.action_type is not ReActActionType.GENERATE_FINAL_ANSWER:
            raise ValueError(f"unsupported resume action: {next_action.action_type}")
        answer = self._ports.answer_synthesis.synthesize(planning_state, next_action)
        return WorkflowTemplateExecutionResult(
            run_id=planning_state.run_id,
            template_name=planning_state.template_name,
            template_descriptor_version=planning_state.template_descriptor_version,
            outcome=answer.outcome,
            final_output=answer.final_output,
            message=answer.message,
            evidence=answer.evidence,
            stage_results=_stage_results_from_state(planning_state),
            reasoning_summary=answer.reasoning_summary,
            model_usage_summary=answer.model_usage_summary,
        )

    def _deny_tool_approval(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> WorkflowTemplateExecutionResult:
        tool_name = action.target_tool_name or "unknown_tool"
        message = f"The {tool_name} tool was not run because approval was denied."
        return WorkflowTemplateExecutionResult(
            run_id=state.run_id,
            template_name=state.template_name,
            template_descriptor_version=state.template_descriptor_version,
            outcome=ReceiptOutcome.TOOL_APPROVAL_DENIED,
            final_output=message,
            message=message,
            reasoning_summary=action.reasoning_summary.model_dump(mode="json"),
        )

    def _pause_for_tool_approval(
        self,
        request: ControlledReActStartRequest,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> WorkflowTemplateExecutionResult:
        if self._ports.snapshot_store is None:
            raise ValueError("snapshot store port is required for approval pause")
        waiting_state = state.model_copy(
            update={
                "phase": ControlledReActRunPhase.WAITING,
                "action_history": state.action_history + (action,),
            }
        )
        snapshot = ControlledReActRunStateSnapshot(
            snapshot_id=f"snap_{request.run_id}",
            run_id=request.run_id,
            state=waiting_state,
        )
        snapshot_ref = self._ports.snapshot_store.save(snapshot)
        tool_name = action.target_tool_name or "unknown_tool"
        expires_at = (datetime.now(UTC) + timedelta(seconds=60)).isoformat().replace(
            "+00:00",
            "Z",
        )
        approval_pause = ApprovalPause(
            approval_id=f"appr_{action.action_id}",
            action_id=action.action_id,
            tool_name=tool_name,
            policy_decision=PolicyDecisionType.REQUIRE_APPROVAL,
            checkpoint_ref=snapshot_ref,
            expires_at=expires_at,
            summary={"tool_name": tool_name},
        )
        message = f"Waiting for approval before {tool_name} can execute."
        return WorkflowTemplateExecutionResult(
            run_id=request.run_id,
            template_name=request.template_name,
            template_descriptor_version=request.template_descriptor_version,
            outcome=ReceiptOutcome.WAITING_FOR_APPROVAL,
            final_output=message,
            message=message,
            approval_pause=approval_pause,
            reasoning_summary=action.reasoning_summary.model_dump(mode="json"),
        )

    def _observe_knowledge(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> ControlledReActRunState:
        if self._ports.knowledge_observation is None:
            raise ValueError("knowledge observation port is required for retrieval actions")
        observing_state = state.model_copy(
            update={
                "phase": ControlledReActRunPhase.OBSERVING,
                "plan_round": state.plan_round + 1,
                "action_history": state.action_history + (action,),
            }
        )
        observation = self._ports.knowledge_observation.observe(observing_state, action)
        return self._commit_observation(observing_state, action, observation)

    def _observe_tool(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> ControlledReActRunState:
        if self._ports.tool_observation is None:
            raise ValueError("tool observation port is required for allowed tool actions")
        observing_state = state.model_copy(
            update={
                "phase": ControlledReActRunPhase.OBSERVING,
                "plan_round": state.plan_round + 1,
                "action_history": state.action_history + (action,),
            }
        )
        observation = self._ports.tool_observation.observe(observing_state, action)
        return self._commit_observation(observing_state, action, observation)

    def _commit_observation(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
        observation: ObservationRecord,
    ) -> ControlledReActRunState:
        result = self._state_machine.advance(
            state,
            TransitionCommand(
                command_id=f"commit_{observation.observation_id}",
                command_type=TransitionCommandType.RECORD_OBSERVATION,
                action=action,
            ),
            EffectResult(
                command_id=f"commit_{observation.observation_id}",
                observation_record=observation,
            ),
        )
        return result.state

    def _constrain_next_action(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
        *,
        max_plan_rounds: int,
    ) -> ReActActionProposal:
        eligible_actions, convergence_signal = compute_eligible_action_set(
            plan_rounds=state.plan_round,
            max_plan_rounds=max_plan_rounds,
            action_history=_action_history_payload(state),
            evidence_trajectory=[
                record.accepted_evidence_count for record in state.observation_records
            ],
            observations=_observation_payloads(state),
        )
        constrained, _rewrite = constrain_action(
            action,
            eligible_actions,
            convergence_signal=convergence_signal,
        )
        return constrained


def _action_history_payload(state: ControlledReActRunState) -> list[Mapping[str, Any]]:
    return [
        {
            "action_type": action.action_type.value,
            "parameters": dict(action.parameters),
        }
        for action in state.action_history
    ]


def _observation_payloads(state: ControlledReActRunState) -> list[Mapping[str, Any]]:
    return [
        {
            "accepted_evidence_count": record.accepted_evidence_count,
            "unresolved_subgoals": list(record.unresolved_subgoals),
        }
        for record in state.observation_records
    ]


def _stage_results_from_state(
    state: ControlledReActRunState,
) -> tuple[WorkflowStageResult, ...]:
    return tuple(
        WorkflowStageResult(
            stage_id=_stage_id_for_observation(record),
            status=WorkflowStageStatus.COMPLETED,
            summary=dict(record.summary),
            produced_fact_refs=record.source_refs or (record.truth_ref,),
        )
        for record in state.observation_records
    )


def _stage_id_for_observation(record: ObservationRecord) -> str:
    if record.action_type is ReActActionType.PROPOSE_TOOL_CALL:
        return "tool"
    if record.action_type is ReActActionType.PLAN_RETRIEVAL:
        return "retrieval"
    return str(record.action_type.value)
