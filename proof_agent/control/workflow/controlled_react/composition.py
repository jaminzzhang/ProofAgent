from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

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
    ModelCallRole,
    ModelRequest,
    ModelResponse,
    ObservationRecord,
    PolicyDecision,
    PolicyDecisionType,
    ReActActionProposal,
    ReActActionType,
    ReasoningSummary,
    ReceiptOutcome,
    RetrievalObservationTruth,
    ReviewDecision,
    ToolObservationTruth,
    ValidationResult,
    ValidationStatus,
    WorkflowStageLlmInteraction,
)
from proof_agent.control.workflow.controlled_react.orchestrator import (
    ControlledReActOrchestrator,
)
from proof_agent.control.workflow.controlled_react.observation_commit import (
    ObservationEffect,
    ObservationIdentity,
    ObservationSummaryBuilder,
)
from proof_agent.control.workflow.controlled_react.ports import (
    AnswerSynthesisResult,
    ControlledReActPorts,
    ObservationTruthStorePort,
    SnapshotStorePort,
    TracePort,
)
from proof_agent.control.workflow.controlled_react.tool_proposal_scope import (
    ToolProposalScopeResolver,
)
from proof_agent.control.workflow.harness_helpers import (
    build_model_request,
    cost_class,
    emit_policy_decision,
    model_response_payload,
    structured_final_answer_output,
    validate_model_output,
)
from proof_agent.control.validators.evidence import evaluate_evidence
from proof_agent.control.knowledge.retrieval_service import (
    KnowledgeRetrievalRequest,
    KnowledgeRetrievalService,
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
            review=_InvocationReviewAdapter(invocation),
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
        )


class _InvocationIntentResolutionAdapter:
    def __init__(self, invocation: HarnessInvocation) -> None:
        self._invocation = invocation
        self._fallback = DeterministicIntentResolver()

    def resolve(self, state: ControlledReActRunState) -> IntentResolutionResult:
        resolver = self._invocation.intent_resolver or self._fallback
        return resolver.resolve(
            question=state.question,
            system_prompt="Resolve user intent before Controlled ReAct planning.",
            context_summary="pre_loop=true",
            workflow_stage_context=None,
            business_flow_skill_packs=self._invocation.business_flow_skill_packs,
        )


class _InvocationMemoryAdapter:
    def __init__(self, invocation: HarnessInvocation) -> None:
        self._memory = invocation.create_memory()

    def read(self, state: ControlledReActRunState) -> Mapping[str, Any]:
        _ = state
        return self._memory.read()

    def write(
        self,
        state: ControlledReActRunState,
        answer: AnswerSynthesisResult,
    ) -> ValidationResult:
        return self._memory.write(
            {
                "question": state.question,
                "outcome": answer.outcome.value,
                "final_output_length": len(answer.final_output),
            }
        )


