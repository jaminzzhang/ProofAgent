from __future__ import annotations

import json
from pathlib import Path
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from proof_agent.bootstrap.knowledge_resolution import KnowledgeBindingResolver
from proof_agent.bootstrap.composition import compose_harness_invocation
from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import (
    AgentManifest,
    ApprovalPause,
    ApprovalStatus,
    ContextAdmission,
    EvidenceChunk,
    PolicyDecisionType,
    PublishedAgentRuntimeFacts,
    ReceiptOutcome,
    ResolvedWorkflowStageRuntimeConfiguration,
    ResolvedKnowledgeBindingSet,
    RunPurpose,
    RunResult,
    TraceEventType,
    WorkflowStageConfigurationRuntimeSource,
    WorkflowStageConfigurationRuntimeSourceType,
    WorkflowStageResult,
    WorkflowStageStatus,
    WorkflowTemplateExecutionInput,
    WorkflowTemplateExecutionResult,
)
from proof_agent.contracts.conversation import context_admission_payload
from proof_agent.control.workflow.stage_configuration import (
    resolve_workflow_stage_runtime_configuration,
    summarize_workflow_stage_configuration,
)
from proof_agent.control.workflow.harness_helpers import (
    emit_model_error,
    finalize_run,
    is_model_error,
)
from proof_agent.errors import ProofAgentError
from proof_agent.observability.audit.trace import TraceWriter
from proof_agent.observability.storage.run_store import RunStore
from proof_agent.runtime.approval_resume import sync_checkpointer
from proof_agent.runtime.graph import build_enterprise_qa_graph
from proof_agent.runtime.react_graph import build_react_enterprise_qa_graph


