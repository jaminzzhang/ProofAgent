"""Fail-closed admission checks for the sole production Published Agent."""

from __future__ import annotations

from typing import Any

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.configuration.importer import build_agent_package_contract_bundle
from proof_agent.configuration.knowledge_release import require_knowledge_release_record
from proof_agent.contracts import (
    PostgresEncryptedModelCredentialReference,
    PublishedAgentVersion,
    ResolvedHybridKnowledgeBinding,
    SharedModelConnectionLifecycleState,
)
from proof_agent.contracts.ports.model_credentials import ModelCredentialResolver
from proof_agent.contracts.ports.shared_assets import ModelConnectionReader
from proof_agent.delivery.published_agents import PublishedAgent


_REAL_MODEL_PROVIDERS = frozenset({"deepseek", "openai", "openai_compatible"})
_FORBIDDEN_PRODUCTION_MODEL_PARAMS = frozenset(
    {
        "api_key_env",
        "base_url_env",
        "organization_env",
        "project_env",
    }
)


class ProductionAgentValidationError(RuntimeError):
    """The active Agent cannot be admitted into a production process."""


def validate_production_agent_candidate(
    *,
    agent: PublishedAgent,
    version: PublishedAgentVersion,
    configuration_store: ModelConnectionReader,
    model_credential_resolver: ModelCredentialResolver,
) -> None:
    """Validate identity, immutable release, Hybrid binding and model authority."""

    if (
        agent.source != "postgres_publication"
        or agent.agent_id != version.agent_id
        or agent.agent_version_id != version.version_id
        or agent.source_draft_id != version.source_draft_id
        or agent.validation_run_id != version.validation_run_id
    ):
        raise ProductionAgentValidationError(
            "production Agent materialization does not match its PostgreSQL version"
        )
    try:
        materialized_bundle = build_agent_package_contract_bundle(
            agent.manifest_path,
            require_writable_artifacts=False,
        )
    except Exception as exc:
        raise ProductionAgentValidationError(
            "production Agent package cannot be reconstructed exactly"
        ) from exc
    if materialized_bundle != version.contract_bundle:
        raise ProductionAgentValidationError(
            "production Agent package differs from its immutable PostgreSQL contract"
        )
    try:
        manifest = load_agent_manifest(
            agent.manifest_path,
            require_writable_artifacts=False,
        )
    except Exception as exc:
        raise ProductionAgentValidationError(
            "production Agent manifest is invalid"
        ) from exc
    if manifest.name != version.agent_id or manifest.workflow.template != "react_enterprise_qa_v3":
        raise ProductionAgentValidationError(
            "production Agent identity or workflow is outside the active product boundary"
        )
    if manifest.package_knowledge_sources:
        raise ProductionAgentValidationError(
            "production Agent cannot depend on package-local Knowledge Sources"
        )
    if manifest.customer is not None:
        raise ProductionAgentValidationError(
            "production Agent cannot expose the removed customer-facing surface"
        )
    if manifest.capabilities.tools.enabled:
        raise ProductionAgentValidationError(
            "initial production Agent cannot enable stateful or package-local tools"
        )
    if manifest.capabilities.memory.enabled:
        raise ProductionAgentValidationError(
            "initial production Agent cannot enable non-authoritative runtime memory"
        )

    bindings = version.resolved_knowledge_bindings
    if bindings is None or len(bindings.bindings) != 1:
        raise ProductionAgentValidationError(
            "initial production Agent requires exactly one frozen Hybrid Knowledge binding"
        )
    if agent.resolved_knowledge_bindings != bindings:
        raise ProductionAgentValidationError(
            "materialized production Agent has stale Knowledge bindings"
        )
    if not all(
        isinstance(binding, ResolvedHybridKnowledgeBinding)
        for binding in bindings.bindings
    ):
        raise ProductionAgentValidationError(
            "production Agent permits only published Hybrid Knowledge bindings"
        )
    if not any(binding.failure_mode == "required" for binding in bindings.bindings):
        raise ProductionAgentValidationError(
            "production Agent requires at least one fail-closed Knowledge binding"
        )
    manifest_bindings = {binding.binding_id: binding for binding in manifest.knowledge_bindings}
    if set(manifest_bindings) != {binding.binding_id for binding in bindings.bindings}:
        raise ProductionAgentValidationError(
            "production Agent manifest and frozen Knowledge bindings diverge"
        )
    for binding in bindings.bindings:
        assert isinstance(binding, ResolvedHybridKnowledgeBinding)
        configured = manifest_bindings[binding.binding_id]
        if (
            configured.source_ref.scope != "shared"
            or configured.source_ref.source_id != binding.source_id
            or configured.retrieval_profile_revision_id
            != binding.retrieval_profile_revision_id
            or configured.failure_mode != binding.failure_mode
        ):
            raise ProductionAgentValidationError(
                "production Agent Hybrid binding does not match its manifest contract"
            )

    release_record = version.knowledge_release_record
    if release_record is None:
        raise ProductionAgentValidationError(
            "production Hybrid Agent requires a Phase F Knowledge Release Record"
        )
    try:
        require_knowledge_release_record(
            record=release_record,
            contract_bundle=version.contract_bundle,
            resolved_knowledge_bindings=bindings,
        )
    except Exception as exc:
        raise ProductionAgentValidationError(
            "production Agent Knowledge Release Record is invalid"
        ) from exc

    model_roles: list[tuple[str, Any]] = [("final_answer", manifest.model)]
    if manifest.react is None:
        raise ProductionAgentValidationError(
            "production Agent requires the Controlled ReAct model planner"
        )
    model_roles.append(("react_planner", manifest.react.planner))
    if manifest.retrieval.planner_model is not None:
        model_roles.append(("retrieval_planner", manifest.retrieval.planner_model))
    if manifest.retrieval.evaluator_model is not None:
        model_roles.append(("retrieval_evaluator", manifest.retrieval.evaluator_model))
    review = manifest.review
    if review is None or review.subagent is None or not review.subagent.fail_closed:
        raise ProductionAgentValidationError(
            "production Agent requires a fail-closed review model"
        )
    model_roles.append(("harness_review", review.subagent))
    for role, config in model_roles:
        _validate_real_model_role(
            role=role,
            config=config,
            configuration_store=configuration_store,
            model_credential_resolver=model_credential_resolver,
        )


