from __future__ import annotations

from proof_agent.contracts import (
    ControlledReActRunState,
    ControlledReActRunStateSnapshot,
    EnforcementPoint,
    ObservationRecord,
    PolicyDecision,
    PolicyDecisionType,
    ReActActionProposal,
    ReActActionType,
    ReasoningSummary,
    ReceiptOutcome,
    ReviewDecision,
    WorkflowTemplateExecutionResult,
)
from proof_agent.control.workflow.controlled_react import (
    AnswerSynthesisResult,
    ControlledReActOrchestrator,
    ControlledReActPorts,
    ControlledReActResumeRequest,
    ControlledReActStartRequest,
)


def test_start_returns_workflow_template_execution_result_for_terminal_answer() -> None:
    orchestrator = ControlledReActOrchestrator(
        ports=ControlledReActPorts(
            planner=_TerminalAnswerPlanner(),
            answer_synthesis=_AnswerSynthesis(),
        )
    )

    result = orchestrator.start(
        ControlledReActStartRequest(
            run_id="run_001",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="What documents are required?",
        )
    )

    assert isinstance(result, WorkflowTemplateExecutionResult)
    assert result.run_id == "run_001"
    assert result.template_name == "react_enterprise_qa_v3"
    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert result.final_output == "Submit the claim form and itemized invoice."


def test_start_replans_after_retrieval_observation_before_answering() -> None:
    orchestrator = ControlledReActOrchestrator(
        ports=ControlledReActPorts(
            planner=_RetrievalThenAnswerPlanner(),
            knowledge_observation=_KnowledgeObservation(),
            answer_synthesis=_ObservationBackedAnswerSynthesis(),
        )
    )

    result = orchestrator.start(
        ControlledReActStartRequest(
            run_id="run_002",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="What documents are required?",
        )
    )

    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert result.final_output == "Submit the claim form and itemized invoice."
    assert result.reasoning_summary is not None
    assert result.reasoning_summary["selected_action"] == "generate_final_answer"


def test_start_constrains_repeated_retrieval_to_refusal_when_plan_budget_is_exhausted() -> None:
    knowledge_observation = _CountingKnowledgeObservation()
    orchestrator = ControlledReActOrchestrator(
        ports=ControlledReActPorts(
            planner=_AlwaysRetrievalPlanner(),
            knowledge_observation=knowledge_observation,
            answer_synthesis=_AnswerSynthesis(),
        )
    )

    result = orchestrator.start(
        ControlledReActStartRequest(
            run_id="run_budget",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="What documents are required?",
            max_plan_rounds=1,
        )
    )

    assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE
    assert result.final_output == "Unable to continue gathering evidence within the plan budget."
    assert knowledge_observation.call_count == 1


def test_start_review_denies_retrieval_without_observation() -> None:
    orchestrator = ControlledReActOrchestrator(
        ports=ControlledReActPorts(
            planner=_AlwaysRetrievalPlanner(),
            review=_DenyRetrievalReview(),
            knowledge_observation=_FailingKnowledgeObservation(),
            answer_synthesis=_AnswerSynthesis(),
        )
    )

    result = orchestrator.start(
        ControlledReActStartRequest(
            run_id="run_review_deny",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="What documents are required?",
        )
    )

    assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE
    assert result.final_output == "The retrieval action was not run because review denied it."


def test_start_suspends_tool_action_with_approval_pause_and_snapshot_ref() -> None:
    snapshot_store = _SnapshotStore()
    orchestrator = ControlledReActOrchestrator(
        ports=ControlledReActPorts(
            planner=_ToolApprovalPlanner(),
            policy=_RequireApprovalToolPolicy(),
            snapshot_store=snapshot_store,
            answer_synthesis=_AnswerSynthesis(),
        )
    )

    result = orchestrator.start(
        ControlledReActStartRequest(
            run_id="run_003",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="Look up this customer's claim status.",
        )
    )

    assert result.outcome is ReceiptOutcome.WAITING_FOR_APPROVAL
    assert result.approval_pause is not None
    assert result.approval_pause.tool_name == "customer_lookup"
    assert result.approval_pause.checkpoint_ref == "snapshot://run_003/snap_001"
    assert snapshot_store.saved_snapshot is not None
    assert snapshot_store.saved_snapshot.state.action_history[0].action_type is (
        ReActActionType.PROPOSE_TOOL_CALL
    )