class _InvocationPlannerAdapter:
    def __init__(self, invocation: HarnessInvocation) -> None:
        self._invocation = invocation
        self._fallback = DeterministicReActPlanner()

    def plan(self, state: ControlledReActRunState) -> ReActActionProposal:
        if _has_tool_observation(state):
            return _final_answer_action("act_generate_after_tool")
        planner = self._invocation.react_planner or self._fallback
        return planner.plan(
            question=state.question,
            system_prompt="Controlled ReAct Orchestrator V3",
            context_summary=_context_summary(state),
            eligible_actions=(
                frozenset(state.effective_react_action_set)
                if state.effective_react_action_set
                else None
            ),
            effective_tool_proposal_scope=state.effective_tool_proposal_scope,
        )


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
        service = KnowledgeRetrievalService(
            trace=self._trace,
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
                max_queries=retrieval.max_queries,
                query_concurrency=retrieval.query_concurrency,
                query_timeout_seconds=retrieval.query_timeout_seconds,
            )
        )
        evidence, accepted_evidence, evaluation_metadata = _admit_evidence(
            retrieval_result.evidence,
            min_score=retrieval.min_score,
        )
        _emit_admitted_evidence_trace(
            self._trace,
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
        emit_policy_decision(self._trace, decision)
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
        emit_policy_decision(self._trace, decision)
        return decision


class _InvocationReviewAdapter:
    def __init__(self, invocation: HarnessInvocation) -> None:
        self._invocation = invocation

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
        if (
            self._invocation.manifest.review is not None
            and self._invocation.manifest.review.mode == "auto"
            and self._invocation.review_subagent is not None
        ):
            return self._invocation.review_subagent.review(
                enforcement_point=point,
                action=action,
                context=context,
            )
        decision = self._invocation.policy.evaluate(
            point,
            context,
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
            metadata={"policy_rule_id": decision.policy_rule_id},
        )


class _ModelAnswerSynthesisAdapter:
    def __init__(self, invocation: HarnessInvocation, *, trace: TracePort) -> None:
        self._invocation = invocation
        self._trace = trace

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
        model_request = build_model_request(
            question=state.question,
            evidence=evidence,
            provider=self._invocation.model_provider.provider_name,
            model=self._invocation.model_provider.model_name,
        )
        estimated_tokens = self._invocation.model_provider.estimate_tokens(model_request)
        policy_decision = self._invocation.policy.evaluate(
            EnforcementPoint.BEFORE_MODEL_CALL,
            _model_call_policy_context(model_request, estimated_tokens=estimated_tokens),
            trace_event_id=f"{state.run_id}:{action.action_id}:before_model_call",
        )
        emit_policy_decision(self._trace, policy_decision)
        if policy_decision.decision is not PolicyDecisionType.ALLOW:
            message = "The final-answer model call was blocked by policy."
            return AnswerSynthesisResult(
                outcome=ReceiptOutcome.POLICY_DENIED,
                final_output=message,
                message=message,
                reasoning_summary=action.reasoning_summary.model_dump(mode="json"),
                evidence=evidence,
                model_usage_summary={
                    "provider": model_request.provider,
                    "model": model_request.model,
                    "role": ModelCallRole.FINAL_ANSWER.value,
                    "message_count": len(model_request.messages),
                    "estimated_tokens": estimated_tokens,
                    "stream": model_request.stream,
                    "cost_class": cost_class(model_request.provider),
                },
            )
        _emit_model_request_trace(
            self._trace,
            model_request,
            estimated_tokens=estimated_tokens,
            stage_id="model_answer",
        )
        try:
            model_response = self._invocation.model_provider.generate(model_request)
        except Exception as exc:
            _emit_model_error_trace(
                self._trace,
                provider=model_request.provider,
                model=model_request.model,
                exc=exc,
                stage_id="model_answer",
            )
            raise
        _emit_model_response_trace(
            self._trace,
            model_response,
            stage_id="model_answer",
        )
        interaction = _llm_interaction_capture(
            stage_id="model_answer",
            stage_label="Model Answer",
            role=ModelCallRole.FINAL_ANSWER.value,
            request=model_request,
            response=model_response,
        )
        outcome = ReceiptOutcome.ANSWERED_WITH_CITATIONS
        validation_results = validate_model_output(
            response=model_response,
            outcome=outcome,
            evidence=evidence,
            question=state.question,
        )
        if any(result.status is ValidationStatus.FAILED for result in validation_results):
            message = "I cannot answer because the model output failed validation."
            return AnswerSynthesisResult(
                outcome=ReceiptOutcome.REFUSED_NO_EVIDENCE,
                final_output=message,
                message=message,
                reasoning_summary=action.reasoning_summary.model_dump(mode="json"),
                evidence=evidence,
                model_usage_summary=_model_usage_summary(
                    request=model_request,
                    response=model_response,
                    estimated_tokens=estimated_tokens,
                ),
                stage_llm_interactions=(interaction,),
            )
        final_answer_output, _parse_error = structured_final_answer_output(
            model_response.content,
            outcome=outcome,
        )
        message = str(final_answer_output.get("message", model_response.content))
        return AnswerSynthesisResult(
            outcome=outcome,
            final_output=message,
            message=message,
            reasoning_summary=action.reasoning_summary.model_dump(mode="json"),
            evidence=evidence,
            model_usage_summary=_model_usage_summary(
                request=model_request,
                response=model_response,
                estimated_tokens=estimated_tokens,
            ),
            stage_llm_interactions=(interaction,),
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
        citation_suffix = f" Citation: {first.citation}." if first.citation else ""
        message = f"{first.content.strip()}{citation_suffix}"
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
        citation_refs = answer_context.citation_refs
        citation_suffix = f" Citation: {citation_refs[0]}." if citation_refs else ""
        message = (
            "Travel meals are reimbursed when supported by governed policy evidence."
            f"{citation_suffix}"
        )
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
            "passed"
            if answer.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
            else "blocked"
        ),
    }


def _emit_admitted_evidence_trace(
    trace: TracePort,
    *,
    accepted_evidence: tuple[EvidenceChunk, ...],
) -> None:
    source_refs = _trace_evidence_source_refs(accepted_evidence)
    citations = [
        chunk.citation for chunk in accepted_evidence if chunk.citation is not None
    ]
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


