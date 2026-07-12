from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Literal

from proof_agent.bootstrap.composition import HarnessInvocation
from proof_agent.contracts import (
    AnswerEvidenceContext,
    ControlledReActRunState,
    EnforcementPoint,
    EvidenceChunk,
    ModelCallRole,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelRole,
    PolicyDecisionType,
    ReActActionProposal,
    ReceiptOutcome,
    TraceEventType,
    ValidationResult,
    ValidationStatus,
    WorkflowStageFailureDiagnostic,
    WorkflowStageLlmInteraction,
    WorkflowStageStatus,
)
from proof_agent.control.context_budget import (
    ContextBudgetKey,
    record_context_overflow_calibration,
)
from proof_agent.control.workflow.harness_helpers import (
    build_model_request,
    cost_class,
    emit_policy_decision,
    model_response_payload,
    structured_final_answer_output,
    validate_model_output,
)
from proof_agent.control.workflow.controlled_react.ports import TracePort
from proof_agent.control.workflow.controlled_react.ports import AnswerSynthesisResult
from proof_agent.control.workflow.controlled_react.model_tracing import (
    build_llm_interaction_capture,
    parse_model_content_json,
)


FINAL_ANSWER_OUTPUT_CONTRACT = "FinalAnswerOutput"
MAX_FINAL_ANSWER_REPAIR_ATTEMPTS = 1


class FinalAnswerAttemptStatus(str, Enum):
    ADMITTED = "admitted"
    POLICY_DENIED = "policy_denied"
    SCHEMA_FAILED = "schema_failed"
    SAFETY_FAILED = "safety_failed"
    CITATION_BINDING_FAILED = "citation_binding_failed"
    FINAL_ANSWER_ADEQUACY_FAILED = "final_answer_adequacy_failed"
    VALIDATION_FAILED = "validation_failed"
    MODEL_ERROR = "model_error"


@dataclass(frozen=True)
class PreparedFinalAnswerAttempt:
    request: ModelRequest
    estimated_tokens: int | None
    evidence: tuple[EvidenceChunk, ...]


@dataclass(frozen=True)
class GeneratedFinalAnswerAttempt:
    prepared: PreparedFinalAnswerAttempt
    response: ModelResponse
    interaction: WorkflowStageLlmInteraction


@dataclass(frozen=True)
class NormalizedFinalAnswerAttempt:
    generated: GeneratedFinalAnswerAttempt
    validation_results: tuple[ValidationResult, ...]
    status: FinalAnswerAttemptStatus
    diagnostic: WorkflowStageFailureDiagnostic | None = None
    message: str | None = None
    prior_generated_attempts: tuple[GeneratedFinalAnswerAttempt, ...] = ()