def test_start_policy_denies_tool_action_without_snapshot_or_tool_execution() -> None:
    snapshot_store = _FailingSnapshotStore()
    orchestrator = ControlledReActOrchestrator(
        ports=ControlledReActPorts(
            planner=_ToolApprovalPlanner(),
            policy=_DenyToolPolicy(),
            snapshot_store=snapshot_store,
            tool_observation=_FailingToolObservation(),
            answer_synthesis=_AnswerSynthesis(),
        )
    )

    result = orchestrator.start(
        ControlledReActStartRequest(
            run_id="run_policy_deny",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="Look up this customer's claim status.",
        )
    )

    assert result.outcome is ReceiptOutcome.TOOL_APPROVAL_DENIED
    assert result.final_output == "The customer_lookup tool was not run because policy denied it."
    assert result.approval_pause is None


def test_start_policy_allows_tool_action_then_replans_to_answer_without_snapshot() -> None:
    orchestrator = ControlledReActOrchestrator(
        ports=ControlledReActPorts(
            planner=_ToolObservationThenAnswerPlanner(),
            policy=_AllowToolPolicy(),
            snapshot_store=_FailingSnapshotStore(),
            tool_observation=_ToolObservation(),
            answer_synthesis=_ObservationBackedAnswerSynthesis(),
        )
    )

    result = orchestrator.start(
        ControlledReActStartRequest(
            run_id="run_policy_allow",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="Look up this customer's claim status.",
        )
    )

    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert result.approval_pause is None
    assert result.reasoning_summary is not None
    assert result.reasoning_summary["selected_action"] == "generate_final_answer"


def test_resume_approved_tool_snapshot_observes_tool_and_answers() -> None:
    action = _proposal("act_tool", ReActActionType.PROPOSE_TOOL_CALL).model_copy(
        update={"target_tool_name": "customer_lookup"}
    )
    snapshot = ControlledReActRunStateSnapshot(
        snapshot_id="snap_run_004",
        run_id="run_004",
        state=ControlledReActRunState(
            run_id="run_004",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="Look up this customer's claim status.",
            action_history=(action,),
        ),
    )
    orchestrator = ControlledReActOrchestrator(
        ports=ControlledReActPorts(
            planner=_ToolObservationThenAnswerPlanner(),
            snapshot_store=_ResumeSnapshotStore(snapshot),
            tool_observation=_ToolObservation(),
            answer_synthesis=_ObservationBackedAnswerSynthesis(),
        )
    )

    result = orchestrator.resume(
        ControlledReActResumeRequest(
            snapshot_ref="snapshot://run_004/snap_001",
            approval_id="appr_act_tool",
            approved=True,
            actor="ops",
        )
    )

    assert result.run_id == "run_004"
    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert result.final_output == "Submit the claim form and itemized invoice."
    assert result.reasoning_summary is not None
    assert result.reasoning_summary["selected_action"] == "generate_final_answer"
    assert [
        stage.stage_id
        for stage in result.stage_results
    ] == ["plan", "tool_review", "tool", "plan", "model_answer", "response"]


