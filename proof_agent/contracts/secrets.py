from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from proof_agent.contracts._base import StrictFrozenModel


class SecretPurpose(StrEnum):
    MODEL_CREDENTIAL = "model_credential"
    KNOWLEDGE_CREDENTIAL = "knowledge_credential"
    TOOL_CREDENTIAL = "tool_credential"
    OIDC_CLIENT_SECRET = "oidc_client_secret"
    SESSION_ENVELOPE_KEY = "session_envelope_key"
    INFRASTRUCTURE_CREDENTIAL = "infrastructure_credential"


class ProductionSecretHandle(StrictFrozenModel):
    """Opaque provider-owned secret reference; never contains resolved material."""

    protocol_id: str = Field(min_length=1)
    handle_id: str = Field(min_length=1)
    purpose: SecretPurpose
    version_id: str | None = None


class SecretHandleValidation(StrictFrozenModel):
    handle: ProductionSecretHandle
    resolvable: bool
    provider_version_id: str | None = None
    checked_at: str
    reason_code: str | None = None