def _validate_real_model_role(
    *,
    role: str,
    config: Any,
    configuration_store: ModelConnectionReader,
    model_credential_resolver: ModelCredentialResolver,
) -> None:
    model_source = getattr(config, "model_source", "inline")
    params = dict(getattr(config, "params", {}))
    connection_id = getattr(config, "connection_id", None)
    if model_source != "shared" or not isinstance(connection_id, str) or not connection_id:
        raise ProductionAgentValidationError(
            f"production Agent role {role} requires a Shared Model Connection"
        )
    forbidden = _FORBIDDEN_PRODUCTION_MODEL_PARAMS.intersection(params)
    if (
        forbidden
        or "credential_secret_handle" in params
        or getattr(config, "credential_ref", None) is not None
    ):
        raise ProductionAgentValidationError(
            f"production Agent role {role} cannot declare inline credentials"
        )
    connection = configuration_store.get_model_connection(connection_id)
    if connection is None:
        raise ProductionAgentValidationError(
            f"production Agent role {role} references a missing Model Connection"
        )
    if (
        connection.provider not in _REAL_MODEL_PROVIDERS
        or not connection.model_identifier.strip()
        or connection.lifecycle_state is not SharedModelConnectionLifecycleState.ACTIVE
        or not isinstance(
            connection.credential_ref,
            PostgresEncryptedModelCredentialReference,
        )
    ):
        raise ProductionAgentValidationError(
            f"production Agent role {role} has an inadmissible Model Connection"
        )
    try:
        validation = model_credential_resolver.validate(connection_id)
    except Exception as exc:
        raise ProductionAgentValidationError(
            f"production Agent role {role} credential validation failed"
        ) from exc
    if not validation.resolvable:
        raise ProductionAgentValidationError(
            f"production Agent role {role} credential is not resolvable"
        )


__all__ = [
    "ProductionAgentValidationError",
    "validate_production_agent_candidate",
]
