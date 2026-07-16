from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.bootstrap.hybrid_execution import (
    HybridRunDependencies as HybridRunDependencies,
    HybridRunRuntime,
)
from proof_agent.contracts import (
    AgentManifest,
    ContextAdmission,
    InstitutionAuthorizationContext,
    MemoryRecallAdmission,
    RunPurpose,
)
from proof_agent.delivery.agent_package_execution import (
    AgentPackageRunRequest,
    ControlledReActOrchestratorDependency,
    execute_agent_package_run,
)
from proof_agent.delivery.published_agents import PublishedAgent
from proof_agent.observability.storage.run_store import RunStore
from proof_agent.control.workflow.controlled_react.ports import (
    ObservationTruthStorePort,
    SnapshotStorePort,
)
from proof_agent.contracts.ports.guarded_http import GuardedHttpClient
from proof_agent.contracts.ports.secret_provider import SecretProvider
from proof_agent.contracts.ports.shared_assets import RuntimeSharedAssetReader

@dataclass(frozen=True)
class RunExecutionDependencies:
    store: RunStore
    runs_dir: Path
    configuration_store: RuntimeSharedAssetReader
    controlled_react_snapshot_store: SnapshotStorePort | None = None
    controlled_react_observation_truth_store: ObservationTruthStorePort | None = None
    controlled_react_orchestrator: ControlledReActOrchestratorDependency | None = None
    hybrid_runtime: HybridRunRuntime | None = None
    guarded_http_client: GuardedHttpClient | None = None
    secret_provider: SecretProvider | None = None


@dataclass(frozen=True)
class PublishedAgentRunExecution:
    result: Any
    detail: Any
    manifest: AgentManifest


def execute_published_agent_run(
    *,
    dependencies: RunExecutionDependencies,
    published_agent: PublishedAgent,
    question: str,
    conversation_context: ContextAdmission | None = None,
    memory_recall_admissions: tuple[MemoryRecallAdmission, ...] = (),
    run_purpose: RunPurpose = RunPurpose.PRODUCTION,
    allow_untrusted_web_supplement: bool = False,
    institution_authorization: InstitutionAuthorizationContext | None = None,
    run_id: str | None = None,
    cancellation_check: Callable[[], None] | None = None,
) -> PublishedAgentRunExecution:
    """Execute one governed run for an already-resolved Published Agent."""

    run_id = run_id or f"run_{uuid4().hex[:8]}"
    run_artifact_dir = dependencies.store.create_run_dir(run_id)
    manifest = load_agent_manifest(
        published_agent.manifest_path,
        require_writable_artifacts=False,
    )
    hybrid_dependencies = None
    if published_agent.resolved_knowledge_bindings is not None:
        has_hybrid = any(
            getattr(binding, "binding_kind", None) == "hybrid"
            for binding in published_agent.resolved_knowledge_bindings.bindings
        )
        if has_hybrid:
            if dependencies.hybrid_runtime is None:
                raise RuntimeError(
                    "Published Hybrid Agent execution requires the production Hybrid runtime"
                )
            hybrid_dependencies = dependencies.hybrid_runtime.bind_for_run(
                published_agent.resolved_knowledge_bindings
            )
        elif dependencies.hybrid_runtime is not None:
            hybrid_dependencies = dependencies.hybrid_runtime.bind_for_run(
                published_agent.resolved_knowledge_bindings
            )
    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=published_agent.manifest_path,
            question=question,
            runs_dir=run_artifact_dir,
            conversation_context=conversation_context,
            memory_recall_admissions=memory_recall_admissions,
            run_id=run_id,
            store=dependencies.store,
            manifest=manifest,
            resolved_knowledge_bindings=published_agent.resolved_knowledge_bindings,
            configuration_store=dependencies.configuration_store,
            run_purpose=run_purpose,
            agent_id=published_agent.agent_id,
            agent_version_id=published_agent.agent_version_id,
            draft_id=published_agent.source_draft_id,
            allow_untrusted_web_supplement=allow_untrusted_web_supplement,
            published_agent_runtime_facts=published_agent.runtime_facts,
            controlled_react_orchestrator=dependencies.controlled_react_orchestrator,
            controlled_react_snapshot_store=dependencies.controlled_react_snapshot_store,
            institution_authorization=(
                institution_authorization or InstitutionAuthorizationContext()
            ),
            hybrid_providers=(
                hybrid_dependencies.hybrid_providers
                if hybrid_dependencies is not None
                else None
            ),
            governed_hybrid_request_factory=(
                hybrid_dependencies.governed_request_factory
                if hybrid_dependencies is not None
                else None
            ),
            controlled_react_observation_truth_store=(
                dependencies.controlled_react_observation_truth_store
            ),
            cancellation_check=cancellation_check,
            guarded_http_client=dependencies.guarded_http_client,
            secret_provider=dependencies.secret_provider,
        )
    )

    detail = dependencies.store.get_run_detail(run_id)
    if detail is None:
        raise RuntimeError("Run artifacts were not persisted.")
    return PublishedAgentRunExecution(result=result, detail=detail, manifest=manifest)
