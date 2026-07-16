from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from pydantic import Field, field_serializer, field_validator

from proof_agent.contracts._base import FrozenDict, StrictFrozenModel, freeze_value


class OidcPrincipal(StrictFrozenModel):
    """Trusted, token-free identity facts verified by the backend OIDC client."""

    subject: str = Field(min_length=1)
    issuer: str = Field(min_length=1)
    audience: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    email: str | None = None
    trusted_groups: tuple[str, ...] = Field(default_factory=tuple)
    trusted_roles: tuple[str, ...] = Field(default_factory=tuple)
    trusted_claims: Mapping[str, tuple[str, ...]] = Field(default_factory=FrozenDict)
    authenticated_at: str
    claims_verified_at: str

    @field_validator("trusted_claims", mode="after")
    @classmethod
    def freeze_trusted_claims(cls, value: Any) -> Mapping[str, tuple[str, ...]]:
        return cast(Mapping[str, tuple[str, ...]], freeze_value(value))

    @field_serializer("trusted_claims")
    def serialize_trusted_claims(
        self, value: Mapping[str, tuple[str, ...]]
    ) -> dict[str, list[str]]:
        return {str(key): list(items) for key, items in value.items()}


class OperatorSessionProjection(StrictFrozenModel):
    """Browser-safe session projection; provider and session tokens are excluded."""

    session_id: str = Field(min_length=1)
    principal: OidcPrincipal
    absolute_expires_at: str
    idle_expires_at: str
    claims_refresh_due_at: str
    csrf_token: str = Field(min_length=32)
    effective_permissions: tuple[str, ...] = Field(default_factory=tuple)


class OidcLoginAttemptRecord(StrictFrozenModel):
    """One-time encrypted server-side OIDC authorization transaction."""

    state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    nonce_envelope: bytes
    pkce_verifier_envelope: bytes
    envelope_key_version: str = Field(min_length=1)
    redirect_uri: str = Field(min_length=1)
    created_at: str
    expires_at: str
    consumed_at: str | None = None


class OperatorSessionRecord(StrictFrozenModel):
    """Server-only OIDC session record; browser/provider tokens stay opaque."""

    session_id: str
    session_version: int = Field(ge=1)
    session_token_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    principal: OidcPrincipal
    provider_token_envelope: bytes
    envelope_key_version: str = Field(min_length=1)
    permission_mapping_version_id: str | None = None
    permission_epoch: int = Field(ge=0)
    created_at: str
    absolute_expires_at: str
    idle_expires_at: str
    claims_verified_at: str
    revoked_at: str | None = None
