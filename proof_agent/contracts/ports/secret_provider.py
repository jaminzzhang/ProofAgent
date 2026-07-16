from __future__ import annotations

from typing import Protocol

from proof_agent.contracts.secrets import ProductionSecretHandle, SecretHandleValidation


class SecretProviderResolutionError(RuntimeError):
    """Sanitized provider failure with no handle locator or secret material."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"secret provider resolution failed: {reason_code}")


class ResolvedSecretMaterial:
    """Short-lived server-only bytes whose representation is always redacted."""

    def __init__(self, *, value: bytes, provider_version_id: str) -> None:
        self._value = bytes(value)
        self.provider_version_id = provider_version_id

    def reveal_for_use(self) -> bytes:
        return bytes(self._value)

    def __repr__(self) -> str:
        return (
            "ResolvedSecretMaterial(value=<redacted>, "
            f"provider_version_id={self.provider_version_id!r})"
        )

    __str__ = __repr__


class SecretProvider(Protocol):
    protocol_id: str

    def validate(self, handle: ProductionSecretHandle, *, checked_at: str) -> SecretHandleValidation:
        ...

    def resolve(self, handle: ProductionSecretHandle) -> ResolvedSecretMaterial: ...
