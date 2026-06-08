from __future__ import annotations

import operator
from collections.abc import Mapping
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from proof_agent.bootstrap.composition import HarnessInvocation
from proof_agent.capabilities.models.protocol import ModelProvider
from proof_agent.capabilities.models.normalization import ModelOutputNormalizationError
from proof_agent.capabilities.tools.approval import create_approval_state
from proof_agent.capabilities.tools.gateway import ToolGatewayResult
from proof_agent.contracts import (
    ApprovalStatus,
    ContextAdmission,
    EnforcementPoint,
    EvidenceChunk,
    ModelCallRole,
    ModelRequest,
    ModelResponse,
    PolicyDecisionType,
    ReActActionProposal,
    ReActActionType,
    ReasoningSummary,
    ReceiptOutcome,
)
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
from proof_agent.control.workflow.node_context import (
    build_workflow_node_context_preview,
    workflow_node_context_summary,
)
from proof_agent.control.workflow.react_enterprise_qa import (
    clarification_message,
    emit_action_proposal,
    emit_reasoning_summary,
    review_action,
    should_stop_for_step_budget,
)
from proof_agent.evaluation.demo.scenarios import UNSUPPORTED_QUESTION
from proof_agent.errors import ProofAgentError
from proof_agent.runtime.graph import _format_untrusted_web_supplement, _maybe_untrusted_web_supplement
from proof_agent.observability.audit.trace import TraceWriter


class ReActGraphState(TypedDict, total=False):
    run_id: str
    question: str
    messages: Annotated[list[Any], operator.add]
    step_count: int
    tool_call_count: int
    action: dict[str, Any] | None
    reasoning_summary: dict[str, Any] | None
    review_results: Annotated[list[dict[str, Any]], operator.add]
    tool_policy_decision: str | None
    evidence: list[dict[str, Any]]
    governance_refusal: ReceiptOutcome | None
    governance_message: str | None
    final_output: str | None


