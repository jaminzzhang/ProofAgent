from __future__ import annotations

import pytest

from proof_agent.contracts import (
    AnswerEvidenceContext,
    ApprovedToolProposalSnapshot,
    ControlledReActRunPhase,
    ControlledReActRunState,
    ControlledReActRunStateSnapshot,
    EffectiveToolProposalScope,
    EvidenceChunk,
    EvidenceStatus,
    EnforcementPoint,
    ObservationRecord,
    PolicyDecision,
    PolicyDecisionType,
    ReActActionProposal,
    ReActActionType,
    ReasoningSummary,
    ReceiptOutcome,
    RetrievalObservationTruth,
    ToolProposalInterface,
    ToolProposalParameter,
    ToolProposalParameterSource,
    ReviewDecision,
    ToolObservationTruth,
    ValidationResult,
    ValidationStatus,
    WorkflowTemplateExecutionResult,
)
from proof_agent.control.workflow.controlled_react import (
    AnswerSynthesisResult,
    ControlledReActOrchestrator,
    ControlledReActPorts,
    ControlledReActResumeRequest,
    ControlledReActStartRequest,
    ObservationEffect,
    ObservationIdentity,
    build_default_controlled_react_orchestrator,
)
from proof_agent.control.workflow.controlled_react.composition import (
    _EvidenceAnswerSynthesisAdapter,
    _tool_summary_projection,
)
from proof_agent.errors import ProofAgentError


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


def test_default_controlled_react_orchestrator_uses_observation_effects() -> None:
    result = build_default_controlled_react_orchestrator().start(
        ControlledReActStartRequest(
            run_id="run_default",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="Are travel meals reimbursed?",
        )
    )

    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert result.stage_results
    assert "evidence" not in result.stage_results[0].summary


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


def test_start_commits_knowledge_observation_effect_before_answering() -> None:
    knowledge_observation = _EffectKnowledgeObservation()
    orchestrator = ControlledReActOrchestrator(
        ports=ControlledReActPorts(
            planner=_RetrievalThenAnswerPlanner(),
            knowledge_observation=knowledge_observation,
            answer_synthesis=_ObservationBackedAnswerSynthesis(),
        )
    )

    result = orchestrator.start(
        ControlledReActStartRequest(
            run_id="run_effect",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="What documents are required?",
        )
    )

    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert knowledge_observation.identity is not None
    assert knowledge_observation.identity.observation_id == "obs_1_act_retrieve"


def test_stage_results_use_commit_trace_projection() -> None:
    orchestrator = ControlledReActOrchestrator(
        ports=ControlledReActPorts(
            planner=_RetrievalThenAnswerPlanner(),
            knowledge_observation=_EffectKnowledgeObservation(),
            answer_synthesis=_ObservationBackedAnswerSynthesis(),
        )
    )

    result = orchestrator.start(
        ControlledReActStartRequest(
            run_id="run_projection",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="What documents are required?",
        )
    )

    retrieval_stage = next(stage for stage in result.stage_results if stage.stage_id == "retrieval")
    assert retrieval_stage.summary["observation_id"] == "obs_1_act_retrieve"
    assert retrieval_stage.summary["truth_kind"] == "retrieval"


def test_answer_synthesis_receives_answer_evidence_context() -> None:
    answer_synthesis = _ContextCapturingAnswerSynthesis()
    orchestrator = ControlledReActOrchestrator(
        ports=ControlledReActPorts(
            planner=_RetrievalThenAnswerPlanner(),
            knowledge_observation=_EffectKnowledgeObservation(),
            answer_synthesis=answer_synthesis,
        )
    )

    result = orchestrator.start(
        ControlledReActStartRequest(
            run_id="run_answer_context",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="What documents are required?",
        )
    )

    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert answer_synthesis.context is not None
    assert answer_synthesis.context.run_id == "run_answer_context"
    assert answer_synthesis.context.observation_truth
    assert answer_synthesis.context.citation_refs == ("claims-guide.md#documents",)


def test_before_answer_policy_denial_blocks_terminal_answer() -> None:
    policy = _DenyAnswerAdmissionPolicy()
    orchestrator = ControlledReActOrchestrator(
        ports=ControlledReActPorts(
            planner=_RetrievalThenAnswerPlanner(),
            knowledge_observation=_EffectKnowledgeObservation(),
            policy=policy,
            answer_synthesis=_ObservationBackedAnswerSynthesis(),
        )
    )

    result = orchestrator.start(
        ControlledReActStartRequest(
            run_id="run_answer_denied",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="What documents are required?",
        )
    )

    assert result.outcome is ReceiptOutcome.POLICY_DENIED
    assert result.final_output == "The final answer was blocked by policy."
    assert policy.context is not None
    assert policy.context["accepted_evidence_count"] == 1
    assert policy.context["citations_present"] is True


