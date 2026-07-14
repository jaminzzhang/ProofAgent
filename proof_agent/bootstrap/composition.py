from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from threading import Lock
from collections.abc import Callable
from typing import Mapping, cast

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
    BusinessFlowSkillPackDefinition,
    ModelCallRole,
    ModelConnectionResolutionRecord,
    ModelConfig,
    InstitutionAuthorizationContext,
    ReActPlannerConfig,
    ResolvedKnowledgeBindingSet,
    ReviewSubagentConfig,
)
from proof_agent.control.policy.engine import PolicyEngine
from proof_agent.control.context_budget import InMemoryContextBudgetCalibrationStore
from proof_agent.control.knowledge.hybrid_request import GovernedHybridRequestFactory
from proof_agent.control.workflow.templates import WorkflowTemplate, resolve_workflow_template
from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.bootstrap.knowledge_resolution import (
    KnowledgeBindingResolver,
    PackageKnowledgeBindingResolver,
)
from proof_agent.bootstrap.model_resolution import resolve_model_role_config
from proof_agent.bootstrap.skills import load_business_flow_skill_pack_set
from proof_agent.capabilities.knowledge.hybrid.model_clients import (
    BoundedSocketPrivateAddressResolver,
    GuardedEmbeddingTransport,
    GuardedKnowledgeModelSchedulerTransport,
    GuardedRerankerTransport,
    PrivateEmbeddingClient,
    PrivateHostPolicy,
    PrivateAddressResolver,
    PrivateNetworkPolicy,
    PrivateKnowledgeModelWorkSchedulerClient,
    PrivateRerankerClient,
    _private_https_endpoint,
)
from proof_agent.capabilities.knowledge.hybrid.parser_clients import (
    GuardedParserTransport,
    PrivateDoclingClient,
    PrivatePaddleClient,
)
from proof_agent.capabilities.knowledge.hybrid.pipeline import PrivateHybridParserPipeline
from proof_agent.capabilities.knowledge.hybrid.provider import (
    HybridIndexProvider,
    HybridRetrievalAuthority,
)
from proof_agent.capabilities.knowledge.hybrid.ports import HybridSearchIndex
from proof_agent.capabilities.knowledge.hybrid.ports import KnowledgeArtifactStore
from proof_agent.capabilities.knowledge.hybrid.publication import (
    HybridProjectionWriter,
    HybridPublicationRepository,
    HybridPublicationService,
)
from proof_agent.capabilities.knowledge.ingestion.hybrid_worker import (
    HybridKnowledgeWorkerFactory,
    HybridPrivateParserBuildConfig,
)


DEFAULT_MEMORY_DENY_FIELDS = frozenset({"access_token", "customer_phone", "provider_api_key"})


@dataclass(frozen=True)
class HybridKnowledgeModelSettings:
    """Secret-free internal service origins for private Knowledge processing."""

    scheduler_endpoint: str
    scheduler_namespace: str
    docling_endpoint: str
    paddle_endpoint: str
    embedding_endpoint: str
    reranker_endpoint: str
    allowed_hosts: tuple[str, ...]
    allowed_cidrs: tuple[str, ...]
    parser_revision: str
    model_digests: tuple[str, ...]
    parser_configuration_sha256: str
    host_policy: PrivateHostPolicy = field(init=False, repr=False)
    network_policy: PrivateNetworkPolicy = field(init=False, repr=False)
    build_config: HybridPrivateParserBuildConfig = field(init=False, repr=False)

    def __post_init__(self) -> None:
        policy = PrivateHostPolicy.from_entries(self.allowed_hosts)
        object.__setattr__(self, "host_policy", policy)
        object.__setattr__(
            self,
            "network_policy",
            PrivateNetworkPolicy.from_entries(self.allowed_cidrs),
        )
        object.__setattr__(
            self,
            "build_config",
            HybridPrivateParserBuildConfig(
                parser_revision=self.parser_revision,
                model_digests=self.model_digests,
                configuration_sha256=self.parser_configuration_sha256,
            ),
        )
        for field_name in (
            "scheduler_endpoint",
            "docling_endpoint",
            "paddle_endpoint",
            "embedding_endpoint",
            "reranker_endpoint",
        ):
            object.__setattr__(
                self,
                field_name,
                _private_https_endpoint(
                    getattr(self, field_name),
                    field=field_name,
                    allowed_hosts=policy,
                ),
            )