def build_react_enterprise_qa_graph(
    invocation: HarnessInvocation,
    trace: TraceWriter,
    approved: bool | None = None,
    conversation_context: ContextAdmission | None = None,
    allow_untrusted_web_supplement: bool = False,
) -> StateGraph:  # type: ignore[type-arg]
    manifest = invocation.manifest
    react = manifest.react
    max_steps = react.max_steps if react is not None else 0
    max_tool_calls = react.max_tool_calls if react is not None else 0
    auto_review_enabled = bool(manifest.review and manifest.review.mode == "auto")
    workflow_node_configs = {node.node_id: node for node in manifest.workflow.nodes}
    _wrap_control_plane_model_providers(invocation, trace)

    def configured_node_context(
        node_id: str,
        state: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        config = workflow_node_configs.get(node_id)
        if config is None:
            return None
        preview = build_workflow_node_context_preview(
            descriptor=invocation.template,
            node_id=node_id,
            prompt=config.prompt,
            context_options=config.context.options,
            sample_context=_workflow_node_runtime_sample_context(
                invocation=invocation,
                state=state,
                conversation_context=conversation_context,
            ),
        )
        summary = workflow_node_context_summary(preview)
        if _workflow_node_summary_has_context(summary):
            descriptor_node = invocation.template.node(node_id)
            trace.emit(
                "workflow_node_context_applied",
                status="ok",
                payload={
                    **summary,
                    "node_label": descriptor_node.label,
                    "model_bearing": descriptor_node.model_bearing,
                    "template_descriptor_version": (
                        manifest.workflow.template_descriptor_version
                        or invocation.template.descriptor_version
                    ),
                },
            )
        return {
            "business_context_addendum": preview["business_context_addendum"],
            "structured_control_context": preview["structured_control_context"],
            "summary": summary,
        }

    def plan_node(state: ReActGraphState) -> dict[str, Any]:
        step_count = int(state.get("step_count", 0))
        if react is None or invocation.react_planner is None:
            return _refusal("ReAct planner is not configured.")
        if should_stop_for_step_budget(step_count, max_steps):
            return _refusal(
                "The ReAct step budget was exhausted before an answer could be produced."
            )

        try:
            node_context = configured_node_context("plan", state)
            proposal = invocation.react_planner.plan(
                question=state["question"],
                system_prompt="Use governed ReAct planning without raw chain-of-thought.",
                context_summary="",
                workflow_node_context=node_context,
            )
        except ModelOutputNormalizationError as exc:
            trace.emit(
                "model_output_normalization_failed",
                status="blocked",
                payload={
                    "role": exc.role,
                    "error_code": exc.error_code,
                    "raw_content_length": exc.raw_content_length,
                },
            )
            return _refusal("The planner output failed validation and the run was stopped.")
        emit_reasoning_summary(trace, proposal)
        emit_action_proposal(trace, proposal)
        return {
            "step_count": step_count + 1,
            "action": _proposal_state_dict(proposal),
            "reasoning_summary": _reasoning_summary_state_dict(proposal),
        }

    def clarify_node(state: ReActGraphState) -> dict[str, Any]:
        proposal = _proposal_from_state(state)
        configured_node_context("clarification", state)
        message = clarification_message(proposal)
        trace.emit(
            "clarification_requested",
            status="waiting",
            payload={
                "action_id": proposal.action_id,
                "missing_fields": list(proposal.parameters.get("missing_fields", ())),
            },
        )
        result = {
            "governance_refusal": ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION,
            "governance_message": message,
            "final_output": message,
        }
        configured_node_context("response", {**state, **result})
        return result

    def review_retrieval_plan_node(state: ReActGraphState) -> dict[str, Any]:
        proposal = _proposal_from_state(state)
        node_context = configured_node_context("retrieval_review", state)
        context = {
            "question": state["question"],
            "query": proposal.parameters.get("query", state["question"]),
            "strategy": manifest.retrieval.strategy,
            "provider": invocation.knowledge_provider.provider_name,
            "top_k": manifest.retrieval.top_k,
            "review_fallback_decision": PolicyDecisionType.DENY.value,
        }
        if node_context is not None:
            context["workflow_node_context_summary"] = node_context["summary"]
            context["workflow_node_context"] = node_context
        decision, review_event = review_action(
            trace=trace,
            policy=invocation.policy,
            enforcement_point=EnforcementPoint.BEFORE_RETRIEVAL_PLAN,
            context=context,
            proposal=proposal,
            auto_review_enabled=auto_review_enabled,
            review_subagent=invocation.review_subagent,
        )
        if decision.decision != PolicyDecisionType.ALLOW:
            return {
                "review_results": [review_event],
                "governance_refusal": ReceiptOutcome.REFUSED_NO_EVIDENCE,
                "governance_message": "I cannot answer because the retrieval plan was blocked by policy.",
            }
        return {"review_results": [review_event]}

    def retrieval_node(state: ReActGraphState) -> dict[str, Any]:
        proposal = _proposal_from_state(state)
        configured_node_context("retrieval", state)
        retrieval_query = str(proposal.parameters.get("query") or state["question"])
        step_proposal = _retrieval_step_action_proposal(retrieval_query)
        step_context = {
            "question": state["question"],
            "query": retrieval_query,
            "step_id": "step_1",
            "provider": invocation.knowledge_provider.provider_name,
            "top_k": manifest.retrieval.top_k,
            "strategy": manifest.retrieval.strategy,
            "review_fallback_decision": PolicyDecisionType.DENY.value,
        }
        step_decision, step_review_event = review_action(
            trace=trace,
            policy=invocation.policy,
            enforcement_point=EnforcementPoint.BEFORE_RETRIEVAL_STEP,
            context=step_context,
            proposal=step_proposal,
            auto_review_enabled=auto_review_enabled,
            review_subagent=invocation.review_subagent,
        )
        if step_decision.decision != PolicyDecisionType.ALLOW:
            return {
                "review_results": [step_review_event],
                "governance_refusal": ReceiptOutcome.REFUSED_NO_EVIDENCE,
                "governance_message": "I cannot answer because the retrieval step was blocked by policy.",
            }

        retrieval = KnowledgeRetrievalService(
            trace=trace,
            policy=invocation.policy,
            knowledge_provider=invocation.knowledge_provider,
        ).retrieve_reviewed(
            KnowledgeRetrievalRequest(
                question=retrieval_query,
                strategy=manifest.retrieval.strategy,
                top_k=manifest.retrieval.top_k,
                min_score=manifest.retrieval.min_score,
                max_steps=manifest.retrieval.max_steps,
                max_rounds=manifest.retrieval.max_rounds,
                planner_model=invocation.retrieval_planner_model,
                evaluator_model=invocation.retrieval_evaluator_model,
                force_empty=state["question"] == UNSUPPORTED_QUESTION,
            ),
            execution_mode="react_reviewed_retrieval",
        )
        evidence = retrieval.evidence
        evidence_result = retrieval.evidence_result

        answer_decision = invocation.policy.evaluate(
            EnforcementPoint.BEFORE_ANSWER,
            {
                "accepted_evidence_count": evidence_result.metadata["accepted_count"],
                "citations_present": bool(evidence),
            },
        )
        emit_policy_decision(trace, answer_decision)

        memory = invocation.create_memory()
        configured_node_context("memory", state)
        memory_result = memory.write({"summary": f"Question: {state['question']}"})
        trace.emit(
            "memory_write_decision",
            status="ok" if memory_result.status == "passed" else "blocked",
            payload={
                "status": memory_result.status.value,
                "metadata": dict(memory_result.metadata),
            },
        )

        if (
            evidence_result.status == "failed"
            or answer_decision.decision != PolicyDecisionType.ALLOW
        ):
            web_supplement = _maybe_untrusted_web_supplement(
                invocation=invocation,
                trace=trace,
                question=state["question"],
                enabled=allow_untrusted_web_supplement,
            )
            message = "I cannot answer because the available evidence is insufficient."
            if web_supplement:
                message = f"{message}\n\n{web_supplement}"
            return {
                "review_results": [step_review_event],
                "governance_refusal": ReceiptOutcome.REFUSED_NO_EVIDENCE,
                "governance_message": message,
            }
        return {
            "review_results": [step_review_event],
            "evidence": [_evidence_state_dict(chunk) for chunk in evidence],
        }

    def model_node(state: ReActGraphState) -> dict[str, Any]:
        evidence = tuple(EvidenceChunk.model_validate(chunk) for chunk in state.get("evidence", []))
        node_context = configured_node_context("model_answer", state)
        model_request = build_model_request(
            question=state["question"],
            evidence=evidence,
            provider=invocation.model_provider.provider_name,
            model=invocation.model_provider.model_name,
            conversation_context=conversation_context,
            workflow_node_context=node_context,
        )
        estimated_tokens = invocation.model_provider.estimate_tokens(model_request)
        proposal = _model_action_proposal(state["question"])
        context: dict[str, Any] = {
            "provider": invocation.model_provider.provider_name,
            "model": invocation.model_provider.model_name,
            "estimated_tokens": estimated_tokens,
            "stream": False,
            "cost_class": cost_class(invocation.model_provider.provider_name),
            "question": state["question"],
            "accepted_evidence_count": len(evidence),
            "citations_present": bool(evidence),
        }
        if node_context is not None:
            context["workflow_node_context_summary"] = node_context["summary"]
            context["workflow_node_context"] = node_context
        decision, review_event = review_action(
            trace=trace,
            policy=invocation.policy,
            enforcement_point=EnforcementPoint.BEFORE_MODEL_CALL,
            context=context,
            proposal=proposal,
            auto_review_enabled=auto_review_enabled,
            review_subagent=invocation.review_subagent,
        )
        if decision.decision != PolicyDecisionType.ALLOW:
            return {
                "review_results": [review_event],
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
        trace.emit("model_response", status="ok", payload=model_response_payload(model_response))

        outcome = ReceiptOutcome.ANSWERED_WITH_CITATIONS
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
            result = {
                "review_results": [review_event],
                "governance_refusal": ReceiptOutcome.REFUSED_NO_EVIDENCE,
                "governance_message": "I cannot answer because the model output failed validation.",
            }
            configured_node_context("response", {**state, **result})
            return result
        result = {
            "review_results": [review_event],
            "final_output": model_response.content,
            "governance_refusal": outcome,
            "governance_message": model_response.content,
        }
        configured_node_context("response", {**state, **result})
        return result

    def review_tool_node(state: ReActGraphState) -> dict[str, Any]:
        proposal = _proposal_from_state(state)
        if int(state.get("tool_call_count", 0)) >= max_tool_calls:
            return {
                "governance_refusal": ReceiptOutcome.REFUSED_NO_EVIDENCE,
                "governance_message": "I cannot run the requested tool because the tool call budget is exhausted.",
            }
        node_context = configured_node_context("tool_review", state)
        context = {
            "tool_name": proposal.target_tool_name,
            "risk_level": proposal.risk_level,
            "parameters": dict(proposal.parameters),
        }
        if node_context is not None:
            context["workflow_node_context_summary"] = node_context["summary"]
            context["workflow_node_context"] = node_context
        decision, review_event = review_action(
            trace=trace,
            policy=invocation.policy,
            enforcement_point=EnforcementPoint.BEFORE_TOOL_CALL,
            context=context,
            proposal=proposal,
            auto_review_enabled=auto_review_enabled,
            review_subagent=invocation.review_subagent,
        )
        if decision.decision in {PolicyDecisionType.DENY, PolicyDecisionType.ESCALATE}:
            return {
                "review_results": [review_event],
                "governance_refusal": ReceiptOutcome.REFUSED_NO_EVIDENCE,
                "governance_message": "I cannot run the requested tool because the tool call was blocked by policy.",
            }
        return {
            "review_results": [review_event],
            "tool_call_count": int(state.get("tool_call_count", 0)) + 1,
            "tool_policy_decision": decision.decision.value,
        }

    def tool_node(state: ReActGraphState) -> dict[str, Any]:
        proposal = _proposal_from_state(state)
        configured_node_context("tool", state)
        tool_name = proposal.target_tool_name or ""
        parameters = dict(proposal.parameters)
        tool_policy_decision = PolicyDecisionType(
            state.get("tool_policy_decision") or PolicyDecisionType.REQUIRE_APPROVAL.value
        )

        if tool_policy_decision == PolicyDecisionType.REQUIRE_APPROVAL and approved is None:
            gateway_result = _request_tool_or_refuse(
                invocation=invocation,
                trace=trace,
                proposal=proposal,
                tool_name=tool_name,
                parameters=parameters,
                approved=False,
            )
            if isinstance(gateway_result, dict):
                return gateway_result
            trace.emit(
                "approval_requested",
                status="waiting",
                payload={"tool_name": tool_name, "state": gateway_result.approval_state.state},
            )
            result = {
                "governance_refusal": ReceiptOutcome.WAITING_FOR_APPROVAL,
                "governance_message": f"Waiting for approval before {tool_name} can execute.",
            }
            configured_node_context("response", {**state, **result})
            return result
        if tool_policy_decision == PolicyDecisionType.REQUIRE_APPROVAL and approved is False:
            denied = create_approval_state(
                run_id=trace.run_id,
                approval_id=f"appr_{tool_name}",
                state=ApprovalStatus.DENIED,
                tool_name=tool_name,
                reason="Approval denied.",
            )
            trace.emit(
                "approval_denied",
                status="blocked",
                payload={"tool_name": denied.tool_name, "state": denied.state.value},
            )
            result = {
                "governance_refusal": ReceiptOutcome.TOOL_APPROVAL_DENIED,
                "governance_message": f"The {tool_name} tool was not run because approval was denied.",
            }
            configured_node_context("response", {**state, **result})
            return result

        gateway_result = _request_tool_or_refuse(
            invocation=invocation,
            trace=trace,
            proposal=proposal,
            tool_name=tool_name,
            parameters=parameters,
            approved=True,
        )
        if isinstance(gateway_result, dict):
            return gateway_result
        trace.emit("approval_granted", status="ok", payload={"tool_name": tool_name})
        trace.emit("tool_result", status="ok", payload=dict(gateway_result.result or {}))
        if tool_name == "untrusted_web_search":
            supplement = _format_untrusted_web_supplement(
                dict(gateway_result.result or {}).get("results", ())
            )
            message = (
                "I cannot answer because the available evidence is insufficient."
                if not supplement
                else f"I cannot answer because the available evidence is insufficient.\n\n{supplement}"
            )
            trace.emit(
                "final_output_disclosure",
                status="ok",
                payload={
                    "used_untrusted_web_context": bool(supplement),
                    "untrusted_web_disclaimer_present": bool(supplement),
                },
            )
            result = {
                "final_output": message,
                "governance_refusal": ReceiptOutcome.REFUSED_NO_EVIDENCE,
                "governance_message": message,
            }
            configured_node_context("response", {**state, **result})
            return result
        message = "Customer policy status is active according to the approved mock lookup."
        result = {
            "final_output": message,
            "governance_refusal": ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            "governance_message": message,
        }
        configured_node_context("response", {**state, **result})
        return result

    def route_after_plan(state: ReActGraphState) -> str:
        if state.get("governance_refusal"):
            return "end"
        action = _proposal_from_state(state).action_type
        if action == ReActActionType.ASK_CLARIFICATION:
            return "clarify"
        if action == ReActActionType.PROPOSE_TOOL_CALL:
            return "review_tool"
        if action == ReActActionType.PLAN_RETRIEVAL:
            return "review_retrieval_plan"
        return "end"

    def route_after_review(state: ReActGraphState) -> str:
        return "end" if state.get("governance_refusal") else "retrieval"

    def route_after_retrieval(state: ReActGraphState) -> str:
        return "end" if state.get("governance_refusal") else "model"

    def route_after_tool_review(state: ReActGraphState) -> str:
        return "end" if state.get("governance_refusal") else "tool"

    builder = StateGraph(ReActGraphState)
    builder.add_node("plan", plan_node)
    builder.add_node("clarify", clarify_node)
    builder.add_node("review_retrieval_plan", review_retrieval_plan_node)
    builder.add_node("retrieval", retrieval_node)
    builder.add_node("model", model_node)
    builder.add_node("review_tool", review_tool_node)
    builder.add_node("tool", tool_node)

    builder.add_edge(START, "plan")
    builder.add_conditional_edges(
        "plan",
        route_after_plan,
        {
            "clarify": "clarify",
            "review_tool": "review_tool",
            "review_retrieval_plan": "review_retrieval_plan",
            "end": END,
        },
    )
    builder.add_conditional_edges(
        "review_retrieval_plan",
        route_after_review,
        {"retrieval": "retrieval", "end": END},
    )
    builder.add_conditional_edges(
        "retrieval",
        route_after_retrieval,
        {"model": "model", "end": END},
    )
    builder.add_edge("model", END)
    builder.add_conditional_edges(
        "review_tool",
        route_after_tool_review,
        {"tool": "tool", "end": END},
    )
    builder.add_edge("tool", END)
    builder.add_edge("clarify", END)
    return builder


def _proposal_from_state(state: ReActGraphState) -> ReActActionProposal:
    return ReActActionProposal.model_validate(state["action"])


class _TracingModelProvider:
    def __init__(
        self,
        *,
        provider: ModelProvider,
        trace: TraceWriter,
        role: ModelCallRole,
    ) -> None:
        self._provider = provider
        self._trace = trace
        self._role = role

    @property
    def inner_provider(self) -> ModelProvider:
        return self._provider

    @property
    def role(self) -> ModelCallRole:
        return self._role

    def bind_trace(self, trace: TraceWriter) -> None:
        self._trace = trace

    @property
    def provider_name(self) -> str:
        return self._provider.provider_name

    @property
    def model_name(self) -> str:
        return self._provider.model_name

    def estimate_tokens(self, request: ModelRequest) -> int | None:
        return self._provider.estimate_tokens(request)

    def generate(self, request: ModelRequest) -> ModelResponse:
        estimated_tokens = self._provider.estimate_tokens(request)
        self._trace.emit(
            "model_request",
            status="ok",
            payload={
                "provider": self.provider_name,
                "model": self.model_name,
                "role": self._role.value,
                "response_format": request.response_format,
                "message_count": len(request.messages),
                "prompt_length": sum(len(message.content) for message in request.messages),
                "system_prompt_length": system_prompt_length(request),
                "estimated_tokens": estimated_tokens,
                "stream": request.stream,
                "cost_class": cost_class(self.provider_name),
            },
        )
        try:
            response = self._provider.generate(request)
        except Exception as exc:
            _emit_control_plane_model_error(
                self._trace,
                role=self._role,
                provider=self.provider_name,
                model=self.model_name,
                exc=exc,
            )
            raise
        payload = model_response_payload(response)
        payload["role"] = self._role.value
        self._trace.emit("model_response", status="ok", payload=payload)
        return response


def _wrap_control_plane_model_providers(
    invocation: HarnessInvocation,
    trace: TraceWriter,
) -> None:
    _wrap_model_provider_attribute(
        invocation.react_planner,
        trace=trace,
        role=ModelCallRole.REACT_PLANNER,
    )
    _wrap_model_provider_attribute(
        invocation.review_subagent,
        trace=trace,
        role=ModelCallRole.HARNESS_REVIEW,
    )


def _wrap_model_provider_attribute(
    owner: object | None,
    *,
    trace: TraceWriter,
    role: ModelCallRole,
) -> None:
    if owner is None or not hasattr(owner, "model_provider"):
        return
    provider = getattr(owner, "model_provider")
    if provider is None:
        return
    if isinstance(provider, _TracingModelProvider):
        if provider.role == role:
            provider.bind_trace(trace)
            return
        provider = provider.inner_provider
    setattr(
        owner,
        "model_provider",
        _TracingModelProvider(provider=provider, trace=trace, role=role),
    )


def _emit_control_plane_model_error(
    trace: TraceWriter,
    *,
    role: ModelCallRole,
    provider: str,
    model: str,
    exc: BaseException,
) -> None:
    trace.emit(
        "model_error",
        status="error",
        payload={
            "role": role.value,
            "provider": provider,
            "model": model,
            "error_code": getattr(exc, "code", "PA_MODEL_002"),
            "error_class": exc.__class__.__name__,
            "retryable": bool(getattr(exc, "retryable", False)),
        },
    )


def _model_action_proposal(question: str) -> ReActActionProposal:
    return ReActActionProposal(
        action_id="act_model_1",
        action_type=ReActActionType.GENERATE_FINAL_ANSWER,
        reasoning_summary=ReasoningSummary(
            goal="Generate the final answer from accepted evidence.",
            observations=("Accepted evidence is available for answer generation.",),
            candidate_actions=(ReActActionType.GENERATE_FINAL_ANSWER,),
            selected_action=ReActActionType.GENERATE_FINAL_ANSWER,
            rationale_summary="The model call can produce a final answer constrained to evidence.",
            risk_flags=(),
            required_evidence=("accepted evidence",),
        ),
        parameters={"question": question},
        risk_level="low",
    )


def _retrieval_step_action_proposal(query: str) -> ReActActionProposal:
    return ReActActionProposal(
        action_id="act_retrieval_step_1",
        action_type=ReActActionType.RUN_RETRIEVAL_STEP,
        reasoning_summary=ReasoningSummary(
            goal="Run one governed retrieval step.",
            observations=("The retrieval plan has been approved for evidence lookup.",),
            candidate_actions=(ReActActionType.RUN_RETRIEVAL_STEP,),
            selected_action=ReActActionType.RUN_RETRIEVAL_STEP,
            rationale_summary="The approved query can be submitted to the configured knowledge provider.",
            risk_flags=(),
            required_evidence=("policy evidence",),
        ),
        parameters={"query": query, "step_id": "step_1"},
        risk_level="low",
    )


def _request_tool_or_refuse(
    *,
    invocation: HarnessInvocation,
    trace: TraceWriter,
    proposal: ReActActionProposal,
    tool_name: str,
    parameters: dict[str, Any],
    approved: bool,
) -> ToolGatewayResult | dict[str, Any]:
    try:
        return invocation.tool_gateway.request_tool(
            tool_name=tool_name,
            parameters=parameters,
            approved=approved,
            run_id=trace.run_id,
        )
    except ProofAgentError as exc:
        return _tool_refusal(trace, proposal, tool_name, exc)
    except Exception as exc:
        return _tool_refusal(trace, proposal, tool_name, exc)


def _tool_refusal(
    trace: TraceWriter,
    proposal: ReActActionProposal,
    tool_name: str,
    exc: Exception,
) -> dict[str, Any]:
    error_code = getattr(exc, "code", "PA_TOOL_001")
    message = "The tool request was rejected by the governance boundary."
    trace.emit(
        "tool_request",
        status="blocked",
        payload={
            "action_id": proposal.action_id,
            "tool_name": tool_name,
            "error_code": error_code,
            "error_class": exc.__class__.__name__,
            "message": str(exc).splitlines()[0],
        },
    )
    return {
        "governance_refusal": ReceiptOutcome.REFUSED_NO_EVIDENCE,
        "governance_message": message,
        "final_output": message,
    }


def _evidence_state_dict(chunk: EvidenceChunk) -> dict[str, Any]:
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


def _proposal_state_dict(proposal: ReActActionProposal) -> dict[str, Any]:
    return {
        "action_id": proposal.action_id,
        "action_type": proposal.action_type.value,
        "reasoning_summary": _reasoning_summary_state_dict(proposal),
        "parameters": _jsonable(dict(proposal.parameters)),
        "target_tool_name": proposal.target_tool_name,
        "risk_level": proposal.risk_level,
    }


def _reasoning_summary_state_dict(proposal: ReActActionProposal) -> dict[str, Any]:
    summary = proposal.reasoning_summary
    return {
        "goal": summary.goal,
        "observations": list(summary.observations),
        "candidate_actions": [action.value for action in summary.candidate_actions],
        "selected_action": summary.selected_action.value,
        "rationale_summary": summary.rationale_summary,
        "risk_flags": list(summary.risk_flags),
        "required_evidence": list(summary.required_evidence),
    }


def _workflow_node_runtime_sample_context(
    *,
    invocation: HarnessInvocation,
    state: Mapping[str, Any],
    conversation_context: ContextAdmission | None,
) -> dict[str, Any]:
    manifest = invocation.manifest
    proposal: ReActActionProposal | None = None
    if state.get("action") is not None:
        proposal = ReActActionProposal.model_validate(state["action"])
    evidence = list(state.get("evidence", []))
    outcome = state.get("governance_refusal")
    recent_conversation_summary = ""
    if conversation_context is not None and conversation_context.admitted:
        recent_conversation_summary = conversation_context.summary
    return {
        "agent_purpose": manifest.purpose,
        "recent_conversation_summary": recent_conversation_summary,
        "bound_knowledge_sources": [
            binding.source_ref.source_id for binding in manifest.knowledge_bindings
        ],
        "bound_tools": str(manifest.tools.file),
        "policy_outline": str(manifest.policy.file),
        "missing_field_schema": (
            list(proposal.parameters.get("missing_fields", ()))
            if proposal is not None
            else []
        ),
        "retrieval_intent": (
            proposal.parameters.get("query", state.get("question", ""))
            if proposal is not None
            else state.get("question", "")
        ),
        "source_routing_metadata": [
            dict(item.get("metadata", {})) for item in evidence if isinstance(item, dict)
        ],
        "evidence_summary": [
            {
                "source": item.get("source"),
                "citation": item.get("citation"),
                "status": item.get("status"),
            }
            for item in evidence
            if isinstance(item, dict)
        ],
        "citation_requirements": "Final answers must be grounded in accepted evidence citations.",
        "response_disclosure_policy": (
            manifest.response.model_dump(mode="json") if manifest.response else {}
        ),
        "tool_proposal": (
            {
                "tool_name": proposal.target_tool_name,
                "risk_level": proposal.risk_level,
                "parameters": dict(proposal.parameters),
            }
            if proposal is not None and proposal.target_tool_name
            else {}
        ),
        "tool_contract_summary": str(manifest.tools.file),
        "approval_requirements": "Medium-risk tool access requires Harness approval.",
        "approval_state": state.get("tool_policy_decision") or "",
        "parameter_bounds": dict(proposal.parameters) if proposal is not None else {},
        "memory_scope": manifest.memory.model_dump(mode="json"),
        "memory_denylist_summary": sorted(invocation.memory_deny_fields),
        "outcome": outcome.value if isinstance(outcome, ReceiptOutcome) else str(outcome or ""),
        "governance_summary": list(state.get("review_results", [])),
    }


def _workflow_node_summary_has_context(summary: dict[str, Any]) -> bool:
    return bool(
        summary.get("prompt_fields")
        or summary.get("context_options")
        or summary.get("business_context_length", 0)
        or summary.get("task_instruction_count", 0)
        or summary.get("output_preference_count", 0)
    )


def _jsonable(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value


def _refusal(message: str) -> dict[str, Any]:
    return {
        "governance_refusal": ReceiptOutcome.REFUSED_NO_EVIDENCE,
        "governance_message": message,
        "final_output": message,
    }
