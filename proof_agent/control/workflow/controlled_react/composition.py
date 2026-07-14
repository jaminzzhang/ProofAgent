from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from proof_agent.capabilities.react.planner import DeterministicReActPlanner
from proof_agent.capabilities.react.intent import DeterministicIntentResolver
from proof_agent.bootstrap.composition import HarnessInvocation
from proof_agent.contracts import (
    AnswerEvidenceContext,
    ControlledReActRunState,
    ControlledReActRunStateSnapshot,
    EffectiveToolProposalScope,
    EvidenceChunk,
    EvidenceStatus,
    EnforcementPoint,
    IntentResolutionResult,
    IntentResolution,
    ModelCallRole,
    ObservationRecord,
    PolicyDecision,
    ReActActionProposal,
    ReActActionType,
    ReasoningSummary,
    ReceiptOutcome,
    RetrievalQueryItem,
    RetrievalObservationTruth,
    ReviewDecision,
    ToolObservationTruth,
    ValidationResult,
    WorkflowStageLlmInteraction,
)
from proof_agent.control.workflow.controlled_react.orchestrator import (
    ControlledReActOrchestrator,
)
from proof_agent.control.workflow.controlled_react.final_answer_attempt import (
    FinalAnswerAttemptRunner,
)
from proof_agent.control.workflow.controlled_react.observation_commit import (
    ObservationEffect,
    ObservationIdentity,
    ObservationSummaryBuilder,
)
from proof_agent.control.workflow.controlled_react.ports import (
    AnswerSynthesisResult,
    ControlledReActPorts,
    MemoryWriteCandidate,
    ObservationTruthStorePort,
    SnapshotStorePort,
    TracePort,
)
from proof_agent.control.workflow.controlled_react.tool_proposal_scope import (
    ToolProposalScopeResolver,
)
from proof_agent.control.workflow.harness_helpers import emit_policy_decision
from proof_agent.control.workflow.react_enterprise_qa import review_action
from proof_agent.control.validators.evidence import evaluate_evidence
from proof_agent.control.knowledge.retrieval_service import (
    KnowledgeRetrievalRequest,
    KnowledgeRetrievalService,
)
from proof_agent.control.knowledge.hybrid_request import GovernedHybridRetrievalRequest
from proof_agent.control.knowledge.answer_validator import (
    render_insurance_answer,
    validate_serialized_insurance_answer,
)
from proof_agent.errors import ProofAgentError


def build_default_controlled_react_orchestrator() -> ControlledReActOrchestrator:
    """Assemble the local deterministic V3 Controlled ReAct orchestrator."""

    return ControlledReActOrchestrator(
        ports=ControlledReActPorts(
            planner=_DeterministicPlannerAdapter(),
            knowledge_observation=_DeterministicKnowledgeObservationAdapter(),
            tool_observation=_DeterministicToolObservationAdapter(),
            snapshot_store=_InMemorySnapshotStoreAdapter(),
            answer_synthesis=_DeterministicAnswerSynthesisAdapter(),
        )
    )


def build_controlled_react_orchestrator_for_invocation(
    invocation: HarnessInvocation,
    *,
    snapshot_store: SnapshotStorePort | None = None,
    observation_truth_store: ObservationTruthStorePort | None = None,
    trace: TracePort | None = None,
) -> ControlledReActOrchestrator:
    """Assemble a run-scoped V3 orchestrator from resolved Harness capabilities."""

    trace_port = trace or _NoopTrace()
    _wrap_control_plane_model_providers_for_v3(invocation, trace_port)
    return ControlledReActOrchestrator(
        ports=ControlledReActPorts(
            planner=_InvocationPlannerAdapter(invocation),
            intent_resolution=_InvocationIntentResolutionAdapter(invocation),
            memory=_InvocationMemoryAdapter(invocation),
            knowledge_observation=_InvocationKnowledgeObservationAdapter(
                invocation,
                trace=trace_port,
            ),
            tool_observation=_InvocationToolObservationAdapter(invocation),
            policy=_InvocationPolicyAdapter(invocation, trace=trace_port),
            review=_InvocationReviewAdapter(invocation, trace=trace_port),
            trace=trace_port,
            tool_proposal_scope=_InvocationToolProposalScopeAdapter(invocation),
            snapshot_store=snapshot_store or _InMemorySnapshotStoreAdapter(),
            observation_truth_store=observation_truth_store,
            answer_synthesis=_ModelAnswerSynthesisAdapter(invocation, trace=trace_port),
        )
    )


