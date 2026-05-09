from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from proof_agent.contracts import ValidationResult, ValidationStatus


REQUIRED_CUSTOMER_LOOKUP_KEYS = {"customer_id", "policy_id", "status", "source"}


def validate_customer_lookup_result(result: Mapping[str, Any]) -> ValidationResult:
    missing = sorted(REQUIRED_CUSTOMER_LOOKUP_KEYS.difference(result))
    source_ok = result.get("source") == "mcp_mock"
    if missing or not source_ok:
        return ValidationResult(
            validator_name="tool_result",
            status=ValidationStatus.FAILED,
            reason="customer_lookup result is invalid.",
            metadata={"missing": tuple(missing), "source_ok": source_ok},
        )
    return ValidationResult(
        validator_name="tool_result",
        status=ValidationStatus.PASSED,
        reason="customer_lookup result is valid.",
        metadata={"source": result["source"]},
    )
