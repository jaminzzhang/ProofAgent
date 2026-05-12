from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from proof_agent.observability.audit.receipt import generate_receipt
from proof_agent.observability.audit.trace import TraceWriter
from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.contracts import (
    ApprovalStatus,
    EvidenceChunk,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelRole,
    ReceiptOutcome,
    RunResult,
    ValidationResult,
)
from proof_agent.evaluation.demo.scenarios import TOOL_REQUIRED_QUESTION, UNSUPPORTED_QUESTION
from proof_agent.capabilities.knowledge import KnowledgeProvider, resolve_knowledge_provider
from proof_agent.capabilities.memory.session import SessionMemory
from proof_agent.control.policy.engine import PolicyEngine
from proof_agent.capabilities.models import resolve_provider
from proof_agent.capabilities.tools.approval import create_approval_state
from proof_agent.capabilities.tools.gateway import ToolGateway
from proof_agent.control.validators.citations import validate_citations_supported_by_evidence
from proof_agent.control.validators.evidence import evaluate_evidence
from proof_agent.control.validators.safety import validate_no_secret_strings
from proof_agent.control.validators.schema import validate_final_output_schema
from proof_agent.errors import ProofAgentError


from proof_agent.observability.storage.compat import update_latest_symlink
from proof_agent.observability.storage.run_store import RunStore