def run_with_langgraph(
    agent_yaml: Path,
    *,
    question: str,
    runs_dir: Path,
    conversation_context: ContextAdmission | None = None,
    run_id: str | None = None,
    store: RunStore | None = None,
    checkpointer: Any | None = None,
    manifest: AgentManifest | None = None,
    knowledge_binding_resolver: KnowledgeBindingResolver | None = None,
    resolved_knowledge_bindings: ResolvedKnowledgeBindingSet | None = None,
    configuration_store: LocalAgentConfigurationStore | None = None,
    run_purpose: RunPurpose = RunPurpose.PRODUCTION,
    agent_id: str | None = None,
    agent_version_id: str | None = None,
    draft_id: str | None = None,
    allow_untrusted_web_supplement: bool = False,
    published_agent_runtime_facts: PublishedAgentRuntimeFacts | None = None,
) -> RunResult:
    """Runtime adapter that executes the Harness using a LangGraph StateGraph."""

    resolved_manifest = manifest or load_agent_manifest(agent_yaml)
    _ensure_executable_template(resolved_manifest, agent_yaml)
    runs_dir.mkdir(parents=True, exist_ok=True)
    trace_path = runs_dir / "trace.jsonl"
    receipt_path = runs_dir / "governance_receipt.md"
    if trace_path.exists():
        trace_path.unlink()
    actual_run_id = run_id or f"run_{uuid4().hex[:8]}"
    trace = TraceWriter(trace_path, run_id=actual_run_id)

    trace.emit("run_started", status="ok", payload={"manifest_path": str(agent_yaml)})
    trace.emit("manifest_loaded", status="ok", payload={"agent_name": resolved_manifest.name})
    if conversation_context is not None:
        trace.emit(
            "context_admission",
            status="ok" if conversation_context.admitted else "blocked",
            payload=context_admission_payload(conversation_context),
        )
    stage_runtime_configuration = _resolve_workflow_stage_runtime_configuration(
        agent_yaml=agent_yaml,
        manifest=resolved_manifest,
        agent_id=agent_id,
        agent_version_id=agent_version_id,
        published_agent_runtime_facts=published_agent_runtime_facts,
    )
    trace.emit(
        TraceEventType.WORKFLOW_STAGE_CONFIGURATION_TRACE_SUMMARY,
        status="ok",
        payload=stage_runtime_configuration.trace_summary.model_dump(mode="json"),
    )
    execution_input = _workflow_template_execution_input(
        run_id=actual_run_id,
        question=question,
        agent_id=agent_id,
        agent_version_id=agent_version_id,
        draft_id=draft_id,
        stage_runtime_configuration=stage_runtime_configuration,
        conversation_context=conversation_context,
    )
    try:
        invocation = compose_harness_invocation(
            agent_yaml,
            manifest=resolved_manifest,
            knowledge_binding_resolver=knowledge_binding_resolver,
            resolved_knowledge_bindings=resolved_knowledge_bindings,
            configuration_store=configuration_store,
        )
    except Exception as exc:
        if is_model_error(exc):
            emit_model_error(
                trace,
                resolved_manifest.model.provider or resolved_manifest.model.connection_id or "",
                resolved_manifest.model.name or "",
                exc,
            )
        raise
    for record in invocation.model_resolution_records:
        trace.emit(
            "model_connection_resolution",
            status="ok",
            payload=record.model_dump(mode="json"),
        )

    builder = _build_graph(
        manifest=resolved_manifest,
        invocation=invocation,
        trace=trace,
        execution_input=execution_input,
        conversation_context=conversation_context,
        allow_untrusted_web_supplement=allow_untrusted_web_supplement,
    )
    checkpointer = checkpointer or _create_checkpointer(resolved_manifest)
    graph = builder.compile(checkpointer=checkpointer)

    state = {
        "run_id": actual_run_id,
        "question": question,
        "messages": [],
        "step_count": 0,
        "tool_call_count": 0,
        "review_results": [],
        "stage_results": [],
        "stage_context_applications": [],
    }
    config = {"configurable": {"thread_id": actual_run_id}}

    final_state = graph.invoke(state, config=config)
    sync_checkpointer(checkpointer)
    interrupt_result = _approval_interrupt(final_state)
    if interrupt_result is not None:
        execution_result = _workflow_execution_result_from_interrupt(
            final_state,
            interrupt_payload=interrupt_result,
            invocation=invocation,
            question=question,
            run_id=actual_run_id,
            execution_input=execution_input,
            agent_id=agent_id,
            agent_version_id=agent_version_id,
            draft_id=draft_id,
        )
        result = _finalize_approval_interrupt(
            trace=trace,
            receipt_path=receipt_path,
            trace_path=trace_path,
            invocation=invocation,
            question=question,
            interrupt_payload=interrupt_result,
            store=store,
            run_purpose=run_purpose,
            agent_id=agent_id,
            agent_version_id=agent_version_id,
            draft_id=draft_id,
        )
        return result.model_copy(
            update={
                "workflow_template_execution_input": execution_input,
                "workflow_template_execution_result": execution_result,
            }
        )

    execution_result = _workflow_execution_result_from_state(
        final_state,
        invocation=invocation,
        question=question,
        run_id=actual_run_id,
        execution_input=execution_input,
        agent_id=agent_id,
        agent_version_id=agent_version_id,
        draft_id=draft_id,
    )

    result = finalize_run(
        trace=trace,
        receipt_path=receipt_path,
        trace_path=trace_path,
        agent_name=invocation.manifest.name,
        question=question,
        outcome=execution_result.outcome,
        message=execution_result.message,
        store=store,
        run_purpose=run_purpose,
        agent_id=agent_id,
        agent_version_id=agent_version_id,
        draft_id=draft_id,
    )
    return result.model_copy(
        update={
            "workflow_template_execution_input": execution_input,
            "workflow_template_execution_result": execution_result,
        }
    )


