from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
from typing import Any, Literal, cast

from proof_agent.contracts import (
    AnswerEvidenceContext,
    ApprovalPause,
    ApprovedToolProposalSnapshot,
    ClarificationNeed,
    ControlledReActRunPhase,
    ControlledReActRunState,
    ControlledReActRunStateSnapshot,
    EffectiveToolProposalScope,
    ObservationRecord,
    ObservationTruthArtifact,
    PolicyDecision,
    PolicyDecisionType,
    ReActActionProposal,
    ReActActionType,
    ReceiptOutcome,
    RetrievalObservationTruth,
    ToolObservationTruth,
    ValidationResult,
    ValidationStatus,
    WorkflowStageResult,
    WorkflowStageLlmInteraction,
    WorkflowStageStatus,
    WorkflowTemplateExecutionResult,
)
from proof_agent.control.workflow.controlled_react.ports import (
    AnswerSynthesisResult,
    ControlledReActPorts,
    MemoryWriteCandidate,
)
from proof_agent.control.workflow.controlled_react.tool_proposal_binding import (
    ToolProposalParameterBinder,
)
from proof_agent.control.workflow.controlled_react.observation_commit import (
    InMemoryObservationTruthStore,
    ObservationCommitter,
    ObservationEffect,
    ObservationIdentity,
)
from proof_agent.control.workflow.react_enterprise_qa import (
    compute_eligible_action_set,
    constrain_action,
    emit_intent_resolution,
    should_block_duplicate_observation_action,
)


@dataclass(frozen=True)
class ControlledReActStartRequest:
    run_id: str
    template_name: str
    template_descriptor_version: str
    question: str
    max_plan_rounds: int = 4
    retrieval_max_queries: int = 3


@dataclass(frozen=True)
class ControlledReActResumeRequest:
    snapshot_ref: str
    approval_id: str
    approved: bool
    actor: str
    max_plan_rounds: int = 4


