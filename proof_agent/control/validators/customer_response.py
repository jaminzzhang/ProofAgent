from __future__ import annotations

import re

from proof_agent.contracts import CustomerSafeResponse, ValidationResult, ValidationStatus


_INTERNAL_PATTERNS = (
    re.compile(r"/api/runs/"),
    re.compile(r"trace\.jsonl"),
    re.compile(r"governance[_\s-]?receipt"),
    re.compile(r"policy_decision"),
    re.compile(r"review_results"),
)


def validate_customer_safe_response(response: CustomerSafeResponse) -> ValidationResult:
    """Validate that a response projection is safe for terminal customers."""

    if any(pattern.search(response.message) for pattern in _INTERNAL_PATTERNS):
        return ValidationResult(
            validator_name="customer_safe_response",
            status=ValidationStatus.FAILED,
            reason="Customer response contains an internal reference.",
            metadata={"reason": "internal_reference"},
        )
    return ValidationResult(
        validator_name="customer_safe_response",
        status=ValidationStatus.PASSED,
        reason="Customer response is safe for projection.",
        metadata={"safe_source_count": len(response.safe_sources)},
    )