def resume_langgraph_approval(
    agent_yaml: Path,
    *,
    runs_dir: Path,
    run_id: str,
    question: str,
    approval_id: str,
    approved: bool,
    checkpointer: Any,
    actor: str = "local-user",
    store: RunStore | None = None,
    manifest: AgentManifest | None = None,
    knowledge_binding_resolver: KnowledgeBindingResolver | None = None,
    resolved_knowledge_bindings: ResolvedKnowledgeBindingSet | None = None,
    configuration_store: LocalAgentConfigurationStore | None = None,
    run_purpose: RunPurpose = RunPurpose.PRODUCTION,
    agent_id: str | None = None,
    agent_version_id: str | None = None,
    draft_id: str | None = None,
    allow_untrusted_web_supplement: bool = False,
    execution_input: WorkflowTemplateExecutionInput | None = None,
) -> RunResult:
    """Resume a LangGraph run from an approval interrupt."""

    resolved_manifest = manifest or load_agent_manifest(agent_yaml)
    _ensure_executable_template(resolved_manifest, agent_yaml)
    trace_path = runs_dir / "trace.jsonl"
    receipt_path = runs_dir / "governance_receipt.md"
    if not trace_path.exists():
        raise ProofAgentError(
            "PA_RUNTIME_001",
            f"trace not found for run resume: {run_id}",
            "Start the run and persist its approval checkpoint before resuming.",
            artifact_path=trace_path,
        )
    trace = TraceWriter(
        trace_path,
        run_id=run_id,
        initial_sequence=_latest_trace_sequence(trace_path),
    )
    invocation = compose_harness_invocation(
        agent_yaml,
        manifest=resolved_manifest,
        knowledge_binding_resolver=knowledge_binding_resolver,
        resolved_knowledge_bindings=resolved_knowledge_bindings,
        configuration_store=configuration_store,
    )
    if execution_input is None:
        stage_runtime_configuration = _resolve_workflow_stage_runtime_configuration(
            agent_yaml=agent_yaml,
            manifest=resolved_manifest,
            agent_id=agent_id,
            agent_version_id=agent_version_id,
            published_agent_runtime_facts=None,
        )
        execution_input = _workflow_template_execution_input(
            run_id=run_id,
            question=question,
            agent_id=agent_id,
            agent_version_id=agent_version_id,
            draft_id=draft_id,
            stage_runtime_configuration=stage_runtime_configuration,
            conversation_context=None,
        )
    builder = _build_graph(
        manifest=resolved_manifest,
        invocation=invocation,
        trace=trace,
        execution_input=execution_input,
        conversation_context=None,
        allow_untrusted_web_supplement=allow_untrusted_web_supplement,
    )
    graph = builder.compile(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": run_id}}
    final_state = graph.invoke(
        Command(resume={"approval_id": approval_id, "approved": approved, "actor": actor}),
        config=config,
    )
    sync_checkpointer(checkpointer)
    interrupt_result = _approval_interrupt(final_state)
    if interrupt_result is not None:
        execution_result = _workflow_execution_result_from_interrupt(
            final_state,
            interrupt_payload=interrupt_result,
            invocation=invocation,
            question=question,
            run_id=run_id,
            execution_input=execution_input,
            agent_id=agent_id,
            agent_version_id=agent_version_id,
            draft_id=draft_id,
        )
        result = _finalize_approval_interrupt(
            trace=trace,
            receipt_path=receipt_path,
            trace_path=trace_path,
            invocation=invocation,
            question=question,
            interrupt_payload=interrupt_result,
            store=store,
            run_purpose=run_purpose,
            agent_id=agent_id,
            agent_version_id=agent_version_id,
            draft_id=draft_id,
        )
        return result.model_copy(
            update={
                "workflow_template_execution_input": execution_input,
                "workflow_template_execution_result": execution_result,
            }
        )

    execution_result = _workflow_execution_result_from_state(
        final_state,
        invocation=invocation,
        question=question,
        run_id=run_id,
        execution_input=execution_input,
        agent_id=agent_id,
        agent_version_id=agent_version_id,
        draft_id=draft_id,
    )
    result = finalize_run(
        trace=trace,
        receipt_path=receipt_path,
        trace_path=trace_path,
        agent_name=invocation.manifest.name,
        question=question,
        outcome=execution_result.outcome,
        message=execution_result.message,
        store=store,
        run_purpose=run_purpose,
        agent_id=agent_id,
        agent_version_id=agent_version_id,
        draft_id=draft_id,
    )
    return result.model_copy(
        update={
            "workflow_template_execution_input": execution_input,
            "workflow_template_execution_result": execution_result,
        }
    )


def _ensure_executable_template(manifest: AgentManifest, agent_yaml: Path) -> None:
    if manifest.workflow.template not in {
        "enterprise_qa",
        "react_enterprise_qa",
        "react_enterprise_qa_v2",
    }:
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"workflow template is not executable yet: {manifest.workflow.template}",
            "Use workflow.template: enterprise_qa, react_enterprise_qa, or react_enterprise_qa_v2.",
            artifact_path=agent_yaml,
        )