def test_resume_denied_tool_snapshot_records_observation_and_replans() -> None:
    action = _proposal("act_tool", ReActActionType.PROPOSE_TOOL_CALL).model_copy(
        update={"target_tool_name": "customer_lookup"}
    )
    snapshot = ControlledReActRunStateSnapshot(
        snapshot_id="snap_run_005",
        run_id="run_005",
        state=ControlledReActRunState(
            run_id="run_005",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="Look up this customer's claim status.",
            action_history=(action,),
        ),
    )
    orchestrator = ControlledReActOrchestrator(
        ports=ControlledReActPorts(
            planner=_ToolObservationThenAnswerPlanner(),
            snapshot_store=_ResumeSnapshotStore(snapshot),
            tool_observation=_FailingToolObservation(),
            answer_synthesis=_ObservationBackedAnswerSynthesis(),
        )
    )

    result = orchestrator.resume(
        ControlledReActResumeRequest(
            snapshot_ref="snapshot://run_004/snap_001",
            approval_id="appr_act_tool",
            approved=False,
            actor="ops",
        )
    )

    assert result.run_id == "run_005"
    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert result.final_output == "Submit the claim form and itemized invoice."
    assert result.approval_pause is None
    assert [
        stage.stage_id
        for stage in result.stage_results
    ] == ["plan", "tool_review", "tool", "plan", "model_answer", "response"]
    tool_stage = next(stage for stage in result.stage_results if stage.stage_id == "tool")
    assert tool_stage.summary["approval_state"] == "denied"


class _TerminalAnswerPlanner:
    def plan(self, state: ControlledReActRunState) -> ReActActionProposal:
        return _proposal("act_answer", ReActActionType.GENERATE_FINAL_ANSWER)


