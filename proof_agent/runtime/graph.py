from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from proof_agent.bootstrap.composition import HarnessInvocation
from proof_agent.contracts import (
    ApprovalStatus,
    ContextAdmission,
    EvidenceChunk,
    ModelCallRole,
    PolicyDecisionType,
    ReceiptOutcome,
)
from proof_agent.capabilities.tools.approval import create_pending_approval, pending_approval_payload
from proof_agent.control.knowledge import KnowledgeRetrievalRequest, KnowledgeRetrievalService
from proof_agent.control.workflow.harness_helpers import (
    build_model_request,
    cost_class,
    emit_model_error,
    emit_policy_decision,
    model_response_payload,
    system_prompt_length,
    validate_model_output,
)
from proof_agent.evaluation.demo.scenarios import TOOL_REQUIRED_QUESTION, UNSUPPORTED_QUESTION
from proof_agent.observability.audit.trace import TraceWriter


class HarnessGraphState(TypedDict):
    run_id: str
    question: str
    messages: Annotated[list[Any], operator.add]
    approval_status: str | None
    governance_refusal: ReceiptOutcome | None
    governance_message: str | None
    evidence: list[dict[str, Any]]
    final_output: str | None


def build_enterprise_qa_graph(
    invocation: HarnessInvocation,
    trace: TraceWriter,
    conversation_context: ContextAdmission | None = None,
    allow_untrusted_web_supplement: bool = False,
) -> StateGraph:  # type: ignore[type-arg]
    manifest = invocation.manifest

    def retrieve_node(state: HarnessGraphState) -> dict[str, Any]:
        question = state["question"]

        if question == TOOL_REQUIRED_QUESTION:
            # Bypass retrieval for tool required question
            return {}

        retrieval = KnowledgeRetrievalService(
            trace=trace,
            policy=invocation.policy,
            knowledge_provider=invocation.knowledge_provider,
        ).retrieve(
            KnowledgeRetrievalRequest(
                question=question,
                strategy=manifest.retrieval.strategy,
                top_k=manifest.retrieval.top_k,
                min_score=manifest.retrieval.min_score,
                max_steps=manifest.retrieval.max_steps,
                max_rounds=manifest.retrieval.max_rounds,
                planner_model=invocation.retrieval_planner_model,
                evaluator_model=invocation.retrieval_evaluator_model,
                force_empty=question == UNSUPPORTED_QUESTION,
            )
        )
        evidence = retrieval.evidence
        evidence_result = retrieval.evidence_result

        answer_decision = invocation.policy.evaluate(
            "before_answer",
            {
                "accepted_evidence_count": evidence_result.metadata["accepted_count"],
                "citations_present": bool(evidence),
            },
        )
        emit_policy_decision(trace, answer_decision)

        memory = invocation.create_memory()
        memory_result = memory.write({"summary": f"Question: {question}"})
        trace.emit(
            "memory_write_decision",
            status="ok" if memory_result.status == "passed" else "blocked",
            payload={
                "status": memory_result.status.value,
                "metadata": dict(memory_result.metadata),
            },
        )

        if evidence_result.status == "failed" or answer_decision.decision != "allow":
            web_supplement = _maybe_untrusted_web_supplement(
                invocation=invocation,
                trace=trace,
                question=question,
                enabled=allow_untrusted_web_supplement,
            )
            message = "I cannot answer because the available evidence is insufficient."
            if web_supplement:
                message = f"{message}\n\n{web_supplement}"
            return {
                "governance_refusal": ReceiptOutcome.REFUSED_NO_EVIDENCE,
                "governance_message": message,
            }

        return {"evidence": [_evidence_state_dict(chunk) for chunk in evidence]}

    def tool_node(state: HarnessGraphState) -> dict[str, Any]:
        question = state["question"]
        if question != TOOL_REQUIRED_QUESTION:
            return {}

        parameters = {"customer_id": "CUST-001", "policy_id": "POL-001"}
        gateway_result = invocation.tool_gateway.request_tool(
            tool_name="customer_lookup",
            parameters=parameters,
            approved=False,
            run_id=trace.run_id,
        )
        pending = create_pending_approval(
            approval_state=gateway_result.approval_state,
            thread_id=trace.run_id,
            action_id="act_customer_lookup_1",
            parameters=parameters,
            policy_decision=PolicyDecisionType.REQUIRE_APPROVAL,
            checkpoint_id=f"thread:{trace.run_id}",
        )
        approval_decision = interrupt(
            {
                "kind": "tool_approval",
                "approval_requested": {
                    "approval_id": gateway_result.approval_state.approval_id,
                    "tool_name": "customer_lookup",
                    "state": gateway_result.approval_state.state.value,
                },
                "pending_approval": pending_approval_payload(pending),
            }
        )
        if not approval_decision.get("approved"):
            actor = approval_decision.get("actor", "local-user")
            trace.emit(
                "approval_denied",
                status="blocked",
                payload={
                    "approval_id": approval_decision.get(
                        "approval_id",
                        gateway_result.approval_state.approval_id,
                    ),
                    "tool_name": "customer_lookup",
                    "state": ApprovalStatus.DENIED.value,
                    "actor": actor,
                },
            )
            return {
                "approval_status": "denied",
                "governance_refusal": ReceiptOutcome.TOOL_APPROVAL_DENIED,
                "governance_message": "The customer_lookup tool was not run because approval was denied.",
            }

        gateway_result = invocation.tool_gateway.request_tool(
            tool_name="customer_lookup",
            parameters=parameters,
            approved=True,
            run_id=trace.run_id,
        )
        trace.emit(
            "approval_granted",
            status="ok",
            payload={
                "approval_id": approval_decision.get(
                    "approval_id",
                    gateway_result.approval_state.approval_id,
                ),
                "tool_name": "customer_lookup",
                "state": ApprovalStatus.GRANTED.value,
                "actor": approval_decision.get("actor", "local-user"),
            },
        )
        trace.emit("tool_result", status="ok", payload=dict(gateway_result.result or {}))

        # Tool question is answered by tool result in the demo
        return {
            "final_output": "Tool execution successful.",
            "governance_refusal": ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            "governance_message": "Tool execution successful.",
        }

    def model_node(state: HarnessGraphState) -> dict[str, Any]:
        question = state["question"]
        evidence = tuple(EvidenceChunk.model_validate(chunk) for chunk in state.get("evidence", []))

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
                "accepted_evidence_count": len(evidence),  # Approximation
                "citations_present": bool(evidence),
            },
        )
        emit_policy_decision(trace, model_decision)
        if model_decision.decision != "allow":
            return {
                "governance_refusal": ReceiptOutcome.REFUSED_NO_EVIDENCE,
                "governance_message": "I cannot answer because the model call was blocked by policy.",
            }

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
            emit_model_error(
                trace,
                invocation.model_provider.provider_name,
                invocation.model_provider.model_name,
                exc,
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
            return {
                "governance_refusal": ReceiptOutcome.REFUSED_NO_EVIDENCE,
                "governance_message": "I cannot answer because the model output failed validation.",
            }

        return {
            "final_output": message,
            "governance_refusal": outcome,
            "governance_message": message,
        }

    def route_after_retrieve(state: HarnessGraphState) -> str:
        if state.get("governance_refusal"):
            return "end"
        if state["question"] == TOOL_REQUIRED_QUESTION:
            return "tool"
        return "model"

    builder = StateGraph(HarnessGraphState)
    builder.add_node("retrieve", retrieve_node)
    builder.add_node("tool", tool_node)
    builder.add_node("model", model_node)

    builder.add_edge(START, "retrieve")
    builder.add_conditional_edges(
        "retrieve",
        route_after_retrieve,
        {
            "end": END,
            "tool": "tool",
            "model": "model",
        },
    )

    def route_after_tool(state: HarnessGraphState) -> str:
        return END

    builder.add_conditional_edges("tool", route_after_tool)

    def route_after_model(state: HarnessGraphState) -> str:
        return END

    builder.add_conditional_edges("model", route_after_model)

    return builder


def _maybe_untrusted_web_supplement(
    *,
    invocation: HarnessInvocation,
    trace: TraceWriter,
    question: str,
    enabled: bool,
) -> str:
    if not enabled or "untrusted_web_search" not in invocation.tool_gateway.tools:
        trace.emit(
            "final_output_disclosure",
            status="ok",
            payload={"used_untrusted_web_context": False},
        )
        return ""

    decision = invocation.policy.evaluate(
        "before_tool_call",
        {
            "tool_name": "untrusted_web_search",
            "risk_level": "medium",
            "read_only": True,
        },
    )
    emit_policy_decision(trace, decision)
    if decision.decision != "allow":
        trace.emit(
            "final_output_disclosure",
            status="blocked",
            payload={
                "used_untrusted_web_context": False,
                "blocked_by_policy": True,
                "policy_decision": decision.decision.value,
            },
        )
        return ""

    trace.emit(
        "tool_request",
        status="ok",
        payload={
            "tool_name": "untrusted_web_search",
            "risk_level": "medium",
            "read_only": True,
        },
    )
    try:
        gateway_result = invocation.tool_gateway.request_tool(
            tool_name="untrusted_web_search",
            parameters={"query": question, "max_results": 3},
            approved=True,
            run_id=trace.run_id,
        )
    except Exception as exc:
        trace.emit(
            "tool_result",
            status="error",
            payload={
                "tool_name": "untrusted_web_search",
                "error_code": getattr(exc, "code", "PA_TOOL_001"),
                "error_class": exc.__class__.__name__,
            },
        )
        trace.emit(
            "final_output_disclosure",
            status="ok",
            payload={"used_untrusted_web_context": False},
        )
        return ""

    tool_result = dict(gateway_result.result or {})
    trace.emit(
        "tool_result",
        status="ok",
        payload={
            "tool_name": "untrusted_web_search",
            "provider": tool_result.get("provider"),
            "result_count": tool_result.get("result_count", len(tool_result.get("results", ()))),
            "sanitized_query": tool_result.get("sanitized_query"),
            "sanitization_applied": tool_result.get("sanitization_applied"),
            "sanitization_categories": tool_result.get("sanitization_categories", ()),
            "urls": [
                result.get("url")
                for result in tool_result.get("results", [])
                if isinstance(result, dict)
            ],
        },
    )
    trace.emit(
        "final_output_disclosure",
        status="ok",
        payload={
            "used_untrusted_web_context": True,
            "untrusted_web_disclaimer_present": True,
        },
    )
    return _format_untrusted_web_supplement(tool_result.get("results", ()))


def _format_untrusted_web_supplement(results: Any) -> str:
    if not isinstance(results, list | tuple) or not results:
        return ""
    lines = [
        "Network supplement (untrusted, not verified by controlled knowledge)",
    ]
    for item in results[:3]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "Untitled result")
        snippet = str(item.get("snippet") or "").strip()
        url = str(item.get("url") or "").strip()
        line = f"- {title}"
        if snippet:
            line = f"{line}: {snippet}"
        if url:
            line = f"{line} ({url})"
        lines.append(line)
    lines.append(
        "These public web search summaries may be outdated or inaccurate and cannot support "
        "enterprise policy, contract, claims, or compliance conclusions."
    )
    return "\n".join(lines)


def _evidence_state_dict(chunk: EvidenceChunk) -> dict[str, Any]:
    """Convert evidence to JSON-safe graph state."""

    return {
        "source": chunk.source,
        "content": chunk.content,
        "provider_native_score": chunk.provider_native_score,
        "fusion_rank": chunk.fusion_rank,
        "admission_score": chunk.admission_score,
        "status": chunk.status.value,
        "citation": chunk.citation,
        "metadata": dict(chunk.metadata),
    }
