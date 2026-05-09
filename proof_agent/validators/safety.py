from __future__ import annotations

from proof_agent.contracts import ValidationResult, ValidationStatus


SECRET_MARKERS = ("api_key", "access_token", "bearer ", "password", "secret-token")


def validate_no_secret_strings(text: str) -> ValidationResult:
    normalized = text.lower()
    matches = tuple(marker for marker in SECRET_MARKERS if marker in normalized)
    if matches:
        return ValidationResult(
            validator_name="safety",
            status=ValidationStatus.FAILED,
            reason="Output contains secret-like strings.",
            metadata={"matches": matches},
        )
    return ValidationResult(
        validator_name="safety",
        status=ValidationStatus.PASSED,
        reason="Output contains no secret-like strings.",
        metadata={},
    )