class _DeterministicPlannerAdapter:
    def __init__(self) -> None:
        self._planner = DeterministicReActPlanner()

    def plan(self, state: ControlledReActRunState) -> ReActActionProposal:
        return self._planner.plan(
            question=state.question,
            system_prompt="Controlled ReAct Orchestrator V3",
            context_summary=_context_summary(state),
            conversation_context=state.conversation_context,
            memory_recall_payloads=state.memory_recall_payloads,
        )


class _InvocationIntentResolutionAdapter:
    def __init__(self, invocation: HarnessInvocation) -> None:
        self._invocation = invocation
        self._fallback = DeterministicIntentResolver()
        self.stage_llm_interactions: tuple[WorkflowStageLlmInteraction, ...] = ()

    def resolve(self, state: ControlledReActRunState) -> IntentResolutionResult:
        resolver = self._invocation.intent_resolver or self._fallback
        result = resolver.resolve(
            question=state.question,
            system_prompt="Resolve user intent before Controlled ReAct planning.",
            context_summary="pre_loop=true",
            workflow_stage_context=None,
            conversation_context=state.conversation_context,
            memory_recall_payloads=state.memory_recall_payloads,
            business_flow_skill_packs=self._invocation.business_flow_skill_packs,
        )
        self.stage_llm_interactions = _intent_resolver_stage_llm_interactions(resolver)
        return result


class _InvocationMemoryAdapter:
    def __init__(self, invocation: HarnessInvocation) -> None:
        self._memory = invocation.create_memory()

    def read(self, state: ControlledReActRunState) -> Mapping[str, Any]:
        _ = state
        return self._memory.read()

    def prepare_write(
        self,
        state: ControlledReActRunState,
        answer: AnswerSynthesisResult,
    ) -> MemoryWriteCandidate:
        return MemoryWriteCandidate(
            values={
                "question": state.question,
                "outcome": answer.outcome.value,
                "final_output_length": len(answer.final_output),
            }
        )

    def commit_write(self, candidate: MemoryWriteCandidate) -> ValidationResult:
        return self._memory.write(
            candidate.values,
        )


class _InvocationPlannerAdapter:
    def __init__(self, invocation: HarnessInvocation) -> None:
        self._invocation = invocation
        self._fallback = DeterministicReActPlanner()
        self.stage_llm_interactions: tuple[WorkflowStageLlmInteraction, ...] = ()

    def plan(self, state: ControlledReActRunState) -> ReActActionProposal:
        self.stage_llm_interactions = ()
        if _has_tool_observation(state):
            return _final_answer_action("act_generate_after_tool")
        governed_action = _governed_hybrid_terminal_action(self._invocation, state)
        if governed_action is not None:
            return governed_action
        planner = self._invocation.react_planner or self._fallback
        action = planner.plan(
            question=state.question,
            system_prompt="Controlled ReAct Orchestrator V3",
            context_summary=_context_summary(state),
            conversation_context=state.conversation_context,
            memory_recall_payloads=state.memory_recall_payloads,
            eligible_actions=(
                frozenset(state.effective_react_action_set)
                if state.effective_react_action_set
                else None
            ),
            effective_tool_proposal_scope=state.effective_tool_proposal_scope,
        )
        self.stage_llm_interactions = _drain_model_provider_stage_llm_interactions(
            planner,
            stage_id="plan",
            stage_label="Plan",
        )
        return action


class _InvocationToolProposalScopeAdapter:
    def __init__(self, invocation: HarnessInvocation) -> None:
        self._invocation = invocation
        self._resolver = ToolProposalScopeResolver()

    def resolve(self, state: ControlledReActRunState) -> EffectiveToolProposalScope:
        return self._resolver.resolve(
            state,
            tools=self._invocation.tool_gateway.tools,
        )


class _DeterministicKnowledgeObservationAdapter:
    def __init__(self) -> None:
        self._summary_builder = ObservationSummaryBuilder()

    def observe(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
        identity: ObservationIdentity,
    ) -> ObservationEffect:
        evidence = EvidenceChunk(
            source="customer-support-policy.md",
            content="Travel meals are reimbursed when supported by governed policy evidence.",
            status=EvidenceStatus.ACCEPTED,
            citation="customer-support-policy.md#travel-meals:L3-L7",
        )
        truth = RetrievalObservationTruth(
            truth_ref=identity.truth_ref,
            observation_id=identity.observation_id,
            action_id=action.action_id,
            accepted_evidence=(evidence,),
            citation_refs=("customer-support-policy.md#travel-meals:L3-L7",),
        )
        summary = self._summary_builder.build(truth)
        record = ObservationRecord(
            observation_id=identity.observation_id,
            action_id=action.action_id,
            action_type=action.action_type,
            round=state.plan_round,
            truth_ref=identity.truth_ref,
            summary=summary,
            accepted_evidence_count=1,
            new_evidence_count=1,
            unresolved_subgoals=(),
            source_refs=("customer-support-policy.md",),
            citation_refs=("customer-support-policy.md#travel-meals:L3-L7",),
        )
        return ObservationEffect(
            observation_record=record,
            truth_artifact=truth,
            trace_projection=dict(summary),
            tool_summary_fields=("status",),
        )


