from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

from proof_agent.contracts.ports.secret_provider import (
    ResolvedSecretMaterial,
    SecretProviderResolutionError,
)
from proof_agent.contracts.secrets import ProductionSecretHandle, SecretHandleValidation


class VaultHttpTransport(Protocol):
    def get_json(
        self,
        path: str,
        *,
        headers: Mapping[str, str],
        query: Mapping[str, str],
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class VaultKvV2Locator:
    mount: str
    path: str
    field: str

    def __post_init__(self) -> None:
        for name, value in (("mount", self.mount), ("path", self.path), ("field", self.field)):
            if not value or value.strip() != value or ".." in value.split("/"):
                raise ValueError(f"Vault locator {name} is invalid")


class VaultKvV2SecretProvider:
    """Exact HashiCorp Vault 2.0 KV v2 read adapter with no lifecycle writes."""

    protocol_id = "hashicorp-vault-2.0-kv-v2"

    def __init__(
        self,
        transport: VaultHttpTransport,
        *,
        token_supplier: Callable[[], str],
        handles: Mapping[str, VaultKvV2Locator],
    ) -> None:
        self._transport = transport
        self._token_supplier = token_supplier
        self._handles = dict(handles)

    def resolve(self, handle: ProductionSecretHandle) -> ResolvedSecretMaterial:
        if handle.protocol_id != self.protocol_id:
            raise SecretProviderResolutionError("protocol_mismatch")
        locator = self._handles.get(handle.handle_id)
        if locator is None:
            raise SecretProviderResolutionError("secret_handle_unavailable")
        token = self._token_supplier()
        if not token:
            raise SecretProviderResolutionError("provider_identity_unavailable")
        query = {} if handle.version_id is None else {"version": handle.version_id}
        try:
            response = self._transport.get_json(
                f"/v1/{quote(locator.mount, safe='')}/data/{quote(locator.path, safe='/')}",
                headers={"X-Vault-Token": token},
                query=query,
            )
            outer = _mapping(response.get("data"))
            values = _mapping(outer.get("data"))
            metadata = _mapping(outer.get("metadata"))
            version = metadata.get("version")
            destroyed = metadata.get("destroyed")
            deletion_time = metadata.get("deletion_time")
            value = values.get(locator.field)
            if destroyed is True or (isinstance(deletion_time, str) and deletion_time):
                raise SecretProviderResolutionError("secret_handle_revoked")
            if not isinstance(version, int | str) or not isinstance(value, str):
                raise SecretProviderResolutionError("provider_response_invalid")
        except SecretProviderResolutionError:
            raise
        except Exception as exc:
            raise SecretProviderResolutionError("provider_unavailable") from exc
        return ResolvedSecretMaterial(
            value=value.encode("utf-8"),
            provider_version_id=str(version),
        )

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


def _mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SecretProviderResolutionError("provider_response_invalid")
    return value
