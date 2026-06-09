from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import cast

from proof_agent.capabilities.knowledge import KnowledgeProvider
from proof_agent.capabilities.knowledge.blended import resolve_blended_knowledge_provider
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
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import (
    AgentManifest,
    ModelCallRole,
    ModelConnectionResolutionRecord,
    ModelConfig,
    ReActPlannerConfig,
    ResolvedKnowledgeBindingSet,
    ReviewSubagentConfig,
)
from proof_agent.control.policy.engine import PolicyEngine
from proof_agent.control.workflow.templates import WorkflowTemplate, resolve_workflow_template
from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.bootstrap.knowledge_resolution import (
    KnowledgeBindingResolver,
    PackageKnowledgeBindingResolver,
)
from proof_agent.bootstrap.model_resolution import resolve_model_role_config


DEFAULT_MEMORY_DENY_FIELDS = frozenset({"access_token", "customer_phone", "provider_api_key"})


@dataclass(frozen=True)
class HarnessInvocation:
    """Resolved dependencies for one governed Harness execution."""

    manifest_path: Path
    manifest: AgentManifest
    template: WorkflowTemplate
    policy: PolicyEngine
    knowledge_provider: KnowledgeProvider
    resolved_knowledge_bindings: ResolvedKnowledgeBindingSet
    model_provider: ModelProvider
    tool_gateway: ToolGateway
    memory_deny_fields: frozenset[str] = DEFAULT_MEMORY_DENY_FIELDS
    intent_resolver: IntentResolver | None = None
    react_planner: ReActPlanner | None = None
    review_subagent: HarnessReviewSubagent | None = None
    retrieval_planner_model: ModelConfig | None = None
    retrieval_evaluator_model: ModelConfig | None = None
    model_resolution_records: tuple[ModelConnectionResolutionRecord, ...] = ()

    def create_memory(self) -> SessionMemory:
        """Create per-run memory with the configured sensitivity boundary."""

        return SessionMemory(deny_fields=self.memory_deny_fields)


def compose_harness_invocation(
    agent_yaml: Path | str,
    *,
    manifest: AgentManifest | None = None,
    knowledge_binding_resolver: KnowledgeBindingResolver | None = None,
    resolved_knowledge_bindings: ResolvedKnowledgeBindingSet | None = None,
    configuration_store: LocalAgentConfigurationStore | None = None,
    require_runtime_credentials: bool = True,
) -> HarnessInvocation:
    """Resolve an Agent Contract into the dependencies needed to run it."""

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
    resolved_retrieval_planner_model = None
    if resolved_manifest.retrieval.planner_model is not None:
        resolved = resolve_model_role_config(
            resolved_manifest.retrieval.planner_model,
            role=ModelCallRole.RETRIEVAL_PLANNER,
            configuration_store=configuration_store,
            require_runtime_credentials=require_runtime_credentials,
        )
        resolved_retrieval_planner_model = resolved.model_config
        model_resolution_records.append(resolved.resolution_record)
    resolved_retrieval_evaluator_model = None
    if resolved_manifest.retrieval.evaluator_model is not None:
        resolved = resolve_model_role_config(
            resolved_manifest.retrieval.evaluator_model,
            role=ModelCallRole.RETRIEVAL_EVALUATOR,
            configuration_store=configuration_store,
            require_runtime_credentials=require_runtime_credentials,
        )
        resolved_retrieval_evaluator_model = resolved.model_config
        model_resolution_records.append(resolved.resolution_record)
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
        react_planner = resolve_react_planner(
            ReActPlannerConfig(
                provider=resolved_planner_model.model_config.provider,
                name=resolved_planner_model.model_config.name,
                params=resolved_planner_model.model_config.params,
            )
        )
        if template.descriptor_version == "react_enterprise_qa.v2":
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
                )
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
            )
        )
    resolved_bindings = resolved_knowledge_bindings
    if resolved_bindings is None:
        resolver = knowledge_binding_resolver or PackageKnowledgeBindingResolver()
        resolved_bindings = resolver.resolve(resolved_manifest)
    return HarnessInvocation(
        manifest_path=manifest_path,
        manifest=resolved_manifest,
        template=template,
        policy=PolicyEngine.from_file(resolved_manifest.policy.file),
        knowledge_provider=cast(
            KnowledgeProvider,
            resolve_blended_knowledge_provider(
                resolved_bindings,
                configuration_store=configuration_store,
            ),
        ),
        resolved_knowledge_bindings=resolved_bindings,
        model_provider=resolve_provider(resolved_answer_model.model_config),
        tool_gateway=ToolGateway.from_file(
            resolved_manifest.tools.file,
            configuration_store=configuration_store,
            tool_source_env=os.environ,
        ),
        intent_resolver=intent_resolver,
        react_planner=react_planner,
        review_subagent=review_subagent,
        retrieval_planner_model=resolved_retrieval_planner_model,
        retrieval_evaluator_model=resolved_retrieval_evaluator_model,
        model_resolution_records=tuple(model_resolution_records),
    )