def _build_graph(
    *,
    manifest: AgentManifest,
    invocation: Any,
    trace: TraceWriter,
    execution_input: WorkflowTemplateExecutionInput,
    conversation_context: ContextAdmission | None,
    allow_untrusted_web_supplement: bool,
) -> Any:
    if manifest.workflow.template == "enterprise_qa":
        return build_enterprise_qa_graph(
            invocation=invocation,
            trace=trace,
            conversation_context=conversation_context,
            allow_untrusted_web_supplement=allow_untrusted_web_supplement,
        )
    return build_react_enterprise_qa_graph(
        invocation=invocation,
        trace=trace,
        execution_input=execution_input,
        conversation_context=conversation_context,
        allow_untrusted_web_supplement=allow_untrusted_web_supplement,
    )


def _workflow_execution_result_from_state(
    final_state: Mapping[str, Any],
    *,
    invocation: Any,
    question: str,
    run_id: str,
    execution_input: WorkflowTemplateExecutionInput,
    agent_id: str | None,
    agent_version_id: str | None,
    draft_id: str | None,
) -> WorkflowTemplateExecutionResult:
    outcome = _receipt_outcome(final_state.get("governance_refusal"))
    message = str(final_state.get("governance_message") or "")
    if outcome is None:
        outcome = ReceiptOutcome.REFUSED_NO_EVIDENCE
        message = "Workflow ended unexpectedly without an outcome."
    final_output = str(final_state.get("final_output") or message)
    return WorkflowTemplateExecutionResult(
        run_id=run_id,
        template_name=invocation.template.name,
        template_descriptor_version=invocation.template.descriptor_version,
        outcome=outcome,
        final_output=final_output,
        message=message,
        agent_id=agent_id,
        agent_version_id=agent_version_id,
        draft_id=draft_id,
        effective_stage_configuration_ref=execution_input.effective_stage_configuration_ref,
        evidence=tuple(
            EvidenceChunk.model_validate(item)
            for item in final_state.get("evidence", ())
        ),
        stage_results=tuple(
            WorkflowStageResult.model_validate(item)
            for item in final_state.get("stage_results", ())
        ),
        intent_resolution=(
            final_state.get("intent_resolution")
            if isinstance(final_state.get("intent_resolution"), Mapping)
            else None
        ),
        reasoning_summary=(
            final_state.get("reasoning_summary")
            if isinstance(final_state.get("reasoning_summary"), Mapping)
            else None
        ),
        review_results=tuple(
            item for item in final_state.get("review_results", ()) if isinstance(item, Mapping)
        ),
        stage_context_applications=_stage_context_applications_from_state(final_state),
        trace_summary_refs=(
            (execution_input.stage_configuration_source.reference,)
            if execution_input.stage_configuration_source.reference
            else ()
        ),
    )


