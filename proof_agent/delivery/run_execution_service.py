from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import (
    AgentManifest,
    ContextAdmission,
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


@dataclass(frozen=True)
class RunExecutionDependencies:
    store: RunStore
    runs_dir: Path
    configuration_store: LocalAgentConfigurationStore
    controlled_react_snapshot_store: SnapshotStorePort | None = None
    controlled_react_observation_truth_store: ObservationTruthStorePort | None = None
    controlled_react_orchestrator: ControlledReActOrchestratorDependency | None = None


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
) -> PublishedAgentRunExecution:
    """Execute one governed run for an already-resolved Published Agent."""

    run_id = f"run_{uuid4().hex[:8]}"
    run_artifact_dir = dependencies.store.create_run_dir(run_id)
    manifest = load_agent_manifest(published_agent.manifest_path)
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
            controlled_react_observation_truth_store=(
                dependencies.controlled_react_observation_truth_store
            ),
        )
    )

    detail = dependencies.store.get_run_detail(run_id)
    if detail is None:
        raise RuntimeError("Run artifacts were not persisted.")
    return PublishedAgentRunExecution(result=result, detail=detail, manifest=manifest)
