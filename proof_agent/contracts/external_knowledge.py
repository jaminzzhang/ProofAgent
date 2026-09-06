"""External configuration and candidates, without provider-owned admission authority."""

from hashlib import sha256
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, StrictStr, field_validator, model_validator

from proof_agent.contracts._base import StrictFrozenModel
from proof_agent.contracts.secrets import ProductionSecretHandle, SecretPurpose


Identifier = Annotated[StrictStr, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]
DatasetIdentifier = Annotated[
    StrictStr,
    Field(pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"),
]
Score = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]


class DifyRetrievalSettings(StrictFrozenModel):
    search_method: Literal["semantic_search", "full_text_search", "keyword_search"] = (
        "semantic_search"
    )
    top_k: int = Field(default=3, strict=True, ge=1, le=20)
    score_threshold: Score = 0.2


class ExternalKnowledgeBinding(StrictFrozenModel):
    schema_version: Literal["external-knowledge-binding.v1"] = "external-knowledge-binding.v1"
    binding_kind: Literal["external_knowledge"] = "external_knowledge"
    binding_id: Identifier
    provider: Literal["dify"]
    endpoint: StrictStr = Field(max_length=2048)
    dataset_id: DatasetIdentifier
    credential_ref: ProductionSecretHandle
    retrieval: DifyRetrievalSettings = Field(default_factory=DifyRetrievalSettings)
    consistency: Literal["mutable_remote"] = "mutable_remote"
    failure_mode: Literal["required"] = "required"
    admission_policy: Literal["external-relevance-and-provenance.v1"] = (
        "external-relevance-and-provenance.v1"
    )

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        parts = urlsplit(value)
        if (
            value != value.strip()
            or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value)
            or parts.scheme != "https"
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
            or "\\" in value
            or "%" in value
            or any(p in {".", ".."} for p in parts.path.split("/"))
        ):
            raise ValueError(
                "External Knowledge endpoint must be a clean HTTPS Service API base URL"
            )
        _ = parts.port
        return value.rstrip("/")

    @model_validator(mode="after")
    def validate_credential(self) -> Self:
        if self.credential_ref.purpose is not SecretPurpose.KNOWLEDGE_CREDENTIAL:
            raise ValueError("External Knowledge requires a Knowledge credential reference")
        if not self.credential_ref.version_id or self.credential_ref.protocol_id not in {
            "local-environment-v1",
            "hashicorp-vault-2.0-kv-v2",
        }:
            raise ValueError(
                "External Knowledge requires a supported versioned credential reference"
            )
        return self


class ExternalKnowledgeCandidate(StrictFrozenModel):
    document_id: Identifier
    chunk_id: Identifier
    content: StrictStr = Field(min_length=1, max_length=100_000)
    content_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    native_score: Score
    available: bool = Field(strict=True)

    @model_validator(mode="after")
    def verify_content(self) -> Self:
        if (
            not self.content.strip()
            or sha256(self.content.encode()).hexdigest() != self.content_sha256
        ):
            raise ValueError("External candidate content identity is invalid")
        return self


class ExternalKnowledgeResult(StrictFrozenModel):
    binding_id: Identifier
    query: StrictStr
    candidates: tuple[ExternalKnowledgeCandidate, ...] = Field(max_length=100)
