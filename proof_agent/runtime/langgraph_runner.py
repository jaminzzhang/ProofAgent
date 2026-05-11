from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from langgraph.checkpoint.memory import MemorySaver

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.contracts import ReceiptOutcome, RunResult
from proof_agent.control.workflow.orchestrator import _finalize
from proof_agent.observability.audit.trace import TraceWriter
from proof_agent.observability.storage.run_store import RunStore
from proof_agent.runtime.graph import build_enterprise_qa_graph


def run_with_langgraph(
    agent_yaml: Path,
    *,
    question: str,
    runs_dir: Path,
    approved: bool | None = None,
    run_id: str | None = None,
    store: RunStore | None = None,
    checkpointer: Any | None = None,
) -> RunResult:
    """Runtime adapter that executes the Harness using a LangGraph StateGraph."""
    
    manifest = load_agent_manifest(agent_yaml)
    runs_dir.mkdir(parents=True, exist_ok=True)
    trace_path = runs_dir / "trace.jsonl"
    receipt_path = runs_dir / "governance_receipt.md"
    if trace_path.exists():
        trace_path.unlink()
    actual_run_id = run_id or f"run_{uuid4().hex[:8]}"
    trace = TraceWriter(trace_path, run_id=actual_run_id)

    trace.emit("run_started", status="ok", payload={"manifest_path": str(agent_yaml)})
    trace.emit("manifest_loaded", status="ok", payload={"agent_name": manifest.name})

    builder = build_enterprise_qa_graph(
        manifest_path=str(agent_yaml),
        trace=trace,
        approved=approved,
    )
    
    if checkpointer is None:
        if manifest.workflow.checkpointer and manifest.workflow.checkpointer.provider == "sqlite":
            if manifest.workflow.checkpointer.uri == "memory":
                checkpointer = MemorySaver()
            else:
                from langgraph.checkpoint.sqlite import SqliteSaver  # type: ignore[import-not-found]
                import sqlite3
                conn = sqlite3.connect((manifest.workflow.checkpointer.uri or "").replace("sqlite:///", ""))
                checkpointer = SqliteSaver(conn)
        else:
            checkpointer = MemorySaver()

    graph = builder.compile(checkpointer=checkpointer)
    
    state = {
        "run_id": actual_run_id,
        "question": question,
        "messages": [],
    }
    config = {"configurable": {"thread_id": actual_run_id}}

    final_state = graph.invoke(state, config=config)  # type: ignore[call-overload]

    outcome = final_state.get("governance_refusal")
    message = final_state.get("governance_message")

    if not outcome:
        outcome = ReceiptOutcome.REFUSED_NO_EVIDENCE
        message = "Workflow ended unexpectedly without an outcome."

    return _finalize(
        trace=trace,
        receipt_path=receipt_path,
        trace_path=trace_path,
        agent_name="enterprise_qa",
        question=question,
        outcome=outcome,
        message=message,
        store=store,
    )
