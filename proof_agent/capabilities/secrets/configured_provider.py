from __future__ import annotations

import json
from pathlib import Path

from pydantic import ConfigDict, Field, HttpUrl, TypeAdapter

from proof_agent.contracts._base import StrictFrozenModel


class SecretProviderCompatibilityInput(StrictFrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    protocol_id: str = Field(pattern=r"^hashicorp-vault-2\.0-kv-v2$")
    product: str = Field(pattern=r"^HashiCorp Vault$")
    product_version: str = Field(pattern=r"^2\.0\.[0-9]+$")
    endpoint_origin: HttpUrl
    authentication_method: str = Field(pattern=r"^vault-agent-token-file$")
    contract_evidence: tuple[str, ...] = Field(min_length=1)


def load_secret_provider_compatibility(path: Path) -> SecretProviderCompatibilityInput:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return TypeAdapter(SecretProviderCompatibilityInput).validate_python(payload)
