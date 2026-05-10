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


def test_before_model_call_can_deny_remote_provider(tmp_path) -> None:
    policy_yaml = tmp_path / "policy.yaml"
    policy_yaml.write_text(
        """
rules:
  - rule_id: model.deny_remote
    enforcement_point: before_model_call
    condition:
      cost_class: remote
    decision:
      on_match: deny
    reason: "Remote model calls are disabled."
""",
        encoding="utf-8",
    )
    engine = PolicyEngine.from_file(policy_yaml)

    decision = engine.evaluate(
        EnforcementPoint.BEFORE_MODEL_CALL,
        {
            "provider": "openai_compatible",
            "model": "gpt-4o-mini",
            "estimated_tokens": 100,
            "stream": False,
            "cost_class": "remote",
        },
    )

    assert decision.decision == PolicyDecisionType.DENY