def test_before_memory_write_denial_blocks_memory_side_effect_without_changing_answer() -> None:
    memory = _CandidateMemory()
    policy = _DenyMemoryWritePolicy()
    trace = _TraceCapture()
    orchestrator = ControlledReActOrchestrator(
        ports=ControlledReActPorts(
            planner=_TerminalAnswerPlanner(),
            memory=memory,
            policy=policy,
            trace=trace,
            answer_synthesis=_AnswerSynthesis(),
        )
    )

    result = orchestrator.start(
        ControlledReActStartRequest(
            run_id="run_memory_denied",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="What documents are required?",
        )
    )

    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert result.final_output == "Submit the claim form and itemized invoice."
    assert memory.commit_count == 0
    assert policy.write_context == {
        "question": "What documents are required?",
        "outcome": "ANSWERED_WITH_CITATIONS",
        "final_output_length": 43,
    }
    memory_stage = next(stage for stage in result.stage_results if stage.stage_id == "memory")
    assert memory_stage.status.value == "blocked"
    assert memory_stage.summary["status"] == "failed"
    assert memory_stage.summary["written_fields"] == ()
    event_types = [event["event_type"] for event in trace.events]
    assert event_types == [
        "memory_write_requested",
        "policy_decision",
        "memory_write_decision",
    ]
    assert trace.events[0]["payload"] == {
        "stage_id": "memory",
        "field_names": ["final_output_length", "outcome", "question"],
        "field_count": 3,
        "write_source": "controlled_react_v3",
    }
    assert trace.events[1]["status"] == "blocked"
    assert trace.events[1]["payload"]["stage_id"] == "memory"
    assert trace.events[1]["payload"]["enforcement_point"] == "before_memory_write"
    assert trace.events[1]["payload"]["decision"] == "deny"
    assert trace.events[2]["status"] == "blocked"
    assert trace.events[2]["payload"]["stage_id"] == "memory"
    assert trace.events[2]["payload"]["decision"] == "deny"
    assert "Submit the claim form" not in repr(trace.events)


def test_before_memory_write_allow_commits_memory_side_effect_without_changing_answer() -> None:
    memory = _CandidateMemory()
    policy = _AllowMemoryWritePolicy()
    trace = _TraceCapture()
    orchestrator = ControlledReActOrchestrator(
        ports=ControlledReActPorts(
            planner=_TerminalAnswerPlanner(),
            memory=memory,
            policy=policy,
            trace=trace,
            answer_synthesis=_AnswerSynthesis(),
        )
    )

    result = orchestrator.start(
        ControlledReActStartRequest(
            run_id="run_memory_allowed",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="What documents are required?",
        )
    )

    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert result.final_output == "Submit the claim form and itemized invoice."
    assert memory.commit_count == 1
    assert memory.committed_values == {
        "question": "What documents are required?",
        "outcome": "ANSWERED_WITH_CITATIONS",
        "final_output_length": 43,
    }
    memory_stage = next(stage for stage in result.stage_results if stage.stage_id == "memory")
    assert memory_stage.status.value == "completed"
    assert memory_stage.summary["status"] == "passed"
    assert memory_stage.summary["written_fields"] == (
        "final_output_length",
        "outcome",
        "question",
    )
    event_types = [event["event_type"] for event in trace.events]
    assert event_types == [
        "memory_write_requested",
        "policy_decision",
        "memory_write_decision",
    ]
    assert trace.events[1]["status"] == "ok"
    assert trace.events[1]["payload"]["enforcement_point"] == "before_memory_write"
    assert trace.events[1]["payload"]["decision"] == "allow"
    assert trace.events[2]["status"] == "ok"
    assert trace.events[2]["payload"]["decision"] == "allow"
    assert "Submit the claim form" not in repr(trace.events)


def test_observation_effect_must_match_allocated_identity() -> None:
    orchestrator = ControlledReActOrchestrator(
        ports=ControlledReActPorts(
            planner=_RetrievalThenAnswerPlanner(),
            knowledge_observation=_WrongIdentityKnowledgeObservation(),
            answer_synthesis=_ObservationBackedAnswerSynthesis(),
        )
    )

    try:
        orchestrator.start(
            ControlledReActStartRequest(
                run_id="run_001",
                template_name="react_enterprise_qa_v3",
                template_descriptor_version="react_enterprise_qa.v3",
                question="What documents are required?",
            )
        )
    except ValueError as exc:
        assert "allocated observation identity" in str(exc)
    else:
        raise AssertionError("orchestrator must reject unallocated observation identity")