class FinalAnswerAttemptRunner:
    def __init__(
        self,
        invocation: HarnessInvocation,
        *,
        trace: TracePort,
        workflow_stage_context: Mapping[str, Any] | None = None,
    ) -> None:
        self._invocation = invocation
        self._trace = trace
        self._workflow_stage_context = workflow_stage_context

    def run(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
        answer_context: AnswerEvidenceContext,
        *,
        evidence: tuple[EvidenceChunk, ...],
    ) -> AnswerSynthesisResult:
        prepared = self.prepare(state, answer_context, evidence=evidence)
        generated = self.generate(state, action, prepared)
        if isinstance(generated, AnswerSynthesisResult):
            return generated
        normalized = self.normalize(state, generated)
        repaired = self.repair(state, action, normalized)
        if isinstance(repaired, AnswerSynthesisResult):
            return repaired
        return self.admit(state, action, repaired)

    def prepare(
        self,
        state: ControlledReActRunState,
        answer_context: AnswerEvidenceContext,
        *,
        evidence: tuple[EvidenceChunk, ...],
    ) -> PreparedFinalAnswerAttempt:
        _ = answer_context
        request = build_model_request(
            question=state.question,
            evidence=evidence,
            provider=self._invocation.model_provider.provider_name,
            model=self._invocation.model_provider.model_name,
            conversation_context=state.conversation_context,
            memory_recall_payloads=state.memory_recall_payloads,
            workflow_stage_context=self._workflow_stage_context,
        )
        estimated_tokens = self._invocation.model_provider.estimate_tokens(request)
        return PreparedFinalAnswerAttempt(
            request=request,
            estimated_tokens=estimated_tokens,
            evidence=evidence,
        )

    def generate(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
        prepared: PreparedFinalAnswerAttempt,
    ) -> GeneratedFinalAnswerAttempt | AnswerSynthesisResult:
        policy_decision = self._invocation.policy.evaluate(
            EnforcementPoint.BEFORE_MODEL_CALL,
            _model_call_policy_context(
                prepared.request,
                estimated_tokens=prepared.estimated_tokens,
            ),
            trace_event_id=f"{state.run_id}:{action.action_id}:before_model_call",
        )
        repair_attempt = _request_repair_attempt(prepared.request)
        emit_policy_decision(
            _StageScopedTrace(self._trace, stage_id="model_answer"),
            policy_decision,
            payload_extra=(
                {"repair_attempt": repair_attempt} if repair_attempt is not None else None
            ),
        )
        if policy_decision.decision is not PolicyDecisionType.ALLOW:
            message = "The final-answer model call was blocked by policy."
            return AnswerSynthesisResult(
                outcome=ReceiptOutcome.POLICY_DENIED,
                final_output=message,
                message=message,
                reasoning_summary=action.reasoning_summary.model_dump(mode="json"),
                evidence=prepared.evidence,
                model_usage_summary={
                    "provider": prepared.request.provider,
                    "model": prepared.request.model,
                    "role": ModelCallRole.FINAL_ANSWER.value,
                    "message_count": len(prepared.request.messages),
                    "estimated_tokens": prepared.estimated_tokens,
                    "stream": prepared.request.stream,
                    "cost_class": cost_class(prepared.request.provider),
                },
            )
        _emit_model_request_trace(
            self._trace,
            prepared.request,
            estimated_tokens=prepared.estimated_tokens,
            stage_id="model_answer",
        )
        try:
            response = self._invocation.model_provider.generate(prepared.request)
        except Exception as exc:
            if _context_overflow_recovery_allowed(
                exc,
                request=prepared.request,
                manifest_context=self._invocation.manifest.context,
            ):
                _emit_model_error_trace(
                    self._trace,
                    provider=prepared.request.provider,
                    model=prepared.request.model,
                    exc=exc,
                    stage_id="model_answer",
                )
                retry_prepared = self._prepare_context_overflow_retry(
                    state,
                    prepared,
                )
                _emit_context_budget_calibration_update(
                    self._trace,
                    prepared=prepared,
                    retry_prepared=retry_prepared,
                    update_ref=_record_context_overflow_calibration(
                        self._invocation,
                        prepared=prepared,
                        retry_prepared=retry_prepared,
                    ),
                )
                return self.generate(state, action, retry_prepared)
            _emit_model_error_trace(
                self._trace,
                provider=prepared.request.provider,
                model=prepared.request.model,
                exc=exc,
                stage_id="model_answer",
            )
            raise
        _emit_model_response_trace(
            self._trace,
            response,
            repair_attempt=_request_repair_attempt(prepared.request),
            stage_id="model_answer",
        )
        interaction = WorkflowStageLlmInteraction.model_validate(
            build_llm_interaction_capture(
                stage_id="model_answer",
                stage_label="Model Answer",
                role=ModelCallRole.FINAL_ANSWER.value,
                request=prepared.request,
                response=response,
            )
        )
        return GeneratedFinalAnswerAttempt(
            prepared=prepared,
            response=response,
            interaction=interaction,
        )

    def _prepare_context_overflow_retry(
        self,
        state: ControlledReActRunState,
        prepared: PreparedFinalAnswerAttempt,
    ) -> PreparedFinalAnswerAttempt:
        retry_request = build_model_request(
            question=state.question,
            evidence=prepared.evidence,
            provider=prepared.request.provider,
            model=prepared.request.model,
            conversation_context=None,
            memory_recall_payloads=(),
        ).model_copy(
            update={
                "temperature": prepared.request.temperature,
                "max_output_tokens": prepared.request.max_output_tokens,
                "timeout_seconds": prepared.request.timeout_seconds,
                "stream": prepared.request.stream,
                "metadata": {
                    **dict(prepared.request.metadata),
                    "conversation_context_admitted": False,
                    "memory_recall_admitted": False,
                    "context_convergence_level": "deep_compression",
                    "context_overflow_recovery": True,
                },
            }
        )
        return PreparedFinalAnswerAttempt(
            request=retry_request,
            estimated_tokens=self._invocation.model_provider.estimate_tokens(retry_request),
            evidence=prepared.evidence,
        )

    def normalize(
        self,
        state: ControlledReActRunState,
        generated: GeneratedFinalAnswerAttempt,
    ) -> NormalizedFinalAnswerAttempt:
        outcome = ReceiptOutcome.ANSWERED_WITH_CITATIONS
        validation_results = validate_model_output(
            response=generated.response,
            outcome=outcome,
            evidence=generated.prepared.evidence,
            question=state.question,
        )
        failed = tuple(
            result for result in validation_results if result.status is ValidationStatus.FAILED
        )
        if failed:
            diagnostic = final_answer_validation_failure_diagnostic(
                trace=self._trace,
                response=generated.response,
                validation_results=validation_results,
            )
            return NormalizedFinalAnswerAttempt(
                generated=generated,
                validation_results=validation_results,
                status=_attempt_status(failed),
                diagnostic=diagnostic,
            )
        final_answer_output, _parse_error = structured_final_answer_output(
            generated.response.content,
            outcome=outcome,
        )
        return NormalizedFinalAnswerAttempt(
            generated=generated,
            validation_results=validation_results,
            status=FinalAnswerAttemptStatus.ADMITTED,
            message=str(final_answer_output.get("message", generated.response.content)),
        )

    def repair(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
        normalized: NormalizedFinalAnswerAttempt,
    ) -> NormalizedFinalAnswerAttempt | AnswerSynthesisResult:
        if not _repair_eligible(normalized):
            return normalized
        repair_request = _final_answer_repair_request(state, normalized)
        repair_prepared = PreparedFinalAnswerAttempt(
            request=repair_request,
            estimated_tokens=self._invocation.model_provider.estimate_tokens(repair_request),
            evidence=normalized.generated.prepared.evidence,
        )
        repair_generated = self.generate(state, action, repair_prepared)
        if isinstance(repair_generated, AnswerSynthesisResult):
            return replace(
                repair_generated,
                stage_llm_interactions=_stage_llm_interactions(normalized),
            )
        repaired = self.normalize(state, repair_generated)
        return replace(
            repaired,
            prior_generated_attempts=(
                *normalized.prior_generated_attempts,
                normalized.generated,
            ),
        )

    def admit(
        self,
        state: ControlledReActRunState,
        action: ReActActionProposal,
        normalized: NormalizedFinalAnswerAttempt,
    ) -> AnswerSynthesisResult:
        generated = normalized.generated
        if normalized.diagnostic is not None:
            message = "I cannot answer because the model output failed validation."
            return AnswerSynthesisResult(
                outcome=ReceiptOutcome.REFUSED_NO_EVIDENCE,
                final_output=message,
                message=message,
                reasoning_summary=action.reasoning_summary.model_dump(mode="json"),
                evidence=generated.prepared.evidence,
                model_usage_summary=_model_usage_summary(
                    request=generated.prepared.request,
                    response=generated.response,
                    estimated_tokens=generated.prepared.estimated_tokens,
                ),
                stage_llm_interactions=_stage_llm_interactions(normalized),
                stage_failure_diagnostics=(normalized.diagnostic,),
            )
        message = normalized.message or generated.response.content
        return AnswerSynthesisResult(
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            final_output=message,
            message=message,
            reasoning_summary=action.reasoning_summary.model_dump(mode="json"),
            evidence=generated.prepared.evidence,
            model_usage_summary=_model_usage_summary(
                request=generated.prepared.request,
                response=generated.response,
                estimated_tokens=generated.prepared.estimated_tokens,
            ),
            stage_llm_interactions=_stage_llm_interactions(normalized),
        )