class _InvocationKnowledgeObservationAdapter:
    def __init__(self, invocation: HarnessInvocation, *, trace: TracePort) -> None:
        self._invocation = invocation
        self._summary_builder = ObservationSummaryBuilder()
        self._trace = trace

    def observe(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
        identity: ObservationIdentity,
    ) -> ObservationEffect:
        query = _string_value(action.parameters.get("query")) or state.question
        retrieval = self._invocation.manifest.retrieval
        trace = _StageScopedTrace(self._trace, stage_id="retrieval")
        service = KnowledgeRetrievalService(
            trace=trace,
            policy=self._invocation.policy,
            knowledge_provider=self._invocation.knowledge_provider,
        )
        retrieval_result = service.retrieve(
            KnowledgeRetrievalRequest(
                question=query,
                strategy=retrieval.strategy,
                top_k=retrieval.top_k,
                min_score=retrieval.min_score,
                max_steps=retrieval.max_steps,
                max_rounds=retrieval.max_rounds,
                planner_model=self._invocation.retrieval_planner_model,
                evaluator_model=self._invocation.retrieval_evaluator_model,
                retrieval_query_set=_retrieval_query_set_from_intent_state(state),
                max_queries=retrieval.max_queries,
                query_concurrency=retrieval.query_concurrency,
                query_timeout_seconds=retrieval.query_timeout_seconds,
                governed_hybrid_request=_governed_hybrid_request_from_controlled_state(
                    self._invocation,
                    state,
                ),
            )
        )
        evidence, accepted_evidence, evaluation_metadata = _admit_evidence(
            retrieval_result.evidence,
            min_score=retrieval.min_score,
        )
        _emit_admitted_evidence_trace(
            trace,
            accepted_evidence=accepted_evidence,
        )
        truth = RetrievalObservationTruth(
            truth_ref=identity.truth_ref,
            observation_id=identity.observation_id,
            action_id=action.action_id,
            accepted_evidence=accepted_evidence,
            rejected_evidence_summary={"count": len(evidence) - len(accepted_evidence)},
            admission_metadata={
                "min_score": self._invocation.manifest.retrieval.min_score,
                "evidence_validation": evaluation_metadata,
                "query": query,
            },
            citation_refs=tuple(
                chunk.citation for chunk in accepted_evidence if chunk.citation is not None
            ),
        )
        summary = self._summary_builder.build(truth)
        record = ObservationRecord(
            observation_id=identity.observation_id,
            action_id=action.action_id,
            action_type=action.action_type,
            round=state.plan_round,
            truth_ref=identity.truth_ref,
            summary=summary,
            accepted_evidence_count=len(accepted_evidence),
            new_evidence_count=len(accepted_evidence),
            unresolved_subgoals=(),
            source_refs=tuple(chunk.source for chunk in accepted_evidence),
            citation_refs=tuple(
                chunk.citation for chunk in accepted_evidence if chunk.citation is not None
            ),
        )
        return ObservationEffect(
            observation_record=record,
            truth_artifact=truth,
            trace_projection=dict(summary),
        )


class _DeterministicToolObservationAdapter:
    def __init__(self) -> None:
        self._summary_builder = ObservationSummaryBuilder()

    def observe(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
        identity: ObservationIdentity,
    ) -> ObservationEffect:
        _ = state
        tool_name = action.target_tool_name or "unknown_tool"
        truth = ToolObservationTruth(
            truth_ref=identity.truth_ref,
            observation_id=identity.observation_id,
            action_id=action.action_id,
            tool_name=tool_name,
            authorized_result={"status": "completed"},
            result_schema_id=f"{tool_name}.v1",
        )
        summary = self._summary_builder.build(
            truth,
            tool_summary_fields=("status",),
        )
        record = ObservationRecord(
            observation_id=identity.observation_id,
            action_id=action.action_id,
            action_type=action.action_type,
            round=state.plan_round,
            truth_ref=identity.truth_ref,
            summary=summary,
            accepted_evidence_count=0,
            new_evidence_count=0,
            unresolved_subgoals=(),
            source_refs=(f"tool://{tool_name}",),
            citation_refs=(),
        )
        return ObservationEffect(
            observation_record=record,
            truth_artifact=truth,
            trace_projection=dict(summary),
        )


