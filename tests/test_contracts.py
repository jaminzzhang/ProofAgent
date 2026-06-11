import pytest
from pydantic import ValidationError

from proof_agent.contracts import (
    ApprovalState,
    ApprovalStatus,
    EnforcementPoint,
    EvidenceChunk,
    EvidenceStatus,
    PendingApproval,
    PolicyDecision,
    PolicyDecisionType,
    ReceiptOutcome,
    TraceEvent,
    TraceEventType,
    WorkflowState,
)
from proof_agent.errors import ProofAgentError


def test_policy_decision_is_typed_and_traceable() -> None:
    decision = PolicyDecision(
        decision=PolicyDecisionType.ALLOW,
        enforcement_point=EnforcementPoint.BEFORE_ANSWER,
        reason="Evidence is sufficient.",
        policy_rule_id="answering.require_retrieval",
        metadata={"accepted_evidence_count": 2},
        trace_event_id="evt_0003",
    )
    assert decision.decision == PolicyDecisionType.ALLOW
    assert decision.trace_event_id == "evt_0003"


def test_policy_decision_metadata_is_immutable() -> None:
    decision = PolicyDecision(
        decision=PolicyDecisionType.ALLOW,
        enforcement_point=EnforcementPoint.BEFORE_ANSWER,
        reason="Evidence is sufficient.",
        policy_rule_id="answering.require_retrieval",
        metadata={"accepted_evidence_count": 2},
        trace_event_id="evt_0003",
    )

    with pytest.raises(TypeError):
        decision.metadata["x"] = 1


def test_workflow_state_collections_are_immutable() -> None:
    evidence = EvidenceChunk(
        source="kb://policy.md",
        content="Policy text",
        admission_score=0.91,
        status=EvidenceStatus.ACCEPTED,
    )
    workflow = WorkflowState(
        run_id="run_001",
        workflow_name="enterprise_qa",
        current_node="retrieve",
        question="What policy applies?",
        evidence=[evidence],
    )

    with pytest.raises(AttributeError):
        workflow.evidence.append(evidence)


def test_workflow_state_defaults_are_isolated() -> None:
    first = WorkflowState(
        run_id="run_001",
        workflow_name="enterprise_qa",
        current_node="retrieve",
        question="What policy applies?",
    )
    second = WorkflowState(
        run_id="run_002",
        workflow_name="enterprise_qa",
        current_node="retrieve",
        question="What policy applies?",
    )

    assert first.evidence == ()
    assert second.evidence == ()
    assert first.memory_writes == ()
    assert second.memory_writes == ()


def test_approval_state_contains_request_and_terminal_trace_fields() -> None:
    approval = ApprovalState(
        run_id="run_001",
        approval_id="appr_0001",
        tool_name="customer_lookup",
        requested_at="2026-05-09T10:30:04Z",
        expires_at="2026-05-09T10:31:04Z",
        state=ApprovalStatus.REQUESTED,
        reason="Human approval required.",
        trace_event_id="evt_0004",
        terminal_trace_event_id="evt_0005",
    )

    assert approval.run_id == "run_001"
    assert approval.approval_id == "appr_0001"
    assert approval.requested_at == "2026-05-09T10:30:04Z"
    assert approval.expires_at == "2026-05-09T10:31:04Z"
    assert approval.trace_event_id == "evt_0004"
    assert approval.terminal_trace_event_id == "evt_0005"


def test_approval_state_requires_contract_fields() -> None:
    with pytest.raises(ValidationError):
        ApprovalState(
            state=ApprovalStatus.REQUESTED,
            tool_name="customer_lookup",
            reason="Human approval required.",
            trace_event_id="evt_0004",
        )


def test_pending_approval_captures_continuation_snapshot() -> None:
    pending = PendingApproval(
        run_id="run_001",
        thread_id="run_001",
        approval_id="appr_customer_lookup",
        action_id="act_tool_1",
        tool_name="customer_lookup",
        parameters={"customer_id": "CUST-001", "policy_id": "POL-001"},
        policy_decision=PolicyDecisionType.REQUIRE_APPROVAL,
        checkpoint_id="checkpoint-001",
        status=ApprovalStatus.REQUESTED,
        created_at="2026-06-09T10:30:04Z",
        expires_at="2026-06-09T10:31:04Z",
    )

    assert pending.run_id == "run_001"
    assert pending.thread_id == "run_001"
    assert pending.action_id == "act_tool_1"
    assert pending.parameters["customer_id"] == "CUST-001"
    assert pending.policy_decision == PolicyDecisionType.REQUIRE_APPROVAL
    assert pending.checkpoint_id == "checkpoint-001"
    assert pending.expires_at == "2026-06-09T10:31:04Z"

    with pytest.raises(TypeError):
        pending.parameters["customer_id"] = "CUST-002"


def test_trace_event_type_is_constrained() -> None:
    event = TraceEvent(
        run_id="run_001",
        event_id="evt_0001",
        sequence=1,
        timestamp="2026-05-09T10:30:00Z",
        event_type=TraceEventType.RUN_STARTED,
        span_id="span_root",
        status="ok",
        payload={"manifest_path": "agent.yaml"},
        redaction={"applied": False, "fields": []},
    )

    assert event.schema_version == "trace.v1"
    assert event.event_type == TraceEventType.RUN_STARTED

    with pytest.raises(ValidationError):
        TraceEvent(
            run_id="run_001",
            event_id="evt_0002",
            sequence=2,
            timestamp="2026-05-09T10:30:01Z",
            event_type="typo",
            span_id="span_root",
            status="ok",
            payload={},
            redaction={"applied": False, "fields": []},
        )

    with pytest.raises(ValidationError):
        TraceEvent(
            schema_version="trace.v2",
            run_id="run_001",
            event_id="evt_0003",
            sequence=3,
            timestamp="2026-05-09T10:30:02Z",
            event_type=TraceEventType.RUN_STARTED,
            span_id="span_root",
            status="ok",
            payload={},
            redaction={"applied": False, "fields": []},
        )


def test_trace_event_payload_and_redaction_are_immutable() -> None:
    event = TraceEvent(
        run_id="run_001",
        event_id="evt_0001",
        sequence=1,
        timestamp="2026-05-09T10:30:00Z",
        event_type=TraceEventType.RUN_STARTED,
        span_id="span_root",
        status="ok",
        payload={"nested": {"field": "value"}},
        redaction={"applied": False, "fields": []},
    )

    with pytest.raises(TypeError):
        event.payload["new"] = "value"

    with pytest.raises(TypeError):
        event.payload["nested"]["field"] = "changed"

    with pytest.raises(AttributeError):
        event.redaction["fields"].append("secret")


def test_receipt_outcomes_match_contract() -> None:
    assert ReceiptOutcome.ANSWERED_WITH_CITATIONS.value == "ANSWERED_WITH_CITATIONS"
    assert ReceiptOutcome.FAILED_RECEIPT_UNAVAILABLE.value == "FAILED_RECEIPT_UNAVAILABLE"


def test_error_message_contains_fix() -> None:
    error = ProofAgentError("PA_CONFIG_001", "missing policy.file", "Add policy.file to agent.yaml")
    assert "Fix: Add policy.file to agent.yaml" in str(error)


def test_error_rejects_invalid_string_code() -> None:
    with pytest.raises(ValueError):
        ProofAgentError("TYPO", "bad code", "Use a valid ErrorCode")
