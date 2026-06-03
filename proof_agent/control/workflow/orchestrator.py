from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from proof_agent.observability.audit.trace import TraceWriter
from proof_agent.bootstrap.composition import compose_harness_invocation
from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.contracts import (
    ApprovalStatus,
    ContextAdmission,
    EvidenceChunk,
    ModelCallRole,
    ReceiptOutcome,
    RunPurpose,
    RunResult,
    ValidationResult,
)
from proof_agent.evaluation.demo.scenarios import TOOL_REQUIRED_QUESTION, UNSUPPORTED_QUESTION
from proof_agent.control.policy.engine import PolicyEngine
from proof_agent.capabilities.knowledge import KnowledgeProvider
from proof_agent.control.knowledge import KnowledgeRetrievalRequest, KnowledgeRetrievalService
from proof_agent.contracts.manifest import ModelConfig
from proof_agent.capabilities.tools.approval import create_approval_state
from proof_agent.capabilities.tools.gateway import ToolGateway
from proof_agent.control.workflow.harness_helpers import (
    build_model_request,
    cost_class,
    emit_model_error,
    emit_policy_decision,
    finalize_run,
    is_model_error,
    model_response_payload,
    system_prompt_length,
    validate_model_output,
)
from proof_agent.observability.storage.run_store import RunStore