def _attempt_status(
    failed_validation_results: tuple[ValidationResult, ...],
) -> FinalAnswerAttemptStatus:
    error_code = _primary_error_code(failed_validation_results)
    if error_code == "schema_failed":
        return FinalAnswerAttemptStatus.SCHEMA_FAILED
    if error_code == "safety_failed":
        return FinalAnswerAttemptStatus.SAFETY_FAILED
    if error_code == "citation_binding_failed":
        return FinalAnswerAttemptStatus.CITATION_BINDING_FAILED
    if error_code == "final_answer_adequacy_failed":
        return FinalAnswerAttemptStatus.FINAL_ANSWER_ADEQUACY_FAILED
    return FinalAnswerAttemptStatus.VALIDATION_FAILED


def _repair_eligible(normalized: NormalizedFinalAnswerAttempt) -> bool:
    if len(normalized.prior_generated_attempts) >= MAX_FINAL_ANSWER_REPAIR_ATTEMPTS:
        return False
    if not normalized.generated.prepared.evidence:
        return False
    if normalized.status is FinalAnswerAttemptStatus.SCHEMA_FAILED:
        return True
    if normalized.status is FinalAnswerAttemptStatus.CITATION_BINDING_FAILED:
        return bool(_allowed_citation_refs(normalized.generated.prepared.evidence))
    return normalized.status is FinalAnswerAttemptStatus.FINAL_ANSWER_ADEQUACY_FAILED


