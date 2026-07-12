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
    AgentContextConfiguration,
    ApprovalPause,
    ClarificationNeed,
    ContextAdmission,
    MemoryRecallAdmission,
    MemoryRecallWorkingPayload,
    PublishedAgentRuntimeFacts,
    ResolvedKnowledgeBindingSet,
    RunStartContextAssembly,
    RunPurpose,
    RunResult,
    TraceEventType,
    WorkflowStageResult,
    WorkflowStageStatus,
    WorkflowTemplateExecutionResult,
)
from proof_agent.contracts.conversation import context_admission_payload
from proof_agent.control.context_assembler import assemble_run_start_context_from_admission
from proof_agent.control.context_budget import InMemoryContextBudgetCalibrationStore
from proof_agent.control.workflow.controlled_react import (
    ControlledReActStartRequest,
    build_controlled_react_orchestrator_for_invocation,
)
from proof_agent.control.workflow.controlled_react.execution_input import (
    build_workflow_template_execution_input,
    resolve_workflow_stage_runtime_configuration,
)
from proof_agent.control.workflow.controlled_react.stage_contexts import (
    build_controlled_react_stage_contexts,
)
from proof_agent.control.workflow.controlled_react.ports import SnapshotStorePort
from proof_agent.control.workflow.controlled_react.ports import ObservationTruthStorePort
from proof_agent.control.workflow.harness_helpers import (
    finalize_run,
)
from proof_agent.control.workflow.templates import resolve_workflow_template
from proof_agent.control.workflow.templates import WorkflowTemplate
from proof_agent.errors import ProofAgentError
from proof_agent.observability.audit.trace import TraceWriter
from proof_agent.observability.storage.run_store import RunStore


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
    memory_recall_admissions: tuple[MemoryRecallAdmission, ...] = ()
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
    context_budget_calibration_store: InMemoryContextBudgetCalibrationStore | None = None


def execute_agent_package_run(request: AgentPackageRunRequest) -> RunResult:
    """Execute one governed Agent Package run through the correct runtime."""

    manifest = request.manifest or load_agent_manifest(request.agent_yaml)
    template = resolve_workflow_template(manifest.workflow.template)
    if manifest.workflow.runtime != "controlled_react":
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"unsupported workflow runtime: {manifest.workflow.runtime}",
            "Use workflow.runtime: controlled_react for react_enterprise_qa_v3.",
            artifact_path=request.agent_yaml,
        )
    run_id = request.run_id or f"run_{uuid4().hex[:8]}"
    run_start_context = _run_start_context_assembly(
        run_id=run_id,
        conversation_context=request.conversation_context,
        memory_recall_admissions=request.memory_recall_admissions,
        context_config=manifest.context,
        context_budget_calibration_store=request.context_budget_calibration_store,
    )
    return _execute_controlled_react_v3_agent_package_run(
        request,
        manifest=manifest,
        template=template,
        run_id=run_id,
        run_start_context=run_start_context,
    )


