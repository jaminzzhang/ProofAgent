"""Secret-free contracts for exact-Release Knowledge Query grants."""

from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, ConfigDict, Field, StringConstraints, model_validator

from knowledge_source_service.contracts.base import StrictContract

AuthorityIdentifier = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"),
]
Sha256Digest = Annotated[
    str,
    StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$"),
]
AllowedQueryStrategy = Literal["single_pass", "agentic"]


class KnowledgeQueryGrantContract(StrictContract):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class KnowledgeQueryGrantBudget(KnowledgeQueryGrantContract):
    """Immutable service-side upper bounds for one exact Grant."""

    max_rounds: int = Field(gt=0)
    max_model_calls: int = Field(gt=0)
    max_candidates: int = Field(gt=0)
    max_model_tokens: int = Field(gt=0)
    max_duration_ms: int = Field(gt=0)


class KnowledgeQueryGrantPolicy(KnowledgeQueryGrantContract):
    """Deployment-owned Query authority that a Release caller cannot widen."""

    client_id: AuthorityIdentifier
    allowed_strategies: tuple[AllowedQueryStrategy, ...] = Field(
        min_length=1,
        max_length=2,
    )
    execution_budget: KnowledgeQueryGrantBudget
    effective_access_scope_digest: Sha256Digest

    @model_validator(mode="after")
    def require_distinct_strategies(self) -> Self:
        if len(set(self.allowed_strategies)) != len(self.allowed_strategies):
            raise ValueError("allowed_strategies must be distinct")
        return self


class ProvisionKnowledgeQueryGrantRequest(KnowledgeQueryGrantContract):
    """Per-call exact Release selection; Knowledge Space is intentionally omitted."""

    knowledge_base_release_id: AuthorityIdentifier


class KnowledgeQueryGrant(KnowledgeQueryGrantPolicy):
    """KSS-derived immutable Grant receipt with the authoritative Space identity."""

    schema_version: Literal["knowledge-query-grant.v1"] = "knowledge-query-grant.v1"
    client_grant_id: AuthorityIdentifier
    knowledge_space_id: AuthorityIdentifier
    knowledge_base_release_id: AuthorityIdentifier
    active: Literal[True] = True
    created_at: AwareDatetime


__all__ = [
    "AllowedQueryStrategy",
    "KnowledgeQueryGrant",
    "KnowledgeQueryGrantBudget",
    "KnowledgeQueryGrantPolicy",
    "ProvisionKnowledgeQueryGrantRequest",
]