def _model_call_policy_context(
    request: ModelRequest,
    *,
    estimated_tokens: int | None,
) -> Mapping[str, Any]:
    return {
        "provider": request.provider,
        "model": request.model,
        "role": ModelCallRole.FINAL_ANSWER.value,
        "estimated_tokens": estimated_tokens,
        "stream": request.stream,
        "cost_class": cost_class(request.provider),
        "message_count": len(request.messages),
        "response_format": request.response_format,
    }


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


def _model_usage_summary(
    *,
    request: ModelRequest,
    response: ModelResponse,
    estimated_tokens: int | None,
) -> dict[str, Any]:
    payload = model_response_payload(response)
    token_usage = payload.get("token_usage")
    return {
        "provider": response.provider_name,
        "model": response.model_name,
        "role": ModelCallRole.FINAL_ANSWER.value,
        "message_count": len(request.messages),
        "estimated_tokens": estimated_tokens,
        "stream": request.stream,
        "cost_class": cost_class(request.provider),
        "finish_reason": response.finish_reason,
        "content_length": len(response.content),
        "token_usage": token_usage,
    }


def _emit_model_request_trace(
    trace: TracePort,
    request: ModelRequest,
    *,
    estimated_tokens: int | None,
    stage_id: str,
) -> None:
    trace.emit(
        "model_request",
        status="ok",
        payload={
            "provider": request.provider,
            "model": request.model,
            "role": ModelCallRole.FINAL_ANSWER.value,
            "response_format": request.response_format,
            "message_count": len(request.messages),
            "prompt_length": sum(len(message.content) for message in request.messages),
            "system_prompt_length": sum(
                len(message.content)
                for message in request.messages
                if message.role.value == "system"
            ),
            "estimated_tokens": estimated_tokens,
            "stream": request.stream,
            "cost_class": cost_class(request.provider),
            "stage_id": stage_id,
        },
    )


def _emit_model_response_trace(
    trace: TracePort,
    response: ModelResponse,
    *,
    stage_id: str,
) -> None:
    payload = model_response_payload(response)
    trace.emit(
        "model_response",
        status="ok",
        payload={
            "provider": response.provider_name,
            "model": response.model_name,
            "role": ModelCallRole.FINAL_ANSWER.value,
            "finish_reason": response.finish_reason,
            "content_length": len(response.content),
            "refusal_reason": response.refusal_reason,
            "token_usage": payload.get("token_usage"),
            "stage_id": stage_id,
        },
    )


def _emit_model_error_trace(
    trace: TracePort,
    *,
    provider: str,
    model: str,
    exc: BaseException,
    stage_id: str,
) -> None:
    trace.emit(
        "model_error",
        status="error",
        payload={
            "provider": provider,
            "model": model,
            "role": ModelCallRole.FINAL_ANSWER.value,
            "error_code": getattr(exc, "code", "PA_MODEL_002"),
            "error_class": exc.__class__.__name__,
            "retryable": bool(getattr(exc, "retryable", False)),
            "stage_id": stage_id,
        },
    )


def _llm_interaction_capture(
    *,
    stage_id: str,
    stage_label: str,
    role: str,
    request: ModelRequest,
    response: ModelResponse,
) -> WorkflowStageLlmInteraction:
    response_json, parse_error = (
        _model_content_json(response.content) if request.response_format == "json" else (None, None)
    )
    return WorkflowStageLlmInteraction(
        stage_id=stage_id,
        stage_label=stage_label,
        role=role,
        provider=response.provider_name,
        model=response.model_name,
        request_json=_model_request_json(request),
        response_json=response_json,
        response_content_length=len(response.content),
        response_json_parse_error_code=parse_error,
    )


def _model_request_json(request: ModelRequest) -> dict[str, Any]:
    return {
        "provider": request.provider,
        "model": request.model,
        "response_format": request.response_format,
        "function_schema": (
            request.function_schema.model_dump(mode="json")
            if request.function_schema is not None
            else None
        ),
        "stream": request.stream,
        "temperature": request.temperature,
        "max_output_tokens": request.max_output_tokens,
        "timeout_seconds": request.timeout_seconds,
        "metadata": dict(request.metadata),
        "evidence_sources": list(request.evidence_sources),
        "messages": [
            {
                "role": message.role.value,
                "content": message.content,
                "name": message.name,
                "metadata": dict(message.metadata),
            }
            for message in request.messages
        ],
    }


def _model_content_json(content: str) -> tuple[Any | None, str | None]:
    stripped = content.strip()
    if not stripped:
        return None, "empty_model_output"
    try:
        return json.loads(stripped), None
    except json.JSONDecodeError:
        return None, "model_output_json_parse_failed"


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
