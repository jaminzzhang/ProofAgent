from proof_agent.contracts import EnforcementPoint, PolicyDecision, PolicyDecisionType, ReceiptOutcome
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


def test_receipt_outcomes_match_contract() -> None:
    assert ReceiptOutcome.ANSWERED_WITH_CITATIONS.value == "ANSWERED_WITH_CITATIONS"
    assert ReceiptOutcome.FAILED_RECEIPT_UNAVAILABLE.value == "FAILED_RECEIPT_UNAVAILABLE"


def test_error_message_contains_fix() -> None:
    error = ProofAgentError("PA_CONFIG_001", "missing policy.file", "Add policy.file to agent.yaml")
    assert "Fix: Add policy.file to agent.yaml" in str(error)
