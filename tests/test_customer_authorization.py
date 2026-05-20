from pathlib import Path

import pytest

from proof_agent.control.customer import (
    CustomerAccessError,
    load_mock_customer_context,
    require_claim_access,
    require_policy_access,
)


CUSTOMERS = Path("examples/insurance_customer_service/customers.yaml")


def test_load_authenticated_mock_customer_context() -> None:
    context = load_mock_customer_context(CUSTOMERS, customer_id="CUST-001")

    assert context.session_type == "authenticated"
    assert context.customer_ref == "CUST-001"
    assert "POL-001" in context.allowed_policy_ids
    assert "CLM-001" in context.allowed_claim_ids


def test_anonymous_mock_customer_context_has_no_resource_access() -> None:
    context = load_mock_customer_context(CUSTOMERS, customer_id=None)

    assert context.session_type == "anonymous"
    assert context.customer_ref is None
    assert context.allowed_policy_ids == ()
    assert context.allowed_claim_ids == ()


def test_cross_customer_policy_access_is_rejected() -> None:
    context = load_mock_customer_context(CUSTOMERS, customer_id="CUST-001")

    with pytest.raises(CustomerAccessError):
        require_policy_access(context, "POL-002")


def test_cross_customer_claim_access_is_rejected() -> None:
    context = load_mock_customer_context(CUSTOMERS, customer_id="CUST-001")

    with pytest.raises(CustomerAccessError):
        require_claim_access(context, "CLM-002")