@dataclass(frozen=True)
class HybridKnowledgeTransportBundle:
    scheduler: GuardedKnowledgeModelSchedulerTransport
    docling: GuardedParserTransport
    paddle: GuardedParserTransport
    embedding: GuardedEmbeddingTransport
    reranker: GuardedRerankerTransport
    resolver: PrivateAddressResolver | None = None


class HybridKnowledgeComposition:
    """One process graph sharing one remote, namespace-scoped scheduler client."""

    def __init__(
        self,
        *,
        scheduler: PrivateKnowledgeModelWorkSchedulerClient,
        parser: PrivateHybridParserPipeline,
        embedding: PrivateEmbeddingClient,
        reranker: PrivateRerankerClient,
        ingestion_worker: HybridKnowledgeWorkerFactory,
        build_config: HybridPrivateParserBuildConfig,
        transports: HybridKnowledgeTransportBundle,
    ) -> None:
        self.scheduler = scheduler
        self.parser = parser
        self.embedding = embedding
        self.reranker = reranker
        self.ingestion_worker = ingestion_worker
        self.build_config = build_config
        self._transports = transports
        self._close_lock = Lock()
        self._pending_closers: dict[str, Callable[[], None]] = {
            "scheduler": self.scheduler.close,
            "docling": getattr(self._transports.docling, "close", lambda: None),
            "paddle": getattr(self._transports.paddle, "close", lambda: None),
            "embedding": getattr(self._transports.embedding, "close", lambda: None),
            "reranker": getattr(self._transports.reranker, "close", lambda: None),
        }
        if self._transports.resolver is not None:
            self._pending_closers["resolver"] = self._transports.resolver.close
        self._closed = False

    def close(self) -> None:
        """Close the complete graph once; FastAPI owns this single hook."""

        with self._close_lock:
            if self._closed:
                return
            failures: list[Exception] = []
            for name, close in tuple(self._pending_closers.items()):
                try:
                    close()
                except Exception as exc:
                    exc.add_note(f"Hybrid composition close failed for {name}")
                    failures.append(exc)
                else:
                    self._pending_closers.pop(name, None)
            if failures:
                raise ExceptionGroup("Hybrid Knowledge composition close failed", failures)
            self._closed = True

    def compose_publication_service(
        self,
        *,
        repository: HybridPublicationRepository,
        artifact_store: KnowledgeArtifactStore,
        index: HybridProjectionWriter,
    ) -> HybridPublicationService:
        """Attach publication to this graph without adding a second scheduler owner."""

        return HybridPublicationService(
            repository=repository,
            artifact_store=artifact_store,
            index=index,
            embedding=self.embedding,
        )

    def compose_retrieval_provider(
        self,
        *,
        authority: HybridRetrievalAuthority,
        index: HybridSearchIndex,
    ) -> HybridIndexProvider:
        """Attach online retrieval to the same scheduler-owned model clients."""

        return HybridIndexProvider(
            authority=authority,
            search=index,
            embedding=self.embedding,
            reranker=self.reranker,
        )


def compose_hybrid_knowledge(
    *,
    settings: HybridKnowledgeModelSettings,
    transports: HybridKnowledgeTransportBundle | None = None,
) -> HybridKnowledgeComposition:
    """Compose production private-model clients without any in-memory queue."""

    resolved_transports = transports or _default_hybrid_transports(settings)
    scheduler = PrivateKnowledgeModelWorkSchedulerClient(
        endpoint=settings.scheduler_endpoint,
        namespace=settings.scheduler_namespace,
        allowed_hosts=settings.host_policy,
        transport=resolved_transports.scheduler,
    )
    parser = PrivateHybridParserPipeline(
        docling=PrivateDoclingClient(
            transport=resolved_transports.docling,
            scheduler=scheduler,
        ),
        paddle=PrivatePaddleClient(
            transport=resolved_transports.paddle,
            scheduler=scheduler,
        ),
    )
    return HybridKnowledgeComposition(
        scheduler=scheduler,
        parser=parser,
        embedding=PrivateEmbeddingClient(
            transport=resolved_transports.embedding,
            scheduler=scheduler,
        ),
        reranker=PrivateRerankerClient(
            transport=resolved_transports.reranker,
            scheduler=scheduler,
        ),
        ingestion_worker=HybridKnowledgeWorkerFactory(scheduler=scheduler),
        build_config=settings.build_config,
        transports=resolved_transports,
    )


