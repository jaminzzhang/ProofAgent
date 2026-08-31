"""Application-only provisioning of immutable exact-Release Query grants."""

from typing import Protocol

from knowledge_source_service.contracts.access_control import (
    AllowedQueryStrategy,
    KnowledgeQueryGrant,
    KnowledgeQueryGrantPolicy,
    ProvisionKnowledgeQueryGrantRequest,
)
from knowledge_source_service.domain.identities import content_identifier, sha256_json


class KnowledgeQueryGrantRegistry(Protocol):
    def grant_release_query(
        self,
        *,
        client_grant_id: str,
        client_id: str,
        knowledge_base_release_id: str,
        allowed_strategies: tuple[AllowedQueryStrategy, ...],
        max_rounds: int,
        max_model_calls: int,
        max_candidates: int,
        max_model_tokens: int,
        max_duration_ms: int,
        effective_access_scope_digest: str,
    ) -> KnowledgeQueryGrant: ...


class KnowledgeQueryGrantProvisioningError(RuntimeError):
    """The Grant authority returned facts that do not match the trusted request."""


class KnowledgeQueryGrantConflict(RuntimeError):
    """The requested Grant conflicts with immutable service authority."""


class KnowledgeQueryGrantProvisioningApplication:
    """Derive one immutable Grant identity and reject any receipt widening."""

    def __init__(
        self,
        *,
        registry: KnowledgeQueryGrantRegistry,
        policy: KnowledgeQueryGrantPolicy,
    ) -> None:
        self._registry = registry
        self._policy = KnowledgeQueryGrantPolicy.model_validate(policy.model_dump(mode="python"))

    def provision(
        self,
        request: ProvisionKnowledgeQueryGrantRequest,
    ) -> KnowledgeQueryGrant:
        validated = ProvisionKnowledgeQueryGrantRequest.model_validate(
            request.model_dump(mode="python")
        )
        policy = self._policy
        client_grant_id = content_identifier(
            "query-grant",
            sha256_json(
                {
                    "policy": policy.model_dump(mode="json"),
                    "request": validated.model_dump(mode="json"),
                }
            ),
        )
        budget = policy.execution_budget
        raw = self._registry.grant_release_query(
            client_grant_id=client_grant_id,
            client_id=policy.client_id,
            knowledge_base_release_id=validated.knowledge_base_release_id,
            allowed_strategies=policy.allowed_strategies,
            max_rounds=budget.max_rounds,
            max_model_calls=budget.max_model_calls,
            max_candidates=budget.max_candidates,
            max_model_tokens=budget.max_model_tokens,
            max_duration_ms=budget.max_duration_ms,
            effective_access_scope_digest=policy.effective_access_scope_digest,
        )
        try:
            grant = KnowledgeQueryGrant.model_validate(raw.model_dump(mode="python"))
        except Exception as exc:
            raise KnowledgeQueryGrantProvisioningError("query_grant_integrity_unavailable") from exc
        if (
            grant.client_grant_id != client_grant_id
            or grant.client_id != policy.client_id
            or grant.knowledge_base_release_id != validated.knowledge_base_release_id
            or grant.allowed_strategies != policy.allowed_strategies
            or grant.execution_budget != policy.execution_budget
            or grant.effective_access_scope_digest != policy.effective_access_scope_digest
            or grant.active is not True
        ):
            raise KnowledgeQueryGrantProvisioningError("query_grant_integrity_unavailable")
        return grant


__all__ = [
    "KnowledgeQueryGrantConflict",
    "KnowledgeQueryGrantProvisioningApplication",
    "KnowledgeQueryGrantProvisioningError",
    "KnowledgeQueryGrantRegistry",
]
