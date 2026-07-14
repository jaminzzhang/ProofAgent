from __future__ import annotations

from typing import Any

from pydantic import ConfigDict, Field, StrictBool, field_validator, model_validator

from proof_agent.contracts._base import FrozenModel


_SCOPE_FIELDS = ("institutions", "regions", "channels", "roles", "business_lines")


class InstitutionAuthorizationContext(FrozenModel):
    """Trusted run-scoped authorization for institution insurance knowledge."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    institutions: tuple[str, ...] = Field(default_factory=tuple)
    regions: tuple[str, ...] = Field(default_factory=tuple)
    channels: tuple[str, ...] = Field(default_factory=tuple)
    roles: tuple[str, ...] = Field(default_factory=tuple)
    business_lines: tuple[str, ...] = Field(default_factory=tuple)
    public_only: StrictBool = True

    @model_validator(mode="before")
    @classmethod
    def derive_public_only(cls, value: Any) -> Any:
        if not isinstance(value, dict) or "public_only" in value:
            return value
        if any(value.get(field) for field in _SCOPE_FIELDS):
            return {**value, "public_only": False}
        return value

    @field_validator(*_SCOPE_FIELDS, mode="before")
    @classmethod
    def canonicalize_scope(cls, value: Any) -> Any:
        if value is None:
            return value
        if not isinstance(value, (list, tuple)):
            raise ValueError("scope values must be an array or tuple")
        canonical: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                raise ValueError("scope values must be strings")
            normalized = item.strip()
            if not normalized:
                raise ValueError("scope values must be nonblank")
            canonical.add(normalized)
        return tuple(sorted(canonical))

    @model_validator(mode="after")
    def validate_public_boundary(self) -> InstitutionAuthorizationContext:
        has_scope = any(getattr(self, field) for field in _SCOPE_FIELDS)
        if self.public_only and has_scope:
            raise ValueError("public-only authorization cannot admit institution scope values")
        if not self.public_only and not has_scope:
            raise ValueError("non-public authorization requires at least one admitted scope value")
        return self

    def trace_safe_summary(self) -> dict[str, Any]:
        """Return canonical admitted values and counts without identity or credentials."""

        return {
            "public_only": self.public_only,
            **{
                field: {
                    "values": list(getattr(self, field)),
                    "count": len(getattr(self, field)),
                }
                for field in _SCOPE_FIELDS
            },
        }
