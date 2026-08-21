"""Trace-safe publication configuration projection for the production Agent Draft."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]

from proof_agent.contracts import (
    DraftKnowledgeReleaseBindingCandidate,
    DraftAgent,
    PostgresEncryptedModelCredentialReference,
    SharedModelConnectionLifecycleState,
)
from proof_agent.contracts.knowledge_service_management import (
    KnowledgeServiceManagementWorkspace,
)
from proof_agent.contracts.ports.shared_assets import ModelConnectionReader


_PRODUCTION_WORKFLOW_TEMPLATE = "react_enterprise_qa_v3"
_PRODUCTION_WORKFLOW_DESCRIPTOR_VERSION = "react_enterprise_qa.v3"
_REAL_MODEL_PROVIDERS = frozenset({"deepseek", "openai", "openai_compatible"})
_FORBIDDEN_PRODUCTION_MODEL_PARAMS = frozenset(
    {
        "api_key_env",
        "base_url_env",
        "organization_env",
        "project_env",
    }
)
_PHASE_F_EVIDENCE_REQUIREMENTS = (
    "shadow",
    "capacity",
    "acceptance",
    "recovery",
)


@dataclass(frozen=True)
class ProductionAgentPublicationConfigurationBlocker:
    """Stable reason why one Draft authoring check does not pass."""

    code: str
    module_id: str
    message: str


@dataclass(frozen=True)
class ProductionAgentPublicationModelRole:
    """Secret-free live Shared Model Connection facts for one runtime role."""

    role: str
    connection_id: str | None
    provider: str | None
    model_identifier: str | None
    lifecycle_state: str | None
    configuration_state: Literal["ready", "blocked"]


@dataclass(frozen=True)
class ProductionAgentPublicationConfiguration:
    """Server-authoritative authoring snapshot without a publication claim."""

    draft_revision: int
    authoring_configuration_state: Literal["ready", "blocked"]
    formal_publication_state: Literal["workspace_draft_not_bound"]
    can_publish_from_dashboard: Literal[False]
    workflow_template: str | None
    workflow_template_descriptor_version: str | None
    knowledge_release_candidate: DraftKnowledgeReleaseBindingCandidate | None
    knowledge_release_queryable: bool
    model_roles: tuple[ProductionAgentPublicationModelRole, ...]
    configuration_blockers: tuple[ProductionAgentPublicationConfigurationBlocker, ...]
    phase_f_evidence_requirements: tuple[str, ...]
    online_smoke_required: Literal[True]
    activation_mode: Literal["postgres_atomic_cas"]


class ProductionAgentPublicationConfigurationProjector:
    """Project one Draft against live model and KSS catalogs without mutating state."""

    def __init__(self, *, configuration_store: ModelConnectionReader) -> None:
        self._configuration_store = configuration_store

    def project(
        self,
        *,
        draft: DraftAgent,
        revision: int,
        catalog: KnowledgeServiceManagementWorkspace,
    ) -> ProductionAgentPublicationConfiguration:
        blockers: list[ProductionAgentPublicationConfigurationBlocker] = []
        raw = _agent_mapping(draft, blockers)
        if _optional_text(raw.get("name")) != draft.agent_id:
            _block(
                blockers,
                code="agent_identity_mismatch",
                module_id="contract",
                message="The Agent Contract identity does not match this Draft.",
            )
        workflow = _mapping(raw.get("workflow"))
        workflow_template = _optional_text(workflow.get("template"))
        descriptor_version = _optional_text(
            workflow.get("template_descriptor_version")
        )
        if (
            workflow_template != _PRODUCTION_WORKFLOW_TEMPLATE
            or descriptor_version != _PRODUCTION_WORKFLOW_DESCRIPTOR_VERSION
        ):
            _block(
                blockers,
                code="workflow_not_production_admissible",
                module_id="workflow",
                message=(
                    "Production publication requires the governed Controlled ReAct V3 "
                    "workflow and descriptor version."
                ),
            )

        if _nonempty_sequence(raw.get("package_knowledge_sources")):
            _block(
                blockers,
                code="package_knowledge_not_allowed",
                module_id="knowledge",
                message="Production publication cannot use package-local Knowledge Sources.",
            )
        if _nonempty_sequence(raw.get("knowledge_bindings")):
            _block(
                blockers,
                code="legacy_knowledge_binding_not_allowed",
                module_id="knowledge",
                message="Production publication cannot use legacy Knowledge bindings.",
            )

        candidate = draft.knowledge_release_binding_candidate
        catalog_ready = catalog.readiness.state == "ready"
        if candidate is None:
            _block(
                blockers,
                code="knowledge_release_candidate_required",
                module_id="knowledge",
                message="Select an exact queryable KSS Release on the Draft.",
            )
        if not catalog_ready:
            _block(
                blockers,
                code="kss_catalog_not_ready",
                module_id="knowledge",
                message="The live KSS Release catalog is not ready.",
            )
        release_queryable = bool(
            candidate is not None
            and catalog_ready
            and any(
                item.state == "queryable"
                and item.knowledge_space_id == candidate.knowledge_space_id
                and item.knowledge_base_id == candidate.knowledge_base_id
                and item.knowledge_base_version_id
                == candidate.knowledge_base_version_id
                and item.knowledge_base_release_id
                == candidate.knowledge_base_release_id
                for item in catalog.releases
            )
        )
        if candidate is not None and catalog_ready and not release_queryable:
            _block(
                blockers,
                code="knowledge_release_not_queryable",
                module_id="knowledge",
                message="The selected exact KSS Release is no longer queryable.",
            )

        roles = _model_role_mappings(raw)
        model_roles = tuple(
            self._model_role_projection(role, config, blockers)
            for role, config in roles
        )

        review_subagent = _mapping(_mapping(raw.get("review")).get("subagent"))
        if review_subagent.get("fail_closed") is not True:
            _block(
                blockers,
                code="review_must_fail_closed",
                module_id="model",
                message="Production publication requires a fail-closed review model.",
            )

        capabilities = _mapping(raw.get("capabilities"))
        if _mapping(capabilities.get("tools")).get("enabled") is not False:
            _block(
                blockers,
                code="tools_must_be_disabled",
                module_id="tools",
                message="Initial production publication requires Tools to be disabled.",
            )
        if _mapping(capabilities.get("memory")).get("enabled") is not False:
            _block(
                blockers,
                code="memory_must_be_disabled",
                module_id="memory",
                message="Initial production publication requires Memory to be disabled.",
            )
        if raw.get("customer") is not None:
            _block(
                blockers,
                code="customer_surface_not_allowed",
                module_id="contract",
                message="The removed customer-facing surface cannot be published.",
            )

        return ProductionAgentPublicationConfiguration(
            draft_revision=revision,
            authoring_configuration_state="ready" if not blockers else "blocked",
            formal_publication_state="workspace_draft_not_bound",
            can_publish_from_dashboard=False,
            workflow_template=workflow_template,
            workflow_template_descriptor_version=descriptor_version,
            knowledge_release_candidate=candidate,
            knowledge_release_queryable=release_queryable,
            model_roles=model_roles,
            configuration_blockers=tuple(blockers),
            phase_f_evidence_requirements=_PHASE_F_EVIDENCE_REQUIREMENTS,
            online_smoke_required=True,
            activation_mode="postgres_atomic_cas",
        )

    def _model_role_projection(
        self,
        role: str,
        config: Mapping[str, Any],
        blockers: list[ProductionAgentPublicationConfigurationBlocker],
    ) -> ProductionAgentPublicationModelRole:
        connection_id = _optional_text(config.get("connection_id"))
        inline_credentials = _has_inline_model_credentials(config)
        if inline_credentials:
            _block(
                blockers,
                code="inline_model_credentials_not_allowed",
                module_id="model",
                message=(
                    f"Production model role {role} cannot declare inline credentials."
                ),
            )
        if config.get("model_source") != "shared" or connection_id is None:
            _block(
                blockers,
                code="shared_model_connection_required",
                module_id="model",
                message=f"Production model role {role} requires a Shared Model Connection.",
            )
            return ProductionAgentPublicationModelRole(
                role=role,
                connection_id=connection_id,
                provider=None,
                model_identifier=None,
                lifecycle_state=None,
                configuration_state="blocked",
            )
        try:
            connection = self._configuration_store.get_model_connection(connection_id)
        except Exception:
            _block(
                blockers,
                code="shared_model_connection_catalog_unavailable",
                module_id="model",
                message=f"Shared Model Connection facts are unavailable for role {role}.",
            )
            return ProductionAgentPublicationModelRole(
                role=role,
                connection_id=connection_id,
                provider=None,
                model_identifier=None,
                lifecycle_state=None,
                configuration_state="blocked",
            )
        if connection is None:
            _block(
                blockers,
                code="shared_model_connection_missing",
                module_id="model",
                message=f"The Shared Model Connection for role {role} does not exist.",
            )
            return ProductionAgentPublicationModelRole(
                role=role,
                connection_id=connection_id,
                provider=None,
                model_identifier=None,
                lifecycle_state=None,
                configuration_state="blocked",
            )

        admissible = not inline_credentials
        if (
            connection.lifecycle_state
            is not SharedModelConnectionLifecycleState.ACTIVE
        ):
            admissible = False
            _block(
                blockers,
                code="shared_model_connection_inactive",
                module_id="model",
                message=f"The Shared Model Connection for role {role} is not active.",
            )
        if (
            connection.provider not in _REAL_MODEL_PROVIDERS
            or not connection.model_identifier.strip()
        ):
            admissible = False
            _block(
                blockers,
                code="shared_model_connection_not_production_admissible",
                module_id="model",
                message=f"The Shared Model Connection for role {role} is not production-admissible.",
            )
        if not isinstance(
            connection.credential_ref,
            PostgresEncryptedModelCredentialReference,
        ):
            admissible = False
            _block(
                blockers,
                code="shared_model_connection_credential_not_production_admissible",
                module_id="model",
                message=(
                    f"The Shared Model Connection for role {role} does not use the "
                    "production credential authority."
                ),
            )
        return ProductionAgentPublicationModelRole(
            role=role,
            connection_id=connection.connection_id,
            provider=connection.provider,
            model_identifier=connection.model_identifier,
            lifecycle_state=connection.lifecycle_state.value,
            configuration_state="ready" if admissible else "blocked",
        )


def _agent_mapping(
    draft: DraftAgent,
    blockers: list[ProductionAgentPublicationConfigurationBlocker],
) -> Mapping[str, Any]:
    try:
        raw = yaml.safe_load(draft.contract_bundle.agent_yaml)
    except yaml.YAMLError:
        raw = None
    if isinstance(raw, Mapping):
        return raw
    _block(
        blockers,
        code="agent_contract_invalid",
        module_id="contract",
        message="The Agent Contract cannot be projected for publication.",
    )
    return {}


def _model_role_mappings(raw: Mapping[str, Any]) -> tuple[tuple[str, Mapping[str, Any]], ...]:
    retrieval = _mapping(raw.get("retrieval"))
    roles: list[tuple[str, Mapping[str, Any]]] = [
        ("final_answer", _mapping(raw.get("model"))),
        ("react_planner", _mapping(_mapping(raw.get("react")).get("planner"))),
    ]
    if retrieval.get("planner_model") is not None:
        roles.append(("retrieval_planner", _mapping(retrieval.get("planner_model"))))
    if retrieval.get("evaluator_model") is not None:
        roles.append(("retrieval_evaluator", _mapping(retrieval.get("evaluator_model"))))
    roles.append(
        (
            "harness_review",
            _mapping(_mapping(raw.get("review")).get("subagent")),
        )
    )
    return tuple(roles)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _nonempty_sequence(value: Any) -> bool:
    return isinstance(value, list | tuple) and bool(value)


def _has_inline_model_credentials(config: Mapping[str, Any]) -> bool:
    params = _mapping(config.get("params"))
    return bool(
        _FORBIDDEN_PRODUCTION_MODEL_PARAMS.intersection(params)
        or "credential_secret_handle" in params
        or config.get("credential_ref") is not None
    )


def _block(
    blockers: list[ProductionAgentPublicationConfigurationBlocker],
    *,
    code: str,
    module_id: str,
    message: str,
) -> None:
    blockers.append(
        ProductionAgentPublicationConfigurationBlocker(
            code=code,
            module_id=module_id,
            message=message,
        )
    )


__all__ = [
    "ProductionAgentPublicationConfiguration",
    "ProductionAgentPublicationConfigurationBlocker",
    "ProductionAgentPublicationConfigurationProjector",
    "ProductionAgentPublicationModelRole",
]
