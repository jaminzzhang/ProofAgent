from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from proof_agent.bootstrap.composition import HarnessInvocation
from proof_agent.contracts import (
    AnswerEvidenceContext,
    ControlledReActRunState,
    EnforcementPoint,
    EvidenceChunk,
    ModelCallRole,
    ModelRequest,
    ModelResponse,
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


FINAL_ANSWER_OUTPUT_CONTRACT = "FinalAnswerOutput"


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
    diagnostic: WorkflowStageFailureDiagnostic | None = None
    message: str | None = None


class FinalAnswerAttemptRunner:
    def __init__(self, invocation: HarnessInvocation, *, trace: TracePort) -> None:
        self._invocation = invocation
        self._trace = trace

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
        repaired = self.repair(normalized)
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
        emit_policy_decision(
            _StageScopedTrace(self._trace, stage_id="model_answer"),
            policy_decision,
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
            stage_id="model_answer",
        )
        interaction = _llm_interaction_capture(
            stage_id="model_answer",
            stage_label="Model Answer",
            role=ModelCallRole.FINAL_ANSWER.value,
            request=prepared.request,
            response=response,
        )
        return GeneratedFinalAnswerAttempt(
            prepared=prepared,
            response=response,
            interaction=interaction,
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
            result
            for result in validation_results
            if result.status is ValidationStatus.FAILED
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
                diagnostic=diagnostic,
            )
        final_answer_output, _parse_error = structured_final_answer_output(
            generated.response.content,
            outcome=outcome,
        )
        return NormalizedFinalAnswerAttempt(
            generated=generated,
            validation_results=validation_results,
            message=str(final_answer_output.get("message", generated.response.content)),
        )

    def repair(
        self,
        normalized: NormalizedFinalAnswerAttempt,
    ) -> NormalizedFinalAnswerAttempt:
        return normalized

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
                stage_llm_interactions=(generated.interaction,),
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
            stage_llm_interactions=(generated.interaction,),
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
    trace.emit(
        "model_request",
        status="ok",
        payload={
            "provider": request.provider,
            "model": request.model,
            "role": ModelCallRole.FINAL_ANSWER.value,
            "response_format": request.response_format,
            "message_count": len(request.messages),
            "prompt_length": sum(len(message.content) for message in request.messages),
            "system_prompt_length": sum(
                len(message.content)
                for message in request.messages
                if message.role.value == "system"
            ),
            "estimated_tokens": estimated_tokens,
            "stream": request.stream,
            "cost_class": cost_class(request.provider),
            "stage_id": stage_id,
        },
    )


def _emit_model_response_trace(
    trace: TracePort,
    response: ModelResponse,
    *,
    stage_id: str,
) -> None:
    payload = model_response_payload(response)
    trace.emit(
        "model_response",
        status="ok",
        payload={
            "provider": response.provider_name,
            "model": response.model_name,
            "role": ModelCallRole.FINAL_ANSWER.value,
            "finish_reason": response.finish_reason,
            "content_length": len(response.content),
            "refusal_reason": response.refusal_reason,
            "token_usage": payload.get("token_usage"),
            "stage_id": stage_id,
        },
    )


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


def _llm_interaction_capture(
    *,
    stage_id: str,
    stage_label: str,
    role: str,
    request: ModelRequest,
    response: ModelResponse,
) -> WorkflowStageLlmInteraction:
    response_json, parse_error = (
        _model_content_json(response.content) if request.response_format == "json" else (None, None)
    )
    return WorkflowStageLlmInteraction(
        stage_id=stage_id,
        stage_label=stage_label,
        role=role,
        provider=response.provider_name,
        model=response.model_name,
        request_json=_model_request_json(request),
        response_json=response_json,
        response_content_length=len(response.content),
        response_json_parse_error_code=parse_error,
    )


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