def _workflow_execution_result_from_interrupt(
    final_state: Mapping[str, Any],
    *,
    interrupt_payload: Mapping[str, Any],
    invocation: Any,
    question: str,
    run_id: str,
    execution_input: WorkflowTemplateExecutionInput,
    agent_id: str | None,
    agent_version_id: str | None,
    draft_id: str | None,
) -> WorkflowTemplateExecutionResult:
    message = str(
        final_state.get("governance_message")
        or _approval_waiting_message(interrupt_payload)
    )
    final_output = str(final_state.get("final_output") or message)
    return WorkflowTemplateExecutionResult(
        run_id=run_id,
        template_name=invocation.template.name,
        template_descriptor_version=invocation.template.descriptor_version,
        outcome=ReceiptOutcome.WAITING_FOR_APPROVAL,
        final_output=final_output,
        message=message,
        agent_id=agent_id,
        agent_version_id=agent_version_id,
        draft_id=draft_id,
        effective_stage_configuration_ref=execution_input.effective_stage_configuration_ref,
        approval_pause=_approval_pause_from_interrupt(interrupt_payload),
        evidence=tuple(
            EvidenceChunk.model_validate(item)
            for item in final_state.get("evidence", ())
        ),
        stage_results=_stage_results_from_interrupt(final_state, interrupt_payload),
        intent_resolution=(
            final_state.get("intent_resolution")
            if isinstance(final_state.get("intent_resolution"), Mapping)
            else None
        ),
        reasoning_summary=(
            final_state.get("reasoning_summary")
            if isinstance(final_state.get("reasoning_summary"), Mapping)
            else None
        ),
        review_results=tuple(
            item for item in final_state.get("review_results", ()) if isinstance(item, Mapping)
        ),
        stage_context_applications=_stage_context_applications_from_state(final_state),
        trace_summary_refs=(
            (execution_input.stage_configuration_source.reference,)
            if execution_input.stage_configuration_source.reference
            else ()
        ),
    )


def _approval_pause_from_interrupt(
    interrupt_payload: Mapping[str, Any],
) -> ApprovalPause:
    pending = interrupt_payload.get("pending_approval")
    requested = interrupt_payload.get("approval_requested")
    pending_payload = pending if isinstance(pending, Mapping) else {}
    requested_payload = requested if isinstance(requested, Mapping) else {}
    policy_decision = _policy_decision(
        pending_payload.get("policy_decision")
        or PolicyDecisionType.REQUIRE_APPROVAL.value
    )
    parameters = pending_payload.get("parameters")
    parameter_count = len(parameters) if isinstance(parameters, Mapping) else 0
    return ApprovalPause(
        approval_id=str(
            pending_payload.get("approval_id")
            or requested_payload.get("approval_id")
            or ""
        ),
        action_id=str(pending_payload.get("action_id") or ""),
        tool_name=str(
            pending_payload.get("tool_name")
            or requested_payload.get("tool_name")
            or "unknown"
        ),
        policy_decision=policy_decision,
        checkpoint_ref=str(
            pending_payload.get("checkpoint_id")
            or pending_payload.get("checkpoint_ref")
            or ""
        ),
        expires_at=(
            str(pending_payload["expires_at"])
            if pending_payload.get("expires_at") is not None
            else None
        ),
        summary={
            "status": str(
                pending_payload.get("status")
                or requested_payload.get("state")
                or "requested"
            ),
            "parameter_count": parameter_count,
        },
    )


def _stage_results_from_interrupt(
    final_state: Mapping[str, Any],
    interrupt_payload: Mapping[str, Any],
) -> tuple[WorkflowStageResult, ...]:
    stage_results = tuple(
        WorkflowStageResult.model_validate(item)
        for item in final_state.get("stage_results", ())
    )
    if any(
        stage.stage_id == "tool" and stage.status is WorkflowStageStatus.WAITING
        for stage in stage_results
    ):
        return stage_results
    return (*stage_results, _tool_waiting_stage_result_from_interrupt(interrupt_payload))


def _tool_waiting_stage_result_from_interrupt(
    interrupt_payload: Mapping[str, Any],
) -> WorkflowStageResult:
    pause = _approval_pause_from_interrupt(interrupt_payload)
    return WorkflowStageResult(
        stage_id="tool",
        status=WorkflowStageStatus.WAITING,
        outcome=ReceiptOutcome.WAITING_FOR_APPROVAL,
        summary={
            "approval_id": pause.approval_id,
            "tool_name": pause.tool_name,
            "state": ApprovalStatus.REQUESTED.value,
            "policy_decision": pause.policy_decision.value,
        },
        produced_fact_refs=("approval_pause",),
    )