class ControlledReActOrchestrator:
    """Run-scoped V3 Controlled ReAct execution interface."""

    def __init__(self, *, ports: ControlledReActPorts) -> None:
        self._ports = ports
        self._observation_truth_store = (
            ports.observation_truth_store or InMemoryObservationTruthStore()
        )
        self._observation_committer = ObservationCommitter(
            truth_store=self._observation_truth_store
        )
        self._tool_proposal_binder = ToolProposalParameterBinder()

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
        state = self._prepare_pre_loop_state(
            state,
            retrieval_max_queries=request.retrieval_max_queries,
        )
        state, action = self._plan_next_action(
            state,
            max_plan_rounds=request.max_plan_rounds,
        )
        return self._run_loop(
            request,
            state=state,
            action=action,
            max_plan_rounds=request.max_plan_rounds,
        )

    def _run_loop(
        self,
        request: ControlledReActStartRequest,
        *,
        state: ControlledReActRunState,
        action: ReActActionProposal,
        max_plan_rounds: int,
    ) -> WorkflowTemplateExecutionResult:
        while True:
            if action.action_type is ReActActionType.REFUSE:
                return self._refuse_plan_budget_exhausted(request, action, state=state)
            if action.action_type is ReActActionType.ASK_CLARIFICATION:
                return self._ask_clarification(request, action)
            if action.action_type is ReActActionType.GENERATE_FINAL_ANSWER:
                if _final_answer_blocked_by_denied_tool(state):
                    answer = _tool_approval_denied_answer(state, action)
                    return _workflow_result_from_answer(state, answer, action)
                answer_context = self._answer_evidence_context(state)
                answer = self._ports.answer_synthesis.synthesize(
                    state,
                    action,
                    answer_context,
                )
                answer = self._admit_final_answer(
                    state,
                    action,
                    answer_context,
                    answer,
                )
                memory_write = self._write_memory(state, answer)
                return _workflow_result_from_answer(
                    state,
                    answer,
                    action,
                    memory_write_result=memory_write,
                )
            if action.action_type is ReActActionType.PLAN_RETRIEVAL:
                if self._review_denies(state, action):
                    return self._deny_retrieval_review(request, action)
                state = self._observe_knowledge(state, action)
                state, action = self._plan_next_action(
                    state,
                    max_plan_rounds=max_plan_rounds,
                )
                continue
            if action.action_type is ReActActionType.PROPOSE_TOOL_CALL:
                if _tool_scope_violation(state, action):
                    return self._deny_tool_scope_violation(request, action)
                state, action = self._bind_tool_proposal(state, action)
                policy_decision = self._policy_decision(state, action)
                if policy_decision is PolicyDecisionType.DENY:
                    return self._deny_tool_policy(request, action)
                if policy_decision is PolicyDecisionType.ALLOW:
                    state = self._observe_tool(state, action)
                    state, action = self._plan_next_action(
                        state,
                        max_plan_rounds=max_plan_rounds,
                    )
                    continue
                return self._pause_for_tool_approval(request, state, action)
            raise ValueError(f"unsupported start action: {action.action_type}")

    def _refuse_plan_budget_exhausted(
        self,
        request: ControlledReActStartRequest,
        action: ReActActionProposal,
        *,
        state: ControlledReActRunState,
    ) -> WorkflowTemplateExecutionResult:
        if action.parameters.get("refusal_reason") == "observation_no_progress":
            message = "Unable to answer because no governed evidence met admission requirements."
        else:
            message = "Unable to continue gathering evidence within the plan budget."
        answer = AnswerSynthesisResult(
            outcome=ReceiptOutcome.REFUSED_NO_EVIDENCE,
            final_output=message,
            message=message,
            reasoning_summary=action.reasoning_summary.model_dump(mode="json"),
        )
        memory_write = self._write_memory(state, answer)
        return WorkflowTemplateExecutionResult(
            run_id=request.run_id,
            template_name=request.template_name,
            template_descriptor_version=request.template_descriptor_version,
            outcome=answer.outcome,
            final_output=message,
            message=message,
            stage_results=_stage_results_for_refusal(
                state,
                answer,
                action,
                memory_write_result=memory_write,
            ),
            intent_resolution=state.intent_resolution,
            reasoning_summary=answer.reasoning_summary,
        )

    def _ask_clarification(
        self,
        request: ControlledReActStartRequest,
        action: ReActActionProposal,
    ) -> WorkflowTemplateExecutionResult:
        missing_fields = _clarification_missing_fields(action)
        message = f"Please provide {_human_join(missing_fields)} before I can continue."
        clarification_need = ClarificationNeed(
            action_id=action.action_id,
            missing_fields=missing_fields,
            message=message,
            summary={
                "reason": "missing_required_context",
                "missing_fields": list(missing_fields),
            },
        )
        return WorkflowTemplateExecutionResult(
            run_id=request.run_id,
            template_name=request.template_name,
            template_descriptor_version=request.template_descriptor_version,
            outcome=ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION,
            final_output=message,
            message=message,
            clarification_need=clarification_need,
            stage_results=(
                WorkflowStageResult(
                    stage_id="clarification",
                    status=WorkflowStageStatus.WAITING,
                    outcome=ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION,
                    summary={"missing_fields": list(missing_fields)},
                    produced_fact_refs=("clarification_need",),
                ),
            ),
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

    def _deny_tool_scope_violation(
        self,
        request: ControlledReActStartRequest,
        action: ReActActionProposal,
    ) -> WorkflowTemplateExecutionResult:
        tool_name = action.target_tool_name or "unknown_tool"
        message = (
            f"The {tool_name} tool was not run because it is outside "
            "the effective tool proposal scope."
        )
        return WorkflowTemplateExecutionResult(
            run_id=request.run_id,
            template_name=request.template_name,
            template_descriptor_version=request.template_descriptor_version,
            outcome=ReceiptOutcome.REFUSED_NO_EVIDENCE,
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
            planning_state = self._observe_tool_approval_denial(state, action, request)
            planning_state, next_action = self._plan_next_action(
                planning_state,
                max_plan_rounds=request.max_plan_rounds,
            )
            return self._run_loop(
                ControlledReActStartRequest(
                    run_id=planning_state.run_id,
                    template_name=planning_state.template_name,
                    template_descriptor_version=planning_state.template_descriptor_version,
                    question=planning_state.question,
                    max_plan_rounds=request.max_plan_rounds,
                ),
                state=planning_state,
                action=next_action,
                max_plan_rounds=request.max_plan_rounds,
            )
        if self._ports.tool_observation is None:
            raise ValueError("tool observation port is required for approval resume")
        if _approved_tool_integrity_mismatch(state, action):
            return self._deny_approved_tool_integrity_mismatch(state, action)
        observing_state = state.model_copy(
            update={
                "phase": ControlledReActRunPhase.OBSERVING,
                "plan_round": state.plan_round + 1,
            }
        )
        identity = _allocate_observation_identity(observing_state, action)
        effect = self._ports.tool_observation.observe(observing_state, action, identity)
        planning_state = self._commit_observation_effect(
            observing_state,
            action,
            effect,
            identity,
        )
        planning_state, next_action = self._plan_next_action(
            planning_state,
            max_plan_rounds=request.max_plan_rounds,
        )
        return self._run_loop(
            ControlledReActStartRequest(
                run_id=planning_state.run_id,
                template_name=planning_state.template_name,
                template_descriptor_version=planning_state.template_descriptor_version,
                question=planning_state.question,
                max_plan_rounds=request.max_plan_rounds,
            ),
            state=planning_state,
            action=next_action,
            max_plan_rounds=request.max_plan_rounds,
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

    def _deny_approved_tool_integrity_mismatch(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> WorkflowTemplateExecutionResult:
        message = "The approved tool proposal no longer matches the pending execution request."
        return WorkflowTemplateExecutionResult(
            run_id=state.run_id,
            template_name=state.template_name,
            template_descriptor_version=state.template_descriptor_version,
            outcome=ReceiptOutcome.REFUSED_NO_EVIDENCE,
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
        approved_tool_snapshot = _approved_tool_snapshot(
            state,
            action,
            policy_decision=PolicyDecisionType.REQUIRE_APPROVAL,
        )
        waiting_state = state.model_copy(
            update={
                "phase": ControlledReActRunPhase.WAITING,
                "action_history": state.action_history + (action,),
                "approved_tool_proposal_snapshot": approved_tool_snapshot,
            }
        )
        snapshot = ControlledReActRunStateSnapshot(
            snapshot_id=f"snap_{request.run_id}",
            run_id=request.run_id,
            state=waiting_state,
        )
        snapshot_ref = self._ports.snapshot_store.save(snapshot)
        tool_name = action.target_tool_name or "unknown_tool"
        expires_at = (
            (datetime.now(UTC) + timedelta(seconds=60))
            .isoformat()
            .replace(
                "+00:00",
                "Z",
            )
        )
        approval_pause = ApprovalPause(
            approval_id=f"appr_{action.action_id}",
            action_id=action.action_id,
            tool_name=tool_name,
            policy_decision=PolicyDecisionType.REQUIRE_APPROVAL,
            checkpoint_ref=snapshot_ref,
            expires_at=expires_at,
            summary={
                "tool_name": tool_name,
                "parameters": _approval_parameters(action.parameters),
                "approved_tool_proposal": _approved_tool_summary(approved_tool_snapshot),
            },
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
            stage_results=_stage_results_for_waiting_approval(waiting_state, action),
            intent_resolution=waiting_state.intent_resolution,
            reasoning_summary=action.reasoning_summary.model_dump(mode="json"),
        )

    def _prepare_pre_loop_state(
        self,
        state: ControlledReActRunState,
        *,
        retrieval_max_queries: int,
    ) -> ControlledReActRunState:
        if self._ports.intent_resolution is not None:
            intent_result = self._ports.intent_resolution.resolve(state)
            stage_llm_interactions = _stage_llm_interactions_from_port(
                self._ports.intent_resolution
            )
            if self._ports.trace is not None:
                emit_intent_resolution(
                    self._ports.trace,
                    intent_result.intent_resolution,
                    max_queries=retrieval_max_queries,
                )
            state = state.model_copy(
                update={
                    "intent_resolution": intent_result.intent_resolution.model_dump(
                        mode="json",
                    ),
                    "stage_llm_interactions": (
                        state.stage_llm_interactions + stage_llm_interactions
                    ),
                }
            )
        if self._ports.memory is not None:
            state = state.model_copy(
                update={
                    "memory_context": dict(self._ports.memory.read(state)),
                    "memory_read_performed": True,
                }
            )
        return state

    def _write_memory(
        self,
        state: ControlledReActRunState,
        answer: AnswerSynthesisResult,
    ) -> ValidationResult | None:
        if self._ports.memory is None:
            return None
        candidate = self._ports.memory.prepare_write(state, answer)
        if candidate is None:
            return None
        self._emit_trace(
            "memory_write_requested",
            payload=_memory_write_requested_payload(candidate),
        )
        policy_decision = self._memory_write_policy_decision(state, candidate)
        if (
            policy_decision is not None
            and policy_decision.decision is not PolicyDecisionType.ALLOW
        ):
            result = _memory_write_denied_result(policy_decision)
            self._emit_trace(
                "memory_write_decision",
                status="blocked",
                payload=_memory_write_decision_payload(
                    candidate,
                    result,
                    policy_decision=policy_decision,
                ),
            )
            return result
        result = self._ports.memory.commit_write(candidate)
        self._emit_trace(
            "memory_write_decision",
            status="ok" if result.status is ValidationStatus.PASSED else "blocked",
            payload=_memory_write_decision_payload(
                candidate,
                result,
                policy_decision=policy_decision,
            ),
        )
        return result

    def _memory_write_policy_decision(
        self,
        state: ControlledReActRunState,
        candidate: MemoryWriteCandidate,
    ) -> PolicyDecision | None:
        if self._ports.policy is None:
            return None
        evaluate_memory_write = getattr(self._ports.policy, "evaluate_memory_write", None)
        if evaluate_memory_write is None:
            return None
        typed_evaluator = cast(
            Callable[[ControlledReActRunState, MemoryWriteCandidate], PolicyDecision],
            evaluate_memory_write,
        )
        decision = typed_evaluator(state, candidate)
        self._emit_trace(
            "policy_decision",
            status="ok" if decision.decision is PolicyDecisionType.ALLOW else "blocked",
            payload={
                "decision": decision.decision.value,
                "enforcement_point": decision.enforcement_point.value,
                "policy_rule_id": decision.policy_rule_id,
                "reason": decision.reason,
            },
        )
        return decision

    def _emit_trace(
        self,
        event_type: str,
        *,
        status: Literal["ok", "blocked", "waiting", "error"] = "ok",
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        if self._ports.trace is None:
            return
        self._ports.trace.emit(event_type, status=status, payload=payload or {})

    def _plan_next_action(
        self,
        state: ControlledReActRunState,
        *,
        max_plan_rounds: int,
    ) -> tuple[ControlledReActRunState, ReActActionProposal]:
        planning_state = self._prepare_plan_state(
            state,
            max_plan_rounds=max_plan_rounds,
        )
        action = self._ports.planner.plan(planning_state)
        action = self._constrain_next_action(
            planning_state,
            action,
            max_plan_rounds=max_plan_rounds,
        )
        return planning_state, action

    def _prepare_plan_state(
        self,
        state: ControlledReActRunState,
        *,
        max_plan_rounds: int,
    ) -> ControlledReActRunState:
        eligible_actions, _convergence_signal = _eligible_actions_for_state(
            state,
            max_plan_rounds=max_plan_rounds,
        )
        scope = None
        tool_scope_projections = tuple(state.tool_proposal_scope_trace_projections)
        if self._ports.tool_proposal_scope is not None:
            scope = self._ports.tool_proposal_scope.resolve(state)
            if not scope.tool_interfaces:
                eligible_actions = frozenset(
                    action
                    for action in eligible_actions
                    if action is not ReActActionType.PROPOSE_TOOL_CALL
                )
            tool_scope_projections = tool_scope_projections + (
                _tool_scope_trace_projection(scope, eligible_actions),
            )
        return state.model_copy(
            update={
                "effective_tool_proposal_scope": scope,
                "effective_react_action_set": tuple(
                    sorted(eligible_actions, key=lambda item: item.value)
                ),
                "bound_tool_proposal": None,
                "approved_tool_proposal_snapshot": None,
                "tool_proposal_scope_trace_projections": tool_scope_projections,
            }
        )

    def _bind_tool_proposal(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> tuple[ControlledReActRunState, ReActActionProposal]:
        scope = state.effective_tool_proposal_scope
        if scope is None:
            return state, action
        bound = self._tool_proposal_binder.bind(state, action, scope)
        return (
            state.model_copy(update={"bound_tool_proposal": bound}),
            action.model_copy(update={"parameters": dict(bound.parameters)}),
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
        identity = _allocate_observation_identity(observing_state, action)
        effect = self._ports.knowledge_observation.observe(
            observing_state,
            action,
            identity,
        )
        return self._commit_observation_effect(observing_state, action, effect, identity)

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
        identity = _allocate_observation_identity(observing_state, action)
        effect = self._ports.tool_observation.observe(observing_state, action, identity)
        return self._commit_observation_effect(observing_state, action, effect, identity)

    def _observe_tool_approval_denial(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
        request: ControlledReActResumeRequest,
    ) -> ControlledReActRunState:
        tool_name = action.target_tool_name or "unknown_tool"
        observing_state = state.model_copy(
            update={
                "phase": ControlledReActRunPhase.OBSERVING,
                "plan_round": state.plan_round + 1,
            }
        )
        identity = _allocate_observation_identity(observing_state, action)
        authorized_result = {
            "approval_state": "denied",
            "actor": request.actor,
        }
        truth = ToolObservationTruth(
            truth_ref=identity.truth_ref,
            observation_id=identity.observation_id,
            action_id=action.action_id,
            tool_name=tool_name,
            authorized_result=authorized_result,
            result_schema_id=f"{tool_name}.approval.v1",
            approval_ref=request.approval_id,
        )
        record = ObservationRecord(
            observation_id=identity.observation_id,
            action_id=action.action_id,
            action_type=action.action_type,
            round=observing_state.plan_round,
            truth_ref=identity.truth_ref,
            accepted_evidence_count=0,
            new_evidence_count=0,
            unresolved_subgoals=("tool_approval_denied",),
            source_refs=(f"tool://{tool_name}",),
            citation_refs=(),
        )
        return self._commit_observation_effect(
            observing_state,
            action,
            ObservationEffect(
                observation_record=record,
                truth_artifact=truth,
                trace_projection=authorized_result,
                tool_summary_projection=authorized_result,
            ),
            identity,
        )

    def _commit_observation_effect(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
        effect: ObservationEffect,
        identity: ObservationIdentity,
    ) -> ControlledReActRunState:
        result = self._observation_committer.commit(
            state,
            action,
            effect,
            expected_identity=identity,
        )
        if len(result.state.observation_records) <= len(state.observation_records):
            return result.state
        existing_projections = tuple(result.state.observation_trace_projections)
        projection_gap_records = result.state.observation_records[len(existing_projections) : -1]
        return result.state.model_copy(
            update={
                "observation_trace_projections": (
                    existing_projections
                    + tuple(dict(record.summary) for record in projection_gap_records)
                    + (result.trace_projection,)
                )
            }
        )

    def _admit_final_answer(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
        answer_context: AnswerEvidenceContext,
        answer: AnswerSynthesisResult,
    ) -> AnswerSynthesisResult:
        if answer.outcome is not ReceiptOutcome.ANSWERED_WITH_CITATIONS:
            return answer
        if self._ports.policy is None:
            return answer
        evaluate_answer = getattr(self._ports.policy, "evaluate_answer", None)
        if evaluate_answer is None:
            return answer
        decision = evaluate_answer(state, action, answer_context, answer)
        if decision.decision is PolicyDecisionType.ALLOW:
            return answer
        message = "The final answer was blocked by policy."
        return AnswerSynthesisResult(
            outcome=ReceiptOutcome.POLICY_DENIED,
            final_output=message,
            message=message,
            reasoning_summary=answer.reasoning_summary,
            model_usage_summary=answer.model_usage_summary,
            evidence=answer.evidence,
            stage_llm_interactions=answer.stage_llm_interactions,
        )

    def _answer_evidence_context(
        self,
        state: ControlledReActRunState,
    ) -> AnswerEvidenceContext:
        truths = tuple(
            self._observation_truth_store.load(record.truth_ref)
            for record in state.observation_records
        )
        _validate_answer_truth_context(state.observation_records, truths)
        citation_refs = tuple(
            ref for record in state.observation_records for ref in record.citation_refs
        )
        source_refs = tuple(
            ref for record in state.observation_records for ref in record.source_refs
        )
        return AnswerEvidenceContext(
            run_id=state.run_id,
            observation_truth=truths,
            citation_refs=citation_refs,
            source_refs=source_refs,
            validation_precheck={
                "observation_count": len(state.observation_records),
                "citation_ref_count": len(citation_refs),
                "source_ref_count": len(source_refs),
            },
        )

    def _constrain_next_action(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
        *,
        max_plan_rounds: int,
    ) -> ReActActionProposal:
        eligible_actions, convergence_signal = _eligible_actions_for_state(
            state,
            max_plan_rounds=max_plan_rounds,
        )
        if state.effective_react_action_set:
            eligible_actions = frozenset(state.effective_react_action_set)
        constrained, _rewrite = constrain_action(
            action,
            eligible_actions,
            convergence_signal=convergence_signal,
        )
        if should_block_duplicate_observation_action(
            constrained,
            action_history=_action_history_payload(state),
            observations=_observation_payloads(state),
        ):
            return constrained.model_copy(
                update={
                    "action_type": ReActActionType.REFUSE,
                    "parameters": {"refusal_reason": "observation_no_progress"},
                }
            )
        return constrained


def _eligible_actions_for_state(
    state: ControlledReActRunState,
    *,
    max_plan_rounds: int,
) -> tuple[frozenset[ReActActionType], str | None]:
    return compute_eligible_action_set(
        plan_rounds=state.plan_round,
        max_plan_rounds=max_plan_rounds,
        action_history=_action_history_payload(state),
        evidence_trajectory=[
            record.accepted_evidence_count for record in state.observation_records
        ],
        observations=_observation_payloads(state),
    )


def _tool_scope_violation(
    state: ControlledReActRunState,
    action: ReActActionProposal,
) -> bool:
    scope = state.effective_tool_proposal_scope
    if scope is None:
        return False
    tool_name = action.target_tool_name
    return tool_name not in scope.tool_contract_ids


def _approved_tool_integrity_mismatch(
    state: ControlledReActRunState,
    action: ReActActionProposal,
) -> bool:
    snapshot = state.approved_tool_proposal_snapshot
    if snapshot is None:
        return False
    if snapshot.action_id != action.action_id:
        return True
    if snapshot.tool_contract_id != (action.target_tool_name or ""):
        return True
    return snapshot.parameter_digest != _parameter_digest(action.parameters)


def _parameter_digest(parameters: Mapping[str, Any]) -> str:
    payload = json.dumps(
        _jsonable(parameters),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _jsonable(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_jsonable(item) for item in value]
    return value


def _tool_scope_trace_projection(
    scope: EffectiveToolProposalScope,
    eligible_actions: frozenset[ReActActionType],
) -> Mapping[str, Any]:
    return {
        "run_id": scope.run_id,
        "plan_round": scope.plan_round,
        "schema_digest": scope.schema_digest,
        "tool_contract_ids": scope.tool_contract_ids,
        "tool_interfaces": tuple(
            {
                "tool_contract_id": interface.tool_contract_id,
                "purpose": interface.purpose,
                "risk_level": interface.risk_level,
                "read_only": interface.read_only,
                "requires_approval": interface.requires_approval,
                "semantic_result_summary": interface.semantic_result_summary,
                "remaining_call_budget": interface.remaining_call_budget,
                "parameters": tuple(
                    {
                        "name": parameter.name,
                        "required": parameter.required,
                        "value_type": parameter.value_type,
                        "value_source": parameter.value_source.value,
                        "description": parameter.description,
                        "enum_values": parameter.enum_values,
                    }
                    for parameter in interface.parameters
                ),
            }
            for interface in scope.tool_interfaces
        ),
        "excluded_count": len(scope.excluded),
        "proposal_action_enabled": ReActActionType.PROPOSE_TOOL_CALL in eligible_actions,
    }


def _action_history_payload(state: ControlledReActRunState) -> list[Mapping[str, Any]]:
    return [
        {
            "action_type": action.action_type.value,
            "parameters": dict(action.parameters),
        }
        for action in state.action_history
    ]


def _allocate_observation_identity(
    state: ControlledReActRunState,
    action: ReActActionProposal,
) -> ObservationIdentity:
    return ObservationIdentity.allocate(
        run_id=state.run_id,
        plan_round=state.plan_round,
        action_id=action.action_id,
    )


def _validate_answer_truth_context(
    records: tuple[ObservationRecord, ...],
    truths: tuple[ObservationTruthArtifact, ...],
) -> None:
    for record, truth in zip(records, truths, strict=True):
        if record.truth_ref != truth.truth_ref:
            raise ValueError("observation record truth_ref does not match truth artifact")
        if record.observation_id != truth.observation_id:
            raise ValueError("observation record id does not match truth artifact")
        if isinstance(truth, RetrievalObservationTruth):
            missing = tuple(ref for ref in record.citation_refs if ref not in truth.citation_refs)
            if missing:
                raise ValueError("observation record citation_refs are missing from truth artifact")
        elif record.citation_refs:
            raise ValueError("tool observation record must not carry citation_refs")


def _observation_payloads(state: ControlledReActRunState) -> list[Mapping[str, Any]]:
    return [
        {
            "accepted_evidence_count": record.accepted_evidence_count,
            "unresolved_subgoals": list(record.unresolved_subgoals),
        }
        for record in state.observation_records
    ]


def _final_answer_blocked_by_denied_tool(state: ControlledReActRunState) -> bool:
    return bool(_denied_tool_names(state)) and all(
        record.accepted_evidence_count <= 0 for record in state.observation_records
    )


def _tool_approval_denied_answer(
    state: ControlledReActRunState,
    action: ReActActionProposal,
) -> AnswerSynthesisResult:
    tool_names = _denied_tool_names(state)
    tool_name = tool_names[0] if tool_names else "requested"
    message = f"The {tool_name} tool is still required after approval was denied."
    return AnswerSynthesisResult(
        outcome=ReceiptOutcome.TOOL_APPROVAL_DENIED,
        final_output=message,
        message=message,
        reasoning_summary=action.reasoning_summary.model_dump(mode="json"),
    )


def _denied_tool_names(state: ControlledReActRunState) -> tuple[str, ...]:
    names: list[str] = []
    for record in state.observation_records:
        if "tool_approval_denied" not in record.unresolved_subgoals:
            continue
        for source_ref in record.source_refs:
            if source_ref.startswith("tool://"):
                names.append(source_ref.removeprefix("tool://"))
                break
    return tuple(names)


def _clarification_missing_fields(
    action: ReActActionProposal,
) -> tuple[str, ...]:
    raw_missing_fields = action.parameters.get("missing_fields", ())
    candidates: tuple[Any, ...]
    if isinstance(raw_missing_fields, str):
        candidates = (raw_missing_fields,)
    else:
        try:
            candidates = tuple(raw_missing_fields)
        except TypeError:
            candidates = ()
    missing_fields = tuple(
        field.strip() for field in candidates if isinstance(field, str) and field.strip()
    )
    return missing_fields or ("required_details",)


def _human_join(values: tuple[str, ...]) -> str:
    if len(values) == 1:
        return values[0]
    return f"{', '.join(values[:-1])}, and {values[-1]}"


def _approval_parameters(parameters: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in parameters.items()}


def _approved_tool_snapshot(
    state: ControlledReActRunState,
    action: ReActActionProposal,
    *,
    policy_decision: PolicyDecisionType,
) -> ApprovedToolProposalSnapshot | None:
    bound = state.bound_tool_proposal
    if bound is None:
        return None
    return ApprovedToolProposalSnapshot(
        snapshot_id=f"approved_{action.action_id}",
        action_id=action.action_id,
        tool_contract_id=bound.tool_contract_id,
        parameters=bound.parameters,
        parameter_digest=bound.parameter_digest,
        scope_digest=bound.scope_digest,
        policy_decision=policy_decision.value,
        risk_level=action.risk_level,
        approval_reason="Human approval required before tool execution.",
    )


def _approved_tool_summary(
    snapshot: ApprovedToolProposalSnapshot | None,
) -> Mapping[str, Any] | None:
    if snapshot is None:
        return None
    return {
        "tool_contract_id": snapshot.tool_contract_id,
        "parameter_keys": tuple(sorted(snapshot.parameters)),
        "parameter_digest": snapshot.parameter_digest,
        "scope_digest": snapshot.scope_digest,
    }


def _stage_results_from_state(
    state: ControlledReActRunState,
) -> tuple[WorkflowStageResult, ...]:
    return tuple(
        WorkflowStageResult(
            stage_id=_stage_id_for_observation(record),
            status=WorkflowStageStatus.COMPLETED,
            summary=_stage_summary_for_observation(state, index, record),
            produced_fact_refs=record.source_refs or (record.truth_ref,),
        )
        for index, record in enumerate(state.observation_records)
    )


def _tool_proposal_scope_stage_results(
    state: ControlledReActRunState,
) -> tuple[WorkflowStageResult, ...]:
    return tuple(
        WorkflowStageResult(
            stage_id="tool_proposal_scope",
            status=WorkflowStageStatus.COMPLETED,
            summary=projection,
            produced_fact_refs=("effective_tool_proposal_scope",),
        )
        for projection in state.tool_proposal_scope_trace_projections
    )


def _stage_summary_for_observation(
    state: ControlledReActRunState,
    index: int,
    record: ObservationRecord,
) -> dict[str, Any]:
    if index < len(state.observation_trace_projections):
        return dict(state.observation_trace_projections[index])
    return dict(record.summary)


def _stage_id_for_observation(record: ObservationRecord) -> str:
    if record.action_type is ReActActionType.PROPOSE_TOOL_CALL:
        return "tool"
    if record.action_type is ReActActionType.PLAN_RETRIEVAL:
        return "retrieval"
    return str(record.action_type.value)


def _stage_results_for_answer(
    state: ControlledReActRunState,
    answer: AnswerSynthesisResult,
    final_action: ReActActionProposal,
    *,
    memory_write_result: ValidationResult | None = None,
) -> tuple[WorkflowStageResult, ...]:
    results: list[WorkflowStageResult] = []
    if state.intent_resolution is not None:
        results.append(_intent_resolution_stage_result(state))
    if state.memory_read_performed:
        results.append(_memory_read_stage_result(state))
    scope_stage_results = list(_tool_proposal_scope_stage_results(state))
    if scope_stage_results:
        results.append(scope_stage_results.pop(0))
    first_retrieval_action = _first_action_of_type(
        state,
        ReActActionType.PLAN_RETRIEVAL,
    )
    if first_retrieval_action is not None:
        results.append(_plan_stage_result(state, first_retrieval_action))
        results.append(_retrieval_review_stage_result(first_retrieval_action))
    first_tool_action = _first_action_of_type(
        state,
        ReActActionType.PROPOSE_TOOL_CALL,
    )
    if first_tool_action is not None:
        results.append(_plan_stage_result(state, first_tool_action))
        results.append(_tool_review_stage_result(first_tool_action))
    results.extend(_stage_results_from_state(state))
    results.extend(scope_stage_results)
    results.append(_plan_stage_result(state, final_action))
    results.append(_model_answer_stage_result(answer))
    if memory_write_result is not None:
        results.append(_memory_write_stage_result(memory_write_result))
    results.append(_response_stage_result(answer))
    return tuple(results)


def _stage_results_for_refusal(
    state: ControlledReActRunState,
    answer: AnswerSynthesisResult,
    final_action: ReActActionProposal,
    *,
    memory_write_result: ValidationResult | None = None,
) -> tuple[WorkflowStageResult, ...]:
    results = _stage_results_before_terminal(state, final_action)
    if memory_write_result is not None:
        results.append(_memory_write_stage_result(memory_write_result))
    results.append(_response_stage_result(answer))
    return tuple(results)


def _stage_results_for_waiting_approval(
    state: ControlledReActRunState,
    action: ReActActionProposal,
) -> tuple[WorkflowStageResult, ...]:
    results: list[WorkflowStageResult] = []
    if state.intent_resolution is not None:
        results.append(_intent_resolution_stage_result(state))
    if state.memory_read_performed:
        results.append(_memory_read_stage_result(state))
    results.extend(_tool_proposal_scope_stage_results(state))
    results.append(_plan_stage_result(state, action))
    results.append(_tool_review_stage_result(action))
    return tuple(results)


def _stage_results_before_terminal(
    state: ControlledReActRunState,
    final_action: ReActActionProposal,
) -> list[WorkflowStageResult]:
    results: list[WorkflowStageResult] = []
    if state.intent_resolution is not None:
        results.append(_intent_resolution_stage_result(state))
    if state.memory_read_performed:
        results.append(_memory_read_stage_result(state))
    scope_stage_results = list(_tool_proposal_scope_stage_results(state))
    if scope_stage_results:
        results.append(scope_stage_results.pop(0))
    first_retrieval_action = _first_action_of_type(
        state,
        ReActActionType.PLAN_RETRIEVAL,
    )
    if first_retrieval_action is not None:
        results.append(_plan_stage_result(state, first_retrieval_action))
        results.append(_retrieval_review_stage_result(first_retrieval_action))
    first_tool_action = _first_action_of_type(
        state,
        ReActActionType.PROPOSE_TOOL_CALL,
    )
    if first_tool_action is not None:
        results.append(_plan_stage_result(state, first_tool_action))
        results.append(_tool_review_stage_result(first_tool_action))
    results.extend(_stage_results_from_state(state))
    results.extend(scope_stage_results)
    results.append(_plan_stage_result(state, final_action))
    return results


def _intent_resolution_stage_result(
    state: ControlledReActRunState,
) -> WorkflowStageResult:
    intent_resolution = dict(state.intent_resolution or {})
    return WorkflowStageResult(
        stage_id="intent_resolution",
        status=WorkflowStageStatus.COMPLETED,
        summary={
            "resolution_id": str(intent_resolution.get("resolution_id", "")),
            "domain_intent": str(intent_resolution.get("domain_intent", "")),
            "recommended_next_action": str(intent_resolution.get("recommended_next_action", "")),
            "confidence": intent_resolution.get("confidence", 0),
        },
        produced_fact_refs=("intent_resolution",),
    )


def _memory_read_stage_result(
    state: ControlledReActRunState,
) -> WorkflowStageResult:
    memory_context = dict(state.memory_context)
    return WorkflowStageResult(
        stage_id="memory_read",
        status=WorkflowStageStatus.COMPLETED,
        summary={
            "read_key_count": len(memory_context),
            "keys": sorted(memory_context),
        },
        produced_fact_refs=("memory_context",),
    )


def _plan_stage_result(
    state: ControlledReActRunState,
    final_action: ReActActionProposal,
) -> WorkflowStageResult:
    return WorkflowStageResult(
        stage_id="plan",
        status=WorkflowStageStatus.COMPLETED,
        summary={
            "action_count": len(state.action_history) + 1,
            "plan_round": state.plan_round,
            "final_action_id": final_action.action_id,
            "final_action_type": final_action.action_type.value,
        },
        produced_fact_refs=("reasoning_summary", "action_proposal"),
    )


def _retrieval_review_stage_result(
    action: ReActActionProposal,
) -> WorkflowStageResult:
    return WorkflowStageResult(
        stage_id="retrieval_review",
        status=WorkflowStageStatus.COMPLETED,
        summary={
            "action_id": action.action_id,
            "action_type": action.action_type.value,
            "review_status": "allowed",
        },
        produced_fact_refs=("review_results",),
    )


def _tool_review_stage_result(
    action: ReActActionProposal,
) -> WorkflowStageResult:
    return WorkflowStageResult(
        stage_id="tool_review",
        status=WorkflowStageStatus.COMPLETED,
        summary={
            "action_id": action.action_id,
            "action_type": action.action_type.value,
            "tool_name": action.target_tool_name or "",
            "review_status": "allowed",
        },
        produced_fact_refs=("review_results",),
    )


def _model_answer_stage_result(answer: AnswerSynthesisResult) -> WorkflowStageResult:
    return WorkflowStageResult(
        stage_id="model_answer",
        status=(
            WorkflowStageStatus.COMPLETED
            if answer.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
            else WorkflowStageStatus.BLOCKED
        ),
        outcome=answer.outcome,
        summary={
            "outcome": answer.outcome.value,
            "final_output_length": len(answer.final_output),
            "model_call_count": len(answer.stage_llm_interactions),
        },
        produced_fact_refs=("final_output", "review_results"),
    )


def _memory_write_stage_result(
    result: ValidationResult,
) -> WorkflowStageResult:
    return WorkflowStageResult(
        stage_id="memory",
        status=(
            WorkflowStageStatus.COMPLETED
            if result.status is ValidationStatus.PASSED
            else WorkflowStageStatus.BLOCKED
        ),
        summary={
            "status": result.status.value,
            "validator_name": result.validator_name,
            "written_fields": list(result.metadata.get("written_fields", ())),
        },
        produced_fact_refs=("memory_write",),
    )


def _memory_write_requested_payload(
    candidate: MemoryWriteCandidate,
) -> dict[str, Any]:
    field_names = list(candidate.field_names)
    return {
        "field_names": field_names,
        "field_count": len(field_names),
        "write_source": candidate.write_source,
    }


def _memory_write_decision_payload(
    candidate: MemoryWriteCandidate,
    result: ValidationResult,
    *,
    policy_decision: PolicyDecision | None,
) -> dict[str, Any]:
    decision = policy_decision.decision.value if policy_decision is not None else "allow"
    payload: dict[str, Any] = {
        "decision": decision,
        "field_names": list(candidate.field_names),
        "field_count": candidate.field_count,
        "write_source": candidate.write_source,
        "validator_status": result.status.value,
        "metadata": dict(result.metadata),
    }
    if policy_decision is not None:
        payload["policy_rule_id"] = policy_decision.policy_rule_id
        payload["reason"] = policy_decision.reason
    return payload


def _memory_write_denied_result(decision: PolicyDecision) -> ValidationResult:
    denied_fields = tuple(decision.metadata.get("denied_fields", ()))
    return ValidationResult(
        validator_name="memory",
        status=ValidationStatus.FAILED,
        reason=decision.reason,
        metadata={
            "denied_fields": denied_fields,
            "policy_rule_id": decision.policy_rule_id,
            "decision": decision.decision.value,
        },
    )


def _response_stage_result(answer: AnswerSynthesisResult) -> WorkflowStageResult:
    return WorkflowStageResult(
        stage_id="response",
        status=WorkflowStageStatus.COMPLETED,
        outcome=answer.outcome,
        summary={
            "outcome": answer.outcome.value,
            "message_length": len(answer.message),
        },
        produced_fact_refs=("final_output",),
    )


def _stage_llm_interactions_from_port(
    port: object,
) -> tuple[WorkflowStageLlmInteraction, ...]:
    interactions = getattr(port, "stage_llm_interactions", ())
    if not isinstance(interactions, list | tuple):
        return ()
    return tuple(
        interaction
        for interaction in interactions
        if isinstance(interaction, WorkflowStageLlmInteraction)
    )


def _first_action_of_type(
    state: ControlledReActRunState,
    action_type: ReActActionType,
) -> ReActActionProposal | None:
    for action in state.action_history:
        if action.action_type is action_type:
            return action
    return None


def _workflow_result_from_answer(
    state: ControlledReActRunState,
    answer: AnswerSynthesisResult,
    final_action: ReActActionProposal,
    *,
    memory_write_result: ValidationResult | None = None,
) -> WorkflowTemplateExecutionResult:
    return WorkflowTemplateExecutionResult(
        run_id=state.run_id,
        template_name=state.template_name,
        template_descriptor_version=state.template_descriptor_version,
        outcome=answer.outcome,
        final_output=answer.final_output,
        message=answer.message,
        evidence=answer.evidence,
        stage_results=_stage_results_for_answer(
            state,
            answer,
            final_action,
            memory_write_result=memory_write_result,
        ),
        intent_resolution=state.intent_resolution,
        reasoning_summary=answer.reasoning_summary,
        model_usage_summary=answer.model_usage_summary,
        stage_llm_interactions=(
            state.stage_llm_interactions + answer.stage_llm_interactions
        ),
    )
