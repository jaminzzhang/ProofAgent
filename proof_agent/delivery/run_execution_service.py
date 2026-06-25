from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import uuid4

from proof_agent.bootstrap.composition import compose_harness_invocation
from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import (
    AgentManifest,
    ApprovalPause,
    ContextAdmission,
    RunPurpose,
    WorkflowStageResult,
    WorkflowStageStatus,
    WorkflowTemplateExecutionResult,
)
from proof_agent.control.workflow.controlled_react import (
    ControlledReActStartRequest,
    build_controlled_react_orchestrator_for_invocation,
)
from proof_agent.control.workflow.harness_helpers import finalize_run
from proof_agent.control.workflow.templates import resolve_workflow_template
from proof_agent.delivery.published_agents import PublishedAgent
from proof_agent.observability.audit.trace import TraceWriter
from proof_agent.observability.storage.run_store import RunStore
from proof_agent.runtime.approval_resume import (
    ControlledReActApprovalResumeContext,
    LangGraphApprovalResumeContext,
    LangGraphApprovalResumeRegistry,
)
from proof_agent.runtime.langgraph_runner import run_with_langgraph


class ControlledReActOrchestratorDependency(Protocol):
    def start(
        self,
        request: ControlledReActStartRequest,
    ) -> WorkflowTemplateExecutionResult: ...


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
    if manifest.workflow.template == "react_enterprise_qa_v3":
        return _execute_controlled_react_v3_published_agent_run(
            dependencies=dependencies,
            published_agent=published_agent,
            question=question,
            run_id=run_id,
            run_artifact_dir=run_artifact_dir,
            manifest=manifest,
            run_purpose=run_purpose,
        )

    checkpointer = dependencies.approval_resume_registry.checkpointer_for(run_id)
    result = run_with_langgraph(
        published_agent.manifest_path,
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
    )

    detail = dependencies.store.get_run_detail(run_id)
    if detail is None:
        raise RuntimeError("Run artifacts were not persisted.")
    if detail.pending_approvals:
        execution_input = result.workflow_template_execution_input
        if execution_input is None:
            raise RuntimeError(
                "Run is waiting for approval without Workflow Template Execution Input."
            )
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


def _execute_controlled_react_v3_published_agent_run(
    *,
    dependencies: RunExecutionDependencies,
    published_agent: PublishedAgent,
    question: str,
    run_id: str,
    run_artifact_dir: Path,
    manifest: AgentManifest,
    run_purpose: RunPurpose,
) -> PublishedAgentRunExecution:
    if manifest.react is None:
        raise RuntimeError("react_enterprise_qa_v3 requires react configuration.")

    invocation = compose_harness_invocation(
        published_agent.manifest_path,
        manifest=manifest,
        resolved_knowledge_bindings=published_agent.resolved_knowledge_bindings,
        configuration_store=dependencies.configuration_store,
    )
    orchestrator = dependencies.controlled_react_orchestrator
    if orchestrator is None:
        orchestrator = build_controlled_react_orchestrator_for_invocation(
            invocation,
            snapshot_store=dependencies.approval_resume_registry.controlled_react_snapshot_store(),
        )

    template = resolve_workflow_template(manifest.workflow.template)
    execution_result = orchestrator.start(
        ControlledReActStartRequest(
            run_id=run_id,
            template_name=manifest.workflow.template,
            template_descriptor_version=(
                manifest.workflow.template_descriptor_version
                or template.descriptor_version
            ),
            question=question,
            max_plan_rounds=manifest.react.max_plan_rounds,
        )
    )
    trace_path = run_artifact_dir / "trace.jsonl"
    receipt_path = run_artifact_dir / "governance_receipt.md"
    trace = TraceWriter(trace_path, run_id=run_id)
    _emit_controlled_react_trace_projection(
        trace,
        manifest=manifest,
        question=question,
        execution_result=execution_result,
        agent_version_id=published_agent.agent_version_id,
    )
    result = finalize_run(
        trace=trace,
        receipt_path=receipt_path,
        trace_path=trace_path,
        agent_name=manifest.name,
        question=question,
        outcome=execution_result.outcome,
        message=execution_result.final_output,
        store=dependencies.store,
        run_purpose=run_purpose,
        agent_id=published_agent.agent_id,
        agent_version_id=published_agent.agent_version_id,
        draft_id=published_agent.source_draft_id,
    ).model_copy(
        update={
            "workflow_template_execution_result": execution_result,
        }
    )
    detail = dependencies.store.get_run_detail(run_id)
    if detail is None:
        raise RuntimeError("Run artifacts were not persisted.")
    if detail.pending_approvals:
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