class _InvocationToolObservationAdapter:
    def __init__(self, invocation: HarnessInvocation) -> None:
        self._invocation = invocation
        self._summary_builder = ObservationSummaryBuilder()

    def observe(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
        identity: ObservationIdentity,
    ) -> ObservationEffect:
        tool_name = action.target_tool_name or "unknown_tool"
        result = self._invocation.tool_gateway.request_tool(
            tool_name=tool_name,
            parameters=dict(action.parameters),
            approved=True,
            run_id=state.run_id,
        )
        tool_result = dict(result.result or {})
        truth = ToolObservationTruth(
            truth_ref=identity.truth_ref,
            observation_id=identity.observation_id,
            action_id=action.action_id,
            tool_name=tool_name,
            authorized_result=tool_result,
            result_schema_id=f"{tool_name}.v1",
            redaction_metadata={"redacted_field_count": 0},
        )
        config = self._invocation.tool_gateway.tools.get(tool_name)
        summary_projection = _tool_summary_projection(
            tool_result,
            summary_fields=config.summary_fields if config is not None else (),
        )
        summary = self._summary_builder.build(
            truth,
            tool_summary_projection=summary_projection,
        )
        record = ObservationRecord(
            observation_id=identity.observation_id,
            action_id=action.action_id,
            action_type=action.action_type,
            round=state.plan_round,
            truth_ref=identity.truth_ref,
            summary=summary,
            accepted_evidence_count=0,
            new_evidence_count=0,
            unresolved_subgoals=(),
            source_refs=(f"tool://{tool_name}",),
            citation_refs=(),
        )
        return ObservationEffect(
            observation_record=record,
            truth_artifact=truth,
            trace_projection={
                **dict(summary),
                "executed": result.executed,
                "approval_state": result.approval_state.model_dump(mode="json"),
            },
            tool_summary_projection=summary_projection,
        )


def _tool_summary_projection(
    tool_result: Mapping[str, Any],
    *,
    summary_fields: tuple[str, ...],
) -> Mapping[str, Any]:
    nested_summary = tool_result.get("summary")
    if isinstance(nested_summary, Mapping):
        _require_summary_fields(nested_summary, summary_fields)
        return {field: nested_summary[field] for field in summary_fields if field in nested_summary}
    _require_summary_fields(tool_result, summary_fields)
    return {field: tool_result[field] for field in summary_fields if field in tool_result}


def _require_summary_fields(
    projection_source: Mapping[str, Any],
    summary_fields: tuple[str, ...],
) -> None:
    missing = [field for field in summary_fields if field not in projection_source]
    if missing:
        raise ProofAgentError(
            "PA_TOOL_SOURCE_002",
            "tool result is missing summary_fields.",
            "Return all Tool Contract summary_fields from the tool result.",
        )


