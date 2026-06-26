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
    RunPurpose,
)
from proof_agent.delivery.agent_package_execution import (
    AgentPackageRunRequest,
    ControlledReActOrchestratorDependency,
    execute_agent_package_run,
)
from proof_agent.delivery.published_agents import PublishedAgent
from proof_agent.observability.storage.run_store import RunStore
from proof_agent.runtime.approval_resume import (
    ControlledReActApprovalResumeContext,
    LangGraphApprovalResumeContext,
    LangGraphApprovalResumeRegistry,
)


@dataclass(frozen=True)
class RunExecutionDependencies:
    store: RunStore
    runs_dir: Path
    configuration_store: LocalAgentConfigurationStore
    approval_resume_registry: LangGraphApprovalResumeRegistry
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
    run_purpose: RunPurpose = RunPurpose.PRODUCTION,
    allow_untrusted_web_supplement: bool = False,
) -> PublishedAgentRunExecution:
    """Execute one governed run for an already-resolved Published Agent."""

    run_id = f"run_{uuid4().hex[:8]}"
    run_artifact_dir = dependencies.store.create_run_dir(run_id)
    manifest = load_agent_manifest(published_agent.manifest_path)
    is_controlled_react_v3 = manifest.workflow.template == "react_enterprise_qa_v3"
    checkpointer = (
        None
        if is_controlled_react_v3
        else dependencies.approval_resume_registry.checkpointer_for(run_id)
    )
    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=published_agent.manifest_path,
            question=question,
            runs_dir=run_artifact_dir,
            conversation_context=conversation_context,
            run_id=run_id,
            store=dependencies.store,
            checkpointer=checkpointer,
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
            controlled_react_snapshot_store=(
                dependencies.approval_resume_registry.controlled_react_snapshot_store()
                if is_controlled_react_v3
                else None
            ),
            controlled_react_observation_truth_store=(
                dependencies.approval_resume_registry.controlled_react_observation_truth_store()
                if is_controlled_react_v3
                else None
            ),
        )
    )

    detail = dependencies.store.get_run_detail(run_id)
    if detail is None:
        raise RuntimeError("Run artifacts were not persisted.")
    if detail.pending_approvals:
        if is_controlled_react_v3:
            dependencies.approval_resume_registry.put_controlled_react(
                ControlledReActApprovalResumeContext(
                    agent_yaml=published_agent.manifest_path,
                    run_id=run_id,
                    question=question,
                    manifest=manifest,
                    resolved_knowledge_bindings=published_agent.resolved_knowledge_bindings,
                    configuration_store=dependencies.configuration_store,
                    run_purpose=detail.run_purpose,
                    agent_id=published_agent.agent_id,
                    agent_version_id=published_agent.agent_version_id,
                    draft_id=published_agent.source_draft_id,
                )
            )
            return PublishedAgentRunExecution(result=result, detail=detail, manifest=manifest)
        execution_input = result.workflow_template_execution_input
        if execution_input is None:
            raise RuntimeError(
                "Run is waiting for approval without Workflow Template Execution Input."
            )
        if checkpointer is None:
            raise RuntimeError("LangGraph approval run is missing checkpointer.")
        dependencies.approval_resume_registry.put(
            LangGraphApprovalResumeContext(
                agent_yaml=published_agent.manifest_path,
                runs_dir=dependencies.store.history_dir / run_id,
                run_id=run_id,
                question=question,
                checkpointer=checkpointer,
                manifest=manifest,
                conversation_context=conversation_context,
                resolved_knowledge_bindings=published_agent.resolved_knowledge_bindings,
                configuration_store=dependencies.configuration_store,
                run_purpose=detail.run_purpose,
                agent_id=published_agent.agent_id,
                agent_version_id=published_agent.agent_version_id,
                draft_id=published_agent.source_draft_id,
                allow_untrusted_web_supplement=allow_untrusted_web_supplement,
                workflow_template_execution_input=execution_input,
            )
        )
    return PublishedAgentRunExecution(result=result, detail=detail, manifest=manifest)