def _policy_decision(value: Any) -> PolicyDecisionType:
    try:
        return PolicyDecisionType(str(value))
    except ValueError:
        return PolicyDecisionType.REQUIRE_APPROVAL


def _approval_waiting_message(interrupt_payload: Mapping[str, Any]) -> str:
    pending = interrupt_payload.get("pending_approval")
    requested = interrupt_payload.get("approval_requested")
    pending_payload = pending if isinstance(pending, Mapping) else {}
    requested_payload = requested if isinstance(requested, Mapping) else {}
    tool_name = str(
        pending_payload.get("tool_name")
        or requested_payload.get("tool_name")
        or "customer_lookup"
    )
    return f"Waiting for approval before {tool_name} can execute."


def _stage_context_applications_from_state(
    final_state: Mapping[str, Any],
) -> tuple[Mapping[str, Any], ...]:
    applications = final_state.get("stage_context_applications", ())
    if not isinstance(applications, list | tuple):
        return ()
    return tuple(item for item in applications if isinstance(item, Mapping))


def _resolve_workflow_stage_runtime_configuration(
    *,
    agent_yaml: Path,
    manifest: AgentManifest,
    agent_id: str | None,
    agent_version_id: str | None,
    published_agent_runtime_facts: PublishedAgentRuntimeFacts | None,
) -> ResolvedWorkflowStageRuntimeConfiguration:
    source = _workflow_stage_configuration_source(
        manifest=manifest,
        agent_version_id=agent_version_id,
    )
    if published_agent_runtime_facts is not None:
        _require_matching_published_agent_runtime_facts(
            agent_id=agent_id,
            agent_version_id=agent_version_id,
            facts=published_agent_runtime_facts,
            artifact_path=agent_yaml,
        )
        return ResolvedWorkflowStageRuntimeConfiguration(
            workflow_stage_availability=(
                published_agent_runtime_facts.workflow_stage_availability
            ),
            effective_stage_configuration=(
                published_agent_runtime_facts.effective_stage_configuration
            ),
            configuration_source=source,
            trace_summary=summarize_workflow_stage_configuration(
                published_agent_runtime_facts.effective_stage_configuration,
                source=source,
            ),
        )
    resolved = resolve_workflow_stage_runtime_configuration(
        agent_yaml.read_text(encoding="utf-8"),
        source=source,
    )
    if resolved is None:
        raise ProofAgentError(
            "PA_CONFIG_002",
            "workflow stage runtime configuration could not be resolved",
            "Use Agent Contract YAML with workflow.template and capabilities.",
            artifact_path=agent_yaml,
        )
    return resolved


def _require_matching_published_agent_runtime_facts(
    *,
    agent_id: str | None,
    agent_version_id: str | None,
    facts: PublishedAgentRuntimeFacts,
    artifact_path: Path,
) -> None:
    if agent_id is not None and facts.agent_id != agent_id:
        raise ProofAgentError(
            "PA_RUNTIME_001",
            "Published Agent runtime facts do not match the requested Agent",
            "Use runtime facts captured from the selected Published Agent Version.",
            artifact_path=artifact_path,
        )
    if agent_version_id is not None and facts.agent_version_id != agent_version_id:
        raise ProofAgentError(
            "PA_RUNTIME_001",
            "Published Agent runtime facts do not match the requested Agent Version",
            "Use runtime facts captured from the selected Published Agent Version.",
            artifact_path=artifact_path,
        )


def _workflow_stage_configuration_source(
    *,
    manifest: AgentManifest,
    agent_version_id: str | None,
) -> WorkflowStageConfigurationRuntimeSource:
    if agent_version_id:
        return WorkflowStageConfigurationRuntimeSource(
            source_type=WorkflowStageConfigurationRuntimeSourceType.PUBLISHED_AGENT_VERSION,
            reference=f"published_version:{agent_version_id}:effective_workflow_stage_configuration",
        )
    return WorkflowStageConfigurationRuntimeSource(
        source_type=WorkflowStageConfigurationRuntimeSourceType.PACKAGE_LOCAL_LATEST,
        reference=f"package_local:{manifest.name}",
    )


