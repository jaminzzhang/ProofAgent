from __future__ import annotations

import json
from pathlib import Path
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
    ContextAdmission,
    ReceiptOutcome,
    ResolvedKnowledgeBindingSet,
    RunPurpose,
    RunResult,
)
from proof_agent.contracts.conversation import context_admission_payload
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
    }
    config = {"configurable": {"thread_id": actual_run_id}}

    final_state = graph.invoke(state, config=config)
    sync_checkpointer(checkpointer)
    interrupt_result = _approval_interrupt(final_state)
    if interrupt_result is not None:
        return _finalize_approval_interrupt(
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

    outcome = final_state.get("governance_refusal")
    message = final_state.get("governance_message")

    if not outcome:
        outcome = ReceiptOutcome.REFUSED_NO_EVIDENCE
        message = "Workflow ended unexpectedly without an outcome."

    return finalize_run(
        trace=trace,
        receipt_path=receipt_path,
        trace_path=trace_path,
        agent_name=invocation.manifest.name,
        question=question,
        outcome=outcome,
        message=message,
        store=store,
        run_purpose=run_purpose,
        agent_id=agent_id,
        agent_version_id=agent_version_id,
        draft_id=draft_id,
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
    builder = _build_graph(
        manifest=resolved_manifest,
        invocation=invocation,
        trace=trace,
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
        return _finalize_approval_interrupt(
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

    outcome = final_state.get("governance_refusal")
    message = final_state.get("governance_message")
    if not outcome:
        outcome = ReceiptOutcome.REFUSED_NO_EVIDENCE
        message = "Workflow ended unexpectedly without an outcome."
    return finalize_run(
        trace=trace,
        receipt_path=receipt_path,
        trace_path=trace_path,
        agent_name=invocation.manifest.name,
        question=question,
        outcome=outcome,
        message=message,
        store=store,
        run_purpose=run_purpose,
        agent_id=agent_id,
        agent_version_id=agent_version_id,
        draft_id=draft_id,
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
        conversation_context=conversation_context,
        allow_untrusted_web_supplement=allow_untrusted_web_supplement,
    )


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