class _NoopTrace:
    def emit(
        self,
        event_type: str,
        *,
        status: str = "ok",
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        _ = (event_type, status, payload)


def _wrap_control_plane_model_providers_for_v3(
    invocation: HarnessInvocation,
    trace: TracePort,
) -> None:
    from proof_agent.control.workflow.react_enterprise_qa_stage_behavior import (
        wrap_control_plane_model_providers,
    )

    wrap_control_plane_model_providers(
        invocation,
        trace,
        stage_id_by_role={
            ModelCallRole.INTENT_RESOLUTION: "intent_resolution",
            ModelCallRole.REACT_PLANNER: "plan",
            ModelCallRole.HARNESS_REVIEW: "retrieval_review",
        },
    )


def _drain_model_provider_stage_llm_interactions(
    owner: object,
    *,
    stage_id: str,
    stage_label: str,
) -> tuple[WorkflowStageLlmInteraction, ...]:
    provider = getattr(owner, "model_provider", None)
    drain = getattr(provider, "drain_sensitive_interactions", None)
    if not callable(drain):
        return ()
    raw_interactions = drain(stage_id=stage_id, stage_label=stage_label)
    if not isinstance(raw_interactions, list | tuple):
        return ()
    interactions: list[WorkflowStageLlmInteraction] = []
    for raw_interaction in raw_interactions:
        if isinstance(raw_interaction, WorkflowStageLlmInteraction):
            interactions.append(raw_interaction)
        elif isinstance(raw_interaction, Mapping):
            interactions.append(WorkflowStageLlmInteraction(**dict(raw_interaction)))
    return tuple(interactions)


class _StageScopedTrace:
    def __init__(self, trace: TracePort, *, stage_id: str) -> None:
        self._trace = trace
        self._stage_id = stage_id

    def emit(
        self,
        event_type: str,
        *,
        status: Literal["ok", "blocked", "waiting", "error"] = "ok",
        payload: Mapping[str, Any] | None = None,
    ) -> object:
        stage_payload = dict(payload or {})
        stage_payload.setdefault("stage_id", self._stage_id)
        return self._trace.emit(event_type, status=status, payload=stage_payload)


class _InvocationPolicyAdapter:
    def __init__(self, invocation: HarnessInvocation, *, trace: TracePort) -> None:
        self._invocation = invocation
        self._trace = trace

    def evaluate(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> PolicyDecision:
        tool_name = action.target_tool_name or "unknown_tool"
        decision = self._invocation.policy.evaluate(
            EnforcementPoint.BEFORE_TOOL_CALL,
            {
                "run_id": state.run_id,
                "tool_name": tool_name,
                "risk_level": action.risk_level,
                "parameters": dict(action.parameters),
            },
            trace_event_id=f"{state.run_id}:{action.action_id}:policy",
        )
        emit_policy_decision(
            _StageScopedTrace(self._trace, stage_id="tool_review"),
            decision,
        )
        return decision

    def evaluate_answer(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
        answer_context: AnswerEvidenceContext,
        answer: AnswerSynthesisResult,
    ) -> PolicyDecision:
        decision = self._invocation.policy.evaluate(
            EnforcementPoint.BEFORE_ANSWER,
            _answer_policy_context(state, answer_context, answer),
            trace_event_id=f"{state.run_id}:{action.action_id}:before_answer",
        )
        emit_policy_decision(
            _StageScopedTrace(self._trace, stage_id="model_answer"),
            decision,
        )
        return decision

    def evaluate_memory_write(
        self,
        state: ControlledReActRunState,
        candidate: MemoryWriteCandidate,
    ) -> PolicyDecision:
        return self._invocation.policy.evaluate(
            EnforcementPoint.BEFORE_MEMORY_WRITE,
            {
                "run_id": state.run_id,
                "write": dict(candidate.values),
                "field_names": list(candidate.field_names),
                "write_source": candidate.write_source,
            },
            trace_event_id=f"{state.run_id}:memory:before_memory_write",
        )


class _InvocationReviewAdapter:
    def __init__(self, invocation: HarnessInvocation, *, trace: TracePort) -> None:
        self._invocation = invocation
        self._trace = trace

    def review(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> ReviewDecision:
        point = EnforcementPoint.BEFORE_RETRIEVAL_PLAN
        context = {
            "run_id": state.run_id,
            "question": state.question,
            "action_type": action.action_type.value,
            "risk_level": action.risk_level,
            "parameters": dict(action.parameters),
        }
        auto_review_enabled = bool(
            self._invocation.manifest.review and self._invocation.manifest.review.mode == "auto"
        )
        low_risk_fast_path_enabled = bool(
            self._invocation.manifest.review and self._invocation.manifest.review.low_risk_fast_path
        )
        decision, review_event = review_action(
            trace=_StageScopedTrace(self._trace, stage_id="retrieval_review"),
            policy=self._invocation.policy,
            enforcement_point=point,
            context=context,
            proposal=action,
            auto_review_enabled=auto_review_enabled,
            review_subagent=self._invocation.review_subagent,
            low_risk_fast_path_enabled=low_risk_fast_path_enabled,
            trace_event_id=f"{state.run_id}:{action.action_id}:retrieval_review",
        )
        return ReviewDecision(
            review_id=f"review.{action.action_id}.{point.value}",
            enforcement_point=point,
            suggested_decision=decision.decision,
            reason=decision.reason,
            confidence=1.0,
            risk_flags=tuple(action.reasoning_summary.risk_flags),
            subject_action_id=action.action_id,
            metadata={
                "policy_rule_id": decision.policy_rule_id,
                "review_event": review_event,
            },
        )


class _ModelAnswerSynthesisAdapter:
    def __init__(self, invocation: HarnessInvocation, *, trace: TracePort) -> None:
        self._invocation = invocation
        self._trace = trace
        self._runner = FinalAnswerAttemptRunner(invocation, trace=trace)

    def synthesize(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
        answer_context: AnswerEvidenceContext,
    ) -> AnswerSynthesisResult:
        evidence = _evidence_from_answer_context(answer_context)
        if not evidence:
            tool_answer = _tool_answer_from_answer_context(answer_context)
            if tool_answer is not None:
                return AnswerSynthesisResult(
                    outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
                    final_output=tool_answer,
                    message=tool_answer,
                    reasoning_summary=action.reasoning_summary.model_dump(mode="json"),
                )
            message = "Unable to answer without accepted governed evidence."
            return AnswerSynthesisResult(
                outcome=ReceiptOutcome.REFUSED_NO_EVIDENCE,
                final_output=message,
                message=message,
                reasoning_summary=action.reasoning_summary.model_dump(mode="json"),
            )
        result = self._runner.run(
            state,
            action,
            answer_context,
            evidence=evidence,
        )
        governed = _governed_hybrid_request_from_controlled_state(
            self._invocation,
            state,
        )
        if governed is None:
            return result
        decision = validate_serialized_insurance_answer(
            result.final_output,
            evidence=evidence,
            requirements=governed.required_evidence_slots,
        )
        if not decision.admitted or decision.deliverable_answer is None:
            message = "Unable to provide an insurance recommendation because the generated answer was not fully supported."
            return AnswerSynthesisResult(
                outcome=ReceiptOutcome.REFUSED_NO_EVIDENCE,
                final_output=message,
                message=message,
                reasoning_summary=action.reasoning_summary.model_dump(mode="json"),
                evidence=evidence,
                stage_llm_interactions=result.stage_llm_interactions,
                stage_failure_diagnostics=result.stage_failure_diagnostics,
            )
        message = render_insurance_answer(decision.deliverable_answer)
        return AnswerSynthesisResult(
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            final_output=message,
            message=message,
            reasoning_summary=result.reasoning_summary,
            model_usage_summary=result.model_usage_summary,
            evidence=evidence,
            stage_llm_interactions=result.stage_llm_interactions,
            stage_failure_diagnostics=result.stage_failure_diagnostics,
        )


class _EvidenceAnswerSynthesisAdapter:
    def synthesize(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
        answer_context: AnswerEvidenceContext,
    ) -> AnswerSynthesisResult:
        _ = state
        evidence = _evidence_from_answer_context(answer_context)
        if not evidence:
            tool_answer = _tool_answer_from_answer_context(answer_context)
            if tool_answer is not None:
                return AnswerSynthesisResult(
                    outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
                    final_output=tool_answer,
                    message=tool_answer,
                    reasoning_summary=action.reasoning_summary.model_dump(mode="json"),
                )
            message = "Unable to answer without accepted governed evidence."
            return AnswerSynthesisResult(
                outcome=ReceiptOutcome.REFUSED_NO_EVIDENCE,
                final_output=message,
                message=message,
                reasoning_summary=action.reasoning_summary.model_dump(mode="json"),
            )
        first = evidence[0]
        message = first.content.strip()
        return AnswerSynthesisResult(
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            final_output=message,
            message=message,
            reasoning_summary=action.reasoning_summary.model_dump(mode="json"),
            evidence=evidence,
        )


class _DeterministicAnswerSynthesisAdapter:
    def synthesize(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
        answer_context: AnswerEvidenceContext,
    ) -> AnswerSynthesisResult:
        _ = state
        _ = answer_context
        message = "Travel meals are reimbursed when supported by governed policy evidence."
        return AnswerSynthesisResult(
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            final_output=message,
            message=message,
            reasoning_summary=action.reasoning_summary.model_dump(mode="json"),
        )


class _InMemorySnapshotStoreAdapter:
    def __init__(self) -> None:
        self._snapshots: dict[str, ControlledReActRunStateSnapshot] = {}

    def save(self, snapshot: ControlledReActRunStateSnapshot) -> str:
        snapshot_ref = f"snapshot://{snapshot.run_id}/{snapshot.snapshot_id}"
        self._snapshots[snapshot_ref] = snapshot
        return snapshot_ref

    def load(self, snapshot_ref: str) -> ControlledReActRunStateSnapshot:
        return self._snapshots[snapshot_ref]


def _context_summary(state: ControlledReActRunState) -> str:
    accepted_count = sum(
        observation.accepted_evidence_count for observation in state.observation_records
    )
    if accepted_count <= 0:
        tool_observation_count = sum(
            1
            for observation in state.observation_records
            if observation.action_type is ReActActionType.PROPOSE_TOOL_CALL
        )
        if tool_observation_count > 0:
            return (
                "next_action=generate_final_answer; "
                f"tool_observation_count={tool_observation_count}; "
                f"observation_count={len(state.observation_records)}"
            )
        return "observation_count=0"
    return (
        "next_action=generate_final_answer; "
        f"accepted_evidence_count={accepted_count}; "
        f"observation_count={len(state.observation_records)}"
    )


def _retrieval_query_set_from_intent_state(
    state: ControlledReActRunState,
) -> tuple[RetrievalQueryItem, ...]:
    intent_resolution = state.intent_resolution
    if not isinstance(intent_resolution, Mapping):
        return ()
    raw_items = intent_resolution.get("retrieval_query_set")
    if not isinstance(raw_items, list | tuple):
        return ()
    items: list[RetrievalQueryItem] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, Mapping):
            continue
        query = _string_value(raw_item.get("query"))
        intent_angle = _string_value(raw_item.get("intent_angle"))
        reason = _string_value(raw_item.get("reason"))
        if query is None or intent_angle is None or reason is None:
            continue
        items.append(
            RetrievalQueryItem(
                query=query,
                intent_angle=intent_angle,
                required=bool(raw_item.get("required", True)),
                reason=reason,
            )
        )
    return tuple(items)


def _intent_resolver_stage_llm_interactions(
    resolver: object,
) -> tuple[WorkflowStageLlmInteraction, ...]:
    raw_interactions = getattr(resolver, "stage_llm_interactions", ())
    if not isinstance(raw_interactions, list | tuple):
        return ()
    interactions: list[WorkflowStageLlmInteraction] = []
    for raw_interaction in raw_interactions:
        if isinstance(raw_interaction, WorkflowStageLlmInteraction):
            interactions.append(raw_interaction)
        elif isinstance(raw_interaction, Mapping):
            interactions.append(WorkflowStageLlmInteraction(**dict(raw_interaction)))
    return tuple(interactions)


def _citation_refs(state: ControlledReActRunState) -> tuple[str, ...]:
    refs: list[str] = []
    for observation in state.observation_records:
        refs.extend(observation.citation_refs)
    return tuple(refs)


def _evidence_from_answer_context(
    answer_context: AnswerEvidenceContext,
) -> tuple[EvidenceChunk, ...]:
    evidence: list[EvidenceChunk] = []
    for truth in answer_context.observation_truth:
        if not isinstance(truth, RetrievalObservationTruth):
            continue
        for chunk in truth.accepted_evidence:
            if chunk.status is EvidenceStatus.ACCEPTED:
                evidence.append(chunk)
    return tuple(evidence)


def _answer_policy_context(
    state: ControlledReActRunState,
    answer_context: AnswerEvidenceContext,
    answer: AnswerSynthesisResult,
) -> Mapping[str, Any]:
    evidence = _evidence_from_answer_context(answer_context)
    authorized_tool_support = any(
        isinstance(truth, ToolObservationTruth)
        and _string_value(truth.authorized_result.get("approval_state")) != "denied"
        for truth in answer_context.observation_truth
    )
    return {
        "run_id": state.run_id,
        "question": state.question,
        "answer_outcome": answer.outcome.value,
        "accepted_evidence_count": len(evidence),
        "citations_present": bool(answer_context.citation_refs),
        "citation_ref_count": len(answer_context.citation_refs),
        "source_ref_count": len(answer_context.source_refs),
        "citation_binding": "validated" if answer_context.citation_refs else "none",
        "authorized_tool_result_support": authorized_tool_support,
        "validation_status": (
            "passed" if answer.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS else "blocked"
        ),
    }


def _emit_admitted_evidence_trace(
    trace: TracePort,
    *,
    accepted_evidence: tuple[EvidenceChunk, ...],
) -> None:
    source_refs = _trace_evidence_source_refs(accepted_evidence)
    citations = [chunk.citation for chunk in accepted_evidence if chunk.citation is not None]
    trace.emit(
        "evidence_evaluation",
        status="ok" if accepted_evidence else "blocked",
        payload={
            "accepted_count": len(accepted_evidence),
            "accepted_sources": source_refs,
            "source_refs": source_refs,
            "citations": citations,
            "metadata": {
                "accepted_sources": source_refs,
                "source_refs": source_refs,
                "citations": citations,
                "evidence": [
                    {
                        "source": chunk.source,
                        "status": chunk.status.value,
                        "evidence_id": chunk.evidence_id,
                        "provider_native_score": chunk.provider_native_score,
                        "admission_score": chunk.admission_score,
                        "citation": chunk.citation,
                        "metadata": dict(chunk.metadata),
                    }
                    for chunk in accepted_evidence
                ],
            },
        },
    )


def _trace_evidence_source_refs(evidence: tuple[EvidenceChunk, ...]) -> list[str]:
    refs: set[str] = set()
    for chunk in evidence:
        refs.add(chunk.source)
        refs.add(chunk.source.rsplit("/", maxsplit=1)[-1].split(".", maxsplit=1)[0])
        if chunk.citation is not None:
            refs.add(chunk.citation)
            refs.add(chunk.citation.split("#", maxsplit=1)[0].rsplit("/", maxsplit=1)[-1])
    return sorted(ref for ref in refs if ref)


def _admit_evidence(
    chunks: tuple[EvidenceChunk, ...],
    *,
    min_score: float,
) -> tuple[tuple[EvidenceChunk, ...], tuple[EvidenceChunk, ...], Mapping[str, Any]]:
    validation = evaluate_evidence(chunks, min_count=1, min_score=min_score)
    evidence: list[EvidenceChunk] = []
    accepted_evidence: list[EvidenceChunk] = []
    for chunk in chunks:
        accepted = (
            chunk.status is not EvidenceStatus.REJECTED
            and chunk.admission_score is not None
            and chunk.admission_score >= min_score
        )
        admitted = chunk.model_copy(
            update={
                "status": EvidenceStatus.ACCEPTED if accepted else EvidenceStatus.REJECTED,
            }
        )
        evidence.append(admitted)
        if accepted:
            accepted_evidence.append(admitted)
    return tuple(evidence), tuple(accepted_evidence), validation.metadata


def _has_tool_observation(state: ControlledReActRunState) -> bool:
    return any(
        observation.action_type is ReActActionType.PROPOSE_TOOL_CALL
        for observation in state.observation_records
    )


def _final_answer_action(action_id: str) -> ReActActionProposal:
    return ReActActionProposal(
        action_id=action_id,
        action_type=ReActActionType.GENERATE_FINAL_ANSWER,
        reasoning_summary=ReasoningSummary(
            goal="Generate a final answer from governed observations.",
            observations=("A governed tool observation is available.",),
            candidate_actions=(
                ReActActionType.GENERATE_FINAL_ANSWER,
                ReActActionType.REFUSE,
            ),
            selected_action=ReActActionType.GENERATE_FINAL_ANSWER,
            rationale_summary="The loop has the tool result needed for the final answer.",
            risk_flags=(),
            required_evidence=("governed tool result",),
        ),
        parameters={},
        risk_level="low",
    )


def _governed_hybrid_terminal_action(
    invocation: HarnessInvocation,
    state: ControlledReActRunState,
) -> ReActActionProposal | None:
    factory = invocation.governed_hybrid_request_factory
    if factory is None or state.intent_resolution is None:
        return None
    intent = IntentResolution.model_validate(state.intent_resolution)
    build = factory.build(intent, state.institution_authorization)
    if build.request is not None:
        return None
    if build.clarification is not None:
        action_type = ReActActionType.ASK_CLARIFICATION
        parameters: Mapping[str, Any] = {
            "missing_fields": build.clarification.missing_fields,
            "reason": build.clarification.reason,
        }
        rationale = "Authority-bearing insurance conditions are missing."
    else:
        action_type = ReActActionType.REFUSE
        parameters = {"reason": build.no_recommendation_reason}
        rationale = "The governed Hybrid request failed deterministic admission."
    return ReActActionProposal(
        action_id=f"hybrid:{intent.resolution_id}:{action_type.value}",
        action_type=action_type,
        reasoning_summary=ReasoningSummary(
            goal="Admit a governed insurance Knowledge request.",
            observations=(rationale,),
            candidate_actions=(
                ReActActionType.ASK_CLARIFICATION,
                ReActActionType.REFUSE,
                ReActActionType.PLAN_RETRIEVAL,
            ),
            selected_action=action_type,
            rationale_summary=rationale,
            risk_flags=("insurance_authority",),
            required_evidence=("trusted authority conditions",),
        ),
        parameters=parameters,
        risk_level="high",
    )


def _governed_hybrid_request_from_controlled_state(
    invocation: HarnessInvocation,
    state: ControlledReActRunState,
) -> GovernedHybridRetrievalRequest | None:
    factory = invocation.governed_hybrid_request_factory
    if factory is None or state.intent_resolution is None:
        return None
    intent = IntentResolution.model_validate(state.intent_resolution)
    return factory.build(intent, state.institution_authorization).request


def _tool_answer_from_answer_context(
    answer_context: AnswerEvidenceContext,
) -> str | None:
    for truth in reversed(answer_context.observation_truth):
        if not isinstance(truth, ToolObservationTruth):
            continue
        tool_name = truth.tool_name
        raw_result = truth.authorized_result
        if _string_value(raw_result.get("approval_state")) == "denied":
            continue
        status = _string_value(raw_result.get("status"))
        if status:
            return f"{tool_name} returned status {status}."
        return f"{tool_name} returned an authorized result."
    return None


def _evidence_payload(chunk: EvidenceChunk) -> dict[str, Any]:
    return {
        "source": chunk.source,
        "content": chunk.content,
        "status": chunk.status.value,
        "evidence_id": chunk.evidence_id,
        "provider_native_score": chunk.provider_native_score,
        "admission_score": chunk.admission_score,
        "citation": chunk.citation,
        "metadata": dict(chunk.metadata),
    }


def _string_value(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None
