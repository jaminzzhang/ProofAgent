from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from proof_agent.contracts import (
    ApprovalPause,
    ClarificationNeed,
    ControlledReActRunPhase,
    ControlledReActRunState,
    ControlledReActRunStateSnapshot,
    ObservationRecord,
    PolicyDecisionType,
    ReActActionProposal,
    ReActActionType,
    ReceiptOutcome,
    ValidationResult,
    ValidationStatus,
    WorkflowStageResult,
    WorkflowStageStatus,
    WorkflowTemplateExecutionResult,
)
from proof_agent.control.workflow.controlled_react.ports import (
    AnswerSynthesisResult,
    ControlledReActPorts,
)
from proof_agent.control.workflow.controlled_react.state_machine import (
    ControlledReActStateMachine,
    EffectResult,
    TransitionCommand,
    TransitionCommandType,
)
from proof_agent.control.workflow.react_enterprise_qa import (
    compute_eligible_action_set,
    constrain_action,
    should_block_duplicate_observation_action,
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
        state = self._prepare_pre_loop_state(state)
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
            return self._refuse_plan_budget_exhausted(request, action, state=state)
        if action.action_type is ReActActionType.ASK_CLARIFICATION:
            return self._ask_clarification(request, action)
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
                memory_write = self._write_memory(state, answer)
                return WorkflowTemplateExecutionResult(
                    run_id=request.run_id,
                    template_name=request.template_name,
                    template_descriptor_version=request.template_descriptor_version,
                    outcome=answer.outcome,
                    final_output=answer.final_output,
                    message=answer.message,
                    evidence=answer.evidence,
                    stage_results=_stage_results_for_answer(
                        state,
                        answer,
                        action,
                        memory_write_result=memory_write,
                    ),
                    intent_resolution=state.intent_resolution,
                    reasoning_summary=answer.reasoning_summary,
                    model_usage_summary=answer.model_usage_summary,
                    stage_llm_interactions=answer.stage_llm_interactions,
                )
            return self._pause_for_tool_approval(request, state, action)
        if action.action_type is not ReActActionType.GENERATE_FINAL_ANSWER:
            raise ValueError(f"unsupported start action: {action.action_type}")
        answer = self._ports.answer_synthesis.synthesize(state, action)
        memory_write = self._write_memory(state, answer)
        return WorkflowTemplateExecutionResult(
            run_id=request.run_id,
            template_name=request.template_name,
            template_descriptor_version=request.template_descriptor_version,
            outcome=answer.outcome,
            final_output=answer.final_output,
            message=answer.message,
            evidence=answer.evidence,
            stage_results=_stage_results_for_answer(
                state,
                answer,
                action,
                memory_write_result=memory_write,
            ),
            intent_resolution=state.intent_resolution,
            reasoning_summary=answer.reasoning_summary,
            model_usage_summary=answer.model_usage_summary,
            stage_llm_interactions=answer.stage_llm_interactions,
        )

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
        message = (
            "Please provide "
            f"{_human_join(missing_fields)} before I can continue."
        )
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
            next_action = self._ports.planner.plan(planning_state)
            if next_action.action_type is ReActActionType.REFUSE:
                return self._refuse_plan_budget_exhausted(
                    ControlledReActStartRequest(
                        run_id=planning_state.run_id,
                        template_name=planning_state.template_name,
                        template_descriptor_version=(
                            planning_state.template_descriptor_version
                        ),
                        question=planning_state.question,
                    ),
                    next_action,
                    state=planning_state,
                )
            if next_action.action_type is not ReActActionType.GENERATE_FINAL_ANSWER:
                raise ValueError(
                    f"unsupported denied approval follow-up action: {next_action.action_type}"
                )
            answer = self._ports.answer_synthesis.synthesize(planning_state, next_action)
            memory_write = self._write_memory(planning_state, answer)
            return WorkflowTemplateExecutionResult(
                run_id=planning_state.run_id,
                template_name=planning_state.template_name,
                template_descriptor_version=planning_state.template_descriptor_version,
                outcome=answer.outcome,
                final_output=answer.final_output,
                message=answer.message,
                evidence=answer.evidence,
                stage_results=_stage_results_for_answer(
                    planning_state,
                    answer,
                    next_action,
                    memory_write_result=memory_write,
                ),
                intent_resolution=planning_state.intent_resolution,
                reasoning_summary=answer.reasoning_summary,
                model_usage_summary=answer.model_usage_summary,
                stage_llm_interactions=answer.stage_llm_interactions,
            )
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
        memory_write = self._write_memory(planning_state, answer)
        return WorkflowTemplateExecutionResult(
            run_id=planning_state.run_id,
            template_name=planning_state.template_name,
            template_descriptor_version=planning_state.template_descriptor_version,
            outcome=answer.outcome,
            final_output=answer.final_output,
            message=answer.message,
            evidence=answer.evidence,
            stage_results=_stage_results_for_answer(
                planning_state,
                answer,
                next_action,
                memory_write_result=memory_write,
            ),
            intent_resolution=planning_state.intent_resolution,
            reasoning_summary=answer.reasoning_summary,
            model_usage_summary=answer.model_usage_summary,
            stage_llm_interactions=answer.stage_llm_interactions,
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
            summary={
                "tool_name": tool_name,
                "parameters": _approval_parameters(action.parameters),
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
    ) -> ControlledReActRunState:
        if self._ports.intent_resolution is not None:
            intent_result = self._ports.intent_resolution.resolve(state)
            state = state.model_copy(
                update={
                    "intent_resolution": intent_result.intent_resolution.model_dump(
                        mode="json",
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
        return self._ports.memory.write(state, answer)

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
        observation = ObservationRecord(
            observation_id=f"obs_denied_{action.action_id}",
            action_id=action.action_id,
            action_type=action.action_type,
            round=observing_state.plan_round,
            truth_ref=f"approval://{request.approval_id}",
            summary={
                "tool_name": tool_name,
                "approval_state": "denied",
                "actor": request.actor,
            },
            accepted_evidence_count=0,
            new_evidence_count=0,
            unresolved_subgoals=("tool_approval_denied",),
            source_refs=(f"tool://{tool_name}",),
            citation_refs=(),
        )
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
        field.strip()
        for field in candidates
        if isinstance(field, str) and field.strip()
    )
    return missing_fields or ("required_details",)


def _human_join(values: tuple[str, ...]) -> str:
    if len(values) == 1:
        return values[0]
    return f"{', '.join(values[:-1])}, and {values[-1]}"


def _approval_parameters(parameters: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in parameters.items()}


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
            "recommended_next_action": str(
                intent_resolution.get("recommended_next_action", "")
            ),
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


def _first_action_of_type(
    state: ControlledReActRunState,
    action_type: ReActActionType,
) -> ReActActionProposal | None:
    for action in state.action_history:
        if action.action_type is action_type:
            return action
    return None