def _context_overflow_recovery_allowed(
    exc: Exception,
    *,
    request: ModelRequest,
    manifest_context: Any,
) -> bool:
    if request.metadata.get("context_overflow_recovery"):
        return False
    if manifest_context is not None:
        if getattr(manifest_context, "budget_profile", None) is not None:
            return False
        if getattr(manifest_context, "dynamic_calibration", True) is False:
            return False
    return _is_context_limit_error(exc)


def _is_context_limit_error(exc: Exception) -> bool:
    code = str(getattr(exc, "code", "") or "")
    if code in {"PA_MODEL_CONTEXT_LIMIT", "context_length_exceeded"}:
        return True
    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "context length",
            "context window",
            "maximum context",
            "too many tokens",
            "token limit",
            "context limit",
        )
    )


def _record_context_overflow_calibration(
    invocation: HarnessInvocation,
    *,
    prepared: PreparedFinalAnswerAttempt,
    retry_prepared: PreparedFinalAnswerAttempt,
) -> str | None:
    update = record_context_overflow_calibration(
        context_config=invocation.manifest.context,
        calibration_store=invocation.context_budget_calibration_store,
        key=ContextBudgetKey(
            provider=prepared.request.provider,
            model=prepared.request.model,
            role=ModelCallRole.FINAL_ANSWER.value,
            profile_version=(
                invocation.manifest.context.budget_profile.profile_version
                if invocation.manifest.context is not None
                and invocation.manifest.context.budget_profile is not None
                else "context_budget.v1"
            ),
        ),
        failed_estimated_tokens=_estimated_tokens(prepared),
        recovered_estimated_tokens=_estimated_tokens(retry_prepared),
    )
    return update.update_ref if update is not None else None


def _estimated_tokens(prepared: PreparedFinalAnswerAttempt) -> int:
    if prepared.estimated_tokens is not None:
        return prepared.estimated_tokens
    return sum(len(message.content) for message in prepared.request.messages)


