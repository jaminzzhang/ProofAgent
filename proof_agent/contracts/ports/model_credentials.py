from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ModelCredentialResolutionError(RuntimeError):
    """Sanitized failure that never includes credential material or ciphertext."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__("model credential cannot be resolved")


class ResolvedModelCredential:
    """Short-lived server-only model credential bytes with redacted representation."""

    def __init__(self, *, value: bytes) -> None:
        self._value = bytes(value)

    def reveal_for_use(self) -> bytes:
        return bytes(self._value)

    def __repr__(self) -> str:
        return "ResolvedModelCredential(value=<redacted>)"

    __str__ = __repr__


@dataclass(frozen=True)
class ModelCredentialValidation:
    connection_id: str
    resolvable: bool
    reason_code: str | None = None


class ModelCredentialResolver(Protocol):
    def validate(self, connection_id: str) -> ModelCredentialValidation: ...

    def resolve(self, connection_id: str) -> ResolvedModelCredential: ...


__all__ = [
    "ModelCredentialResolutionError",
    "ModelCredentialResolver",
    "ModelCredentialValidation",
    "ResolvedModelCredential",
]