def compose_hybrid_knowledge_from_env(
    environ: Mapping[str, str] | None = None,
) -> HybridKnowledgeComposition | None:
    """Activate Hybrid production composition only through an explicit flag."""

    source = os.environ if environ is None else environ
    enabled = source.get("PA_HYBRID_KNOWLEDGE_MODELS_ENABLED", "").strip().lower()
    if enabled in {"", "0", "false", "no"}:
        return None
    if enabled not in {"1", "true", "yes"}:
        raise ValueError("PA_HYBRID_KNOWLEDGE_MODELS_ENABLED must be a boolean flag")
    keys = {
        "scheduler_endpoint": "PA_KNOWLEDGE_MODEL_SCHEDULER_ENDPOINT",
        "scheduler_namespace": "PA_KNOWLEDGE_MODEL_SCHEDULER_NAMESPACE",
        "docling_endpoint": "PA_KNOWLEDGE_DOCLING_ENDPOINT",
        "paddle_endpoint": "PA_KNOWLEDGE_PADDLE_ENDPOINT",
        "embedding_endpoint": "PA_KNOWLEDGE_EMBEDDING_ENDPOINT",
        "reranker_endpoint": "PA_KNOWLEDGE_RERANKER_ENDPOINT",
    }
    values: dict[str, str] = {}
    for field_name, key in keys.items():
        value = source.get(key, "").strip()
        if not value:
            raise ValueError(f"{key} is required when private Knowledge models are enabled")
        values[field_name] = value
    allowed_hosts_value = source.get("PA_KNOWLEDGE_MODEL_ALLOWED_HOSTS", "").strip()
    if not allowed_hosts_value:
        raise ValueError(
            "PA_KNOWLEDGE_MODEL_ALLOWED_HOSTS is required when private Knowledge models are enabled"
        )
    allowed_hosts = tuple(item.strip() for item in allowed_hosts_value.split(",") if item.strip())
    allowed_cidrs_value = source.get("PA_KNOWLEDGE_MODEL_ALLOWED_CIDRS", "").strip()
    if not allowed_cidrs_value:
        raise ValueError(
            "PA_KNOWLEDGE_MODEL_ALLOWED_CIDRS is required when private Knowledge models are enabled"
        )
    allowed_cidrs = tuple(item.strip() for item in allowed_cidrs_value.split(",") if item.strip())
    parser_revision = source.get("PA_KNOWLEDGE_PARSER_REVISION", "").strip()
    if not parser_revision:
        raise ValueError(
            "PA_KNOWLEDGE_PARSER_REVISION is required when private Knowledge models are enabled"
        )
    model_digests_value = source.get("PA_KNOWLEDGE_MODEL_DIGESTS", "").strip()
    model_digests = tuple(item.strip() for item in model_digests_value.split(",") if item.strip())
    if not model_digests:
        raise ValueError(
            "PA_KNOWLEDGE_MODEL_DIGESTS is required when private Knowledge models are enabled"
        )
    parser_configuration_sha256 = source.get("PA_KNOWLEDGE_PARSER_CONFIGURATION_SHA256", "").strip()
    if not parser_configuration_sha256:
        raise ValueError(
            "PA_KNOWLEDGE_PARSER_CONFIGURATION_SHA256 is required when private Knowledge models "
            "are enabled"
        )
    return compose_hybrid_knowledge(
        settings=HybridKnowledgeModelSettings(
            **values,
            allowed_hosts=allowed_hosts,
            allowed_cidrs=allowed_cidrs,
            parser_revision=parser_revision,
            model_digests=model_digests,
            parser_configuration_sha256=parser_configuration_sha256,
        )
    )