def _emit_controlled_react_trace_projection(
    trace: TraceWriter,
    *,
    manifest: AgentManifest,
    question: str,
    execution_result: WorkflowTemplateExecutionResult,
    agent_version_id: str | None,
) -> None:
    trace.emit(
        "run_started",
        status="ok",
        payload={
            "agent_name": manifest.name,
            "question": question,
            "template_name": execution_result.template_name,
            "runtime": "controlled_react_orchestrator",
        },
    )
    trace.emit(
        "workflow_stage_configuration_trace_summary",
        status="ok",
        payload={
            "source": {
                "source_type": (
                    "published_agent_version"
                    if agent_version_id is not None
                    else "agent_manifest"
                ),
                "reference": (
                    f"published_version:{agent_version_id}"
                    if agent_version_id is not None
                    else str(manifest.name)
                ),
            },
            "template_name": execution_result.template_name,
            "template_descriptor_version": (
                execution_result.template_descriptor_version
            ),
            "stages": [
                {"stage_id": stage_result.stage_id}
                for stage_result in execution_result.stage_results
            ],
        },
    )
    if execution_result.evidence:
        _emit_controlled_react_evidence_projection(trace, execution_result)
    for stage_result in execution_result.stage_results:
        _emit_controlled_react_stage_result(trace, stage_result)
    if execution_result.approval_pause is not None:
        _emit_controlled_react_approval_pause(
            trace,
            execution_result.approval_pause,
        )


def _emit_controlled_react_evidence_projection(
    trace: TraceWriter,
    execution_result: WorkflowTemplateExecutionResult,
) -> None:
    evidence_payload = [
        {
            "source": chunk.source,
            "content": chunk.content,
            "status": chunk.status.value,
            "evidence_id": chunk.evidence_id,
            "provider_native_score": chunk.provider_native_score,
            "admission_score": chunk.admission_score,
            "citation": chunk.citation,
            "metadata": dict(chunk.metadata),
        }
        for chunk in execution_result.evidence
    ]
    trace.emit(
        "retrieval_result",
        status="ok",
        payload={
            "query": "controlled_react_observation",
            "chunk_count": len(execution_result.evidence),
            "sources": [chunk.source for chunk in execution_result.evidence],
        },
    )
    trace.emit(
        "evidence_evaluation",
        status="ok",
        payload={
            "accepted_count": len(execution_result.evidence),
            "metadata": {"evidence": evidence_payload},
        },
    )


def _emit_controlled_react_stage_result(
    trace: TraceWriter,
    stage_result: WorkflowStageResult,
) -> None:
    trace.emit(
        "workflow_stage_result",
        status=_trace_status_for_stage_result(stage_result),
        payload={
            "stage_id": stage_result.stage_id,
            "status": stage_result.status.value,
            "outcome": (
                stage_result.outcome.value
                if stage_result.outcome is not None
                else None
            ),
            "summary": dict(stage_result.summary),
            "produced_fact_refs": list(stage_result.produced_fact_refs),
        },
    )


def _emit_controlled_react_approval_pause(
    trace: TraceWriter,
    approval_pause: ApprovalPause,
) -> None:
    payload = {
        "approval_id": approval_pause.approval_id,
        "action_id": approval_pause.action_id,
        "tool_name": approval_pause.tool_name,
        "policy_decision": approval_pause.policy_decision.value,
        "checkpoint_ref": approval_pause.checkpoint_ref,
        "expires_at": approval_pause.expires_at,
        "summary": dict(approval_pause.summary),
    }
    trace.emit("approval_requested", status="waiting", payload=payload)
    trace.emit("pending_approval_created", status="waiting", payload=payload)


def _trace_status_for_stage_result(
    stage_result: WorkflowStageResult,
) -> Literal["ok", "blocked", "waiting", "error"]:
    if stage_result.status is WorkflowStageStatus.BLOCKED:
        return "blocked"
    if stage_result.status is WorkflowStageStatus.WAITING:
        return "waiting"
    return "ok"