class _AnswerSynthesis:
    def synthesize(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> AnswerSynthesisResult:
        _ = state
        return AnswerSynthesisResult(
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            final_output="Submit the claim form and itemized invoice.",
            message="Answered with governed citations.",
            reasoning_summary=action.reasoning_summary.model_dump(mode="json"),
        )


class _RetrievalThenAnswerPlanner:
    def plan(self, state: ControlledReActRunState) -> ReActActionProposal:
        if not state.observation_records:
            return _proposal("act_retrieve", ReActActionType.PLAN_RETRIEVAL)
        return _proposal("act_answer", ReActActionType.GENERATE_FINAL_ANSWER)


class _KnowledgeObservation:
    def observe(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> ObservationRecord:
        return ObservationRecord(
            observation_id="obs_retrieval",
            action_id=action.action_id,
            action_type=action.action_type,
            round=state.plan_round,
            truth_ref="evidence",
            summary={"accepted_evidence_count": 1, "new_evidence_count": 1},
            accepted_evidence_count=1,
            new_evidence_count=1,
            unresolved_subgoals=(),
            source_refs=("claims-guide.md",),
            citation_refs=("claims-guide.md#documents",),
        )


class _CountingKnowledgeObservation(_KnowledgeObservation):
    def __init__(self) -> None:
        self.call_count = 0

    def observe(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> ObservationRecord:
        self.call_count += 1
        return super().observe(state, action)


class _FailingKnowledgeObservation:
    def observe(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> ObservationRecord:
        _ = (state, action)
        raise AssertionError("review denied retrieval must not execute observation")


class _ObservationBackedAnswerSynthesis:
    def synthesize(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> AnswerSynthesisResult:
        if not state.observation_records:
            raise AssertionError("answer synthesis requires an ObservationRecord")
        return AnswerSynthesisResult(
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            final_output="Submit the claim form and itemized invoice.",
            message="Answered with governed citations.",
            reasoning_summary=action.reasoning_summary.model_dump(mode="json"),
        )


class _ToolApprovalPlanner:
    def plan(self, state: ControlledReActRunState) -> ReActActionProposal:
        _ = state
        proposal = _proposal("act_tool", ReActActionType.PROPOSE_TOOL_CALL)
        return proposal.model_copy(update={"target_tool_name": "customer_lookup"})


class _AlwaysRetrievalPlanner:
    def plan(self, state: ControlledReActRunState) -> ReActActionProposal:
        _ = state
        return _proposal("act_retrieve", ReActActionType.PLAN_RETRIEVAL)


class _DenyRetrievalReview:
    def review(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> ReviewDecision:
        _ = state
        return ReviewDecision(
            review_id="review_deny_retrieval",
            enforcement_point=EnforcementPoint.BEFORE_RETRIEVAL_PLAN,
            suggested_decision=PolicyDecisionType.DENY,
            reason="retrieval is not allowed for this question",
            confidence=1.0,
            risk_flags=("retrieval_denied",),
            subject_action_id=action.action_id,
        )


class _ToolObservationThenAnswerPlanner:
    def plan(self, state: ControlledReActRunState) -> ReActActionProposal:
        if not state.observation_records:
            return _proposal("act_tool", ReActActionType.PROPOSE_TOOL_CALL).model_copy(
                update={"target_tool_name": "customer_lookup"}
            )
        return _proposal("act_answer", ReActActionType.GENERATE_FINAL_ANSWER)


class _SnapshotStore:
    saved_snapshot: ControlledReActRunStateSnapshot | None = None

    def save(self, snapshot: ControlledReActRunStateSnapshot) -> str:
        self.saved_snapshot = snapshot
        return "snapshot://run_003/snap_001"


class _FailingSnapshotStore:
    def save(self, snapshot: ControlledReActRunStateSnapshot) -> str:
        _ = snapshot
        raise AssertionError("policy denied tool actions must not save snapshots")

    def load(self, snapshot_ref: str) -> ControlledReActRunStateSnapshot:
        _ = snapshot_ref
        raise AssertionError("start should not load snapshots")


class _DenyToolPolicy:
    def evaluate(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> PolicyDecision:
        _ = (state, action)
        return PolicyDecision(
            decision=PolicyDecisionType.DENY,
            enforcement_point=EnforcementPoint.BEFORE_TOOL_CALL,
            reason="customer_lookup is denied for this run",
            policy_rule_id="tools.customer_lookup.deny",
            trace_event_id="trace_policy_deny",
        )


class _RequireApprovalToolPolicy:
    def evaluate(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> PolicyDecision:
        _ = (state, action)
        return PolicyDecision(
            decision=PolicyDecisionType.REQUIRE_APPROVAL,
            enforcement_point=EnforcementPoint.BEFORE_TOOL_CALL,
            reason="customer_lookup requires approval",
            policy_rule_id="tools.customer_lookup.approval",
            trace_event_id="trace_policy_approval",
        )


class _AllowToolPolicy:
    def evaluate(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> PolicyDecision:
        _ = (state, action)
        return PolicyDecision(
            decision=PolicyDecisionType.ALLOW,
            enforcement_point=EnforcementPoint.BEFORE_TOOL_CALL,
            reason="customer_lookup is allowed",
            policy_rule_id="tools.customer_lookup.allow",
            trace_event_id="trace_policy_allow",
        )


class _ResumeSnapshotStore:
    def __init__(self, snapshot: ControlledReActRunStateSnapshot) -> None:
        self._snapshot = snapshot

    def save(self, snapshot: ControlledReActRunStateSnapshot) -> str:
        _ = snapshot
        raise AssertionError("resume should not save a snapshot in this slice")

    def load(self, snapshot_ref: str) -> ControlledReActRunStateSnapshot:
        assert snapshot_ref == "snapshot://run_004/snap_001"
        return self._snapshot


class _ToolObservation:
    def observe(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> ObservationRecord:
        return ObservationRecord(
            observation_id="obs_tool",
            action_id=action.action_id,
            action_type=action.action_type,
            round=state.plan_round,
            truth_ref="tool_result",
            summary={"tool_name": action.target_tool_name, "status": "completed"},
            accepted_evidence_count=0,
            new_evidence_count=0,
            unresolved_subgoals=(),
            source_refs=("tool://customer_lookup",),
            citation_refs=(),
        )


class _FailingToolObservation:
    def observe(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> ObservationRecord:
        _ = (state, action)
        raise AssertionError("denied approval must not execute tool observation")


def _proposal(action_id: str, action_type: ReActActionType) -> ReActActionProposal:
    return ReActActionProposal(
        action_id=action_id,
        action_type=action_type,
        reasoning_summary=ReasoningSummary(
            goal="answer with available governed facts",
            observations=("claim form and invoice are required",),
            candidate_actions=(action_type,),
            selected_action=action_type,
            rationale_summary="Evidence is sufficient for a concise answer.",
            risk_flags=(),
            required_evidence=("claims guide",),
        ),
        parameters={},
        risk_level="low",
    )
