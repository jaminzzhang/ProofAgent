from proof_agent.contracts import (
    CustomerAuthorizationContext,
    CustomerFeedbackSignal,
    CustomerOwnedResource,
    CustomerRunProgressState,
    CustomerSafeResponse,
    CustomerSessionType,
    HandoffReason,
)


def test_customer_authorization_context_is_trace_safe() -> None:
    context = CustomerAuthorizationContext(
        session_type=CustomerSessionType.AUTHENTICATED,
        customer_ref="cust_demo_001",
        owned_resources=(
            CustomerOwnedResource(
                resource_type="account",
                resource_id="ACC-001",
                label="Account ending 001",
            ),
        ),
        auth_scope=("read:account",),
    )

    payload = context.model_dump(mode="json")

    assert payload["session_type"] == "authenticated"
    assert payload["customer_ref"] == "cust_demo_001"
    assert payload["owned_resources"][0]["resource_type"] == "account"
    assert "allowed_policy_ids" not in payload
    assert "allowed_claim_ids" not in payload
    assert "access_token" not in payload
    assert "raw_token" not in payload


def test_customer_safe_response_does_not_need_internal_links() -> None:
    response = CustomerSafeResponse(
        progress_state=CustomerRunProgressState.COMPLETED,
        message="Travel meal reimbursement requires an itemized receipt.",
        safe_sources=("claim-reimbursement-policy.md",),
    )

    payload = response.model_dump(mode="json")

    assert payload["progress_state"] == "completed"
    assert "trace" not in payload
    assert "receipt" not in payload


def test_handoff_reason_values_are_stable() -> None:
    assert HandoffReason.TRANSACTIONAL_ACTION_REQUESTED.value == "transactional_action_requested"
    assert HandoffReason.CROSS_CUSTOMER_ACCESS_ATTEMPT.value == "cross_customer_access_attempt"


def test_feedback_signal_is_observation_only() -> None:
    feedback = CustomerFeedbackSignal(rating="down", comment="Not enough detail.")

    assert feedback.rating == "down"
    assert feedback.applies_to_training is False
