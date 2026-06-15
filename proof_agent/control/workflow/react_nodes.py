from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from proof_agent.bootstrap.composition import HarnessInvocation
from proof_agent.capabilities.models.normalization import ModelOutputNormalizationError
from proof_agent.capabilities.models.protocol import ModelProvider
from proof_agent.capabilities.tools.approval import (
    create_pending_approval,
    pending_approval_payload,
)
from proof_agent.capabilities.tools.gateway import ToolGatewayResult
from proof_agent.contracts import (
    ContextAdmission,
    EnforcementPoint,
    EvidenceChunk,
    IntentResolution,
    ModelCallRole,
    ModelRequest,
    ModelResponse,
    PolicyDecisionType,
    ReActActionProposal,
    ReActActionType,
    ReasoningSummary,
    ReceiptOutcome,
    WorkflowTemplateExecutionInput,
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
from proof_agent.control.workflow.stage_context import (
    build_workflow_stage_context_preview,
    workflow_stage_context_summary,
)
from proof_agent.control.workflow.react_enterprise_qa import (
    clarification_message,
    emit_action_proposal,
    emit_intent_resolution,
    emit_reasoning_summary,
    review_action,
    should_stop_for_step_budget,
)
from proof_agent.errors import ProofAgentError
from proof_agent.evaluation.demo.scenarios import UNSUPPORTED_QUESTION
from proof_agent.observability.audit.trace import TraceWriter
from proof_agent.runtime.graph import _format_untrusted_web_supplement, _maybe_untrusted_web_supplement


class ReActWorkflowNodes:
    """Node implementations for the React Enterprise QA workflow."""

    def __init__(
        self,
        *,
        invocation: HarnessInvocation,
        trace: TraceWriter,
        execution_input: WorkflowTemplateExecutionInput,
        conversation_context: ContextAdmission | None,
        allow_untrusted_web_supplement: bool,
    ) -> None:
        self.invocation = invocation
        self.trace = trace
        self.execution_input = execution_input
        self.conversation_context = conversation_context
        self.allow_untrusted_web_supplement = allow_untrusted_web_supplement
        self.manifest = invocation.manifest
        self.react = self.manifest.react
        self.max_steps = self.react.max_steps if self.react is not None else 0
        self.max_tool_calls = self.react.max_tool_calls if self.react is not None else 0
        self.auto_review_enabled = bool(
            self.manifest.review and self.manifest.review.mode == "auto"
        )
        self.workflow_stage_configs = {
            stage.id: stage
            for stage in self.execution_input.effective_stage_configuration.stages
        }

    def configured_stage_context(
        self,
        stage_id: str,
        state: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        config = self.workflow_stage_configs.get(stage_id)
        if config is None:
            return None
        preview = build_workflow_stage_context_preview(
            descriptor=self.invocation.template,
            stage_id=stage_id,
            prompt=config.prompt,
            context_options=config.context,
            sample_context=_workflow_stage_runtime_sample_context(
                invocation=self.invocation,
                state=state,
                conversation_context=self.conversation_context,
            ),
        )
        summary = workflow_stage_context_summary(preview)
        if _workflow_stage_summary_has_context(summary):
            descriptor_stage = self.invocation.template.stage(stage_id)
            self.trace.emit(
                "workflow_stage_context_applied",
                status="ok",
                payload={
                    **summary,
                    "stage_label": descriptor_stage.label,
                    "model_bearing": descriptor_stage.model_bearing,
                    "template_descriptor_version": (
                        self.execution_input.template_descriptor_version
                    ),
                },
            )
        return {
            "business_context_addendum": preview["business_context_addendum"],
            "structured_control_context": preview["structured_control_context"],
            "summary": summary,
        }

    def intent_resolution(self, state: Mapping[str, Any]) -> dict[str, Any]:
        if self.invocation.intent_resolver is None:
            return _refusal("Intent resolver is not configured.")
        try:
            stage_context = self.configured_stage_context("intent_resolution", state)
            resolution = self.invocation.intent_resolver.resolve(
                question=state["question"],
                system_prompt="Resolve user intent without raw chain-of-thought.",
                context_summary=_conversation_context_summary(self.conversation_context),
                workflow_stage_context=stage_context,
            )
        except ModelOutputNormalizationError as exc:
            self.trace.emit(
                "model_output_normalization_failed",
                status="blocked",
                payload={
                    "role": exc.role,
                    "error_code": exc.error_code,
                    "raw_content_length": exc.raw_content_length,
                },
            )
            return _refusal(
                "The intent resolution output failed validation and the run was stopped."
            )
        emit_intent_resolution(self.trace, resolution)
        return {"intent_resolution": _intent_resolution_state_dict(resolution)}

    def plan(self, state: Mapping[str, Any]) -> dict[str, Any]:
        step_count = int(state.get("step_count", 0))
        if self.react is None or self.invocation.react_planner is None:
            return _refusal("ReAct planner is not configured.")
        if should_stop_for_step_budget(step_count, self.max_steps):
            return _refusal(
                "The ReAct step budget was exhausted before an answer could be produced."
            )

        try:
            stage_context = self.configured_stage_context("plan", state)
            proposal = self.invocation.react_planner.plan(
                question=state["question"],
                system_prompt="Use governed ReAct planning without raw chain-of-thought.",
                context_summary=_intent_context_summary(state),
                workflow_stage_context=stage_context,
            )
        except ModelOutputNormalizationError as exc:
            self.trace.emit(
                "model_output_normalization_failed",
                status="blocked",
                payload={
                    "role": exc.role,
                    "error_code": exc.error_code,
                    "raw_content_length": exc.raw_content_length,
                },
            )
            return _refusal("The planner output failed validation and the run was stopped.")
        emit_reasoning_summary(self.trace, proposal)
        emit_action_proposal(self.trace, proposal)
        return {
            "step_count": step_count + 1,
            "action": _proposal_state_dict(proposal),
            "reasoning_summary": _reasoning_summary_state_dict(proposal),
        }

    def clarify(self, state: Mapping[str, Any]) -> dict[str, Any]:
        proposal = proposal_from_state(state)
        self.configured_stage_context("clarification", state)
        message = clarification_message(proposal)
        self.trace.emit(
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
        self.configured_stage_context("response", {**state, **result})
        return result

    def review_retrieval_plan(self, state: Mapping[str, Any]) -> dict[str, Any]:
        proposal = proposal_from_state(state)
        stage_context = self.configured_stage_context("retrieval_review", state)
        context = {
            "question": state["question"],
            "query": proposal.parameters.get("query", state["question"]),
            "strategy": self.manifest.retrieval.strategy,
            "provider": self.invocation.knowledge_provider.provider_name,
            "top_k": self.manifest.retrieval.top_k,
            "review_fallback_decision": PolicyDecisionType.DENY.value,
        }
        if stage_context is not None:
            context["workflow_stage_context_summary"] = stage_context["summary"]
            context["workflow_stage_context"] = stage_context
        decision, review_event = review_action(
            trace=self.trace,
            policy=self.invocation.policy,
            enforcement_point=EnforcementPoint.BEFORE_RETRIEVAL_PLAN,
            context=context,
            proposal=proposal,
            auto_review_enabled=self.auto_review_enabled,
            review_subagent=self.invocation.review_subagent,
        )
        if decision.decision != PolicyDecisionType.ALLOW:
            return {
                "review_results": [review_event],
                "governance_refusal": ReceiptOutcome.REFUSED_NO_EVIDENCE,
                "governance_message": "I cannot answer because the retrieval plan was blocked by policy.",
            }
        return {"review_results": [review_event]}

    def retrieval(self, state: Mapping[str, Any]) -> dict[str, Any]:
        proposal = proposal_from_state(state)
        self.configured_stage_context("retrieval", state)
        retrieval_query = str(proposal.parameters.get("query") or state["question"])
        step_proposal = _retrieval_step_action_proposal(retrieval_query)
        step_context = {
            "question": state["question"],
            "query": retrieval_query,
            "step_id": "step_1",
            "provider": self.invocation.knowledge_provider.provider_name,
            "top_k": self.manifest.retrieval.top_k,
            "strategy": self.manifest.retrieval.strategy,
            "review_fallback_decision": PolicyDecisionType.DENY.value,
        }
        step_decision, step_review_event = review_action(
            trace=self.trace,
            policy=self.invocation.policy,
            enforcement_point=EnforcementPoint.BEFORE_RETRIEVAL_STEP,
            context=step_context,
            proposal=step_proposal,
            auto_review_enabled=self.auto_review_enabled,
            review_subagent=self.invocation.review_subagent,
        )
        if step_decision.decision != PolicyDecisionType.ALLOW:
            return {
                "review_results": [step_review_event],
                "governance_refusal": ReceiptOutcome.REFUSED_NO_EVIDENCE,
                "governance_message": "I cannot answer because the retrieval step was blocked by policy.",
            }

        retrieval = KnowledgeRetrievalService(
            trace=self.trace,
            policy=self.invocation.policy,
            knowledge_provider=self.invocation.knowledge_provider,
        ).retrieve_reviewed(
            KnowledgeRetrievalRequest(
                question=retrieval_query,
                strategy=self.manifest.retrieval.strategy,
                top_k=self.manifest.retrieval.top_k,
                min_score=self.manifest.retrieval.min_score,
                max_steps=self.manifest.retrieval.max_steps,
                max_rounds=self.manifest.retrieval.max_rounds,
                planner_model=self.invocation.retrieval_planner_model,
                evaluator_model=self.invocation.retrieval_evaluator_model,
                force_empty=state["question"] == UNSUPPORTED_QUESTION,
            ),
            execution_mode="react_reviewed_retrieval",
        )
        evidence = retrieval.evidence
        evidence_result = retrieval.evidence_result

        answer_decision = self.invocation.policy.evaluate(
            EnforcementPoint.BEFORE_ANSWER,
            {
                "accepted_evidence_count": evidence_result.metadata["accepted_count"],
                "citations_present": bool(evidence),
            },
        )
        emit_policy_decision(self.trace, answer_decision)

        if self.workflow_stage_available("memory"):
            memory = self.invocation.create_memory()
            self.configured_stage_context("memory", state)
            memory_result = memory.write({"summary": f"Question: {state['question']}"})
            self.trace.emit(
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
                invocation=self.invocation,
                trace=self.trace,
                question=state["question"],
                enabled=self.allow_untrusted_web_supplement,
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

    def model(self, state: Mapping[str, Any]) -> dict[str, Any]:
        evidence = tuple(EvidenceChunk.model_validate(chunk) for chunk in state.get("evidence", []))
        stage_context = self.configured_stage_context("model_answer", state)
        model_request = build_model_request(
            question=state["question"],
            evidence=evidence,
            provider=self.invocation.model_provider.provider_name,
            model=self.invocation.model_provider.model_name,
            conversation_context=self.conversation_context,
            workflow_stage_context=stage_context,
        )
        estimated_tokens = self.invocation.model_provider.estimate_tokens(model_request)
        proposal = _model_action_proposal(state["question"])
        context: dict[str, Any] = {
            "provider": self.invocation.model_provider.provider_name,
            "model": self.invocation.model_provider.model_name,
            "estimated_tokens": estimated_tokens,
            "stream": False,
            "cost_class": cost_class(self.invocation.model_provider.provider_name),
            "question": state["question"],
            "accepted_evidence_count": len(evidence),
            "citations_present": bool(evidence),
        }
        if stage_context is not None:
            context["workflow_stage_context_summary"] = stage_context["summary"]
            context["workflow_stage_context"] = stage_context
        decision, review_event = review_action(
            trace=self.trace,
            policy=self.invocation.policy,
            enforcement_point=EnforcementPoint.BEFORE_MODEL_CALL,
            context=context,
            proposal=proposal,
            auto_review_enabled=self.auto_review_enabled,
            review_subagent=self.invocation.review_subagent,
        )
        if decision.decision != PolicyDecisionType.ALLOW:
            return {
                "review_results": [review_event],
                "governance_refusal": ReceiptOutcome.REFUSED_NO_EVIDENCE,
                "governance_message": "I cannot answer because the model call was blocked by policy.",
            }

        self.trace.emit(
            "model_request",
            status="ok",
            payload={
                "provider": self.invocation.model_provider.provider_name,
                "model": self.invocation.model_provider.model_name,
                "role": ModelCallRole.FINAL_ANSWER.value,
                "response_format": model_request.response_format,
                "message_count": len(model_request.messages),
                "prompt_length": sum(len(message.content) for message in model_request.messages),
                "system_prompt_length": system_prompt_length(model_request),
                "estimated_tokens": estimated_tokens,
                "stream": model_request.stream,
                "cost_class": cost_class(self.invocation.model_provider.provider_name),
            },
        )
        try:
            model_response = self.invocation.model_provider.generate(model_request)
        except Exception as exc:
            emit_model_error(
                self.trace,
                self.invocation.model_provider.provider_name,
                self.invocation.model_provider.model_name,
                exc,
            )
            raise
        self.trace.emit("model_response", status="ok", payload=model_response_payload(model_response))

        outcome = ReceiptOutcome.ANSWERED_WITH_CITATIONS
        validation_results = validate_model_output(
            response=model_response,
            outcome=outcome,
            evidence=evidence,
        )
        for validation in validation_results:
            self.trace.emit(
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
            self.configured_stage_context("response", {**state, **result})
            return result
        result = {
            "review_results": [review_event],
            "final_output": model_response.content,
            "governance_refusal": outcome,
            "governance_message": model_response.content,
        }
        self.configured_stage_context("response", {**state, **result})
        return result

    def review_tool(self, state: Mapping[str, Any]) -> dict[str, Any]:
        proposal = proposal_from_state(state)
        if not (
            self.workflow_stage_available("tool_review")
            and self.workflow_stage_available("tool")
        ):
            return _tool_capability_disabled_delta()
        if int(state.get("tool_call_count", 0)) >= self.max_tool_calls:
            return {
                "governance_refusal": ReceiptOutcome.REFUSED_NO_EVIDENCE,
                "governance_message": "I cannot run the requested tool because the tool call budget is exhausted.",
            }
        stage_context = self.configured_stage_context("tool_review", state)
        context = {
            "tool_name": proposal.target_tool_name,
            "risk_level": proposal.risk_level,
            "parameters": dict(proposal.parameters),
        }
        if stage_context is not None:
            context["workflow_stage_context_summary"] = stage_context["summary"]
            context["workflow_stage_context"] = stage_context
        decision, review_event = review_action(
            trace=self.trace,
            policy=self.invocation.policy,
            enforcement_point=EnforcementPoint.BEFORE_TOOL_CALL,
            context=context,
            proposal=proposal,
            auto_review_enabled=self.auto_review_enabled,
            review_subagent=self.invocation.review_subagent,
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

    def tool(self, state: Mapping[str, Any]) -> dict[str, Any]:
        proposal = proposal_from_state(state)
        if not self.workflow_stage_available("tool"):
            return _tool_capability_disabled_delta()
        self.configured_stage_context("tool", state)
        tool_name = proposal.target_tool_name or ""
        parameters = dict(proposal.parameters)
        tool_policy_decision = PolicyDecisionType(
            state.get("tool_policy_decision") or PolicyDecisionType.REQUIRE_APPROVAL.value
        )

        if tool_policy_decision == PolicyDecisionType.REQUIRE_APPROVAL:
            gateway_result = _request_tool_or_refuse(
                invocation=self.invocation,
                trace=self.trace,
                proposal=proposal,
                tool_name=tool_name,
                parameters=parameters,
                approved=False,
            )
            if isinstance(gateway_result, dict):
                return gateway_result
            pending = create_pending_approval(
                approval_state=gateway_result.approval_state,
                thread_id=self.trace.run_id,
                action_id=proposal.action_id,
                parameters=parameters,
                policy_decision=tool_policy_decision,
                checkpoint_id=f"thread:{self.trace.run_id}",
            )
            return {
                "approval_interrupt": {
                    "kind": "tool_approval",
                    "approval_requested": {
                        "approval_id": gateway_result.approval_state.approval_id,
                        "tool_name": tool_name,
                        "state": gateway_result.approval_state.state.value,
                    },
                    "pending_approval": pending_approval_payload(pending),
                },
                "governance_refusal": ReceiptOutcome.WAITING_FOR_APPROVAL,
                "governance_message": (
                    f"Waiting for approval before {tool_name} can execute."
                ),
            }

        gateway_result = _request_tool_or_refuse(
            invocation=self.invocation,
            trace=self.trace,
            proposal=proposal,
            tool_name=tool_name,
            parameters=parameters,
            approved=True,
        )
        if isinstance(gateway_result, dict):
            return gateway_result
        self.trace.emit("tool_result", status="ok", payload=dict(gateway_result.result or {}))
        if tool_name == "untrusted_web_search":
            supplement = _format_untrusted_web_supplement(
                dict(gateway_result.result or {}).get("results", ())
            )
            message = (
                "I cannot answer because the available evidence is insufficient."
                if not supplement
                else f"I cannot answer because the available evidence is insufficient.\n\n{supplement}"
            )
            self.trace.emit(
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
            self.configured_stage_context("response", {**state, **result})
            return result
        message = "Customer policy status is active according to the approved mock lookup."
        result = {
            "final_output": message,
            "governance_refusal": ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            "governance_message": message,
        }
        self.configured_stage_context("response", {**state, **result})
        return result

    def workflow_stage_available(self, stage_id: str) -> bool:
        return self.execution_input.workflow_stage_availability.is_available(stage_id)


def proposal_from_state(state: Mapping[str, Any]) -> ReActActionProposal:
    return ReActActionProposal.model_validate(state["action"])


def _tool_capability_disabled_delta() -> dict[str, Any]:
    message = "The tools capability is disabled for this Agent Contract."
    return {
        "governance_refusal": ReceiptOutcome.REFUSED_NO_EVIDENCE,
        "governance_message": message,
        "final_output": message,
    }


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


def wrap_control_plane_model_providers(
    invocation: HarnessInvocation,
    trace: TraceWriter,
) -> None:
    _wrap_model_provider_attribute(
        invocation.intent_resolver,
        trace=trace,
        role=ModelCallRole.INTENT_RESOLUTION,
    )
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


def _intent_resolution_state_dict(resolution: IntentResolution) -> dict[str, Any]:
    return {
        "resolution_id": resolution.resolution_id,
        "user_goal": resolution.user_goal,
        "domain_intent": resolution.domain_intent,
        "known_facts": list(resolution.known_facts),
        "missing_fields": list(resolution.missing_fields),
        "ambiguities": list(resolution.ambiguities),
        "risk_flags": list(resolution.risk_flags),
        "confidence": resolution.confidence,
        "recommended_next_action": resolution.recommended_next_action.value,
    }


def _conversation_context_summary(conversation_context: ContextAdmission | None) -> str:
    if conversation_context is not None and conversation_context.admitted:
        return conversation_context.summary
    return ""


def _intent_context_summary(state: Mapping[str, Any]) -> str:
    resolution = state.get("intent_resolution")
    if not isinstance(resolution, Mapping):
        return ""
    return (
        "Intent Resolution: "
        f"user_goal={resolution.get('user_goal', '')}; "
        f"domain_intent={resolution.get('domain_intent', '')}; "
        f"missing_fields={resolution.get('missing_fields', [])}; "
        f"ambiguities={resolution.get('ambiguities', [])}; "
        f"recommended_next_action={resolution.get('recommended_next_action', '')}."
    )


def _workflow_stage_runtime_sample_context(
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
    tool_contract_path = (
        str(manifest.capabilities.tools.file)
        if manifest.capabilities.tools.enabled and manifest.capabilities.tools.file is not None
        else ""
    )
    return {
        "agent_purpose": manifest.purpose,
        "intent_resolution": state.get("intent_resolution") or {},
        "recent_conversation_summary": recent_conversation_summary,
        "bound_knowledge_sources": [
            binding.source_ref.source_id for binding in manifest.knowledge_bindings
        ],
        "bound_tools": tool_contract_path,
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
        "tool_contract_summary": tool_contract_path,
        "approval_requirements": "Medium-risk tool access requires Harness approval.",
        "approval_state": state.get("tool_policy_decision") or "",
        "parameter_bounds": dict(proposal.parameters) if proposal is not None else {},
        "memory_scope": {
            "enabled": manifest.capabilities.memory.enabled,
            "provider": manifest.capabilities.memory.provider,
            "scopes": dict(manifest.capabilities.memory.scopes),
        },
        "memory_denylist_summary": sorted(invocation.memory_deny_fields),
        "outcome": outcome.value if isinstance(outcome, ReceiptOutcome) else str(outcome or ""),
        "governance_summary": list(state.get("review_results", [])),
    }


def _workflow_stage_summary_has_context(summary: dict[str, Any]) -> bool:
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
