from pathlib import Path

import pytest

from examples.insurance_customer_service.customer_adapter import (
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
    assert "POL-001" in _resource_ids(context, "policy")
    assert "CLM-001" in _resource_ids(context, "claim")


def test_anonymous_mock_customer_context_has_no_resource_access() -> None:
    context = load_mock_customer_context(CUSTOMERS, customer_id=None)

    assert context.session_type == "anonymous"
    assert context.customer_ref is None
    assert context.owned_resources == ()


def test_cross_customer_policy_access_is_rejected() -> None:
    context = load_mock_customer_context(CUSTOMERS, customer_id="CUST-001")

    with pytest.raises(CustomerAccessError):
        require_policy_access(context, "POL-002")


def test_cross_customer_claim_access_is_rejected() -> None:
    context = load_mock_customer_context(CUSTOMERS, customer_id="CUST-001")

    with pytest.raises(CustomerAccessError):
        require_claim_access(context, "CLM-002")


def _resource_ids(context: object, resource_type: str) -> tuple[str, ...]:
    return tuple(
        resource.resource_id
        for resource in getattr(context, "owned_resources")
        if resource.resource_type == resource_type
    )