def _final_answer_repair_request(
    state: ControlledReActRunState,
    normalized: NormalizedFinalAnswerAttempt,
) -> ModelRequest:
    generated = normalized.generated
    request = generated.prepared.request
    previous_json, previous_parse_error = parse_model_content_json(
        generated.response.content
    )
    validation_error = {
        "error_code": normalized.status.value,
        "contract_name": FINAL_ANSWER_OUTPUT_CONTRACT,
        "field_paths": list(normalized.diagnostic.field_paths if normalized.diagnostic else ()),
        "violation_codes": list(
            normalized.diagnostic.violation_codes if normalized.diagnostic else ()
        ),
        "violation_count": normalized.diagnostic.violation_count if normalized.diagnostic else 0,
    }
    repair_payload: dict[str, Any] = {
        "question": state.question,
        "instruction": (
            "Repair the previous final answer output. Return only one JSON object "
            "matching the required output contract. Use only the accepted evidence and "
            "copy allowed citation refs exactly into citations. Keep message as natural "
            "user-visible prose with no citation refs, source labels, bracketed numeric "
            "references, knowledge:// URIs, or reference blocks."
        ),
        "required_output_contract": {
            "name": FINAL_ANSWER_OUTPUT_CONTRACT,
            "required_fields": ["message", "citations"],
            "field_types": {
                "message": (
                    "customer-visible prose only; no citation refs, source labels, "
                    "or reference blocks"
                ),
                "citations": "array of exact allowed citation refs",
            },
        },
        "accepted_evidence": [
            {
                "source": chunk.source,
                "citation": chunk.citation,
                "content": chunk.content,
            }
            for chunk in generated.prepared.evidence
        ],
        "allowed_citation_refs": list(_allowed_citation_refs(generated.prepared.evidence)),
        "validation_error": validation_error,
        "previous_response_json": previous_json,
        "previous_response_parse_error_code": previous_parse_error,
    }
    if state.conversation_context is not None and state.conversation_context.admitted:
        repair_payload["conversation_context"] = {
            "summary": state.conversation_context.summary,
            "usage": "follow_up_resolution_only_not_evidence",
        }
    return ModelRequest(
        provider=request.provider,
        model=request.model,
        messages=(
            ModelMessage(
                role=ModelRole.SYSTEM,
                content=(
                    "You are repairing a Proof Agent final answer JSON object. "
                    "Do not add facts beyond accepted evidence. Do not include markdown, "
                    "explanations, tool calls, or chain-of-thought."
                ),
            ),
            ModelMessage(
                role=ModelRole.USER,
                content=json.dumps(repair_payload, ensure_ascii=False, sort_keys=True),
            ),
        ),
        response_format="json",
        function_schema=request.function_schema,
        stream=request.stream,
        metadata={
            **dict(request.metadata),
            "role": ModelCallRole.FINAL_ANSWER.value,
            "repair_attempt": 1,
        },
        evidence_sources=request.evidence_sources,
    )


def _allowed_citation_refs(evidence: tuple[EvidenceChunk, ...]) -> tuple[str, ...]:
    refs: list[str] = []
    for chunk in evidence:
        for value in (chunk.citation, chunk.source):
            if isinstance(value, str) and value.strip() and value not in refs:
                refs.append(value)
    return tuple(refs)


def _stage_llm_interactions(
    normalized: NormalizedFinalAnswerAttempt,
) -> tuple[WorkflowStageLlmInteraction, ...]:
    return tuple(
        attempt.interaction
        for attempt in (
            *normalized.prior_generated_attempts,
            normalized.generated,
        )
    )