def _workflow_template_execution_input(
    *,
    run_id: str,
    question: str,
    agent_id: str | None,
    agent_version_id: str | None,
    draft_id: str | None,
    stage_runtime_configuration: ResolvedWorkflowStageRuntimeConfiguration,
    conversation_context: ContextAdmission | None,
) -> WorkflowTemplateExecutionInput:
    return WorkflowTemplateExecutionInput(
        run_id=run_id,
        template_name=stage_runtime_configuration.effective_stage_configuration.template_name,
        template_descriptor_version=(
            stage_runtime_configuration
            .effective_stage_configuration
            .template_descriptor_version
        ),
        question=question,
        agent_id=agent_id,
        agent_version_id=agent_version_id,
        draft_id=draft_id,
        effective_stage_configuration_ref=(
            stage_runtime_configuration.configuration_source.reference
        ),
        workflow_stage_availability=(
            stage_runtime_configuration.workflow_stage_availability
        ),
        effective_stage_configuration=(
            stage_runtime_configuration.effective_stage_configuration
        ),
        stage_configuration_source=(
            stage_runtime_configuration.configuration_source
        ),
        conversation_context_summary=_conversation_context_summary(conversation_context),
    )


def _conversation_context_summary(
    conversation_context: ContextAdmission | None,
) -> Mapping[str, Any]:
    if conversation_context is None:
        return {}
    return context_admission_payload(conversation_context)


def _receipt_outcome(value: Any) -> ReceiptOutcome | None:
    if isinstance(value, ReceiptOutcome):
        return value
    if isinstance(value, str) and value:
        return ReceiptOutcome(value)
    return None


def _create_checkpointer(manifest: AgentManifest) -> Any:
    if manifest.workflow.checkpointer and manifest.workflow.checkpointer.provider == "sqlite":
        if manifest.workflow.checkpointer.uri == "memory":
            return MemorySaver()
        from langgraph.checkpoint.sqlite import SqliteSaver  # type: ignore[import-not-found]
        import sqlite3

        conn = sqlite3.connect(
            (manifest.workflow.checkpointer.uri or "").replace("sqlite:///", "")
        )
        return SqliteSaver(conn)
    return MemorySaver()


def _approval_interrupt(final_state: Any) -> dict[str, Any] | None:
    interrupts = final_state.get("__interrupt__") if isinstance(final_state, dict) else None
    if not interrupts:
        return None
    for item in interrupts:
        value = getattr(item, "value", item)
        if isinstance(value, dict) and value.get("kind") == "tool_approval":
            return value
    return None


def _finalize_approval_interrupt(
    *,
    trace: TraceWriter,
    receipt_path: Path,
    trace_path: Path,
    invocation: Any,
    question: str,
    interrupt_payload: dict[str, Any],
    store: RunStore | None,
    run_purpose: RunPurpose,
    agent_id: str | None,
    agent_version_id: str | None,
    draft_id: str | None,
) -> RunResult:
    requested = interrupt_payload.get("approval_requested")
    if isinstance(requested, dict):
        trace.emit("approval_requested", status="waiting", payload=requested)
    pending = interrupt_payload.get("pending_approval")
    if isinstance(pending, dict):
        trace.emit("pending_approval_created", status="waiting", payload=pending)
    return finalize_run(
        trace=trace,
        receipt_path=receipt_path,
        trace_path=trace_path,
        agent_name=invocation.manifest.name,
        question=question,
        outcome=ReceiptOutcome.WAITING_FOR_APPROVAL,
        message="Waiting for approval before customer_lookup can execute.",
        store=store,
        run_purpose=run_purpose,
        agent_id=agent_id,
        agent_version_id=agent_version_id,
        draft_id=draft_id,
    )


def _latest_trace_sequence(trace_path: Path) -> int:
    sequence = 0
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            try:
                sequence = max(sequence, int(event.get("sequence") or 0))
            except (TypeError, ValueError):
                continue
    return sequence
