"""Server-owned development grants; never fields of an editable Agent manifest."""

from hashlib import sha256
from typing import Literal

from pydantic import Field

from proof_agent.contracts._base import StrictFrozenModel
from proof_agent.contracts.egress import ExactHttpsOrigin
from proof_agent.contracts.external_knowledge import ExternalKnowledgeBinding


class KnowledgeConnectionAuthorization(StrictFrozenModel):
    binding_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    origin: ExactHttpsOrigin
    address_mode: Literal["public_dns", "local_proxy_dns"]
    authorized_by: str = Field(min_length=1)
    authorized_at: str = Field(min_length=1)


def binding_digest(binding: ExternalKnowledgeBinding) -> str:
    return sha256(binding.model_dump_json().encode()).hexdigest()
