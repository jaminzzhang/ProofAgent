from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from proof_agent.contracts import ValidationResult


def validate_final_output_schema(output: Mapping[str, Any]) -> ValidationResult:
    required = {"outcome", "message"}
    missing = sorted(required.difference(output))
    citations = output.get("citations", ())
    citations_valid = isinstance(citations, list | tuple)
    if missing or not citations_valid:
        return ValidationResult(
            validator_name="schema",
            status="failed",
            reason="Final output schema is invalid.",
            metadata={"missing": tuple(missing), "citations_valid": citations_valid},
        )
    return ValidationResult(
        validator_name="schema",
        status="passed",
        reason="Final output schema is valid.",
        metadata={"fields": tuple(output.keys())},
    )
