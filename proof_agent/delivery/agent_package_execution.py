from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import uuid4

from proof_agent.bootstrap.composition import compose_harness_invocation
from proof_agent.bootstrap.knowledge_resolution import KnowledgeBindingResolver
from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import (
    AgentManifest,
    ApprovalPause,
    ClarificationNeed,
    ContextAdmission,
    PublishedAgentRuntimeFacts,
    ResolvedKnowledgeBindingSet,
    RunPurpose,
    RunResult,
    WorkflowStageResult,
    WorkflowStageStatus,
    WorkflowTemplateExecutionResult,
)
from proof_agent.control.workflow.controlled_react import (
    ControlledReActStartRequest,
    build_controlled_react_orchestrator_for_invocation,
)
from proof_agent.control.workflow.controlled_react.ports import SnapshotStorePort
from proof_agent.control.workflow.controlled_react.ports import ObservationTruthStorePort
from proof_agent.control.workflow.harness_helpers import (
    finalize_run,
)
from proof_agent.control.workflow.templates import resolve_workflow_template
from proof_agent.observability.audit.trace import TraceWriter
from proof_agent.observability.storage.run_store import RunStore
from proof_agent.runtime.langgraph_runner import (
    _resolve_workflow_stage_runtime_configuration,
    _workflow_template_execution_input,
    run_with_langgraph,
)


class ControlledReActOrchestratorDependency(Protocol):
    def start(
        self,
        request: ControlledReActStartRequest,
    ) -> WorkflowTemplateExecutionResult: ...


@dataclass(frozen=True)
class AgentPackageRunRequest:
    agent_yaml: Path
    question: str
    runs_dir: Path
    conversation_context: ContextAdmission | None = None
    run_id: str | None = None
    store: RunStore | None = None
    checkpointer: Any | None = None
    manifest: AgentManifest | None = None
    knowledge_binding_resolver: KnowledgeBindingResolver | None = None
    resolved_knowledge_bindings: ResolvedKnowledgeBindingSet | None = None
    configuration_store: LocalAgentConfigurationStore | None = None
    run_purpose: RunPurpose = RunPurpose.PRODUCTION
    agent_id: str | None = None
    agent_version_id: str | None = None
    draft_id: str | None = None
    allow_untrusted_web_supplement: bool = False
    published_agent_runtime_facts: PublishedAgentRuntimeFacts | None = None
    controlled_react_orchestrator: ControlledReActOrchestratorDependency | None = None
    controlled_react_snapshot_store: SnapshotStorePort | None = None
    controlled_react_observation_truth_store: ObservationTruthStorePort | None = None


def execute_agent_package_run(request: AgentPackageRunRequest) -> RunResult:
    """Execute one governed Agent Package run through the correct runtime."""

    manifest = request.manifest or load_agent_manifest(request.agent_yaml)
    if manifest.workflow.template != "react_enterprise_qa_v3":
        return run_with_langgraph(
            request.agent_yaml,
            question=request.question,
            runs_dir=request.runs_dir,
            conversation_context=request.conversation_context,
            run_id=request.run_id,
            store=request.store,
            checkpointer=request.checkpointer,
            manifest=manifest,
            knowledge_binding_resolver=request.knowledge_binding_resolver,
            resolved_knowledge_bindings=request.resolved_knowledge_bindings,
            configuration_store=request.configuration_store,
            run_purpose=request.run_purpose,
            agent_id=request.agent_id,
            agent_version_id=request.agent_version_id,
            draft_id=request.draft_id,
            allow_untrusted_web_supplement=request.allow_untrusted_web_supplement,
            published_agent_runtime_facts=request.published_agent_runtime_facts,
        )
    return _execute_controlled_react_v3_agent_package_run(request, manifest=manifest)


