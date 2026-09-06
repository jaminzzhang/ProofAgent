"""Composition root for the ProofAgent harness and its external authorities."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import os
from pathlib import Path

from proof_agent.bootstrap.knowledge_resolution import (
    ManifestKnowledgeAuthorityGuard,
)
from proof_agent.bootstrap.external_knowledge import ExternalKnowledgeRuntime, development_knowledge_dependencies
from proof_agent.contracts.external_knowledge import ExternalKnowledgeBinding
from proof_agent.contracts.ports.external_knowledge import ExternalKnowledgeSourceSet
from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.bootstrap.model_resolution import resolve_model_role_config
from proof_agent.bootstrap.skills import load_business_flow_skill_pack_set
from proof_agent.capabilities.memory.session import SessionMemory
from proof_agent.capabilities.models import ModelProvider, resolve_provider
from proof_agent.capabilities.react import (
    IntentResolver,
    ReActPlanner,
    resolve_intent_resolver,
    resolve_react_planner,
)
from proof_agent.capabilities.review import HarnessReviewSubagent, resolve_review_subagent
from proof_agent.capabilities.tools.gateway import ToolGateway
from proof_agent.contracts import (
    AgentManifest,
    BusinessFlowSkillPackDefinition,
    InstitutionAuthorizationContext,
    ModelCallRole,
    ModelConfig,
    ModelConnectionResolutionRecord,
    ReActPlannerConfig,
    ResolvedKnowledgeBindingSet,
    ReviewSubagentConfig,
)
from proof_agent.contracts.ports.guarded_http import GuardedHttpClient
from proof_agent.contracts.ports.knowledge_candidates import (
    KnowledgeCandidateAdmissionScorer,
    KnowledgeCandidateService,
)
from proof_agent.contracts.ports.model_credentials import ModelCredentialResolver
from proof_agent.contracts.ports.secret_provider import SecretProvider
from proof_agent.contracts.ports.shared_assets import RuntimeSharedAssetReader
from proof_agent.control.context_budget import InMemoryContextBudgetCalibrationStore
from proof_agent.control.knowledge.candidate_request import KnowledgeCandidateQueryFactory
from proof_agent.control.policy.engine import PolicyEngine
from proof_agent.control.workflow.templates import WorkflowTemplate, resolve_workflow_template
from proof_agent.errors import ProofAgentError


DEFAULT_MEMORY_DENY_FIELDS = frozenset(
    {"access_token", "customer_phone", "provider_api_key"}
)


@dataclass(frozen=True)
class HarnessInvocation:
    """Resolved dependencies for one governed Harness execution."""

    manifest_path: Path
    manifest: AgentManifest
    template: WorkflowTemplate
    policy: PolicyEngine
    resolved_knowledge_bindings: ResolvedKnowledgeBindingSet
    model_provider: ModelProvider
    tool_gateway: ToolGateway
    memory_deny_fields: frozenset[str] = DEFAULT_MEMORY_DENY_FIELDS
    intent_resolver: IntentResolver | None = None
    react_planner: ReActPlanner | None = None
    review_subagent: HarnessReviewSubagent | None = None
    retrieval_planner_model: ModelConfig | None = None
    retrieval_evaluator_model: ModelConfig | None = None
    business_flow_skill_packs: tuple[BusinessFlowSkillPackDefinition, ...] = ()
    model_resolution_records: tuple[ModelConnectionResolutionRecord, ...] = ()
    context_budget_calibration_store: InMemoryContextBudgetCalibrationStore = field(
        default_factory=InMemoryContextBudgetCalibrationStore
    )
    institution_authorization: InstitutionAuthorizationContext = field(
        default_factory=InstitutionAuthorizationContext
    )
    knowledge_candidate_service: KnowledgeCandidateService | None = None
    external_knowledge: ExternalKnowledgeSourceSet | None = None
    knowledge_candidate_query_factory: KnowledgeCandidateQueryFactory | None = None
    knowledge_candidate_admission_scorer: (
        KnowledgeCandidateAdmissionScorer | None
    ) = None
    model_resolver: Callable[[ModelConfig], ModelProvider] = resolve_provider
    cancellation_check: Callable[[], None] = lambda: None

    def create_memory(self) -> SessionMemory:
        return SessionMemory(deny_fields=self.memory_deny_fields)


def compose_harness_invocation(
    agent_yaml: Path | str,
    *,
    manifest: AgentManifest | None = None,
    resolved_knowledge_bindings: ResolvedKnowledgeBindingSet | None = None,
    configuration_store: RuntimeSharedAssetReader | None = None,
    require_runtime_credentials: bool = True,
    context_budget_calibration_store: InMemoryContextBudgetCalibrationStore | None = None,
    institution_authorization: InstitutionAuthorizationContext | None = None,
    knowledge_candidate_service: KnowledgeCandidateService | None = None,
    knowledge_candidate_query_factory: KnowledgeCandidateQueryFactory | None = None,
    knowledge_candidate_admission_scorer: (
        KnowledgeCandidateAdmissionScorer | None
    ) = None,
    guarded_http_client: GuardedHttpClient | None = None,
    secret_provider: SecretProvider | None = None,
    model_credential_resolver: ModelCredentialResolver | None = None,
    cancellation_check: Callable[[], None] | None = None,
) -> HarnessInvocation:
    """Resolve one governed Agent with optional external Knowledge providers."""

    candidate_dependencies = (
        knowledge_candidate_service,
        knowledge_candidate_query_factory,
        knowledge_candidate_admission_scorer,
    )
    if any(item is not None for item in candidate_dependencies):
        raise ProofAgentError(
            "PA_CONFIG_002",
            "The legacy KSS runtime is retired.",
            "Configure an external Knowledge provider binding.",
        )

    model_provider_resolver = _model_provider_resolver(
        guarded_http_client=guarded_http_client,
        secret_provider=secret_provider,
        model_credential_resolver=model_credential_resolver,
    )
    manifest_path = Path(agent_yaml).resolve()
    resolved_manifest = manifest or load_agent_manifest(manifest_path)
    template = resolve_workflow_template(resolved_manifest.workflow.template)
    model_resolution_records: list[ModelConnectionResolutionRecord] = []
    resolved_answer_model = resolve_model_role_config(
        resolved_manifest.model,
        role=ModelCallRole.FINAL_ANSWER,
        configuration_store=configuration_store,
        require_runtime_credentials=require_runtime_credentials,
    )
    model_resolution_records.append(resolved_answer_model.resolution_record)

    resolved_retrieval_planner_model = _resolve_optional_model(
        resolved_manifest.retrieval.planner_model,
        role=ModelCallRole.RETRIEVAL_PLANNER,
        configuration_store=configuration_store,
        require_runtime_credentials=require_runtime_credentials,
        records=model_resolution_records,
    )
    resolved_retrieval_evaluator_model = _resolve_optional_model(
        resolved_manifest.retrieval.evaluator_model,
        role=ModelCallRole.RETRIEVAL_EVALUATOR,
        configuration_store=configuration_store,
        require_runtime_credentials=require_runtime_credentials,
        records=model_resolution_records,
    )

    react_planner = None
    intent_resolver = None
    if resolved_manifest.react is not None:
        resolved_planner_model = resolve_model_role_config(
            resolved_manifest.react.planner,
            role=ModelCallRole.REACT_PLANNER,
            configuration_store=configuration_store,
            require_runtime_credentials=require_runtime_credentials,
        )
        model_resolution_records.append(resolved_planner_model.resolution_record)
        planner_config = ReActPlannerConfig(
            provider=resolved_planner_model.model_config.provider,
            name=resolved_planner_model.model_config.name,
            params=resolved_planner_model.model_config.params,
        )
        react_planner = resolve_react_planner(
            planner_config,
            guarded_http_client=guarded_http_client,
            secret_provider=secret_provider,
            model_credential_resolver=model_credential_resolver,
        )
        resolved_intent_model = resolve_model_role_config(
            resolved_manifest.react.planner,
            role=ModelCallRole.INTENT_RESOLUTION,
            configuration_store=configuration_store,
            require_runtime_credentials=require_runtime_credentials,
        )
        model_resolution_records.append(resolved_intent_model.resolution_record)
        intent_resolver = resolve_intent_resolver(
            ReActPlannerConfig(
                provider=resolved_intent_model.model_config.provider,
                name=resolved_intent_model.model_config.name,
                params=resolved_intent_model.model_config.params,
            ),
            max_queries=resolved_manifest.retrieval.max_queries,
            guarded_http_client=guarded_http_client,
            secret_provider=secret_provider,
            model_credential_resolver=model_credential_resolver,
        )

    review_subagent = None
    if resolved_manifest.review is not None and resolved_manifest.review.subagent is not None:
        resolved_review_model = resolve_model_role_config(
            resolved_manifest.review.subagent,
            role=ModelCallRole.HARNESS_REVIEW,
            configuration_store=configuration_store,
            require_runtime_credentials=require_runtime_credentials,
        )
        model_resolution_records.append(resolved_review_model.resolution_record)
        review_subagent = resolve_review_subagent(
            ReviewSubagentConfig(
                provider=resolved_review_model.model_config.provider,
                name=resolved_review_model.model_config.name,
                fail_closed=resolved_manifest.review.subagent.fail_closed,
                params=resolved_review_model.model_config.params,
            ),
            guarded_http_client=guarded_http_client,
            secret_provider=secret_provider,
            model_credential_resolver=model_credential_resolver,
        )

    resolved_bindings = resolved_knowledge_bindings
    if resolved_bindings is None:
        resolved_bindings = ManifestKnowledgeAuthorityGuard().resolve(resolved_manifest)
    external_bindings = _validate_knowledge_authority(resolved_bindings)
    expected_bindings = ManifestKnowledgeAuthorityGuard().resolve(resolved_manifest)
    if resolved_bindings != expected_bindings:
        raise ProofAgentError(
            "PA_CONFIG_002", "Frozen Knowledge bindings differ from the Agent manifest.",
            "Validate and publish the exact external Knowledge configuration again.",
        )
    external_knowledge = None
    if external_bindings:
        guarded_http_client, secret_provider = development_knowledge_dependencies(guarded_http_client, secret_provider)
        if guarded_http_client is None or secret_provider is None:
            raise ProofAgentError(
                "PA_CONFIG_002", "External Knowledge requires guarded HTTP and a Secret Provider.",
                "Compose the server-owned transport and credential resolver before execution.",
            )
        external_knowledge = ExternalKnowledgeRuntime(
            external_bindings, http_client=guarded_http_client, secret_provider=secret_provider,
            timeout_seconds=min(resolved_manifest.retrieval.query_timeout_seconds, 60.0),
        )

    policy = PolicyEngine.from_file(resolved_manifest.policy.file)
    return HarnessInvocation(
        manifest_path=manifest_path,
        manifest=resolved_manifest,
        template=template,
        policy=policy,
        resolved_knowledge_bindings=resolved_bindings,
        model_provider=model_provider_resolver(resolved_answer_model.model_config),
        tool_gateway=_tool_gateway_for_manifest(
            resolved_manifest,
            configuration_store=configuration_store,
            guarded_http_client=guarded_http_client,
        ),
        intent_resolver=intent_resolver,
        react_planner=react_planner,
        review_subagent=review_subagent,
        retrieval_planner_model=resolved_retrieval_planner_model,
        retrieval_evaluator_model=resolved_retrieval_evaluator_model,
        business_flow_skill_packs=load_business_flow_skill_pack_set(
            resolved_manifest,
            template=template,
            manifest_path=manifest_path,
        ),
        model_resolution_records=tuple(model_resolution_records),
        context_budget_calibration_store=(
            context_budget_calibration_store
            if context_budget_calibration_store is not None
            else InMemoryContextBudgetCalibrationStore()
        ),
        institution_authorization=(
            institution_authorization or InstitutionAuthorizationContext()
        ),
        knowledge_candidate_service=knowledge_candidate_service,
        external_knowledge=external_knowledge,
        knowledge_candidate_query_factory=knowledge_candidate_query_factory,
        knowledge_candidate_admission_scorer=knowledge_candidate_admission_scorer,
        model_resolver=model_provider_resolver,
        cancellation_check=cancellation_check or (lambda: None),
    )


def _resolve_optional_model(
    config: ModelConfig | None,
    *,
    role: ModelCallRole,
    configuration_store: RuntimeSharedAssetReader | None,
    require_runtime_credentials: bool,
    records: list[ModelConnectionResolutionRecord],
) -> ModelConfig | None:
    if config is None:
        return None
    resolved = resolve_model_role_config(
        config,
        role=role,
        configuration_store=configuration_store,
        require_runtime_credentials=require_runtime_credentials,
    )
    records.append(resolved.resolution_record)
    return resolved.model_config


def _validate_knowledge_authority(
    bindings: ResolvedKnowledgeBindingSet,
) -> tuple[ExternalKnowledgeBinding, ...]:
    external: list[ExternalKnowledgeBinding] = []
    for binding in bindings.bindings:
        if not isinstance(binding, ExternalKnowledgeBinding):
            raise ProofAgentError(
                "PA_CONFIG_002", "The legacy KSS binding is retired.",
                "Create and validate an external Knowledge binding before execution.",
            )
        external.append(binding)
    return tuple(external)


def _model_provider_resolver(
    *,
    guarded_http_client: GuardedHttpClient | None,
    secret_provider: SecretProvider | None,
    model_credential_resolver: ModelCredentialResolver | None,
) -> Callable[[ModelConfig], ModelProvider]:
    if (
        guarded_http_client is None
        and secret_provider is None
        and model_credential_resolver is None
    ):
        return resolve_provider
    return lambda config: resolve_provider(
        config,
        guarded_http_client=guarded_http_client,
        secret_provider=secret_provider,
        model_credential_resolver=model_credential_resolver,
    )


def _tool_gateway_for_manifest(
    manifest: AgentManifest,
    *,
    configuration_store: RuntimeSharedAssetReader | None,
    guarded_http_client: GuardedHttpClient | None = None,
) -> ToolGateway:
    tools = manifest.capabilities.tools
    if not tools.enabled or tools.file is None:
        return ToolGateway({})
    return ToolGateway.from_file(
        tools.file,
        configuration_store=configuration_store,
        tool_source_env=os.environ,
        guarded_http_client=guarded_http_client,
    )


__all__ = ["HarnessInvocation", "compose_harness_invocation"]
