"""External configuration and candidates, without provider-owned admission authority."""

from hashlib import sha256
from typing import Annotated, Any, Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, StrictStr, field_validator, model_validator

from proof_agent.contracts._base import StrictFrozenModel
from proof_agent.contracts.secrets import ProductionSecretHandle, SecretPurpose
from proof_agent.contracts.structured_evidence import StructuredEvidenceRecord, parse_structured_evidence


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


class AgentsetRetrievalSettings(StrictFrozenModel):
    search_method: Literal["semantic", "keyword"] = "semantic"
    top_k: int = Field(default=3, strict=True, ge=1, le=20)
    score_threshold: Score = 0.2
    rerank: bool = Field(default=True, strict=True)
    rerank_model: Literal[
        "zeroentropy:zerank-2", "zeroentropy:zerank-1", "zeroentropy:zerank-1-small",
        "cohere:rerank-v4.0-pro", "cohere:rerank-v4.0-fast", "cohere:rerank-v3.5",
        "cohere:rerank-english-v3.0", "cohere:rerank-multilingual-v3.0",
    ] = "zeroentropy:zerank-2"


class ExternalKnowledgeBinding(StrictFrozenModel):
    schema_version: Literal["external-knowledge-binding.v1"] = "external-knowledge-binding.v1"
    binding_kind: Literal["external_knowledge"] = "external_knowledge"
    binding_id: Identifier
    provider: Literal["dify", "agentset"]
    endpoint: StrictStr = Field(max_length=2048)
    dataset_id: DatasetIdentifier | None = Field(default=None, exclude_if=lambda value: value is None)
    namespace_id: Annotated[StrictStr, Field(max_length=128, pattern=r"^ns_[A-Za-z0-9_-]+$")] | None = Field(default=None, exclude_if=lambda value: value is None)
    tenant_id: Annotated[StrictStr, Field(pattern=r"^[A-Za-z0-9]{1,64}$")] | None = Field(default=None, exclude_if=lambda value: value is None)
    content_format: Literal["text", "structured_json"] = Field(default="text", exclude_if=lambda value: value == "text")
    credential_ref: ProductionSecretHandle
    retrieval: DifyRetrievalSettings | AgentsetRetrievalSettings = Field(default_factory=DifyRetrievalSettings)
    consistency: Literal["mutable_remote"] = "mutable_remote"
    failure_mode: Literal["required"] = "required"
    admission_policy: Literal["external-relevance-and-provenance.v1"] = (
        "external-relevance-and-provenance.v1"
    )

    @model_validator(mode="before")
    @classmethod
    def select_provider_settings(cls, value: Any) -> Any:
        if isinstance(value, dict) and value.get("provider") in {"dify", "agentset"}:
            value = dict(value)
            settings = AgentsetRetrievalSettings if value["provider"] == "agentset" else DifyRetrievalSettings
            value["retrieval"] = settings.model_validate(value.get("retrieval", {}))
        return value

    @property
    def source_id(self) -> str:
        identity = self.dataset_id if self.provider == "dify" else self.namespace_id
        assert identity is not None
        return identity

    @model_validator(mode="after")
    def validate_source_scope(self) -> Self:
        if self.provider == "dify":
            if not self.dataset_id or self.namespace_id is not None or self.tenant_id is not None:
                raise ValueError("Dify requires only a Dataset identity")
            if not isinstance(self.retrieval, DifyRetrievalSettings):
                raise ValueError("Dify requires Dify retrieval settings")
        elif not self.namespace_id or self.dataset_id is not None or not isinstance(self.retrieval, AgentsetRetrievalSettings):
            raise ValueError("Agentset requires a Namespace and Agentset retrieval settings")
        return self

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
    document_id: Identifier | None = None
    chunk_id: Annotated[StrictStr, Field(min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_.:#-]+$")]
    content: StrictStr = Field(min_length=1, max_length=100_000)
    content_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    native_score: Score
    available: bool = Field(strict=True)
    structured_data: StructuredEvidenceRecord | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def verify_content(self) -> Self:
        if (
            not self.content.strip()
            or sha256(self.content.encode()).hexdigest() != self.content_sha256
        ):
            raise ValueError("External candidate content identity is invalid")
        if self.structured_data is not None and parse_structured_evidence(self.content) != self.structured_data:
            raise ValueError("External structured record differs from its source content")
        return self


class ExternalKnowledgeResult(StrictFrozenModel):
    binding_id: Identifier
    query: StrictStr
    candidates: tuple[ExternalKnowledgeCandidate, ...] = Field(max_length=100)