def final_answer_validation_failure_diagnostic(
    *,
    trace: TracePort,
    response: ModelResponse,
    validation_results: tuple[ValidationResult, ...],
) -> WorkflowStageFailureDiagnostic:
    failed = tuple(
        result for result in validation_results if result.status is ValidationStatus.FAILED
    )
    payload = _final_answer_validation_failure_payload(
        response=response,
        failed_validation_results=failed,
    )
    event = trace.emit(
        TraceEventType.FINAL_ANSWER_VALIDATION_FAILED,
        status="blocked",
        payload=payload,
    )
    return WorkflowStageFailureDiagnostic(
        stage_id="model_answer",
        stage_label="Model Answer",
        event_type=TraceEventType.FINAL_ANSWER_VALIDATION_FAILED.value,
        status=WorkflowStageStatus.BLOCKED,
        error_code=str(payload["error_code"]),
        role=ModelCallRole.FINAL_ANSWER.value,
        raw_content_length=len(response.content),
        related_event_id=getattr(event, "event_id", None),
        contract_name=FINAL_ANSWER_OUTPUT_CONTRACT,
        violation_codes=tuple(payload.get("violation_codes", ())),
        field_paths=tuple(payload.get("field_paths", ())),
        violation_count=int(payload.get("violation_count", 0)),
    )


def _final_answer_validation_failure_payload(
    *,
    response: ModelResponse,
    failed_validation_results: tuple[ValidationResult, ...],
) -> dict[str, Any]:
    return {
        "stage_id": "model_answer",
        "role": ModelCallRole.FINAL_ANSWER.value,
        "error_code": _primary_error_code(failed_validation_results),
        "validator_names": tuple(result.validator_name for result in failed_validation_results),
        "violation_codes": _metadata_sequence(failed_validation_results, "violation_codes"),
        "field_paths": _metadata_sequence(failed_validation_results, "field_paths"),
        "violation_count": _violation_count(failed_validation_results),
        "contract_name": FINAL_ANSWER_OUTPUT_CONTRACT,
        "raw_content_length": len(response.content),
    }


def _primary_error_code(failed_validation_results: tuple[ValidationResult, ...]) -> str:
    validator_names = {result.validator_name for result in failed_validation_results}
    if "schema" in validator_names:
        return "schema_failed"
    if "safety" in validator_names:
        return "safety_failed"
    if "citations" in validator_names:
        return "citation_binding_failed"
    if "final_answer_adequacy" in validator_names:
        return "final_answer_adequacy_failed"
    return "final_answer_validation_failed"


def _metadata_sequence(
    failed_validation_results: tuple[ValidationResult, ...],
    key: str,
) -> tuple[str, ...]:
    values: list[str] = []
    for result in failed_validation_results:
        metadata = result.metadata
        raw = metadata.get(key)
        if isinstance(raw, str):
            candidates: tuple[str, ...] = (raw,)
        elif isinstance(raw, list | tuple):
            candidates = tuple(item for item in raw if isinstance(item, str))
        else:
            candidates = ()
        for candidate in candidates:
            if candidate not in values:
                values.append(candidate)
    return tuple(values)


def _violation_count(failed_validation_results: tuple[ValidationResult, ...]) -> int:
    total = 0
    for result in failed_validation_results:
        metadata: Mapping[str, Any] = result.metadata
        count = metadata.get("violation_count")
        if isinstance(count, int):
            total += count
            continue
        violation_codes = metadata.get("violation_codes")
        if isinstance(violation_codes, list | tuple):
            total += len(violation_codes)
    return total


class _StageScopedTrace:
    def __init__(self, trace: TracePort, *, stage_id: str) -> None:
        self._trace = trace
        self._stage_id = stage_id

    def emit(
        self,
        event_type: str,
        *,
        status: Literal["ok", "blocked", "waiting", "error"] = "ok",
        payload: Mapping[str, Any] | None = None,
    ) -> object:
        stage_payload = dict(payload or {})
        stage_payload.setdefault("stage_id", self._stage_id)
        return self._trace.emit(event_type, status=status, payload=stage_payload)


def _model_call_policy_context(
    request: ModelRequest,
    *,
    estimated_tokens: int | None,
) -> Mapping[str, Any]:
    return {
        "provider": request.provider,
        "model": request.model,
        "role": ModelCallRole.FINAL_ANSWER.value,
        "estimated_tokens": estimated_tokens,
        "stream": request.stream,
        "cost_class": cost_class(request.provider),
        "message_count": len(request.messages),
        "response_format": request.response_format,
    }


