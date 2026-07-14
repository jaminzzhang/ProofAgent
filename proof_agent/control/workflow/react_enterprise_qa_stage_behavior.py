from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from proof_agent.bootstrap.composition import HarnessInvocation
from proof_agent.capabilities.models.normalization import ModelOutputNormalizationError
from proof_agent.capabilities.models.protocol import ModelProvider
from proof_agent.capabilities.tools.gateway import ToolGatewayResult
from proof_agent.contracts import (
    ApprovalStatus,
    BusinessFlowSkillPackDefinition,
    ContextAdmission,
    EnforcementPoint,
    EvidenceChunk,
    BusinessFlowSkillPackAdmissionDecision,
    IntentResolution,
    IntentResolutionResult,
    MemoryRecallWorkingPayload,
    ModelCallRole,
    ModelRequest,
    ModelResponse,
    PolicyDecisionType,
    ReActActionProposal,
    ReActActionType,
    ReasoningSummary,
    ReceiptOutcome,
    WorkflowStagePromptConfig,
    WorkflowTemplateExecutionInput,
    RetrievalQueryItem,
)
from proof_agent.control.knowledge import KnowledgeRetrievalRequest, KnowledgeRetrievalService
from proof_agent.control.knowledge.hybrid_request import GovernedHybridRetrievalRequest
from proof_agent.control.workflow.business_flow_skill_packs import (
    admit_business_flow_skill_pack,
)
from proof_agent.control.workflow.harness_helpers import (
    build_model_request,
    cost_class,
    emit_model_error,
    emit_policy_decision,
    model_response_payload,
    structured_final_answer_output,
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
from proof_agent.observability.audit.trace import TraceEmitter, TraceWriter
from proof_agent.runtime.graph import (
    _format_untrusted_web_supplement,
    _maybe_untrusted_web_supplement,
)


class ReActEnterpriseQAStageBehavior:
    """Scheduler-neutral stage behavior for the React Enterprise QA workflow."""

    def __init__(
        self,
        *,
        invocation: HarnessInvocation,
        trace: TraceWriter,
        execution_input: WorkflowTemplateExecutionInput,
        conversation_context: ContextAdmission | None,
        memory_recall_payloads: tuple[MemoryRecallWorkingPayload, ...],
        allow_untrusted_web_supplement: bool,
    ) -> None:
        self.invocation = invocation
        self.trace = trace
        self.execution_input = execution_input
        self.conversation_context = conversation_context
        self.memory_recall_payloads = memory_recall_payloads
        self.allow_untrusted_web_supplement = allow_untrusted_web_supplement
        self.manifest = invocation.manifest
        self.react = self.manifest.react
        self.max_steps = self.react.max_steps if self.react is not None else 0
        self.max_tool_calls = self.react.max_tool_calls if self.react is not None else 0
        self.auto_review_enabled = bool(
            self.manifest.review and self.manifest.review.mode == "auto"
        )
        self.low_risk_review_fast_path_enabled = bool(
            self.manifest.review and self.manifest.review.low_risk_fast_path
        )
        self.workflow_stage_configs = {
            stage.id: stage for stage in self.execution_input.effective_stage_configuration.stages
        }

    def configured_stage_context(
        self,
        stage_id: str,
        state: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        config = self.workflow_stage_configs.get(stage_id)
        if config is None:
            return None
        prompt, business_flow_skill_pack_id = _stage_prompt_with_business_flow_addendum(
            stage_id=stage_id,
            prompt=config.prompt,
            state=state,
            skill_packs=self.invocation.business_flow_skill_packs,
        )
        preview = build_workflow_stage_context_preview(
            descriptor=self.invocation.template,
            stage_id=stage_id,
            prompt=prompt,
            context_options=config.context,
            sample_context=_workflow_stage_runtime_sample_context(
                invocation=self.invocation,
                state=state,
                conversation_context=self.conversation_context,
            ),
        )
        summary = workflow_stage_context_summary(preview)
        descriptor_stage = self.invocation.template.stage(stage_id)
        application: dict[str, Any] | None = None
        if _workflow_stage_summary_has_context(summary):
            application = {
                **summary,
                "stage_label": descriptor_stage.label,
                "model_bearing": descriptor_stage.model_bearing,
                "template_descriptor_version": (self.execution_input.template_descriptor_version),
            }
            if business_flow_skill_pack_id is not None:
                application["context_source"] = "business_flow_skill_pack"
                application["business_flow_skill_pack_id"] = business_flow_skill_pack_id
        # Always emit a workflow_stage_context_applied boundary so the Workflow
        # projection can mark the stage visited and attribute runtime events to
        # it. When the context summary has no substance, emit a minimal payload
        # carrying just the fields the projection reads (stage_id / label /
        # model_bearing). Suppressing the boundary would leave the Workflow tab
        # empty even though the stage ran.
        boundary_payload = (
            application
            if application is not None
            else {
                "stage_id": stage_id,
                "stage_label": descriptor_stage.label,
                "model_bearing": descriptor_stage.model_bearing,
                "template_descriptor_version": (self.execution_input.template_descriptor_version),
            }
        )
        self.trace.emit(
            "workflow_stage_context_applied",
            status="ok",
            payload=boundary_payload,
        )
        return {
            "business_context_addendum": preview["business_context_addendum"],
            "structured_control_context": preview["structured_control_context"],
            "summary": summary,
            "application": application,
        }

    def intent_resolution(self, state: Mapping[str, Any]) -> dict[str, Any]:
        if self.invocation.intent_resolver is None:
            return _refusal("Intent resolver is not configured.")
        stage_context: Mapping[str, Any] | None = None
        try:
            stage_context = self.configured_stage_context("intent_resolution", state)
            intent_result = self.invocation.intent_resolver.resolve(
                question=state["question"],
                system_prompt="Resolve user intent without raw chain-of-thought.",
                context_summary=_conversation_context_summary(self.conversation_context),
                workflow_stage_context=stage_context,
                memory_recall_payloads=self.memory_recall_payloads,
                business_flow_skill_packs=self.invocation.business_flow_skill_packs,
            )
        except ModelOutputNormalizationError as exc:
            llm_interactions = _drain_stage_llm_interactions(
                self.invocation.intent_resolver,
                stage_id="intent_resolution",
                stage_label=self._stage_label("intent_resolution"),
            )
            event = self.trace.emit(
                "model_output_normalization_failed",
                status="blocked",
                payload=_model_output_failure_payload(exc),
            )
            return {
                **_refusal(
                    "The intent resolution output failed validation and the run was stopped."
                ),
                **_stage_context_applications_delta(state, stage_context),
                "stage_llm_interactions": llm_interactions,
                "stage_failure_diagnostics": [
                    _model_output_failure_diagnostic(
                        stage_id="intent_resolution",
                        stage_label=self._stage_label("intent_resolution"),
                        event_id=event.event_id,
                        exc=exc,
                    )
                ],
            }
        llm_interactions = _drain_stage_llm_interactions(
            self.invocation.intent_resolver,
            stage_id="intent_resolution",
            stage_label=self._stage_label("intent_resolution"),
        )
        resolution = intent_result.intent_resolution
        emit_intent_resolution(
            self.trace,
            resolution,
            max_queries=self.manifest.retrieval.max_queries,
        )
        business_flow_delta = self._business_flow_skill_pack_admission_delta(
            intent_result,
        )
        blocked_business_flow_delta = _blocked_business_flow_delta(business_flow_delta)
        if blocked_business_flow_delta is not None:
            _emit_business_flow_clarification_requested(
                self.trace,
                blocked_business_flow_delta,
            )
            return {
                "intent_resolution": _intent_resolution_state_dict(resolution),
                **business_flow_delta,
                **blocked_business_flow_delta,
                **_stage_context_applications_delta(state, stage_context),
                "stage_llm_interactions": llm_interactions,
            }
        hybrid_request_delta = self._governed_hybrid_request_delta(resolution)
        if hybrid_request_delta.get("clarification_need") is not None:
            clarification_need = hybrid_request_delta["clarification_need"]
            self.trace.emit(
                "clarification_requested",
                status="waiting",
                payload={
                    "action_id": clarification_need["action_id"],
                    "missing_fields": list(clarification_need["missing_fields"]),
                    "clarification_type": "hybrid_authority_conditions",
                },
            )
        if hybrid_request_delta.get("governance_refusal") is not None:
            return {
                "intent_resolution": _intent_resolution_state_dict(resolution),
                **business_flow_delta,
                **hybrid_request_delta,
                **_stage_context_applications_delta(state, stage_context),
                "stage_llm_interactions": llm_interactions,
            }
        return {
            "intent_resolution": _intent_resolution_state_dict(resolution),
            **hybrid_request_delta,
            **business_flow_delta,
            **_stage_context_applications_delta(state, stage_context),
            "stage_llm_interactions": llm_interactions,
        }

    def _governed_hybrid_request_delta(
        self,
        resolution: IntentResolution,
    ) -> dict[str, Any]:
        factory = self.invocation.governed_hybrid_request_factory
        if factory is None:
            return {}
        build = factory.build(resolution, self.invocation.institution_authorization)
        if build.request is not None:
            return {"governed_hybrid_request": build.request.model_dump(mode="json")}
        if build.clarification is not None:
            missing_fields = build.clarification.missing_fields
            message = (
                "Please provide "
                f"{', '.join(missing_fields)} before I can search governed insurance rules."
            )
            return {
                "governance_refusal": ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION,
                "governance_message": message,
                "final_output": message,
                "clarification_need": {
                    "action_id": f"hybrid:{resolution.resolution_id}:clarify",
                    "missing_fields": missing_fields,
                    "message": message,
                    "summary": {"reason": build.clarification.reason},
                },
            }
        return _refusal(
            "The governed insurance Knowledge request could not be admitted safely: "
            f"{build.no_recommendation_reason}."
        )

    def _business_flow_skill_pack_admission_delta(
        self,
        intent_result: IntentResolutionResult,
    ) -> dict[str, Any]:
        if not self.invocation.business_flow_skill_packs:
            return {}
        recommendation = intent_result.business_flow_skill_pack_recommendation
        if recommendation is None:
            return {}
        result = admit_business_flow_skill_pack(
            recommendation,
            self.invocation.business_flow_skill_packs,
            route_min_confidence=(
                self.invocation.manifest.capabilities.skills.admission.route_min_confidence
            ),
            authorization_context_present=False,
        )
        recommendation_payload = _jsonable(
            result.recommendation.model_dump(mode="python", warnings=False)
        )
        admission = _jsonable(result.admission.model_dump(mode="python", warnings=False))
        self.trace.emit(
            "business_flow_skill_pack_recommendation",
            status="ok",
            payload=_business_flow_skill_pack_recommendation_trace_payload(recommendation_payload),
        )
        self.trace.emit(
            "business_flow_skill_pack_admission",
            status=(
                "ok"
                if result.admission.decision
                in {
                    BusinessFlowSkillPackAdmissionDecision.ADMITTED,
                    BusinessFlowSkillPackAdmissionDecision.NO_PACK,
                }
                else "blocked"
            ),
            payload={
                **dict(result.admission.trace_summary),
                "recommendation_id": result.recommendation.recommendation_id,
                "intent_resolution_id": result.recommendation.intent_resolution_id,
            },
        )
        return {
            "business_flow_skill_pack_recommendation": recommendation_payload,
            "business_flow_skill_pack_admission": admission,
            "primary_business_flow_skill_pack_id": result.admission.selected_pack_id,
        }

    def plan(self, state: Mapping[str, Any]) -> dict[str, Any]:
        return self._plan_single_pass(state)

    def _plan_normalization_failure(
        self,
        state: Mapping[str, Any],
        stage_context: Mapping[str, Any] | None,
        exc: ModelOutputNormalizationError,
    ) -> dict[str, Any]:
        llm_interactions = _drain_stage_llm_interactions(
            self.invocation.react_planner,
            stage_id="plan",
            stage_label=self._stage_label("plan"),
        )
        event = self.trace.emit(
            "model_output_normalization_failed",
            status="blocked",
            payload=_model_output_failure_payload(exc),
        )
        return {
            **_refusal("The planner output failed validation and the run was stopped."),
            **_stage_context_applications_delta(state, stage_context),
            "stage_llm_interactions": llm_interactions,
            "stage_failure_diagnostics": [
                _model_output_failure_diagnostic(
                    stage_id="plan",
                    stage_label=self._stage_label("plan"),
                    event_id=event.event_id,
                    exc=exc,
                )
            ],
        }

    def _plan_single_pass(self, state: Mapping[str, Any]) -> dict[str, Any]:
        step_count = int(state.get("step_count", 0))
        if self.react is None or self.invocation.react_planner is None:
            return _refusal("ReAct planner is not configured.")
        if should_stop_for_step_budget(step_count, self.max_steps):
            return _refusal(
                "The ReAct step budget was exhausted before an answer could be produced."
            )

        stage_context: Mapping[str, Any] | None = None
        try:
            stage_context = self.configured_stage_context("plan", state)
            proposal = self.invocation.react_planner.plan(
                question=state["question"],
                system_prompt="Use governed ReAct planning without raw chain-of-thought.",
                context_summary=_intent_context_summary(state),
                workflow_stage_context=stage_context,
                memory_recall_payloads=self.memory_recall_payloads,
            )
        except ModelOutputNormalizationError as exc:
            return self._plan_normalization_failure(state, stage_context, exc)
        llm_interactions = _drain_stage_llm_interactions(
            self.invocation.react_planner,
            stage_id="plan",
            stage_label=self._stage_label("plan"),
        )
        emit_reasoning_summary(self.trace, proposal)
        emit_action_proposal(self.trace, proposal)
        return {
            "step_count": step_count + 1,
            "action": _proposal_state_dict(proposal),
            "reasoning_summary": _reasoning_summary_state_dict(proposal),
            **_stage_context_applications_delta(state, stage_context),
            "stage_llm_interactions": llm_interactions,
        }

    def clarify(self, state: Mapping[str, Any]) -> dict[str, Any]:
        proposal = proposal_from_state(state)
        clarification_stage_context = self.configured_stage_context("clarification", state)
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
        response_stage_context = self.configured_stage_context("response", {**state, **result})
        return {
            **result,
            **_stage_context_applications_delta(
                state,
                clarification_stage_context,
                response_stage_context,
            ),
        }

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
            low_risk_fast_path_enabled=self.low_risk_review_fast_path_enabled,
        )
        if decision.decision != PolicyDecisionType.ALLOW:
            return {
                "review_results": [review_event],
                "governance_refusal": ReceiptOutcome.REFUSED_NO_EVIDENCE,
                "governance_message": "I cannot answer because the retrieval plan was blocked by policy.",
                **_stage_context_applications_delta(state, stage_context),
            }
        return {
            "review_results": [review_event],
            **_stage_context_applications_delta(state, stage_context),
        }

    def retrieval(self, state: Mapping[str, Any]) -> dict[str, Any]:
        proposal = proposal_from_state(state)
        retrieval_stage_context = self.configured_stage_context("retrieval", state)
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
            low_risk_fast_path_enabled=self.low_risk_review_fast_path_enabled,
        )
        if step_decision.decision != PolicyDecisionType.ALLOW:
            return {
                "review_results": [step_review_event],
                "governance_refusal": ReceiptOutcome.REFUSED_NO_EVIDENCE,
                "governance_message": "I cannot answer because the retrieval step was blocked by policy.",
                **_stage_context_applications_delta(state, retrieval_stage_context),
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
                retrieval_query_set=_retrieval_query_set_from_state(state),
                max_queries=self.manifest.retrieval.max_queries,
                query_concurrency=self.manifest.retrieval.query_concurrency,
                query_timeout_seconds=self.manifest.retrieval.query_timeout_seconds,
                preferred_binding_ids=_admitted_business_flow_knowledge_binding_refs(
                    state,
                    self.invocation.business_flow_skill_packs,
                ),
                force_empty=state["question"] == UNSUPPORTED_QUESTION,
                governed_hybrid_request=_governed_hybrid_request_from_state(state),
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

        memory_stage_context: Mapping[str, Any] | None = None
        if self.workflow_stage_available("memory"):
            memory = self.invocation.create_memory()
            memory_stage_context = self.configured_stage_context("memory", state)
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
                **_stage_context_applications_delta(
                    state,
                    retrieval_stage_context,
                    memory_stage_context,
                ),
            }
        evidence_state = [_evidence_state_dict(chunk) for chunk in evidence]

        return {
            "review_results": [step_review_event],
            "evidence": evidence_state,
            **_stage_context_applications_delta(
                state,
                retrieval_stage_context,
                memory_stage_context,
            ),
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
            memory_recall_payloads=self.memory_recall_payloads,
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
            low_risk_fast_path_enabled=self.low_risk_review_fast_path_enabled,
        )
        if decision.decision != PolicyDecisionType.ALLOW:
            return {
                "review_results": [review_event],
                "governance_refusal": ReceiptOutcome.REFUSED_NO_EVIDENCE,
                "governance_message": "I cannot answer because the model call was blocked by policy.",
                **_stage_context_applications_delta(state, stage_context),
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
        self.trace.emit(
            "model_response", status="ok", payload=model_response_payload(model_response)
        )
        llm_interactions = [
            _llm_interaction_capture(
                stage_id="model_answer",
                stage_label=self._stage_label("model_answer"),
                role=ModelCallRole.FINAL_ANSWER.value,
                request=model_request,
                response=model_response,
            )
        ]

        outcome = ReceiptOutcome.ANSWERED_WITH_CITATIONS
        validation_results = validate_model_output(
            response=model_response,
            outcome=outcome,
            evidence=evidence,
            question=str(state.get("question", "")),
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
            response_stage_context = self.configured_stage_context("response", {**state, **result})
            return {
                **result,
                **_stage_context_applications_delta(
                    state,
                    stage_context,
                    response_stage_context,
                ),
                "stage_llm_interactions": llm_interactions,
            }
        final_answer_output, _ = structured_final_answer_output(
            model_response.content,
            outcome=outcome,
        )
        final_message = str(final_answer_output.get("message", model_response.content))
        result = {
            "review_results": [review_event],
            "final_output": final_message,
            "governance_refusal": outcome,
            "governance_message": final_message,
        }
        response_stage_context = self.configured_stage_context("response", {**state, **result})
        return {
            **result,
            **_stage_context_applications_delta(
                state,
                stage_context,
                response_stage_context,
            ),
            "stage_llm_interactions": llm_interactions,
        }

    def review_tool(self, state: Mapping[str, Any]) -> dict[str, Any]:
        proposal = proposal_from_state(state)
        if not (
            self.workflow_stage_available("tool_review") and self.workflow_stage_available("tool")
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
            low_risk_fast_path_enabled=self.low_risk_review_fast_path_enabled,
        )
        if decision.decision in {PolicyDecisionType.DENY, PolicyDecisionType.ESCALATE}:
            return {
                "review_results": [review_event],
                "governance_refusal": ReceiptOutcome.REFUSED_NO_EVIDENCE,
                "governance_message": "I cannot run the requested tool because the tool call was blocked by policy.",
                **_stage_context_applications_delta(state, stage_context),
            }
        return {
            "review_results": [review_event],
            "tool_call_count": int(state.get("tool_call_count", 0)) + 1,
            "tool_policy_decision": decision.decision.value,
            **_stage_context_applications_delta(state, stage_context),
        }

    def tool(
        self,
        state: Mapping[str, Any],
        *,
        approval_decision: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        proposal = proposal_from_state(state)
        if not self.workflow_stage_available("tool"):
            return _tool_capability_disabled_delta()
        tool_stage_context = self.configured_stage_context("tool", state)
        tool_name = proposal.target_tool_name or ""
        parameters = dict(proposal.parameters)
        tool_policy_decision = PolicyDecisionType(
            state.get("tool_policy_decision") or PolicyDecisionType.REQUIRE_APPROVAL.value
        )

        if (
            tool_policy_decision == PolicyDecisionType.REQUIRE_APPROVAL
            and approval_decision is None
        ):
            gateway_result = _request_tool_or_refuse(
                invocation=self.invocation,
                trace=self.trace,
                proposal=proposal,
                tool_name=tool_name,
                parameters=parameters,
                approved=False,
            )
            if isinstance(gateway_result, dict):
                return {
                    **gateway_result,
                    **_stage_context_applications_delta(state, tool_stage_context),
                }
            return {
                "governance_refusal": ReceiptOutcome.WAITING_FOR_APPROVAL,
                "governance_message": (f"Waiting for approval before {tool_name} can execute."),
                "tool_approval_action_id": proposal.action_id,
                "tool_approval_checkpoint_ref": f"thread:{self.trace.run_id}",
                "tool_approval_parameters": parameters,
                "tool_approval_policy_decision": tool_policy_decision,
                "tool_approval_risk_level": proposal.risk_level,
                "tool_approval_state": gateway_result.approval_state,
                "tool_approval_tool_name": tool_name,
                **_stage_context_applications_delta(state, tool_stage_context),
            }

        if approval_decision is not None and not approval_decision.get("approved"):
            actor = approval_decision.get("actor", "local-user")
            self.trace.emit(
                "approval_denied",
                status="blocked",
                payload={
                    "approval_id": approval_decision.get("approval_id", "appr_unknown"),
                    "tool_name": tool_name,
                    "state": ApprovalStatus.DENIED.value,
                    "actor": actor,
                },
            )
            message = f"The {tool_name} tool was not run because approval was denied."
            result = {
                "governance_refusal": ReceiptOutcome.TOOL_APPROVAL_DENIED,
                "governance_message": message,
                "final_output": message,
            }
            return {
                **result,
                **_stage_context_applications_delta(state, tool_stage_context),
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
            return {
                **gateway_result,
                **_stage_context_applications_delta(state, tool_stage_context),
            }
        if approval_decision is not None:
            self.trace.emit(
                "approval_granted",
                status="ok",
                payload={
                    "approval_id": approval_decision.get(
                        "approval_id",
                        gateway_result.approval_state.approval_id,
                    ),
                    "tool_name": tool_name,
                    "state": ApprovalStatus.GRANTED.value,
                    "actor": approval_decision.get("actor", "local-user"),
                },
            )
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
            response_stage_context = self.configured_stage_context("response", {**state, **result})
            return {
                **result,
                **_stage_context_applications_delta(
                    state,
                    tool_stage_context,
                    response_stage_context,
                ),
            }
        message = "Customer policy status is active according to the approved mock lookup."
        result = {
            "final_output": message,
            "governance_refusal": ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            "governance_message": message,
        }
        response_stage_context = self.configured_stage_context("response", {**state, **result})
        return {
            **result,
            **_stage_context_applications_delta(
                state,
                tool_stage_context,
                response_stage_context,
            ),
        }

    def workflow_stage_available(self, stage_id: str) -> bool:
        return self.execution_input.workflow_stage_availability.is_available(stage_id)

    def _stage_label(self, stage_id: str) -> str:
        try:
            return self.execution_input.effective_stage_configuration.stage(stage_id).label
        except KeyError:
            return stage_id


def proposal_from_state(state: Mapping[str, Any]) -> ReActActionProposal:
    return ReActActionProposal.model_validate(state["action"])


def _stage_context_applications_delta(
    state: Mapping[str, Any],
    *stage_contexts: Mapping[str, Any] | None,
) -> dict[str, Any]:
    _ = state
    applications: list[dict[str, Any]] = []
    added = False
    for stage_context in stage_contexts:
        if not isinstance(stage_context, Mapping):
            continue
        application = stage_context.get("application")
        if not isinstance(application, Mapping):
            continue
        applications.append(dict(application))
        added = True
    if not added:
        return {}
    return {"stage_context_applications": applications}


def _model_output_failure_payload(exc: ModelOutputNormalizationError) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "role": exc.role,
        "error_code": exc.error_code,
        "raw_content_length": exc.raw_content_length,
    }
    if exc.contract_name is not None:
        payload["contract_name"] = exc.contract_name
    if exc.violation_codes:
        payload["violation_codes"] = list(exc.violation_codes)
    if exc.field_paths:
        payload["field_paths"] = list(exc.field_paths)
    if exc.violation_count:
        payload["violation_count"] = exc.violation_count
    return payload


def _model_output_failure_diagnostic(
    *,
    stage_id: str,
    stage_label: str,
    event_id: str,
    exc: ModelOutputNormalizationError,
) -> dict[str, Any]:
    diagnostic = {
        "stage_id": stage_id,
        "stage_label": stage_label,
        "event_type": "model_output_normalization_failed",
        "status": "blocked",
        "error_code": exc.error_code,
        "role": exc.role,
        "raw_content_length": exc.raw_content_length,
        "related_event_id": event_id,
        "contract_name": exc.contract_name,
        "violation_codes": list(exc.violation_codes),
        "field_paths": list(exc.field_paths),
        "violation_count": exc.violation_count,
    }
    return {key: value for key, value in diagnostic.items() if value not in (None, [], 0)}


def _drain_stage_llm_interactions(
    owner: object | None,
    *,
    stage_id: str,
    stage_label: str,
) -> list[dict[str, Any]]:
    provider = getattr(owner, "model_provider", None)
    if not isinstance(provider, _TracingModelProvider):
        return []
    return provider.drain_sensitive_interactions(
        stage_id=stage_id,
        stage_label=stage_label,
    )


def _llm_interaction_capture(
    *,
    stage_id: str,
    stage_label: str,
    role: str,
    request: ModelRequest,
    response: ModelResponse,
) -> dict[str, Any]:
    response_json, parse_error = (
        _model_content_json(response.content) if request.response_format == "json" else (None, None)
    )
    capture = {
        "stage_id": stage_id,
        "stage_label": stage_label,
        "role": role,
        "provider": response.provider_name,
        "model": response.model_name,
        "request_json": _model_request_json(request),
        "response_json": response_json,
        "response_content_length": len(response.content),
        "response_json_parse_error_code": parse_error,
    }
    return {key: value for key, value in capture.items() if value is not None}


def _model_request_json(request: ModelRequest) -> dict[str, Any]:
    return {
        "provider": request.provider,
        "model": request.model,
        "response_format": request.response_format,
        "function_schema": (
            request.function_schema.model_dump(mode="json")
            if request.function_schema is not None
            else None
        ),
        "stream": request.stream,
        "temperature": request.temperature,
        "max_output_tokens": request.max_output_tokens,
        "timeout_seconds": request.timeout_seconds,
        "metadata": dict(request.metadata),
        "evidence_sources": list(request.evidence_sources),
        "messages": [
            {
                "role": message.role.value,
                "content": message.content,
                "name": message.name,
                "metadata": dict(message.metadata),
            }
            for message in request.messages
        ],
    }


def _model_content_json(content: str) -> tuple[Any | None, str | None]:
    stripped = content.strip()
    if not stripped:
        return None, "empty_model_output"
    try:
        return json.loads(stripped), None
    except json.JSONDecodeError:
        return None, "model_output_json_parse_failed"


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
        trace: TraceEmitter,
        role: ModelCallRole,
        stage_id: str | None = None,
    ) -> None:
        self._provider = provider
        self._trace = trace
        self._role = role
        self._stage_id = stage_id
        self._sensitive_interactions: list[dict[str, Any]] = []

    @property
    def inner_provider(self) -> ModelProvider:
        return self._provider

    @property
    def role(self) -> ModelCallRole:
        return self._role

    def bind_trace(self, trace: TraceEmitter, *, stage_id: str | None = None) -> None:
        self._trace = trace
        self._stage_id = stage_id

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
        request_payload = {
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
        }
        if self._stage_id is not None:
            request_payload["stage_id"] = self._stage_id
        self._trace.emit(
            "model_request",
            status="ok",
            payload=request_payload,
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
                stage_id=self._stage_id,
            )
            raise
        payload = model_response_payload(response)
        payload["role"] = self._role.value
        if self._stage_id is not None:
            payload["stage_id"] = self._stage_id
        self._trace.emit("model_response", status="ok", payload=payload)
        self._sensitive_interactions.append(
            _llm_interaction_capture(
                stage_id="",
                stage_label="",
                role=self._role.value,
                request=request,
                response=response,
            )
        )
        return response

    def drain_sensitive_interactions(
        self,
        *,
        stage_id: str,
        stage_label: str,
    ) -> list[dict[str, Any]]:
        interactions = self._sensitive_interactions
        self._sensitive_interactions = []
        return [
            {
                **interaction,
                "stage_id": stage_id,
                "stage_label": stage_label,
            }
            for interaction in interactions
        ]


def wrap_control_plane_model_providers(
    invocation: HarnessInvocation,
    trace: TraceEmitter,
    *,
    stage_id_by_role: Mapping[ModelCallRole, str] | None = None,
) -> None:
    _wrap_model_provider_attribute(
        invocation.intent_resolver,
        trace=trace,
        role=ModelCallRole.INTENT_RESOLUTION,
        stage_id=_stage_id_for_control_plane_role(
            ModelCallRole.INTENT_RESOLUTION,
            stage_id_by_role,
        ),
    )
    _wrap_model_provider_attribute(
        invocation.react_planner,
        trace=trace,
        role=ModelCallRole.REACT_PLANNER,
        stage_id=_stage_id_for_control_plane_role(
            ModelCallRole.REACT_PLANNER,
            stage_id_by_role,
        ),
    )
    _wrap_model_provider_attribute(
        invocation.review_subagent,
        trace=trace,
        role=ModelCallRole.HARNESS_REVIEW,
        stage_id=_stage_id_for_control_plane_role(
            ModelCallRole.HARNESS_REVIEW,
            stage_id_by_role,
        ),
    )


def _wrap_model_provider_attribute(
    owner: object | None,
    *,
    trace: TraceEmitter,
    role: ModelCallRole,
    stage_id: str | None = None,
) -> None:
    if owner is None or not hasattr(owner, "model_provider"):
        return
    provider = getattr(owner, "model_provider")
    if provider is None:
        return
    if isinstance(provider, _TracingModelProvider):
        if provider.role == role:
            provider.bind_trace(trace, stage_id=stage_id)
            return
        provider = provider.inner_provider
    setattr(
        owner,
        "model_provider",
        _TracingModelProvider(
            provider=provider,
            trace=trace,
            role=role,
            stage_id=stage_id,
        ),
    )


def _stage_id_for_control_plane_role(
    role: ModelCallRole,
    stage_id_by_role: Mapping[ModelCallRole, str] | None,
) -> str | None:
    if stage_id_by_role is None:
        return None
    return stage_id_by_role.get(role)


def _emit_control_plane_model_error(
    trace: TraceEmitter,
    *,
    role: ModelCallRole,
    provider: str,
    model: str,
    exc: BaseException,
    stage_id: str | None = None,
) -> None:
    payload = {
        "role": role.value,
        "provider": provider,
        "model": model,
        "error_code": getattr(exc, "code", "PA_MODEL_002"),
        "error_class": exc.__class__.__name__,
        "retryable": bool(getattr(exc, "retryable", False)),
    }
    if stage_id is not None:
        payload["stage_id"] = stage_id
    trace.emit(
        "model_error",
        status="error",
        payload=payload,
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
        "retrieval_query_set": [
            {
                "query": item.query,
                "intent_angle": item.intent_angle,
                "required": item.required,
                "reason": item.reason,
            }
            for item in resolution.retrieval_query_set
        ],
        "insurance_condition_proposal": {
            "values": dict(resolution.insurance_condition_proposal.values)
        },
    }


def _retrieval_query_set_from_state(
    state: Mapping[str, Any],
) -> tuple[RetrievalQueryItem, ...]:
    resolution = state.get("intent_resolution")
    if not isinstance(resolution, Mapping):
        return ()
    raw_items = resolution.get("retrieval_query_set")
    if not isinstance(raw_items, list | tuple):
        return ()
    items: list[RetrievalQueryItem] = []
    for raw_item in raw_items:
        if isinstance(raw_item, Mapping):
            items.append(RetrievalQueryItem.model_validate(dict(raw_item)))
    return tuple(items)


def _governed_hybrid_request_from_state(
    state: Mapping[str, Any],
) -> GovernedHybridRetrievalRequest | None:
    raw = state.get("governed_hybrid_request")
    if raw is None:
        return None
    return GovernedHybridRetrievalRequest.model_validate(raw)


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
            list(proposal.parameters.get("missing_fields", ())) if proposal is not None else []
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


def _business_flow_skill_pack_recommendation_trace_payload(
    recommendation: Mapping[str, Any],
) -> dict[str, Any]:
    raw_candidate_packs = recommendation.get("candidate_packs", ())
    candidate_packs = raw_candidate_packs if isinstance(raw_candidate_packs, list | tuple) else ()
    return {
        "recommendation_id": recommendation.get("recommendation_id"),
        "intent_resolution_id": recommendation.get("intent_resolution_id"),
        "recommendation_type": recommendation.get("recommendation_type"),
        "route_confidence": recommendation.get("confidence"),
        "reason": recommendation.get("reason"),
        "candidate_count": len(candidate_packs),
        "candidate_packs": [
            {
                "pack_id": candidate.get("pack_id"),
                "confidence": candidate.get("confidence"),
                "reason": candidate.get("reason"),
            }
            for candidate in candidate_packs
            if isinstance(candidate, Mapping)
        ],
        "requires_task_split": recommendation.get("requires_task_split", False),
    }


def _stage_prompt_with_business_flow_addendum(
    *,
    stage_id: str,
    prompt: Mapping[str, Any] | WorkflowStagePromptConfig,
    state: Mapping[str, Any],
    skill_packs: tuple[BusinessFlowSkillPackDefinition, ...],
) -> tuple[Mapping[str, Any] | WorkflowStagePromptConfig, str | None]:
    selected_pack_id = state.get("primary_business_flow_skill_pack_id")
    if not selected_pack_id:
        return prompt, None
    for skill_pack in skill_packs:
        if skill_pack.id != selected_pack_id:
            continue
        addendum = skill_pack.stage_prompt_addenda.get(stage_id)
        if addendum is None:
            return prompt, None
        return _merge_stage_prompt(prompt, addendum), skill_pack.id
    return prompt, None


def _admitted_business_flow_knowledge_binding_refs(
    state: Mapping[str, Any],
    skill_packs: tuple[BusinessFlowSkillPackDefinition, ...],
) -> tuple[str, ...]:
    selected_pack_id = state.get("primary_business_flow_skill_pack_id")
    if not selected_pack_id:
        return ()
    for skill_pack in skill_packs:
        if skill_pack.id == selected_pack_id:
            return skill_pack.knowledge_binding_refs
    return ()


def _merge_stage_prompt(
    prompt: Mapping[str, Any] | WorkflowStagePromptConfig,
    addendum: WorkflowStagePromptConfig,
) -> WorkflowStagePromptConfig:
    base = _stage_prompt_config(prompt)
    return WorkflowStagePromptConfig(
        business_context=_join_prompt_text(
            base.business_context,
            addendum.business_context,
        ),
        task_instructions=(
            *base.task_instructions,
            *addendum.task_instructions,
        ),
        output_preferences=(
            *base.output_preferences,
            *addendum.output_preferences,
        ),
    )


def _stage_prompt_config(
    prompt: Mapping[str, Any] | WorkflowStagePromptConfig,
) -> WorkflowStagePromptConfig:
    if isinstance(prompt, WorkflowStagePromptConfig):
        return prompt
    return WorkflowStagePromptConfig(
        business_context=str(prompt.get("business_context", "") or ""),
        task_instructions=tuple(str(item) for item in prompt.get("task_instructions", ()) or ()),
        output_preferences=tuple(str(item) for item in prompt.get("output_preferences", ()) or ()),
    )


def _join_prompt_text(*parts: str) -> str:
    return "\n\n".join(part for part in parts if part)


def _blocked_business_flow_delta(delta: Mapping[str, Any]) -> dict[str, Any] | None:
    admission = delta.get("business_flow_skill_pack_admission")
    if not isinstance(admission, Mapping):
        return None
    decision = admission.get("decision")
    if decision == BusinessFlowSkillPackAdmissionDecision.NEEDS_CLARIFICATION.value:
        message = (
            "I need one intended business flow before I can continue. "
            "Please name the relevant Skill Pack or restate the request with a "
            "more specific business domain."
        )
        trace_summary = admission.get("trace_summary")
        trace_summary_map = trace_summary if isinstance(trace_summary, Mapping) else {}
        candidate_count = trace_summary_map.get("candidate_count", 0)
        summary = {
            "reason": "business_flow_skill_pack",
            "failure_reason": admission.get("failure_reason"),
            "candidate_count": candidate_count,
        }
        return {
            "governance_refusal": ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION,
            "governance_message": message,
            "final_output": message,
            "clarification_need": {
                "action_id": admission.get("admission_id"),
                "missing_fields": ("business_flow_skill_pack",),
                "message": message,
                "summary": summary,
            },
        }
    if decision in {
        BusinessFlowSkillPackAdmissionDecision.REFUSED.value,
        BusinessFlowSkillPackAdmissionDecision.FAILED_CLOSED.value,
    }:
        return _refusal("The Business Flow Skill Pack recommendation could not be admitted safely.")
    return None


def _emit_business_flow_clarification_requested(
    trace: TraceWriter,
    delta: Mapping[str, Any],
) -> None:
    clarification_need = delta.get("clarification_need")
    if not isinstance(clarification_need, Mapping):
        return
    trace.emit(
        "clarification_requested",
        status="waiting",
        payload={
            "action_id": clarification_need.get("action_id"),
            "missing_fields": list(clarification_need.get("missing_fields", ())),
            "clarification_type": "business_flow_skill_pack",
        },
    )


def _refusal(message: str) -> dict[str, Any]:
    return {
        "governance_refusal": ReceiptOutcome.REFUSED_NO_EVIDENCE,
        "governance_message": message,
        "final_output": message,
    }
