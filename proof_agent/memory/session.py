from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from proof_agent.contracts import ValidationResult, ValidationStatus


class SessionMemory:
    def __init__(self, *, deny_fields: set[str] | frozenset[str]) -> None:
        self.deny_fields = set(deny_fields)
        self._data: dict[str, Any] = {}

    def write(self, values: Mapping[str, Any]) -> ValidationResult:
        denied = sorted(set(values).intersection(self.deny_fields))
        if denied:
            return ValidationResult(
                validator_name="memory",
                status=ValidationStatus.FAILED,
                reason=f"Denied memory field(s): {', '.join(denied)}",
                metadata={"denied_fields": tuple(denied)},
            )
        self._data.update(dict(values))
        return ValidationResult(
            validator_name="memory",
            status=ValidationStatus.PASSED,
            reason="Session memory write allowed.",
            metadata={"written_fields": tuple(values.keys())},
        )

    def read(self) -> dict[str, Any]:
        return dict(self._data)

    def clear(self) -> None:
        self._data.clear()
