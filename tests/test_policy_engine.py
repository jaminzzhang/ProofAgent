from proof_agent.contracts import EnforcementPoint, PolicyDecisionType
from proof_agent.policy.engine import PolicyEngine


def test_before_answer_denies_weak_evidence() -> None:
    engine = PolicyEngine.from_file("examples/enterprise_qa/policy.yaml")
    decision = engine.evaluate(
        EnforcementPoint.BEFORE_ANSWER,
        {"accepted_evidence_count": 0, "citations_present": False},
    )
    assert decision.decision == PolicyDecisionType.DENY
    assert decision.policy_rule_id == "answering.require_retrieval"


def test_before_tool_call_requires_approval() -> None:
    engine = PolicyEngine.from_file("examples/enterprise_qa/policy.yaml")
    decision = engine.evaluate(
        EnforcementPoint.BEFORE_TOOL_CALL,
        {"tool_name": "customer_lookup", "risk_level": "medium"},
    )
    assert decision.decision == PolicyDecisionType.REQUIRE_APPROVAL
