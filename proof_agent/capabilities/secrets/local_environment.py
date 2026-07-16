from __future__ import annotations

from collections.abc import Mapping

from proof_agent.contracts.ports.secret_provider import (
    ResolvedSecretMaterial,
    SecretProviderResolutionError,
)
from proof_agent.contracts.secrets import ProductionSecretHandle, SecretHandleValidation


class LocalEnvironmentSecretProvider:
    """Explicit development-only environment credential adapter."""

    protocol_id = "local-environment-v1"

    def __init__(self, environment: Mapping[str, str], *, mode: str) -> None:
        if mode != "development":
            raise ValueError("local environment secrets are forbidden outside development mode")
        self._environment = dict(environment)

    def resolve(self, handle: ProductionSecretHandle) -> ResolvedSecretMaterial:
        if handle.protocol_id != self.protocol_id:
            raise SecretProviderResolutionError("protocol_mismatch")
        value = self._environment.get(handle.handle_id)
        if value is None:
            raise SecretProviderResolutionError("secret_handle_unavailable")
        return ResolvedSecretMaterial(value=value.encode("utf-8"), provider_version_id="env")

    def validate(
        self,
        handle: ProductionSecretHandle,
        *,
        checked_at: str,
    ) -> SecretHandleValidation:
        try:
            material = self.resolve(handle)
        except SecretProviderResolutionError as exc:
            return SecretHandleValidation(
                handle=handle,
                resolvable=False,
                checked_at=checked_at,
                reason_code=exc.reason_code,
            )
        return SecretHandleValidation(
            handle=handle,
            resolvable=True,
            provider_version_id=material.provider_version_id,
            checked_at=checked_at,
        )
