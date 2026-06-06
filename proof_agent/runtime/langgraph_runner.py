from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from langgraph.checkpoint.memory import MemorySaver

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
from proof_agent.runtime.graph import build_enterprise_qa_graph
from proof_agent.runtime.react_graph import build_react_enterprise_qa_graph


def run_with_langgraph(
    agent_yaml: Path,
    *,
    question: str,
    runs_dir: Path,
    approved: bool | None = None,
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
) -> RunResult:
    """Runtime adapter that executes the Harness using a LangGraph StateGraph."""

    resolved_manifest = manifest or load_agent_manifest(agent_yaml)
    if resolved_manifest.workflow.template not in {"enterprise_qa", "react_enterprise_qa"}:
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"workflow template is not executable yet: {resolved_manifest.workflow.template}",
            "Use workflow.template: enterprise_qa or react_enterprise_qa.",
            artifact_path=agent_yaml,
        )
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

    if resolved_manifest.workflow.template == "enterprise_qa":
        builder = build_enterprise_qa_graph(
            invocation=invocation,
            trace=trace,
            approved=approved,
            conversation_context=conversation_context,
        )
    else:
        builder = build_react_enterprise_qa_graph(
            invocation=invocation,
            trace=trace,
            approved=approved,
            conversation_context=conversation_context,
        )

    if checkpointer is None:
        if (
            resolved_manifest.workflow.checkpointer
            and resolved_manifest.workflow.checkpointer.provider == "sqlite"
        ):
            if resolved_manifest.workflow.checkpointer.uri == "memory":
                checkpointer = MemorySaver()
            else:
                from langgraph.checkpoint.sqlite import SqliteSaver  # type: ignore[import-not-found]
                import sqlite3

                conn = sqlite3.connect(
                    (resolved_manifest.workflow.checkpointer.uri or "").replace("sqlite:///", "")
                )
                checkpointer = SqliteSaver(conn)
        else:
            checkpointer = MemorySaver()

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

    final_state = graph.invoke(state, config=config)  # type: ignore[call-overload]

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
