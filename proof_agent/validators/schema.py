from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from proof_agent.contracts import ValidationResult, ValidationStatus


def validate_final_output_schema(output: Mapping[str, Any]) -> ValidationResult:
    """Validate the minimal final-output shape expected by receipts and tests."""

    required = {"outcome", "message"}
    missing = sorted(required.difference(output))
    citations = output.get("citations", ())
    citations_valid = isinstance(citations, list | tuple)
    if missing or not citations_valid:
        return ValidationResult(
            validator_name="schema",
            status=ValidationStatus.FAILED,
            reason="Final output schema is invalid.",
            metadata={"missing": tuple(missing), "citations_valid": citations_valid},
        )
    return ValidationResult(
        validator_name="schema",
        status=ValidationStatus.PASSED,
        reason="Final output schema is valid.",
        metadata={"fields": tuple(output.keys())},
    )
