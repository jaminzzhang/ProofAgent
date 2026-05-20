from proof_agent.contracts import CustomerSafeResponse
from proof_agent.control.validators.customer_response import validate_customer_safe_response


def test_customer_response_rejects_internal_links() -> None:
    response = CustomerSafeResponse(
        message="See /api/runs/run_123/trace for details.",
    )

    result = validate_customer_safe_response(response)

    assert result.status == "failed"
    assert result.metadata["reason"] == "internal_reference"


def test_customer_response_accepts_safe_source_names() -> None:
    response = CustomerSafeResponse(
        message="Inpatient claims require the claim form and itemized invoice.",
        safe_sources=("claim-reimbursement-policy.md",),
    )

    result = validate_customer_safe_response(response)

    assert result.status == "passed"
