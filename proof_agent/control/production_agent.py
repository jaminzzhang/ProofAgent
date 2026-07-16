"""Fail-closed admission checks for the sole production Published Agent."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.configuration.importer import build_agent_package_contract_bundle
from proof_agent.configuration.knowledge_release import require_knowledge_release_record
from proof_agent.contracts import (
    ProductionSecretHandle,
    PublishedAgentVersion,
    ResolvedHybridKnowledgeBinding,
    SecretPurpose,
)
from proof_agent.contracts.ports.secret_provider import SecretProvider
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
    secret_provider: SecretProvider,
    checked_at: datetime | None = None,
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
    validation_time = checked_at or datetime.now(UTC)
    checked_at_text = validation_time.astimezone(UTC).isoformat().replace("+00:00", "Z")
    for role, config in model_roles:
        _validate_real_model_role(
            role=role,
            config=config,
            secret_provider=secret_provider,
            checked_at=checked_at_text,
        )


def _validate_real_model_role(
    *,
    role: str,
    config: Any,
    secret_provider: SecretProvider,
    checked_at: str,
) -> None:
    provider = getattr(config, "provider", None)
    model_name = getattr(config, "name", None)
    model_source = getattr(config, "model_source", "inline")
    params = dict(getattr(config, "params", {}))
    if (
        model_source != "inline"
        or provider not in _REAL_MODEL_PROVIDERS
        or not isinstance(model_name, str)
        or not model_name.strip()
    ):
        raise ProductionAgentValidationError(
            f"production Agent role {role} requires an admitted real model"
        )
    forbidden = _FORBIDDEN_PRODUCTION_MODEL_PARAMS.intersection(params)
    if forbidden or getattr(config, "credential_ref", None) is not None:
        raise ProductionAgentValidationError(
            f"production Agent role {role} cannot use environment credentials"
        )
    try:
        raw_handle = params.get("credential_secret_handle")
        handle = ProductionSecretHandle.model_validate(
            dict(raw_handle) if isinstance(raw_handle, Mapping) else raw_handle,
        )
    except (TypeError, ValueError) as exc:
        raise ProductionAgentValidationError(
            f"production Agent role {role} has no valid model Secret Handle"
        ) from exc
    if (
        handle.purpose is not SecretPurpose.MODEL_CREDENTIAL
        or handle.protocol_id != secret_provider.protocol_id
    ):
        raise ProductionAgentValidationError(
            f"production Agent role {role} has an incompatible model Secret Handle"
        )
    try:
        validation = secret_provider.validate(handle, checked_at=checked_at)
    except Exception as exc:
        raise ProductionAgentValidationError(
            f"production Agent role {role} Secret Handle validation failed"
        ) from exc
    if validation.handle != handle or not validation.resolvable:
        raise ProductionAgentValidationError(
            f"production Agent role {role} Secret Handle is not resolvable"
        )


__all__ = [
    "ProductionAgentValidationError",
    "validate_production_agent_candidate",
]