def _execute_controlled_react_v3_agent_package_run(
    request: AgentPackageRunRequest,
    *,
    manifest: AgentManifest,
) -> RunResult:
    if manifest.react is None:
        raise RuntimeError("react_enterprise_qa_v3 requires react configuration.")

    request.runs_dir.mkdir(parents=True, exist_ok=True)
    trace_path = request.runs_dir / "trace.jsonl"
    receipt_path = request.runs_dir / "governance_receipt.md"
    if trace_path.exists():
        trace_path.unlink()
    run_id = request.run_id or f"run_{uuid4().hex[:8]}"
    trace = TraceWriter(trace_path, run_id=run_id)
    _emit_controlled_react_run_started(
        trace,
        manifest=manifest,
        question=request.question,
    )
    stage_runtime_configuration = _resolve_workflow_stage_runtime_configuration(
        agent_yaml=request.agent_yaml,
        manifest=manifest,
        agent_id=request.agent_id,
        agent_version_id=request.agent_version_id,
        published_agent_runtime_facts=request.published_agent_runtime_facts,
    )
    execution_input = _workflow_template_execution_input(
        run_id=run_id,
        question=request.question,
        agent_id=request.agent_id,
        agent_version_id=request.agent_version_id,
        draft_id=request.draft_id,
        stage_runtime_configuration=stage_runtime_configuration,
        conversation_context=request.conversation_context,
    )
    invocation = compose_harness_invocation(
        request.agent_yaml,
        manifest=manifest,
        knowledge_binding_resolver=request.knowledge_binding_resolver,
        resolved_knowledge_bindings=request.resolved_knowledge_bindings,
        configuration_store=request.configuration_store,
    )
    orchestrator = request.controlled_react_orchestrator
    if orchestrator is None:
        orchestrator = build_controlled_react_orchestrator_for_invocation(
            invocation,
            snapshot_store=request.controlled_react_snapshot_store,
            observation_truth_store=request.controlled_react_observation_truth_store,
            trace=trace,
        )
    template = resolve_workflow_template(manifest.workflow.template)
    execution_result = orchestrator.start(
        ControlledReActStartRequest(
            run_id=run_id,
            template_name=manifest.workflow.template,
            template_descriptor_version=(
                manifest.workflow.template_descriptor_version or template.descriptor_version
            ),
            question=request.question,
            max_plan_rounds=manifest.react.max_plan_rounds,
            retrieval_max_queries=manifest.retrieval.max_queries,
        )
    ).model_copy(
        update={
            "agent_id": request.agent_id,
            "agent_version_id": request.agent_version_id,
            "draft_id": request.draft_id,
            "effective_stage_configuration_ref": (
                execution_input.effective_stage_configuration_ref
            ),
            "trace_summary_refs": (
                (execution_input.stage_configuration_source.reference,)
                if execution_input.stage_configuration_source.reference
                else ()
            ),
        }
    )
    emit_controlled_react_trace_projection(
        trace,
        manifest=manifest,
        execution_result=execution_result,
        agent_version_id=request.agent_version_id,
    )
    result = finalize_run(
        trace=trace,
        receipt_path=receipt_path,
        trace_path=trace_path,
        agent_name=manifest.name,
        question=request.question,
        outcome=execution_result.outcome,
        message=execution_result.final_output,
        store=request.store,
        run_purpose=request.run_purpose,
        agent_id=request.agent_id,
        agent_version_id=request.agent_version_id,
        draft_id=request.draft_id,
        final_output_stage_id=_final_output_stage_id(execution_result),
    )
    return result.model_copy(
        update={
            "workflow_template_execution_input": execution_input,
            "workflow_template_execution_result": execution_result,
        }
    )


def _final_output_stage_id(execution_result: WorkflowTemplateExecutionResult) -> str | None:
    if not execution_result.stage_results:
        return None
    return execution_result.stage_results[-1].stage_id


def _emit_controlled_react_run_started(
    trace: TraceWriter,
    *,
    manifest: AgentManifest,
    question: str,
) -> None:
    trace.emit(
        "run_started",
        status="ok",
        payload={
            "agent_name": manifest.name,
            "question": question,
            "template_name": manifest.workflow.template,
            "runtime": "controlled_react_orchestrator",
        },
    )