def _model_usage_summary(
    *,
    request: ModelRequest,
    response: ModelResponse,
    estimated_tokens: int | None,
) -> dict[str, Any]:
    payload = model_response_payload(response)
    token_usage = payload.get("token_usage")
    return {
        "provider": response.provider_name,
        "model": response.model_name,
        "role": ModelCallRole.FINAL_ANSWER.value,
        "message_count": len(request.messages),
        "estimated_tokens": estimated_tokens,
        "stream": request.stream,
        "cost_class": cost_class(request.provider),
        "finish_reason": response.finish_reason,
        "content_length": len(response.content),
        "token_usage": token_usage,
    }


def _emit_model_request_trace(
    trace: TracePort,
    request: ModelRequest,
    *,
    estimated_tokens: int | None,
    stage_id: str,
) -> None:
    repair_attempt = _request_repair_attempt(request)
    payload: dict[str, Any] = {
        "provider": request.provider,
        "model": request.model,
        "role": ModelCallRole.FINAL_ANSWER.value,
        "response_format": request.response_format,
        "message_count": len(request.messages),
        "prompt_length": sum(len(message.content) for message in request.messages),
        "system_prompt_length": sum(
            len(message.content) for message in request.messages if message.role.value == "system"
        ),
        "estimated_tokens": estimated_tokens,
        "stream": request.stream,
        "cost_class": cost_class(request.provider),
        "stage_id": stage_id,
    }
    if repair_attempt is not None:
        payload["repair_attempt"] = repair_attempt
    if request.metadata.get("context_overflow_recovery"):
        payload["context_overflow_recovery"] = True
        payload["context_convergence_level"] = request.metadata.get("context_convergence_level")
    trace.emit(
        "model_request",
        status="ok",
        payload=payload,
    )


def _emit_model_response_trace(
    trace: TracePort,
    response: ModelResponse,
    *,
    repair_attempt: int | None = None,
    stage_id: str,
) -> None:
    payload = model_response_payload(response)
    event_payload = {
        "provider": response.provider_name,
        "model": response.model_name,
        "role": ModelCallRole.FINAL_ANSWER.value,
        "finish_reason": response.finish_reason,
        "content_length": len(response.content),
        "refusal_reason": response.refusal_reason,
        "token_usage": payload.get("token_usage"),
        "stage_id": stage_id,
    }
    if repair_attempt is not None:
        event_payload["repair_attempt"] = repair_attempt
    trace.emit(
        "model_response",
        status="ok",
        payload=event_payload,
    )


def _emit_context_budget_calibration_update(
    trace: TracePort,
    *,
    prepared: PreparedFinalAnswerAttempt,
    retry_prepared: PreparedFinalAnswerAttempt,
    update_ref: str | None,
) -> None:
    trace.emit(
        "context_budget_calibration_update",
        status="ok",
        payload={
            "provider": prepared.request.provider,
            "model": prepared.request.model,
            "role": ModelCallRole.FINAL_ANSWER.value,
            "convergence_level": "deep_compression",
            "failed_estimated_tokens": _estimated_tokens(prepared),
            "recovered_estimated_tokens": _estimated_tokens(retry_prepared),
            "calibration_update_ref": update_ref,
        },
    )


def _request_repair_attempt(request: ModelRequest) -> int | None:
    repair_attempt = request.metadata.get("repair_attempt")
    return repair_attempt if isinstance(repair_attempt, int) else None


def _emit_model_error_trace(
    trace: TracePort,
    *,
    provider: str,
    model: str,
    exc: BaseException,
    stage_id: str,
) -> None:
    trace.emit(
        "model_error",
        status="error",
        payload={
            "provider": provider,
            "model": model,
            "role": ModelCallRole.FINAL_ANSWER.value,
            "error_code": getattr(exc, "code", "PA_MODEL_002"),
            "error_class": exc.__class__.__name__,
            "retryable": bool(getattr(exc, "retryable", False)),
            "stage_id": stage_id,
        },
    )