def run_enterprise_qa(
    agent_yaml: Path,
    *,
    question: str,
    runs_dir: Path,
    approved: bool | None = None,
    conversation_context: ContextAdmission | None = None,
    run_id: str | None = None,
    store: RunStore | None = None,
    run_purpose: RunPurpose = RunPurpose.PRODUCTION,
    agent_id: str | None = None,
    agent_version_id: str | None = None,
    draft_id: str | None = None,
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
        invocation = compose_harness_invocation(agent_yaml, manifest=manifest)
    except Exception as exc:
        if is_model_error(exc):
            emit_model_error(trace, manifest.model.provider, manifest.model.name, exc)
        raise

    # Retrieval is still policy-gated even in the deterministic local demo.
    evidence, evidence_result = _run_retrieval(
        question=question,
        trace=trace,
        policy=invocation.policy,
        knowledge_provider=invocation.knowledge_provider,
        strategy=manifest.retrieval.strategy,
        top_k=manifest.retrieval.top_k,
        min_score=manifest.retrieval.min_score,
        max_steps=manifest.retrieval.max_steps,
        max_rounds=manifest.retrieval.max_rounds,
        planner_model=manifest.retrieval.planner_model,
        evaluator_model=manifest.retrieval.evaluator_model,
        force_empty=question == UNSUPPORTED_QUESTION,
    )

    if question == TOOL_REQUIRED_QUESTION:
        # Tool-required questions leave the normal answer path and exercise approval gating.
        return _handle_tool_question(
            tool_gateway=invocation.tool_gateway,
            trace=trace,
            receipt_path=receipt_path,
            trace_path=trace_path,
            agent_name=invocation.manifest.name,
            question=question,
            approved=approved,
            store=store,
            run_purpose=run_purpose,
            agent_id=agent_id,
            agent_version_id=agent_version_id,
            draft_id=draft_id,
        )

    answer_decision = invocation.policy.evaluate(
        "before_answer",
        {
            "accepted_evidence_count": evidence_result.metadata["accepted_count"],
            "citations_present": bool(evidence),
        },
    )
    emit_policy_decision(trace, answer_decision)

    memory = invocation.create_memory()
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
        model_request = build_model_request(
            question=question,
            evidence=evidence,
            provider=invocation.model_provider.provider_name,
            model=invocation.model_provider.model_name,
            conversation_context=conversation_context,
        )
        estimated_tokens = invocation.model_provider.estimate_tokens(model_request)
        model_decision = invocation.policy.evaluate(
            "before_model_call",
            {
                "provider": invocation.model_provider.provider_name,
                "model": invocation.model_provider.model_name,
                "estimated_tokens": estimated_tokens,
                "stream": model_request.stream,
                "cost_class": cost_class(invocation.model_provider.provider_name),
                "question": question,
                "accepted_evidence_count": evidence_result.metadata["accepted_count"],
                "citations_present": bool(evidence),
            },
        )
        emit_policy_decision(trace, model_decision)
        if model_decision.decision != "allow":
            outcome = ReceiptOutcome.REFUSED_NO_EVIDENCE
            message = "I cannot answer because the model call was blocked by policy."
        else:
            trace.emit(
                "model_request",
                status="ok",
                payload={
                    "provider": invocation.model_provider.provider_name,
                    "model": invocation.model_provider.model_name,
                    "role": ModelCallRole.FINAL_ANSWER.value,
                    "response_format": model_request.response_format,
                    "message_count": len(model_request.messages),
                    "prompt_length": sum(len(message.content) for message in model_request.messages),
                    "system_prompt_length": system_prompt_length(model_request),
                    "estimated_tokens": estimated_tokens,
                    "stream": model_request.stream,
                    "cost_class": cost_class(invocation.model_provider.provider_name),
                },
            )
            try:
                model_response = invocation.model_provider.generate(model_request)
            except Exception as exc:
                trace.emit(
                    "model_error",
                    status="error",
                    payload={
                        "provider": invocation.model_provider.provider_name,
                        "model": invocation.model_provider.model_name,
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
                payload=model_response_payload(model_response),
            )
            outcome = ReceiptOutcome.ANSWERED_WITH_CITATIONS
            message = model_response.content
            validation_results = validate_model_output(
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


def _handle_tool_question(
    *,
    tool_gateway: ToolGateway,
    trace: TraceWriter,
    receipt_path: Path,
    trace_path: Path,
    agent_name: str,
    question: str,
    approved: bool | None,
    store: RunStore | None = None,
    run_purpose: RunPurpose = RunPurpose.PRODUCTION,
    agent_id: str | None = None,
    agent_version_id: str | None = None,
    draft_id: str | None = None,
) -> RunResult:
    """Exercise the mock MCP approval flow for a tool-required question."""

    if approved is None:
        # A missing approval is a terminal waiting state; the tool is not executed.
        gateway_result = tool_gateway.request_tool(
            tool_name="customer_lookup",
            parameters={"customer_id": "CUST-001", "policy_id": "POL-001"},
            approved=False,
        )
        trace.emit(
            "approval_requested",
            status="waiting",
            payload={"tool_name": "customer_lookup", "state": gateway_result.approval_state.state},
        )
        return finalize_run(
            trace=trace,
            receipt_path=receipt_path,
            trace_path=trace_path,
            agent_name=agent_name,
            question=question,
            outcome=ReceiptOutcome.WAITING_FOR_APPROVAL,
            message="Waiting for approval before customer_lookup can execute.",
            store=store,
            run_purpose=run_purpose,
            agent_id=agent_id,
            agent_version_id=agent_version_id,
            draft_id=draft_id,
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
        return finalize_run(
            trace=trace,
            receipt_path=receipt_path,
            trace_path=trace_path,
            agent_name=agent_name,
            question=question,
            outcome=ReceiptOutcome.TOOL_APPROVAL_DENIED,
            message="The customer_lookup tool was not run because approval was denied.",
            store=store,
            run_purpose=run_purpose,
            agent_id=agent_id,
            agent_version_id=agent_version_id,
            draft_id=draft_id,
        )

    gateway_result = tool_gateway.request_tool(
        tool_name="customer_lookup",
        parameters={"customer_id": "CUST-001", "policy_id": "POL-001"},
        approved=True,
    )
    trace.emit("approval_granted", status="ok", payload={"tool_name": "customer_lookup"})
    trace.emit("tool_result", status="ok", payload=dict(gateway_result.result or {}))
    return finalize_run(
        trace=trace,
        receipt_path=receipt_path,
        trace_path=trace_path,
        agent_name=agent_name,
        question=question,
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        message="Customer policy status is active according to the approved mock lookup.",
        store=store,
        run_purpose=run_purpose,
        agent_id=agent_id,
        agent_version_id=agent_version_id,
        draft_id=draft_id,
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
    """Compatibility wrapper around the Control Plane retrieval service."""

    result = KnowledgeRetrievalService(
        trace=trace,
        policy=policy,
        knowledge_provider=knowledge_provider,
    ).retrieve(
        KnowledgeRetrievalRequest(
            question=question,
            strategy="single_step",
            top_k=top_k,
            min_score=min_score,
            force_empty=force_empty,
        )
    )
    return result.evidence, result.evidence_result


def _run_retrieval(
    *,
    question: str,
    trace: TraceWriter,
    policy: PolicyEngine,
    knowledge_provider: KnowledgeProvider,
    strategy: str,
    top_k: int,
    min_score: float,
    max_steps: int | None = None,
    max_rounds: int | None = None,
    planner_model: ModelConfig | None = None,
    evaluator_model: ModelConfig | None = None,
    force_empty: bool = False,
) -> tuple[tuple[EvidenceChunk, ...], ValidationResult]:
    result = KnowledgeRetrievalService(
        trace=trace,
        policy=policy,
        knowledge_provider=knowledge_provider,
    ).retrieve(
        KnowledgeRetrievalRequest(
            question=question,
            strategy=strategy,
            top_k=top_k,
            min_score=min_score,
            max_steps=max_steps,
            max_rounds=max_rounds,
            planner_model=planner_model,
            evaluator_model=evaluator_model,
            force_empty=force_empty,
        )
    )
    return result.evidence, result.evidence_result


def _run_agentic_retrieval(
    *,
    question: str,
    trace: TraceWriter,
    policy: PolicyEngine,
    knowledge_provider: KnowledgeProvider,
    top_k: int,
    min_score: float,
    max_steps: int | None,
    max_rounds: int | None = None,
    planner_model: ModelConfig | None = None,
    evaluator_model: ModelConfig | None = None,
    force_empty: bool = False,
) -> tuple[tuple[EvidenceChunk, ...], ValidationResult]:
    """Compatibility wrapper around the Control Plane retrieval service."""

    result = KnowledgeRetrievalService(
        trace=trace,
        policy=policy,
        knowledge_provider=knowledge_provider,
    ).retrieve(
        KnowledgeRetrievalRequest(
            question=question,
            strategy="agentic",
            top_k=top_k,
            min_score=min_score,
            max_steps=max_steps,
            max_rounds=max_rounds,
            planner_model=planner_model,
            evaluator_model=evaluator_model,
            force_empty=force_empty,
        )
    )
    return result.evidence, result.evidence_result