def run_enterprise_qa(
    agent_yaml: Path,
    *,
    question: str,
    runs_dir: Path,
    approved: bool | None = None,
    run_id: str | None = None,
    store: RunStore | None = None,
) -> RunResult:
    """Run the local Enterprise QA harness and write trace/receipt artifacts.

    When ``store`` is provided, artifacts are also saved to a per-run history
    directory and the ``runs/latest`` symlink is updated.  When ``store`` is
    ``None`` (the default), behavior is identical to the original CLI.
    """

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
    try:
        model_provider = resolve_provider(manifest.model)
    except Exception as exc:
        trace.emit(
            "model_error",
            status="error",
            payload={
                "provider": manifest.model.provider,
                "model": manifest.model.name,
                "error_code": getattr(exc, "code", "PA_MODEL_002"),
                "error_class": exc.__class__.__name__,
                "retryable": False,
                "message": str(exc).splitlines()[0],
            },
        )
        raise

    # Retrieval is still policy-gated even in the deterministic local demo.
    policy = PolicyEngine.from_file(manifest.policy.file)
    _ensure_retrieval_strategy_is_executable(manifest.retrieval.strategy)
    knowledge_provider = resolve_knowledge_provider(manifest.knowledge)
    evidence, evidence_result = _run_single_step_retrieval(
        question=question,
        trace=trace,
        policy=policy,
        knowledge_provider=knowledge_provider,
        top_k=manifest.retrieval.top_k,
        min_score=manifest.retrieval.min_score,
        force_empty=question == UNSUPPORTED_QUESTION,
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
            store=store,
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
        model_request = _build_model_request(
            question=question,
            evidence=evidence,
            provider=model_provider.provider_name,
            model=model_provider.model_name,
        )
        estimated_tokens = model_provider.estimate_tokens(model_request)
        model_decision = policy.evaluate(
            "before_model_call",
            {
                "provider": model_provider.provider_name,
                "model": model_provider.model_name,
                "estimated_tokens": estimated_tokens,
                "stream": model_request.stream,
                "cost_class": _cost_class(model_provider.provider_name),
                "question": question,
                "accepted_evidence_count": evidence_result.metadata["accepted_count"],
                "citations_present": bool(evidence),
            },
        )
        _emit_policy(trace, model_decision)
        if model_decision.decision != "allow":
            outcome = ReceiptOutcome.REFUSED_NO_EVIDENCE
            message = "I cannot answer because the model call was blocked by policy."
        else:
            trace.emit(
                "model_request",
                status="ok",
                payload={
                    "provider": model_provider.provider_name,
                    "model": model_provider.model_name,
                    "message_count": len(model_request.messages),
                    "prompt_length": sum(len(message.content) for message in model_request.messages),
                    "system_prompt_length": _system_prompt_length(model_request),
                    "estimated_tokens": estimated_tokens,
                    "stream": model_request.stream,
                    "cost_class": _cost_class(model_provider.provider_name),
                },
            )
            try:
                model_response = model_provider.generate(model_request)
            except Exception as exc:
                trace.emit(
                    "model_error",
                    status="error",
                    payload={
                        "provider": model_provider.provider_name,
                        "model": model_provider.model_name,
                        "error_code": getattr(exc, "code", "PA_MODEL_002"),
                        "error_class": exc.__class__.__name__,
                        "retryable": False,
                        "message": str(exc).splitlines()[0],
                    },
                )
                raise
            trace.emit(
                "model_response",
                status="ok",
                payload=_model_response_payload(model_response),
            )
            outcome = ReceiptOutcome.ANSWERED_WITH_CITATIONS
            message = model_response.content
            validation_results = _validate_model_output(
                response=model_response,
                outcome=outcome,
                evidence=evidence,
            )
            for validation in validation_results:
                trace.emit(
                    "evidence_evaluation",
                    status="ok" if validation.status == "passed" else "blocked",
                    payload={
                        "validator_name": validation.validator_name,
                        "status": validation.status.value,
                        "metadata": dict(validation.metadata),
                    },
                )
            if any(validation.status == "failed" for validation in validation_results):
                outcome = ReceiptOutcome.REFUSED_NO_EVIDENCE
                message = "I cannot answer because the model output failed validation."

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


def _handle_tool_question(
    *,
    manifest_tools_file: Path,
    trace: TraceWriter,
    receipt_path: Path,
    trace_path: Path,
    question: str,
    approved: bool | None,
    store: RunStore | None = None,
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
            store=store,
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
            store=store,
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
        store=store,
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


def _run_single_step_retrieval(
    *,
    question: str,
    trace: TraceWriter,
    policy: PolicyEngine,
    knowledge_provider: KnowledgeProvider,
    top_k: int,
    min_score: float,
    force_empty: bool = False,
) -> tuple[tuple[EvidenceChunk, ...], ValidationResult]:
    """Run one governed retrieval step and evaluate candidate evidence."""

    retrieval_decision = policy.evaluate(
        "before_retrieval",
        {"question": question, "strategy": "single_step"},
    )
    _emit_policy(trace, retrieval_decision)
    step_context = {
        "question": question,
        "step_id": "step_1",
        "provider": knowledge_provider.provider_name,
        "top_k": top_k,
    }
    step_decision = policy.evaluate("before_retrieval_step", step_context)
    _emit_policy(trace, step_decision)
    if retrieval_decision.decision != "allow" or step_decision.decision != "allow":
        evidence: tuple[EvidenceChunk, ...] = ()
    else:
        trace.emit(
            "retrieval_step",
            status="ok",
            payload=step_context,
        )
        evidence = knowledge_provider.retrieve(question, top_k=top_k)
        if force_empty:
            # Force a no-evidence path so refusal behavior is reproducible in tests and demos.
            evidence = ()
    trace.emit(
        "retrieval_result",
        status="ok",
        payload={
            "step_id": "step_1",
            "provider": knowledge_provider.provider_name,
            "candidate_count": len(evidence),
            "chunk_count": len(evidence),
            "sources": [chunk.source for chunk in evidence],
        },
    )
    evidence_result = evaluate_evidence(evidence, min_count=1, min_score=min_score)
    trace.emit(
        "evidence_evaluation",
        status="ok" if evidence_result.status == "passed" else "blocked",
        payload={
            "validator_name": evidence_result.validator_name,
            "status": evidence_result.status.value,
            "metadata": dict(evidence_result.metadata),
        },
    )
    return evidence, evidence_result


def _ensure_retrieval_strategy_is_executable(strategy: str) -> None:
    if strategy == "agentic":
        raise ProofAgentError(
            "PA_RETRIEVAL_001",
            "agentic retrieval strategy is not implemented in this build",
            "Use retrieval.strategy: single_step for executable first-stage runs.",
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
    store: RunStore | None = None,
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
    result = RunResult(
        final_output=message,
        outcome=outcome,
        trace_path=trace_path,
        receipt_path=receipt_path,
    )
    if store is not None:
        store.save_run_artifacts(
            trace.run_id,
            trace_source=trace_path,
            receipt_source=receipt_path,
            question=question,
            outcome=outcome,
        )
        history_dir = store.history_dir.parent
        update_latest_symlink(store.history_dir / trace.run_id, history_dir)
    return result


def _build_model_request(
    *,
    question: str,
    evidence: tuple[EvidenceChunk, ...],
    provider: str,
    model: str,
) -> ModelRequest:
    evidence_text = "\n\n".join(getattr(chunk, "content") for chunk in evidence)
    messages = (
        ModelMessage(
            role=ModelRole.SYSTEM,
            content="Answer using only accepted evidence. Refuse when evidence is insufficient.",
        ),
        ModelMessage(
            role=ModelRole.USER,
            content=f"Question: {question}\n\nEvidence:\n{evidence_text}",
        ),
    )
    return ModelRequest(
        provider=provider,
        model=model,
        messages=messages,
        metadata={"question": question},
        evidence_sources=tuple(getattr(chunk, "source") for chunk in evidence),
    )


def _cost_class(provider: str) -> str:
    if provider == "deterministic":
        return "local"
    if provider == "azure_openai":
        return "enterprise"
    return "remote"


def _system_prompt_length(request: ModelRequest) -> int:
    return sum(len(message.content) for message in request.messages if message.role == ModelRole.SYSTEM)


def _model_response_payload(response: ModelResponse) -> dict[str, object]:
    token_usage = None
    if response.token_usage is not None:
        token_usage = {
            "input_tokens": response.token_usage.input_tokens,
            "output_tokens": response.token_usage.output_tokens,
            "total_tokens": response.token_usage.total_tokens,
        }
    return {
        "provider": response.provider_name,
        "model": response.model_name,
        "finish_reason": response.finish_reason,
        "content_length": len(response.content),
        "refusal_reason": response.refusal_reason,
        "token_usage": token_usage,
    }


def _validate_model_output(
    *,
    response: ModelResponse,
    outcome: ReceiptOutcome,
    evidence: tuple[EvidenceChunk, ...],
) -> tuple[ValidationResult, ...]:
    return (
        validate_final_output_schema(
            {"outcome": outcome.value, "message": response.content, "citations": []}
        ),
        validate_no_secret_strings(response.content),
        validate_citations_supported_by_evidence(response.content, evidence),
    )
