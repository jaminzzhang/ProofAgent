from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from proof_agent.capabilities.react.planner import DeterministicReActPlanner
from proof_agent.bootstrap.composition import HarnessInvocation
from proof_agent.contracts import (
    ControlledReActRunState,
    ControlledReActRunStateSnapshot,
    EvidenceChunk,
    EvidenceStatus,
    EnforcementPoint,
    ObservationRecord,
    PolicyDecision,
    ReActActionProposal,
    ReActActionType,
    ReasoningSummary,
    ReceiptOutcome,
)
from proof_agent.control.workflow.controlled_react.orchestrator import (
    ControlledReActOrchestrator,
)
from proof_agent.control.workflow.controlled_react.ports import (
    AnswerSynthesisResult,
    ControlledReActPorts,
    SnapshotStorePort,
)
from proof_agent.control.validators.evidence import evaluate_evidence


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
) -> ControlledReActOrchestrator:
    """Assemble a run-scoped V3 orchestrator from resolved Harness capabilities."""

    return ControlledReActOrchestrator(
        ports=ControlledReActPorts(
            planner=_InvocationPlannerAdapter(invocation),
            knowledge_observation=_InvocationKnowledgeObservationAdapter(invocation),
            tool_observation=_InvocationToolObservationAdapter(invocation),
            policy=_InvocationPolicyAdapter(invocation),
            snapshot_store=snapshot_store or _InMemorySnapshotStoreAdapter(),
            answer_synthesis=_EvidenceAnswerSynthesisAdapter(),
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
        )


class _DeterministicKnowledgeObservationAdapter:
    def observe(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> ObservationRecord:
        query = _string_value(action.parameters.get("query")) or state.question
        return ObservationRecord(
            observation_id=f"obs_{action.action_id}",
            action_id=action.action_id,
            action_type=action.action_type,
            round=state.plan_round,
            truth_ref="knowledge://deterministic/local",
            summary={
                "query": query,
                "accepted_evidence_count": 1,
                "new_evidence_count": 1,
            },
            accepted_evidence_count=1,
            new_evidence_count=1,
            unresolved_subgoals=(),
            source_refs=("customer-support-policy.md",),
            citation_refs=("customer-support-policy.md#travel-meals:L3-L7",),
        )


class _InvocationKnowledgeObservationAdapter:
    def __init__(self, invocation: HarnessInvocation) -> None:
        self._invocation = invocation

    def observe(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> ObservationRecord:
        query = _string_value(action.parameters.get("query")) or state.question
        evidence, accepted_evidence, evaluation_metadata = _admit_evidence(
            self._invocation.knowledge_provider.retrieve(
                query,
                top_k=self._invocation.manifest.retrieval.top_k,
            ),
            min_score=self._invocation.manifest.retrieval.min_score,
        )
        return ObservationRecord(
            observation_id=f"obs_{action.action_id}",
            action_id=action.action_id,
            action_type=action.action_type,
            round=state.plan_round,
            truth_ref="knowledge://configured_provider",
            summary={
                "query": query,
                "accepted_evidence_count": len(accepted_evidence),
                "new_evidence_count": len(accepted_evidence),
                "rejected_evidence_count": len(evidence) - len(accepted_evidence),
                "min_score": self._invocation.manifest.retrieval.min_score,
                "evidence_validation": evaluation_metadata,
                "evidence": [_evidence_payload(chunk) for chunk in evidence],
            },
            accepted_evidence_count=len(accepted_evidence),
            new_evidence_count=len(accepted_evidence),
            unresolved_subgoals=(),
            source_refs=tuple(chunk.source for chunk in accepted_evidence),
            citation_refs=tuple(
                chunk.citation for chunk in accepted_evidence if chunk.citation is not None
            ),
        )


class _DeterministicToolObservationAdapter:
    def observe(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> ObservationRecord:
        _ = state
        tool_name = action.target_tool_name or "unknown_tool"
        return ObservationRecord(
            observation_id=f"obs_{action.action_id}",
            action_id=action.action_id,
            action_type=action.action_type,
            round=state.plan_round,
            truth_ref=f"tool://{tool_name}",
            summary={"tool_name": tool_name, "status": "completed"},
            accepted_evidence_count=0,
            new_evidence_count=0,
            unresolved_subgoals=(),
            source_refs=(f"tool://{tool_name}",),
            citation_refs=(),
        )


class _InvocationToolObservationAdapter:
    def __init__(self, invocation: HarnessInvocation) -> None:
        self._invocation = invocation

    def observe(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> ObservationRecord:
        tool_name = action.target_tool_name or "unknown_tool"
        result = self._invocation.tool_gateway.request_tool(
            tool_name=tool_name,
            parameters=dict(action.parameters),
            approved=True,
            run_id=state.run_id,
        )
        tool_result = dict(result.result or {})
        return ObservationRecord(
            observation_id=f"obs_{action.action_id}",
            action_id=action.action_id,
            action_type=action.action_type,
            round=state.plan_round,
            truth_ref=f"tool://{tool_name}",
            summary={
                "tool_name": tool_name,
                "executed": result.executed,
                "approval_state": result.approval_state.model_dump(mode="json"),
                "result": tool_result,
            },
            accepted_evidence_count=0,
            new_evidence_count=0,
            unresolved_subgoals=(),
            source_refs=(f"tool://{tool_name}",),
            citation_refs=(),
        )


class _InvocationPolicyAdapter:
    def __init__(self, invocation: HarnessInvocation) -> None:
        self._invocation = invocation

    def evaluate(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> PolicyDecision:
        tool_name = action.target_tool_name or "unknown_tool"
        return self._invocation.policy.evaluate(
            EnforcementPoint.BEFORE_TOOL_CALL,
            {
                "run_id": state.run_id,
                "tool_name": tool_name,
                "risk_level": action.risk_level,
                "parameters": dict(action.parameters),
            },
            trace_event_id=f"{state.run_id}:{action.action_id}:policy",
        )


class _EvidenceAnswerSynthesisAdapter:
    def synthesize(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> AnswerSynthesisResult:
        evidence = _evidence_from_observations(state)
        if not evidence:
            tool_answer = _tool_answer_from_observations(state)
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
    ) -> AnswerSynthesisResult:
        citation_refs = _citation_refs(state)
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
        observation.accepted_evidence_count
        for observation in state.observation_records
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


def _evidence_from_observations(
    state: ControlledReActRunState,
) -> tuple[EvidenceChunk, ...]:
    evidence: list[EvidenceChunk] = []
    for observation in state.observation_records:
        raw_evidence = observation.summary.get("evidence")
        if not isinstance(raw_evidence, list | tuple):
            continue
        for item in raw_evidence:
            if isinstance(item, Mapping):
                chunk = EvidenceChunk.model_validate(item)
                if chunk.status is EvidenceStatus.ACCEPTED:
                    evidence.append(chunk)
    return tuple(evidence)


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


def _tool_answer_from_observations(state: ControlledReActRunState) -> str | None:
    for observation in reversed(state.observation_records):
        if observation.action_type is not ReActActionType.PROPOSE_TOOL_CALL:
            continue
        tool_name = _string_value(observation.summary.get("tool_name")) or "tool"
        raw_result = observation.summary.get("result")
        if not isinstance(raw_result, Mapping):
            continue
        status = _string_value(raw_result.get("status"))
        customer_id = _string_value(raw_result.get("customer_id"))
        policy_id = _string_value(raw_result.get("policy_id"))
        source = _string_value(raw_result.get("source"))
        subject = " ".join(
            value
            for value in (
                f"customer {customer_id}" if customer_id else None,
                f"policy {policy_id}" if policy_id else None,
            )
            if value is not None
        )
        subject_suffix = f" for {subject}" if subject else ""
        source_suffix = f" Source: {source}." if source else ""
        if status:
            return f"{tool_name} returned status {status}{subject_suffix}.{source_suffix}"
        return f"{tool_name} returned: {dict(raw_result)}"
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
