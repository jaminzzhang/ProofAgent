"""Verify one exact-Release production-local KSS Grant and Query boundary.

This verifier creates or replays only the policy-bounded Query Grant. It does not
create a KSS Release, register a Reference, publish an Agent, or establish a release
Gate.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
import sys
from typing import Any
from uuid import uuid4
import warnings

from proof_agent.capabilities.knowledge.source_service_query_grant_provisioner import (
    KnowledgeSourceServiceQueryGrantProvisioner,
)
from proof_agent.capabilities.persistence.postgres.bundle import PostgresPersistenceBundle
from proof_agent.contracts import (
    ProductionAgentKnowledgeQueryGrantRequest,
    ProductionSecretHandle,
    ResolvedKnowledgeBindingSet,
    ResolvedKnowledgeSourceServiceBinding,
    SecretPurpose,
)
from proof_agent.contracts.ports.secret_provider import SecretProvider
from proof_agent.errors import ProofAgentError


_PLACEHOLDER_RELEASE_ID = "replace-with-exact-kss-release-id"
_VERIFICATION_QUESTION = "What evidence is available for this exact release?"


def verify_exact_release_query_authority(
    *,
    release_id: str,
    expected_runtime_client_id: str,
    binding: ResolvedKnowledgeSourceServiceBinding,
    provisioner: Any,
    runtime: Any,
) -> dict[str, object]:
    """Provision and exercise one exact policy-bounded local Query authority."""

    exact_release_id = _exact_release_id(release_id)
    runtime_client_id = _required_value(
        expected_runtime_client_id,
        label="production-local KSS runtime client identity",
    )
    if binding.knowledge_base_release_id != exact_release_id:
        raise RuntimeError("production-local binding changed the exact KSS Release")

    grant = provisioner.provision_query_grant(
        ProductionAgentKnowledgeQueryGrantRequest(
            knowledge_base_release_id=exact_release_id,
        )
    )
    if grant.client_id != runtime_client_id:
        raise RuntimeError("Query Grant changed the expected runtime client identity")
    if grant.knowledge_base_release_id != exact_release_id:
        raise RuntimeError("Query Grant changed the exact KSS Release")
    if "single_pass" not in grant.allowed_strategies:
        raise RuntimeError("Query Grant policy does not allow verifier strategy")

    dependencies = runtime.bind_for_run(ResolvedKnowledgeBindingSet(bindings=(binding,)))
    request = dependencies.query_factory.build(
        run_id=f"production-local-query-authority-{uuid4()}",
        retrieval_action_id="verify-exact-release-query-authority",
        semantic_attempt="1",
        question=_VERIFICATION_QUESTION,
        strategy="single_pass",
    )
    if request.knowledge_base_release_id != exact_release_id:
        raise RuntimeError("runtime query factory changed the exact KSS Release")
    if request.execution_budget != grant.execution_budget:
        raise RuntimeError("runtime Query budget drifted from the Query Grant policy")

    result = dependencies.service.query(request)
    if result.retrieval_lineage.knowledge_base_release_id != exact_release_id:
        raise RuntimeError("Query result changed the exact Release")
    if result.retrieval_lineage.access_scope_digest != grant.effective_access_scope_digest:
        raise RuntimeError("Query result changed the effective access scope")
    if result.execution_summary.strategy != request.strategy:
        raise RuntimeError("Query result changed the verifier strategy")
    _require_budget_within_grant(
        usage=result.execution_summary.budget_usage,
        grant_budget=grant.execution_budget,
    )

    candidate_count = sum(len(group.candidate_evidence) for group in result.evidence_groups)
    return {
        "schema_version": "production-local-kss-query-authority-verification.v1",
        "evidence_class": "local_production_validation_only",
        "knowledge_base_release_id": exact_release_id,
        "knowledge_space_id": grant.knowledge_space_id,
        "runtime_client_id": grant.client_id,
        "client_grant_id": grant.client_grant_id,
        "knowledge_query_id": result.knowledge_query_id,
        "strategy": result.execution_summary.strategy,
        "candidate_count": candidate_count,
        "budget_usage": result.execution_summary.budget_usage.model_dump(mode="json"),
    }


def main() -> None:
    from authlib.deprecate import (  # type: ignore[import-untyped]
        AuthlibDeprecationWarning,
    )

    warnings.simplefilter("ignore", AuthlibDeprecationWarning)
    from proof_agent.bootstrap.application_services import (
        compose_application_persistence,
        compose_production_egress_client,
        compose_production_vault_secret_provider,
    )
    from proof_agent.bootstrap.knowledge_candidate_runtime import (
        compose_production_knowledge_candidate_runtime,
    )

    values = os.environ
    release_id = _exact_release_id(values.get("PROOF_AGENT_KSS_RELEASE_ID", ""))
    runtime_client_id = _required(
        values,
        "PROOF_AGENT_KSS_RUNTIME_CLIENT_ID",
    )
    persistence = compose_application_persistence(environment=values)
    if not isinstance(persistence, PostgresPersistenceBundle):
        persistence.close()
        raise RuntimeError("production-local Query verification requires PostgreSQL")
    try:
        guarded = compose_production_egress_client(persistence)
        secret_provider = compose_production_vault_secret_provider(
            guarded,
            environment=values,
        )
        runtime = compose_production_knowledge_candidate_runtime(
            values,
            http_client=guarded,
            secret_provider=secret_provider,
        )
        binding = _runtime_binding(
            values,
            secret_provider=secret_provider,
            release_id=release_id,
        )
        provisioner = KnowledgeSourceServiceQueryGrantProvisioner(
            endpoint=_required(values, "PROOF_AGENT_KSS_ENDPOINT"),
            http_client=guarded,
            authorization_header_factory=lambda: _operator_authorization(
                secret_provider,
                _required(values, "PROOF_AGENT_KSS_OPERATOR_SECRET_HANDLE"),
            ),
            timeout_seconds=float(values.get("PROOF_AGENT_KSS_TIMEOUT_SECONDS", "10")),
        )
        result = verify_exact_release_query_authority(
            release_id=release_id,
            expected_runtime_client_id=runtime_client_id,
            binding=binding,
            provisioner=provisioner,
            runtime=runtime,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
    finally:
        persistence.close()


def cli() -> int:
    """Run the verifier without exposing exception or upstream response details."""

    try:
        main()
    except ProofAgentError as error:
        error_code = error.code
    except ValueError:
        error_code = "invalid_verification_input"
    except RuntimeError:
        error_code = "query_authority_verification_failed"
    else:
        return 0
    print(
        json.dumps(
            {
                "schema_version": "production-local-kss-query-authority-failure.v1",
                "status": "failed",
                "error_code": error_code,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        file=sys.stderr,
        flush=True,
    )
    return 1


def _runtime_binding(
    values: Mapping[str, str],
    *,
    secret_provider: SecretProvider,
    release_id: str,
) -> ResolvedKnowledgeSourceServiceBinding:
    return ResolvedKnowledgeSourceServiceBinding(
        binding_id=_required(values, "PROOF_AGENT_KSS_BINDING_ID"),
        knowledge_base_release_id=release_id,
        client_credential_ref=ProductionSecretHandle(
            protocol_id=secret_provider.protocol_id,
            handle_id=_required(values, "PROOF_AGENT_KSS_CLIENT_SECRET_HANDLE"),
            purpose=SecretPurpose.KNOWLEDGE_CREDENTIAL,
            version_id=_required(
                values,
                "PROOF_AGENT_KSS_CLIENT_SECRET_VERSION_ID",
            ),
        ),
        admission_scorer_id=_required(
            values,
            "PROOF_AGENT_KSS_ADMISSION_SCORER_ID",
        ),
        admission_scorer_revision=_required(
            values,
            "PROOF_AGENT_KSS_ADMISSION_SCORER_REVISION",
        ),
    )


def _operator_authorization(provider: SecretProvider, handle_id: str) -> str:
    material = provider.resolve(
        ProductionSecretHandle(
            protocol_id=provider.protocol_id,
            handle_id=handle_id,
            purpose=SecretPurpose.KNOWLEDGE_CREDENTIAL,
        )
    ).reveal_for_use()
    try:
        token = material.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("KSS operator credential is invalid") from error
    if (
        not token
        or len(material) > 16 * 1024
        or token != token.strip()
        or any(character.isspace() for character in token)
    ):
        raise ValueError("KSS operator credential is invalid")
    return f"Bearer {token}"


def _require_budget_within_grant(*, usage: Any, grant_budget: Any) -> None:
    limits = {
        "rounds": "max_rounds",
        "model_calls": "max_model_calls",
        "candidates": "max_candidates",
        "model_tokens": "max_model_tokens",
        "duration_ms": "max_duration_ms",
    }
    if any(
        getattr(usage, usage_field) > getattr(grant_budget, limit_field)
        for usage_field, limit_field in limits.items()
    ):
        raise RuntimeError("Query result exceeded the Query Grant budget")


def _exact_release_id(value: str) -> str:
    normalized = value.strip()
    if not normalized or normalized == _PLACEHOLDER_RELEASE_ID:
        raise ValueError("an existing exact KSS Release is required for verification")
    return normalized


def _required(values: Mapping[str, str], key: str) -> str:
    return _required_value(values.get(key, ""), label=key)


def _required_value(value: str, *, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} is required")
    return normalized


if __name__ == "__main__":
    raise SystemExit(cli())
