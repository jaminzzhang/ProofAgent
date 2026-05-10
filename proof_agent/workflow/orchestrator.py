from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from proof_agent.audit.receipt import generate_receipt
from proof_agent.audit.trace import TraceWriter
from proof_agent.config.loader import load_agent_manifest
from proof_agent.contracts import ApprovalStatus, ReceiptOutcome, RunResult
from proof_agent.demo.deterministic_provider import DeterministicProvider
from proof_agent.demo.scenarios import TOOL_REQUIRED_QUESTION, UNSUPPORTED_QUESTION
from proof_agent.knowledge.local_provider import LocalKnowledgeProvider
from proof_agent.memory.session import SessionMemory
from proof_agent.policy.engine import PolicyEngine
from proof_agent.tools.approval import create_approval_state
from proof_agent.tools.gateway import ToolGateway
from proof_agent.validators.evidence import evaluate_evidence


def run_enterprise_qa(
    agent_yaml: Path,
    *,
    question: str,
    runs_dir: Path,
    approved: bool | None = None,
) -> RunResult:
    """Run the local Enterprise QA harness and write trace/receipt artifacts."""

    manifest = load_agent_manifest(agent_yaml)
    runs_dir.mkdir(parents=True, exist_ok=True)
    trace_path = runs_dir / "trace.jsonl"
    receipt_path = runs_dir / "governance_receipt.md"
    if trace_path.exists():
        trace_path.unlink()
    run_id = f"run_{uuid4().hex[:8]}"
    trace = TraceWriter(trace_path, run_id=run_id)

    trace.emit("run_started", status="ok", payload={"manifest_path": str(agent_yaml)})
    trace.emit("manifest_loaded", status="ok", payload={"agent_name": manifest.name})

    # Retrieval is still policy-gated even in the deterministic local demo.
    policy = PolicyEngine.from_file(manifest.policy.file)
    retrieval_decision = policy.evaluate("before_retrieval", {"question": question})
    _emit_policy(trace, retrieval_decision)

    evidence = LocalKnowledgeProvider(manifest.knowledge.path).retrieve(question, top_k=2)
    if question == UNSUPPORTED_QUESTION:
        # Force a no-evidence path so refusal behavior is reproducible in tests and demos.
        evidence = ()
    trace.emit(
        "retrieval_result",
        status="ok",
        payload={"chunk_count": len(evidence), "sources": [chunk.source for chunk in evidence]},
    )

    evidence_result = evaluate_evidence(evidence, min_count=1, min_score=0.2)
    trace.emit(
        "evidence_evaluation",
        status="ok" if evidence_result.status == "passed" else "blocked",
        payload={
            "validator_name": evidence_result.validator_name,
            "status": evidence_result.status.value,
            "metadata": dict(evidence_result.metadata),
        },
    )

    if question == TOOL_REQUIRED_QUESTION:
        # Tool-required questions leave the normal answer path and exercise approval gating.
        return _handle_tool_question(
            manifest_tools_file=manifest.tools.file,
            trace=trace,
            receipt_path=receipt_path,
            trace_path=trace_path,
            question=question,
            approved=approved,
        )

    answer_decision = policy.evaluate(
        "before_answer",
        {
            "accepted_evidence_count": evidence_result.metadata["accepted_count"],
            "citations_present": bool(evidence),
        },
    )
    _emit_policy(trace, answer_decision)

    memory = SessionMemory(deny_fields={"access_token", "customer_phone", "provider_api_key"})
    # v1 stores only a harmless session summary to demonstrate memory policy checks.
    memory_result = memory.write({"summary": f"Question: {question}"})
    trace.emit(
        "memory_write_decision",
        status="ok" if memory_result.status == "passed" else "blocked",
        payload={"status": memory_result.status.value, "metadata": dict(memory_result.metadata)},
    )

    if evidence_result.status == "failed" or answer_decision.decision != "allow":
        outcome = ReceiptOutcome.REFUSED_NO_EVIDENCE
        message = "I cannot answer because the available evidence is insufficient."
    else:
        outcome = ReceiptOutcome.ANSWERED_WITH_CITATIONS
        message = DeterministicProvider().answer(question)

    return _finalize(
        trace=trace,
        receipt_path=receipt_path,
        trace_path=trace_path,
        agent_name="enterprise_qa",
        question=question,
        outcome=outcome,
        message=message,
    )