def test_answer_context_rejects_record_citations_missing_from_truth() -> None:
    orchestrator = ControlledReActOrchestrator(
        ports=ControlledReActPorts(
            planner=_RetrievalThenAnswerPlanner(),
            knowledge_observation=_CitationMismatchKnowledgeObservation(),
            answer_synthesis=_ObservationBackedAnswerSynthesis(),
        )
    )

    try:
        orchestrator.start(
            ControlledReActStartRequest(
                run_id="run_001",
                template_name="react_enterprise_qa_v3",
                template_descriptor_version="react_enterprise_qa.v3",
                question="What documents are required?",
            )
        )
    except ValueError as exc:
        assert "citation_refs are missing from truth artifact" in str(exc)
    else:
        raise AssertionError("orchestrator must reject unverifiable citation refs")


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
    assert [stage.stage_id for stage in result.stage_results] == [
        "plan",
        "retrieval_review",
        "response",
    ]


def test_empty_effective_tool_scope_removes_tool_action_from_planner_state() -> None:
    planner = _CapturingRefusalPlanner()
    orchestrator = ControlledReActOrchestrator(
        ports=ControlledReActPorts(
            planner=planner,
            tool_proposal_scope=_EmptyToolProposalScope(),
            answer_synthesis=_AnswerSynthesis(),
        )
    )

    result = orchestrator.start(
        ControlledReActStartRequest(
            run_id="run_empty_tool_scope",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="Look up claim status.",
        )
    )

    assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE
    assert planner.captured_state is not None
    assert planner.captured_state.effective_tool_proposal_scope is not None
    assert planner.captured_state.effective_tool_proposal_scope.tool_contract_ids == ()
    assert (
        ReActActionType.PROPOSE_TOOL_CALL not in planner.captured_state.effective_react_action_set
    )
    scope_stages = [
        stage for stage in result.stage_results if stage.stage_id == "tool_proposal_scope"
    ]
    assert len(scope_stages) == 1
    scope_summary = dict(scope_stages[0].summary)
    assert scope_summary["schema_digest"] == "sha256:empty"
    assert scope_summary["tool_contract_ids"] == ()
    assert scope_summary["proposal_action_enabled"] is False
    assert "input_schema" not in repr(scope_summary)
    assert "tool_source_id" not in repr(scope_summary)


def test_scope_outside_tool_proposal_fails_before_policy_and_execution() -> None:
    orchestrator = ControlledReActOrchestrator(
        ports=ControlledReActPorts(
            planner=_ToolApprovalPlanner(),
            tool_proposal_scope=_ClaimOnlyToolProposalScope(),
            policy=_FailingPolicy(),
            tool_observation=_FailingToolObservation(),
            answer_synthesis=_AnswerSynthesis(),
        )
    )

    result = orchestrator.start(
        ControlledReActStartRequest(
            run_id="run_scope_violation",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="Look up customer policy status.",
        )
    )

    assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE
    assert result.final_output == (
        "The customer_lookup tool was not run because it is outside "
        "the effective tool proposal scope."
    )
    assert [stage.stage_id for stage in result.stage_results] == [
        "tool_proposal_scope",
        "plan",
        "tool_review",
        "response",
    ]


def test_tool_proposal_binding_runs_before_policy_review() -> None:
    policy = _CapturingAllowPolicy()
    orchestrator = ControlledReActOrchestrator(
        ports=ControlledReActPorts(
            planner=_CreateTicketThenAnswerPlanner(),
            tool_proposal_scope=_CreateTicketToolProposalScope(),
            policy=policy,
            tool_observation=_ToolObservation(),
            answer_synthesis=_ObservationBackedAnswerSynthesis(),
        )
    )

    result = orchestrator.start(
        ControlledReActStartRequest(
            run_id="run_bind_policy",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="Create a service ticket.",
        )
    )

    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert policy.parameters is not None
    assert policy.parameters["idempotency_key"] == (
        "run_bind_policy:act_create_ticket:create_service_ticket"
    )


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