def emit_controlled_react_trace_projection(
    trace: TraceWriter,
    *,
    manifest: AgentManifest,
    execution_result: WorkflowTemplateExecutionResult,
    agent_version_id: str | None,
) -> None:
    trace.emit(
        "workflow_stage_configuration_trace_summary",
        status="ok",
        payload={
            "source": {
                "source_type": (
                    "published_agent_version" if agent_version_id is not None else "agent_manifest"
                ),
                "reference": (
                    f"published_version:{agent_version_id}"
                    if agent_version_id is not None
                    else str(manifest.name)
                ),
            },
            "template_name": execution_result.template_name,
            "template_descriptor_version": execution_result.template_descriptor_version,
            "stages": [
                {"stage_id": stage_result.stage_id}
                for stage_result in execution_result.stage_results
            ],
        },
    )
    for stage_result in execution_result.stage_results:
        _emit_controlled_react_stage_result(trace, stage_result)
    if execution_result.approval_pause is not None:
        _emit_controlled_react_approval_pause(
            trace,
            execution_result.approval_pause,
        )
    if execution_result.clarification_need is not None:
        _emit_controlled_react_clarification_requested(
            trace,
            execution_result.clarification_need,
        )


def _emit_controlled_react_stage_result(
    trace: TraceWriter,
    stage_result: WorkflowStageResult,
) -> None:
    if stage_result.stage_id == "tool_proposal_scope":
        trace.emit(
            "tool_proposal_scope",
            status="ok",
            payload={"stage_id": stage_result.stage_id, **dict(stage_result.summary)},
        )
    trace.emit(
        "workflow_stage_result",
        status=_trace_status_for_stage_result(stage_result),
        payload={
            "stage_id": stage_result.stage_id,
            "status": stage_result.status.value,
            "outcome": (stage_result.outcome.value if stage_result.outcome is not None else None),
            "summary": dict(stage_result.summary),
            "produced_fact_refs": list(stage_result.produced_fact_refs),
        },
    )


def _emit_controlled_react_approval_pause(
    trace: TraceWriter,
    approval_pause: ApprovalPause,
) -> None:
    summary = dict(approval_pause.summary)
    parameters = summary.get("parameters")
    payload = {
        "run_id": trace.run_id,
        "thread_id": trace.run_id,
        "approval_id": approval_pause.approval_id,
        "action_id": approval_pause.action_id,
        "tool_name": approval_pause.tool_name,
        "parameters": dict(parameters) if isinstance(parameters, Mapping) else {},
        "policy_decision": approval_pause.policy_decision.value,
        "checkpoint_ref": approval_pause.checkpoint_ref,
        "checkpoint_id": approval_pause.checkpoint_ref,
        "status": "requested",
        "expires_at": approval_pause.expires_at,
        "summary": summary,
        "stage_id": "tool_review",
    }
    trace.emit("approval_requested", status="waiting", payload=payload)
    trace.emit("pending_approval_created", status="waiting", payload=payload)


def _emit_controlled_react_clarification_requested(
    trace: TraceWriter,
    clarification_need: ClarificationNeed,
) -> None:
    trace.emit(
        "clarification_requested",
        status="waiting",
        payload={
            "stage_id": "clarification",
            "action_id": clarification_need.action_id,
            "missing_fields": list(clarification_need.missing_fields),
            "message": clarification_need.message,
            "summary": dict(clarification_need.summary),
        },
    )


def _trace_status_for_stage_result(
    stage_result: WorkflowStageResult,
) -> Literal["ok", "blocked", "waiting", "error"]:
    if stage_result.status is WorkflowStageStatus.BLOCKED:
        return "blocked"
    if stage_result.status is WorkflowStageStatus.WAITING:
        return "waiting"
    return "ok"