def _handle_tool_question(
    *,
    manifest_tools_file: Path,
    trace: TraceWriter,
    receipt_path: Path,
    trace_path: Path,
    question: str,
    approved: bool | None,
) -> RunResult:
    """Exercise the mock MCP approval flow for a tool-required question."""

    gateway = ToolGateway.from_file(manifest_tools_file)
    if approved is None:
        # A missing approval is a terminal waiting state; the tool is not executed.
        gateway_result = gateway.request_tool(
            tool_name="customer_lookup",
            parameters={"customer_id": "CUST-001", "policy_id": "POL-001"},
            approved=False,
        )
        trace.emit(
            "approval_requested",
            status="waiting",
            payload={"tool_name": "customer_lookup", "state": gateway_result.approval_state.state},
        )
        return _finalize(
            trace=trace,
            receipt_path=receipt_path,
            trace_path=trace_path,
            agent_name="enterprise_qa",
            question=question,
            outcome=ReceiptOutcome.WAITING_FOR_APPROVAL,
            message="Waiting for approval before customer_lookup can execute.",
        )
    if approved is False:
        # Explicit denial is recorded separately from waiting so receipts are unambiguous.
        denied = create_approval_state(
            run_id=trace.run_id,
            approval_id="appr_customer_lookup",
            state=ApprovalStatus.DENIED,
            tool_name="customer_lookup",
            reason="Approval denied.",
        )
        trace.emit(
            "approval_denied",
            status="blocked",
            payload={"tool_name": denied.tool_name, "state": denied.state.value},
        )
        return _finalize(
            trace=trace,
            receipt_path=receipt_path,
            trace_path=trace_path,
            agent_name="enterprise_qa",
            question=question,
            outcome=ReceiptOutcome.TOOL_APPROVAL_DENIED,
            message="The customer_lookup tool was not run because approval was denied.",
        )

    gateway_result = gateway.request_tool(
        tool_name="customer_lookup",
        parameters={"customer_id": "CUST-001", "policy_id": "POL-001"},
        approved=True,
    )
    trace.emit("approval_granted", status="ok", payload={"tool_name": "customer_lookup"})
    trace.emit("tool_result", status="ok", payload=dict(gateway_result.result or {}))
    return _finalize(
        trace=trace,
        receipt_path=receipt_path,
        trace_path=trace_path,
        agent_name="enterprise_qa",
        question=question,
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        message="Customer policy status is active according to the approved mock lookup.",
    )


def _emit_policy(trace: TraceWriter, decision: object) -> None:
    """Record a policy decision in the trace without leaking engine internals."""

    trace.emit(
        "policy_decision",
        status="ok" if getattr(decision, "decision") == "allow" else "blocked",
        payload={
            "decision": getattr(decision, "decision").value,
            "policy_rule_id": getattr(decision, "policy_rule_id"),
            "reason": getattr(decision, "reason"),
        },
    )


def _finalize(
    *,
    trace: TraceWriter,
    receipt_path: Path,
    trace_path: Path,
    agent_name: str,
    question: str,
    outcome: ReceiptOutcome,
    message: str,
) -> RunResult:
    """Emit the final output, render the receipt, and return CLI-facing metadata."""

    trace.emit(
        "final_output",
        status="ok" if outcome == ReceiptOutcome.ANSWERED_WITH_CITATIONS else "blocked",
        payload={
            "agent_name": agent_name,
            "question": question,
            "outcome": outcome.value,
            "message": message,
        },
    )
    generate_receipt(trace_path, receipt_path)
    return RunResult(
        final_output=message,
        outcome=outcome,
        trace_path=trace_path,
        receipt_path=receipt_path,
    )