def _default_hybrid_transports(
    settings: HybridKnowledgeModelSettings,
) -> HybridKnowledgeTransportBundle:
    from proof_agent.capabilities.knowledge.hybrid.model_clients import (
        HttpEmbeddingTransport,
        HttpKnowledgeModelSchedulerTransport,
        HttpRerankerTransport,
    )
    from proof_agent.capabilities.knowledge.hybrid.parser_clients import HttpParserTransport

    resolver = BoundedSocketPrivateAddressResolver()
    try:
        return HybridKnowledgeTransportBundle(
            scheduler=HttpKnowledgeModelSchedulerTransport(
                network_policy=settings.network_policy,
                resolver=resolver,
            ),
            docling=HttpParserTransport(
                endpoint=settings.docling_endpoint,
                allowed_hosts=settings.host_policy,
                network_policy=settings.network_policy,
                resolver=resolver,
            ),
            paddle=HttpParserTransport(
                endpoint=settings.paddle_endpoint,
                allowed_hosts=settings.host_policy,
                network_policy=settings.network_policy,
                resolver=resolver,
            ),
            embedding=HttpEmbeddingTransport(
                endpoint=settings.embedding_endpoint,
                allowed_hosts=settings.host_policy,
                network_policy=settings.network_policy,
                resolver=resolver,
            ),
            reranker=HttpRerankerTransport(
                endpoint=settings.reranker_endpoint,
                allowed_hosts=settings.host_policy,
                network_policy=settings.network_policy,
                resolver=resolver,
            ),
            resolver=resolver,
        )
    except BaseException:
        resolver.close()
        raise


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
    business_flow_skill_packs: tuple[BusinessFlowSkillPackDefinition, ...] = ()
    model_resolution_records: tuple[ModelConnectionResolutionRecord, ...] = ()
    context_budget_calibration_store: InMemoryContextBudgetCalibrationStore = field(
        default_factory=InMemoryContextBudgetCalibrationStore
    )
    institution_authorization: InstitutionAuthorizationContext = field(
        default_factory=InstitutionAuthorizationContext
    )
    governed_hybrid_request_factory: GovernedHybridRequestFactory | None = None

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
    context_budget_calibration_store: InMemoryContextBudgetCalibrationStore | None = None,
    institution_authorization: InstitutionAuthorizationContext | None = None,
    governed_hybrid_request_factory: GovernedHybridRequestFactory | None = None,
    hybrid_providers: Mapping[str, HybridIndexProvider] | None = None,
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
        if template.descriptor_version in {
            "react_enterprise_qa.v2",
            "react_enterprise_qa.v3",
        }:
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
    policy = PolicyEngine.from_file(resolved_manifest.policy.file)
    business_flow_skill_packs = load_business_flow_skill_pack_set(
        resolved_manifest,
        template=template,
        manifest_path=manifest_path,
    )
    return HarnessInvocation(
        manifest_path=manifest_path,
        manifest=resolved_manifest,
        template=template,
        policy=policy,
        knowledge_provider=cast(
            KnowledgeProvider,
            resolve_blended_knowledge_provider(
                resolved_bindings,
                configuration_store=configuration_store,
                hybrid_providers=hybrid_providers,
            ),
        ),
        resolved_knowledge_bindings=resolved_bindings,
        model_provider=resolve_provider(resolved_answer_model.model_config),
        tool_gateway=_tool_gateway_for_manifest(
            resolved_manifest,
            configuration_store=configuration_store,
        ),
        intent_resolver=intent_resolver,
        react_planner=react_planner,
        review_subagent=review_subagent,
        retrieval_planner_model=resolved_retrieval_planner_model,
        retrieval_evaluator_model=resolved_retrieval_evaluator_model,
        business_flow_skill_packs=business_flow_skill_packs,
        model_resolution_records=tuple(model_resolution_records),
        context_budget_calibration_store=(
            context_budget_calibration_store
            if context_budget_calibration_store is not None
            else InMemoryContextBudgetCalibrationStore()
        ),
        institution_authorization=(institution_authorization or InstitutionAuthorizationContext()),
        governed_hybrid_request_factory=governed_hybrid_request_factory,
    )


def _tool_gateway_for_manifest(
    manifest: AgentManifest,
    *,
    configuration_store: LocalAgentConfigurationStore | None,
) -> ToolGateway:
    tools = manifest.capabilities.tools
    if not tools.enabled:
        return ToolGateway({})
    if tools.file is None:
        return ToolGateway({})
    return ToolGateway.from_file(
        tools.file,
        configuration_store=configuration_store,
        tool_source_env=os.environ,
    )