def _execute_controlled_react_v3_agent_package_run(
    request: AgentPackageRunRequest,
    *,
    manifest: AgentManifest,
    template: WorkflowTemplate,
    run_id: str,
    run_start_context: RunStartContextAssembly | None,
) -> RunResult:
    if manifest.react is None:
        raise RuntimeError("react_enterprise_qa_v3 requires react configuration.")

    request.runs_dir.mkdir(parents=True, exist_ok=True)
    trace_path = request.runs_dir / "trace.jsonl"
    receipt_path = request.runs_dir / "governance_receipt.md"
    if trace_path.exists():
        trace_path.unlink()
    trace = TraceWriter(trace_path, run_id=run_id)
    _emit_controlled_react_run_started(
        trace,
        manifest=manifest,
        question=request.question,
    )
    _emit_run_start_context_trace(trace, run_start_context)
    stage_runtime_configuration = resolve_workflow_stage_runtime_configuration(
        agent_yaml=request.agent_yaml,
        manifest=manifest,
        agent_id=request.agent_id,
        agent_version_id=request.agent_version_id,
        published_agent_runtime_facts=request.published_agent_runtime_facts,
    )
    execution_input = build_workflow_template_execution_input(
        run_id=run_id,
        question=request.question,
        agent_id=request.agent_id,
        agent_version_id=request.agent_version_id,
        draft_id=request.draft_id,
        stage_runtime_configuration=stage_runtime_configuration,
        conversation_context=request.conversation_context,
        run_start_context=run_start_context,
    )
    invocation = compose_harness_invocation(
        request.agent_yaml,
        manifest=manifest,
        knowledge_binding_resolver=request.knowledge_binding_resolver,
        resolved_knowledge_bindings=request.resolved_knowledge_bindings,
        configuration_store=request.configuration_store,
        context_budget_calibration_store=request.context_budget_calibration_store,
    )
    stage_contexts, initial_stage_context_applications = build_controlled_react_stage_contexts(
        invocation=invocation,
        execution_input=execution_input,
        conversation_context=request.conversation_context,
    )
    configured_stage_context_applications = list(initial_stage_context_applications)

    def apply_business_flow_stage_contexts(selected_pack_id: str) -> None:
        admitted_contexts, admitted_applications = build_controlled_react_stage_contexts(
            invocation=invocation,
            execution_input=execution_input,
            conversation_context=request.conversation_context,
            selected_business_flow_skill_pack_id=selected_pack_id,
        )
        stage_contexts.clear()
        stage_contexts.update(admitted_contexts)
        configured_stage_context_applications.clear()
        configured_stage_context_applications.extend(admitted_applications)

    for record in invocation.model_resolution_records:
        trace.emit(
            TraceEventType.MODEL_CONNECTION_RESOLUTION,
            status="ok",
            payload=record.model_dump(mode="json"),
        )
    orchestrator = request.controlled_react_orchestrator
    if orchestrator is None:
        orchestrator = build_controlled_react_orchestrator_for_invocation(
            invocation,
            snapshot_store=request.controlled_react_snapshot_store,
            observation_truth_store=request.controlled_react_observation_truth_store,
            trace=trace,
            stage_contexts=stage_contexts,
            business_flow_admission_callback=apply_business_flow_stage_contexts,
        )
    execution_result = orchestrator.start(
        ControlledReActStartRequest(
            run_id=run_id,
            template_name=manifest.workflow.template,
            template_descriptor_version=(
                manifest.workflow.template_descriptor_version or template.descriptor_version
            ),
            question=request.question,
            conversation_context=request.conversation_context,
            memory_recall_payloads=_memory_recall_working_payloads(run_start_context),
            max_plan_rounds=manifest.react.max_plan_rounds,
            retrieval_max_queries=manifest.retrieval.max_queries,
        )
    )
    visited_stage_ids = {stage.stage_id for stage in execution_result.stage_results}
    stage_context_applications = tuple(
        application
        for application in configured_stage_context_applications
        if application.get("stage_id") in visited_stage_ids
    )
    execution_result = execution_result.model_copy(
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
            "stage_context_applications": stage_context_applications,
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


def _run_start_context_assembly(
    *,
    run_id: str,
    conversation_context: ContextAdmission | None,
    memory_recall_admissions: tuple[MemoryRecallAdmission, ...],
    context_config: AgentContextConfiguration | None,
    context_budget_calibration_store: InMemoryContextBudgetCalibrationStore | None,
) -> RunStartContextAssembly | None:
    if conversation_context is None and not memory_recall_admissions:
        return None
    return assemble_run_start_context_from_admission(
        run_id=run_id,
        conversation_context=conversation_context or ContextAdmission(admitted=False),
        memory_recall_admissions=memory_recall_admissions,
        context_config=context_config,
        context_budget_calibration_store=context_budget_calibration_store,
    )


def _memory_recall_working_payloads(
    run_start_context: RunStartContextAssembly | None,
) -> tuple[MemoryRecallWorkingPayload, ...]:
    if run_start_context is None:
        return ()
    return tuple(
        admission.working_payload
        for admission in run_start_context.memory_recall_admissions
        if admission.admitted and admission.working_payload is not None
    )


def _emit_run_start_context_trace(
    trace: TraceWriter,
    run_start_context: RunStartContextAssembly | None,
) -> None:
    if run_start_context is None:
        return
    if run_start_context.conversation_context is not None:
        trace.emit(
            TraceEventType.CONTEXT_ADMISSION,
            status="ok" if run_start_context.conversation_context.admitted else "blocked",
            payload=context_admission_payload(run_start_context.conversation_context),
        )
    for admission in run_start_context.memory_recall_admissions:
        trace.emit(
            TraceEventType.MEMORY_RECALL_SUMMARY,
            status="ok" if admission.admitted else "blocked",
            payload=admission.trace_summary().model_dump(mode="json"),
        )
    trace.emit(
        TraceEventType.CONTEXT_ASSEMBLY_SUMMARY,
        status="ok",
        payload=run_start_context.trace_safe_summary.model_dump(mode="json"),
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
    for application in execution_result.stage_context_applications:
        trace.emit(
            "workflow_stage_context_applied",
            status="ok",
            payload=dict(application),
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
