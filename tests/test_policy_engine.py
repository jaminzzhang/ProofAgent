from proof_agent.contracts import EnforcementPoint, PolicyDecisionType, ReviewDecision
from proof_agent.control.policy.engine import PolicyEngine


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


def test_retrieval_step_defaults_to_allow() -> None:
    engine = PolicyEngine.from_file("examples/enterprise_qa/policy.yaml")
    decision = engine.evaluate(
        EnforcementPoint.BEFORE_RETRIEVAL_STEP,
        {"provider": "local_markdown", "step_id": "step_1", "top_k": 2},
    )

    assert decision.decision == PolicyDecisionType.ALLOW


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


def test_policy_overrides_review_allow_for_medium_customer_lookup() -> None:
    engine = PolicyEngine.from_file("examples/enterprise_qa/policy.yaml")
    review_decision = ReviewDecision(
        review_id="review.act_tool_1.before_tool_call",
        enforcement_point=EnforcementPoint.BEFORE_TOOL_CALL,
        suggested_decision=PolicyDecisionType.ALLOW,
        reason="The proposed lookup has business justification.",
        confidence=0.8,
        risk_flags=(),
        subject_action_id="act_tool_1",
    )

    decision, event = engine.evaluate_with_review(
        EnforcementPoint.BEFORE_TOOL_CALL,
        {"tool_name": "customer_lookup", "risk_level": "medium"},
        review_decision=review_decision,
    )

    assert decision.decision == PolicyDecisionType.REQUIRE_APPROVAL
    assert decision.policy_rule_id == "tools.customer_lookup.approval"
    assert event["used_review"] is True
    assert event["review_id"] == "review.act_tool_1.before_tool_call"
    assert event["suggested_decision"] == "allow"
    assert event["final_decision"] == "require_approval"
    assert event["overridden"] is True


def test_invalid_model_call_review_fails_closed_to_deny() -> None:
    engine = PolicyEngine.from_file("examples/enterprise_qa/policy.yaml")
    review_decision = ReviewDecision(
        review_id="review.act_model_1.before_model_call",
        enforcement_point=EnforcementPoint.BEFORE_MODEL_CALL,
        suggested_decision=PolicyDecisionType.REQUIRE_APPROVAL,
        reason="Ask a human before invoking the model.",
        confidence=0.7,
        risk_flags=("model_call",),
        subject_action_id="act_model_1",
    )

    decision, event = engine.evaluate_with_review(
        EnforcementPoint.BEFORE_MODEL_CALL,
        {"accepted_evidence_count": 1},
        review_decision=review_decision,
    )

    assert decision.decision == PolicyDecisionType.DENY
    assert event["used_review"] is True
    assert event["error_code"] == "invalid_review_decision"
    assert event["final_decision"] == "deny"


def test_malformed_retrieval_review_fallback_fails_closed_to_deny() -> None:
    engine = PolicyEngine.from_file("examples/enterprise_qa/policy.yaml")
    review_decision = ReviewDecision(
        review_id="review.act_retrieve_1.before_tool_call",
        enforcement_point=EnforcementPoint.BEFORE_TOOL_CALL,
        suggested_decision=PolicyDecisionType.ALLOW,
        reason="Wrong enforcement point for retrieval planning.",
        confidence=0.7,
        risk_flags=(),
        subject_action_id="act_retrieve_1",
    )

    decision, event = engine.evaluate_with_review(
        EnforcementPoint.BEFORE_RETRIEVAL_PLAN,
        {"review_fallback_decision": "not_a_decision"},
        review_decision=review_decision,
    )

    assert decision.decision == PolicyDecisionType.DENY
    assert event["used_review"] is True
    assert event["error_code"] == "review_enforcement_point_mismatch"
    assert event["final_decision"] == "deny"


def test_stricter_review_reason_is_not_copied_to_policy_decision() -> None:
    engine = PolicyEngine.from_file("examples/enterprise_qa/policy.yaml")
    sentinel = "RAW_MODEL_OUTPUT_SHOULD_NOT_TRACE"
    review_decision = ReviewDecision(
        review_id="review.act_retrieve_1.before_retrieval_plan",
        enforcement_point=EnforcementPoint.BEFORE_RETRIEVAL_PLAN,
        suggested_decision=PolicyDecisionType.DENY,
        reason=sentinel,
        confidence=0.7,
        risk_flags=(),
        subject_action_id="act_retrieve_1",
    )

    decision, event = engine.evaluate_with_review(
        EnforcementPoint.BEFORE_RETRIEVAL_PLAN,
        {"query": "travel meal reimbursement rule"},
        review_decision=review_decision,
    )

    assert decision.decision == PolicyDecisionType.DENY
    assert decision.reason == (
        "Auto review suggested a stricter decision at before_retrieval_plan."
    )
    assert sentinel not in decision.reason
    assert event["used_review"] is True
    assert event["final_decision"] == "deny"