def test_approval_pause_freezes_bound_tool_proposal_snapshot() -> None:
    snapshot_store = _SnapshotStore()
    orchestrator = ControlledReActOrchestrator(
        ports=ControlledReActPorts(
            planner=_CreateTicketThenAnswerPlanner(),
            tool_proposal_scope=_CreateTicketToolProposalScope(),
            policy=_RequireApprovalToolPolicy(),
            snapshot_store=snapshot_store,
            answer_synthesis=_AnswerSynthesis(),
        )
    )

    result = orchestrator.start(
        ControlledReActStartRequest(
            run_id="run_bound_approval",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="Create a service ticket.",
        )
    )

    assert result.outcome is ReceiptOutcome.WAITING_FOR_APPROVAL
    assert result.approval_pause is not None
    assert "approved_tool_proposal" in result.approval_pause.summary
    approval_summary = result.approval_pause.summary["approved_tool_proposal"]
    assert approval_summary["tool_contract_id"] == "create_service_ticket"
    assert approval_summary["parameter_keys"] == (
        "idempotency_key",
        "ticket_subject",
    )
    assert approval_summary["parameter_digest"].startswith("sha256:")
    assert snapshot_store.saved_snapshot is not None
    approved_snapshot = snapshot_store.saved_snapshot.state.approved_tool_proposal_snapshot
    assert approved_snapshot is not None
    assert approved_snapshot.tool_contract_id == "create_service_ticket"
    assert approved_snapshot.parameters["idempotency_key"] == (
        "run_bound_approval:act_create_ticket:create_service_ticket"
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
    assert [stage.stage_id for stage in result.stage_results] == [
        "plan",
        "tool_review",
        "response",
    ]


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


def test_start_can_observe_tool_then_retrieval_before_answering() -> None:
    answer_synthesis = _ContextCapturingAnswerSynthesis()
    orchestrator = ControlledReActOrchestrator(
        ports=ControlledReActPorts(
            planner=_ToolThenRetrievalThenAnswerPlanner(),
            policy=_AllowToolPolicy(),
            tool_observation=_ToolObservation(),
            knowledge_observation=_EffectKnowledgeObservation(),
            answer_synthesis=answer_synthesis,
        )
    )

    result = orchestrator.start(
        ControlledReActStartRequest(
            run_id="run_tool_then_retrieval",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="Look up the customer status and cite the policy.",
        )
    )

    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert [
        stage.stage_id for stage in result.stage_results if stage.stage_id in {"tool", "retrieval"}
    ] == ["tool", "retrieval"]
    assert answer_synthesis.context is not None
    assert len(answer_synthesis.context.observation_truth) == 2


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
    assert [stage.stage_id for stage in result.stage_results] == [
        "plan",
        "tool_review",
        "tool",
        "plan",
        "model_answer",
        "response",
    ]


def test_resume_fails_closed_when_approved_tool_snapshot_integrity_mismatches() -> None:
    action = _proposal("act_tool", ReActActionType.PROPOSE_TOOL_CALL).model_copy(
        update={
            "target_tool_name": "create_service_ticket",
            "parameters": {
                "ticket_subject": "Claim follow-up",
                "idempotency_key": "tampered",
            },
        }
    )
    snapshot = ControlledReActRunStateSnapshot(
        snapshot_id="snap_run_integrity",
        run_id="run_integrity",
        state=ControlledReActRunState(
            run_id="run_integrity",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="Create a service ticket.",
            phase=ControlledReActRunPhase.WAITING,
            action_history=(action,),
            approved_tool_proposal_snapshot=ApprovedToolProposalSnapshot(
                snapshot_id="approved_act_tool",
                action_id=action.action_id,
                tool_contract_id="create_service_ticket",
                parameters={
                    "ticket_subject": "Claim follow-up",
                    "idempotency_key": "original",
                },
                parameter_digest="sha256:original",
                scope_digest="sha256:scope",
                policy_decision=PolicyDecisionType.REQUIRE_APPROVAL.value,
                risk_level="high",
                approval_reason="Human approval required before tool execution.",
            ),
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
            approved=True,
            actor="ops",
        )
    )

    assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE
    assert result.final_output == (
        "The approved tool proposal no longer matches the pending execution request."
    )
    assert [stage.stage_id for stage in result.stage_results] == [
        "plan",
        "tool_review",
        "response",
    ]


def test_resume_can_observe_tool_then_retrieval_before_answering() -> None:
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
            question="Look up this customer's claim status and cite policy.",
            action_history=(action,),
        ),
    )
    answer_synthesis = _ContextCapturingAnswerSynthesis()
    orchestrator = ControlledReActOrchestrator(
        ports=ControlledReActPorts(
            planner=_ToolThenRetrievalThenAnswerPlanner(),
            snapshot_store=_ResumeSnapshotStore(snapshot),
            tool_observation=_ToolObservation(),
            knowledge_observation=_EffectKnowledgeObservation(),
            answer_synthesis=answer_synthesis,
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

    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert [
        stage.stage_id for stage in result.stage_results if stage.stage_id in {"tool", "retrieval"}
    ] == ["tool", "retrieval"]
    assert answer_synthesis.context is not None
    assert len(answer_synthesis.context.observation_truth) == 2


def test_tool_answer_fallback_does_not_echo_raw_authorized_result() -> None:
    truth = ToolObservationTruth(
        truth_ref="observation://run_001/obs_tool/truth",
        observation_id="obs_tool",
        action_id="act_tool",
        tool_name="customer_lookup",
        authorized_result={
            "raw_payload": {"customer_phone": "555-0100"},
            "internal_note": "must-not-echo",
        },
        result_schema_id="customer_lookup.v1",
    )

    result = _EvidenceAnswerSynthesisAdapter().synthesize(
        ControlledReActRunState(
            run_id="run_001",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="Look up this customer.",
        ),
        _proposal("act_answer", ReActActionType.GENERATE_FINAL_ANSWER),
        AnswerEvidenceContext(
            run_id="run_001",
            observation_truth=(truth,),
            source_refs=("tool://customer_lookup",),
        ),
    )

    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert "must-not-echo" not in result.final_output
    assert "555-0100" not in result.final_output
    assert result.final_output == "customer_lookup returned an authorized result."


def test_tool_answer_fallback_does_not_treat_approval_denial_as_authorized_result() -> None:
    truth = ToolObservationTruth(
        truth_ref="observation://run_001/obs_tool/truth",
        observation_id="obs_tool",
        action_id="act_tool",
        tool_name="customer_lookup",
        authorized_result={"approval_state": "denied", "actor": "ops"},
        result_schema_id="customer_lookup.approval.v1",
        approval_ref="appr_act_tool",
    )

    result = _EvidenceAnswerSynthesisAdapter().synthesize(
        ControlledReActRunState(
            run_id="run_001",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="Look up this customer.",
        ),
        _proposal("act_answer", ReActActionType.GENERATE_FINAL_ANSWER),
        AnswerEvidenceContext(
            run_id="run_001",
            observation_truth=(truth,),
            source_refs=("tool://customer_lookup",),
        ),
    )

    assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE
    assert result.final_output == "Unable to answer without accepted governed evidence."


def test_tool_summary_projection_requires_configured_fields() -> None:
    with pytest.raises(ProofAgentError, match="missing summary_fields"):
        _tool_summary_projection(
            {"raw_payload": {"customer_phone": "555-0100"}},
            summary_fields=("status",),
        )


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
    assert result.outcome is ReceiptOutcome.TOOL_APPROVAL_DENIED
    assert result.final_output == "The customer_lookup tool is still required after approval was denied."
    assert result.approval_pause is None
    assert [stage.stage_id for stage in result.stage_results] == [
        "plan",
        "tool_review",
        "tool",
        "plan",
        "model_answer",
        "response",
    ]
    tool_stage = next(stage for stage in result.stage_results if stage.stage_id == "tool")
    assert tool_stage.summary["approval_state"] == "denied"


def test_resume_denied_tool_snapshot_can_replan_to_alternate_retrieval_answer() -> None:
    action = _proposal("act_tool", ReActActionType.PROPOSE_TOOL_CALL).model_copy(
        update={"target_tool_name": "customer_lookup"}
    )
    snapshot = ControlledReActRunStateSnapshot(
        snapshot_id="snap_run_alt",
        run_id="run_alt",
        state=ControlledReActRunState(
            run_id="run_alt",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="Look up this customer's claim status.",
            action_history=(action,),
        ),
    )
    orchestrator = ControlledReActOrchestrator(
        ports=ControlledReActPorts(
            planner=_DeniedToolThenRetrievalThenAnswerPlanner(),
            snapshot_store=_ResumeSnapshotStore(snapshot),
            tool_observation=_FailingToolObservation(),
            knowledge_observation=_EffectKnowledgeObservation(),
            answer_synthesis=_EvidenceAnswerSynthesisAdapter(),
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

    assert result.run_id == "run_alt"
    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert result.final_output == (
        "Submit the claim form and itemized invoice. Citation: claims-guide.md#documents."
    )
    stage_ids = [stage.stage_id for stage in result.stage_results]
    assert "tool" in stage_ids
    assert "retrieval" in stage_ids
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
        answer_context: AnswerEvidenceContext,
    ) -> AnswerSynthesisResult:
        _ = (state, answer_context)
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
        identity: ObservationIdentity,
    ) -> ObservationEffect:
        evidence = EvidenceChunk(
            source="claims-guide.md",
            content="Submit the claim form and itemized invoice.",
            status=EvidenceStatus.ACCEPTED,
            citation="claims-guide.md#documents",
        )
        truth = RetrievalObservationTruth(
            truth_ref=identity.truth_ref,
            observation_id=identity.observation_id,
            action_id=action.action_id,
            accepted_evidence=(evidence,),
            citation_refs=("claims-guide.md#documents",),
        )
        record = ObservationRecord(
            observation_id=identity.observation_id,
            action_id=action.action_id,
            action_type=action.action_type,
            round=state.plan_round,
            truth_ref=identity.truth_ref,
            summary={"accepted_evidence_count": 1, "new_evidence_count": 1},
            accepted_evidence_count=1,
            new_evidence_count=1,
            unresolved_subgoals=(),
            source_refs=("claims-guide.md",),
            citation_refs=("claims-guide.md#documents",),
        )
        return ObservationEffect(
            observation_record=record,
            truth_artifact=truth,
            trace_projection={"observation_id": identity.observation_id},
        )


class _EffectKnowledgeObservation:
    identity: ObservationIdentity | None = None

    def observe(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
        identity: ObservationIdentity,
    ) -> ObservationEffect:
        self.identity = identity
        evidence = EvidenceChunk(
            source="claims-guide.md",
            content="Submit the claim form and itemized invoice.",
            status=EvidenceStatus.ACCEPTED,
            citation="claims-guide.md#documents",
        )
        truth = RetrievalObservationTruth(
            truth_ref=identity.truth_ref,
            observation_id=identity.observation_id,
            action_id=action.action_id,
            accepted_evidence=(evidence,),
            citation_refs=("claims-guide.md#documents",),
        )
        record = ObservationRecord(
            observation_id=identity.observation_id,
            action_id=action.action_id,
            action_type=action.action_type,
            round=state.plan_round,
            truth_ref=identity.truth_ref,
            summary={"accepted_evidence_count": 1, "citation_count": 1},
            accepted_evidence_count=1,
            new_evidence_count=1,
            unresolved_subgoals=(),
            source_refs=("claims-guide.md",),
            citation_refs=("claims-guide.md#documents",),
        )
        return ObservationEffect(
            observation_record=record,
            truth_artifact=truth,
            trace_projection={"observation_id": identity.observation_id},
        )


class _WrongIdentityKnowledgeObservation:
    def observe(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
        identity: ObservationIdentity,
    ) -> ObservationEffect:
        _ = identity
        wrong_identity = ObservationIdentity.allocate(
            run_id=state.run_id,
            plan_round=state.plan_round + 100,
            action_id=action.action_id,
        )
        evidence = EvidenceChunk(
            source="claims-guide.md",
            content="Submit the claim form and itemized invoice.",
            status=EvidenceStatus.ACCEPTED,
            citation="claims-guide.md#documents",
        )
        truth = RetrievalObservationTruth(
            truth_ref=wrong_identity.truth_ref,
            observation_id=wrong_identity.observation_id,
            action_id=action.action_id,
            accepted_evidence=(evidence,),
            citation_refs=("claims-guide.md#documents",),
        )
        record = ObservationRecord(
            observation_id=wrong_identity.observation_id,
            action_id=action.action_id,
            action_type=action.action_type,
            round=state.plan_round,
            truth_ref=wrong_identity.truth_ref,
            summary={"accepted_evidence_count": 1, "citation_count": 1},
            accepted_evidence_count=1,
            new_evidence_count=1,
            source_refs=("claims-guide.md",),
            citation_refs=("claims-guide.md#documents",),
        )
        return ObservationEffect(
            observation_record=record,
            truth_artifact=truth,
            trace_projection={"observation_id": wrong_identity.observation_id},
        )


class _CitationMismatchKnowledgeObservation:
    def observe(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
        identity: ObservationIdentity,
    ) -> ObservationEffect:
        _ = state
        evidence = EvidenceChunk(
            source="claims-guide.md",
            content="Submit the claim form and itemized invoice.",
            status=EvidenceStatus.ACCEPTED,
            citation="claims-guide.md#documents",
        )
        truth = RetrievalObservationTruth(
            truth_ref=identity.truth_ref,
            observation_id=identity.observation_id,
            action_id=action.action_id,
            accepted_evidence=(evidence,),
            citation_refs=(),
        )
        record = ObservationRecord(
            observation_id=identity.observation_id,
            action_id=action.action_id,
            action_type=action.action_type,
            round=state.plan_round,
            truth_ref=identity.truth_ref,
            summary={"accepted_evidence_count": 1, "citation_count": 1},
            accepted_evidence_count=1,
            new_evidence_count=1,
            source_refs=("claims-guide.md",),
            citation_refs=("claims-guide.md#documents",),
        )
        return ObservationEffect(
            observation_record=record,
            truth_artifact=truth,
            trace_projection={"observation_id": identity.observation_id},
        )


class _CountingKnowledgeObservation(_KnowledgeObservation):
    def __init__(self) -> None:
        self.call_count = 0

    def observe(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
        identity: ObservationIdentity,
    ) -> ObservationEffect:
        self.call_count += 1
        return super().observe(state, action, identity)


class _FailingKnowledgeObservation:
    def observe(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
        identity: ObservationIdentity,
    ) -> ObservationEffect:
        _ = (state, action, identity)
        raise AssertionError("review denied retrieval must not execute observation")


class _ObservationBackedAnswerSynthesis:
    def synthesize(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
        answer_context: AnswerEvidenceContext,
    ) -> AnswerSynthesisResult:
        _ = answer_context
        if not state.observation_records:
            raise AssertionError("answer synthesis requires an ObservationRecord")
        return AnswerSynthesisResult(
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            final_output="Submit the claim form and itemized invoice.",
            message="Answered with governed citations.",
            reasoning_summary=action.reasoning_summary.model_dump(mode="json"),
        )


class _ContextCapturingAnswerSynthesis:
    def __init__(self) -> None:
        self.context = None

    def synthesize(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
        answer_context: AnswerEvidenceContext,
    ) -> AnswerSynthesisResult:
        _ = state
        self.context = answer_context
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


class _CapturingRefusalPlanner:
    def __init__(self) -> None:
        self.captured_state: ControlledReActRunState | None = None

    def plan(self, state: ControlledReActRunState) -> ReActActionProposal:
        self.captured_state = state
        return _proposal("act_refuse", ReActActionType.REFUSE)


class _EmptyToolProposalScope:
    def resolve(self, state: ControlledReActRunState) -> EffectiveToolProposalScope:
        return EffectiveToolProposalScope(
            run_id=state.run_id,
            plan_round=state.plan_round,
            schema_digest="sha256:empty",
        )


class _ClaimOnlyToolProposalScope:
    def resolve(self, state: ControlledReActRunState) -> EffectiveToolProposalScope:
        return EffectiveToolProposalScope(
            run_id=state.run_id,
            plan_round=state.plan_round,
            schema_digest="sha256:claim",
            tool_interfaces=(
                ToolProposalInterface(
                    tool_contract_id="claim_status_lookup",
                    purpose="claim status lookup",
                    risk_level="medium",
                    read_only=True,
                    requires_approval=False,
                ),
            ),
        )


class _CreateTicketToolProposalScope:
    def resolve(self, state: ControlledReActRunState) -> EffectiveToolProposalScope:
        return EffectiveToolProposalScope(
            run_id=state.run_id,
            plan_round=state.plan_round,
            schema_digest="sha256:create-ticket",
            tool_interfaces=(
                ToolProposalInterface(
                    tool_contract_id="create_service_ticket",
                    purpose="create service ticket",
                    risk_level="high",
                    read_only=False,
                    requires_approval=True,
                    parameters=(
                        ToolProposalParameter(
                            name="ticket_subject",
                            required=True,
                            value_type="string",
                            value_source=ToolProposalParameterSource.USER_SUPPLIED,
                        ),
                        ToolProposalParameter(
                            name="idempotency_key",
                            required=True,
                            value_type="string",
                            value_source=ToolProposalParameterSource.SYSTEM_GENERATED,
                        ),
                    ),
                ),
            ),
        )


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


class _DenyAnswerAdmissionPolicy:
    def __init__(self) -> None:
        self.context: dict[str, object] | None = None

    def evaluate_answer(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
        answer_context: AnswerEvidenceContext,
        answer: AnswerSynthesisResult,
    ) -> PolicyDecision:
        _ = (state, action, answer)
        self.context = {
            "accepted_evidence_count": sum(
                1
                for truth in answer_context.observation_truth
                if isinstance(truth, RetrievalObservationTruth)
                for chunk in truth.accepted_evidence
                if chunk.status is EvidenceStatus.ACCEPTED
            ),
            "citations_present": bool(answer_context.citation_refs),
        }
        return PolicyDecision(
            decision=PolicyDecisionType.DENY,
            enforcement_point=EnforcementPoint.BEFORE_ANSWER,
            reason="answer admission denied",
            policy_rule_id="answer.deny",
            metadata=self.context,
            trace_event_id="trace_answer_deny",
        )


class _MemoryCandidateFixture:
    def __init__(self, values: dict[str, object]) -> None:
        self.values = values
        self.field_names = tuple(sorted(values))
        self.write_source = "controlled_react_v3"

    @property
    def field_count(self) -> int:
        return len(self.field_names)


class _CandidateMemory:
    def __init__(self) -> None:
        self.commit_count = 0
        self.committed_values: dict[str, object] | None = None

    def read(self, state: ControlledReActRunState) -> dict[str, object]:
        _ = state
        return {}

    def prepare_write(
        self,
        state: ControlledReActRunState,
        answer: AnswerSynthesisResult,
    ) -> _MemoryCandidateFixture:
        return _MemoryCandidateFixture(
            {
                "question": state.question,
                "outcome": answer.outcome.value,
                "final_output_length": len(answer.final_output),
            }
        )

    def commit_write(self, candidate: _MemoryCandidateFixture) -> ValidationResult:
        self.commit_count += 1
        self.committed_values = dict(candidate.values)
        return ValidationResult(
            validator_name="memory",
            status=ValidationStatus.PASSED,
            reason="Session memory write allowed.",
            metadata={"written_fields": candidate.field_names},
        )

    def write(
        self,
        state: ControlledReActRunState,
        answer: AnswerSynthesisResult,
    ) -> ValidationResult:
        _ = (state, answer)
        raise AssertionError("orchestrator must gate prepared memory writes")


class _DenyMemoryWritePolicy:
    def __init__(self) -> None:
        self.write_context: dict[str, object] | None = None

    def evaluate_memory_write(
        self,
        state: ControlledReActRunState,
        candidate: _MemoryCandidateFixture,
    ) -> PolicyDecision:
        _ = state
        self.write_context = dict(candidate.values)
        return PolicyDecision(
            decision=PolicyDecisionType.DENY,
            enforcement_point=EnforcementPoint.BEFORE_MEMORY_WRITE,
            reason="question must not be written to memory",
            policy_rule_id="memory.deny_question",
            metadata={"denied_fields": ("question",)},
            trace_event_id="trace_memory_deny",
        )


class _AllowMemoryWritePolicy:
    def evaluate_memory_write(
        self,
        state: ControlledReActRunState,
        candidate: _MemoryCandidateFixture,
    ) -> PolicyDecision:
        _ = (state, candidate)
        return PolicyDecision(
            decision=PolicyDecisionType.ALLOW,
            enforcement_point=EnforcementPoint.BEFORE_MEMORY_WRITE,
            reason="memory write is allowed",
            policy_rule_id="memory.allow",
            trace_event_id="trace_memory_allow",
        )


class _TraceCapture:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(
        self,
        event_type: str,
        *,
        status: str = "ok",
        payload: dict[str, object] | None = None,
    ) -> None:
        self.events.append(
            {
                "event_type": event_type,
                "status": status,
                "payload": dict(payload or {}),
            }
        )


class _ToolObservationThenAnswerPlanner:
    def plan(self, state: ControlledReActRunState) -> ReActActionProposal:
        if not state.observation_records:
            return _proposal("act_tool", ReActActionType.PROPOSE_TOOL_CALL).model_copy(
                update={"target_tool_name": "customer_lookup"}
            )
        return _proposal("act_answer", ReActActionType.GENERATE_FINAL_ANSWER)


class _CreateTicketThenAnswerPlanner:
    def plan(self, state: ControlledReActRunState) -> ReActActionProposal:
        if not state.observation_records:
            return _proposal(
                "act_create_ticket",
                ReActActionType.PROPOSE_TOOL_CALL,
            ).model_copy(
                update={
                    "target_tool_name": "create_service_ticket",
                    "parameters": {"ticket_subject": "Claim follow-up"},
                }
            )
        return _proposal("act_answer", ReActActionType.GENERATE_FINAL_ANSWER)


class _ToolThenRetrievalThenAnswerPlanner:
    def plan(self, state: ControlledReActRunState) -> ReActActionProposal:
        if not state.observation_records:
            return _proposal("act_tool", ReActActionType.PROPOSE_TOOL_CALL).model_copy(
                update={"target_tool_name": "customer_lookup"}
            )
        if len(state.observation_records) == 1:
            return _proposal("act_retrieve", ReActActionType.PLAN_RETRIEVAL)
        return _proposal("act_answer", ReActActionType.GENERATE_FINAL_ANSWER)


class _DeniedToolThenRetrievalThenAnswerPlanner:
    def plan(self, state: ControlledReActRunState) -> ReActActionProposal:
        if not state.observation_records:
            return _proposal("act_tool", ReActActionType.PROPOSE_TOOL_CALL).model_copy(
                update={"target_tool_name": "customer_lookup"}
            )
        if len(state.observation_records) == 1:
            return _proposal("act_retrieve", ReActActionType.PLAN_RETRIEVAL)
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


class _FailingPolicy:
    def evaluate(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> PolicyDecision:
        _ = (state, action)
        raise AssertionError("scope violations must not reach PolicyEngine")


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


class _CapturingAllowPolicy:
    def __init__(self) -> None:
        self.parameters: dict[str, object] | None = None

    def evaluate(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
    ) -> PolicyDecision:
        _ = state
        self.parameters = dict(action.parameters)
        return PolicyDecision(
            decision=PolicyDecisionType.ALLOW,
            enforcement_point=EnforcementPoint.BEFORE_TOOL_CALL,
            reason="bound tool proposal is allowed",
            policy_rule_id="tools.create_service_ticket.allow",
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
        identity: ObservationIdentity,
    ) -> ObservationEffect:
        tool_name = action.target_tool_name or "unknown_tool"
        truth = ToolObservationTruth(
            truth_ref=identity.truth_ref,
            observation_id=identity.observation_id,
            action_id=action.action_id,
            tool_name=tool_name,
            authorized_result={"status": "pending"},
            result_schema_id=f"{tool_name}.v1",
        )
        record = ObservationRecord(
            observation_id=identity.observation_id,
            action_id=action.action_id,
            action_type=action.action_type,
            round=state.plan_round,
            truth_ref=identity.truth_ref,
            summary={"tool_name": action.target_tool_name, "status": "completed"},
            accepted_evidence_count=0,
            new_evidence_count=0,
            unresolved_subgoals=(),
            source_refs=(f"tool://{tool_name}",),
            citation_refs=(),
        )
        return ObservationEffect(
            observation_record=record,
            truth_artifact=truth,
            trace_projection={"observation_id": identity.observation_id},
        )


class _FailingToolObservation:
    def observe(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
        identity: ObservationIdentity,
    ) -> ObservationEffect:
        _ = (state, action, identity)
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
