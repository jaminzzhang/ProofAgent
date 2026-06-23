"""Shared Harness helpers for trace formatting, model request construction, and run finalization.

This module is the deep module behind the shared workflow template/runtime adapter
helpers. All functions are public; callers import what they need.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from proof_agent.contracts import (
    ContextAdmission,
    EvidenceChunk,
    ModelFunctionSchema,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelRole,
    ReceiptOutcome,
    RunPurpose,
    RunResult,
    ValidationResult,
    ValidationStatus,
)
from proof_agent.control.validators.citations import (
    validate_citation_refs_supported_by_evidence,
)
from proof_agent.control.validators.safety import validate_no_secret_strings
from proof_agent.control.validators.schema import validate_final_output_schema
from proof_agent.observability.audit.receipt import generate_receipt
from proof_agent.observability.audit.trace import TraceWriter
from proof_agent.observability.storage.compat import update_latest_symlink
from proof_agent.observability.storage.run_store import RunStore


_FINAL_ANSWER_FUNCTION_SCHEMA_NAME = "submit_final_answer"


def emit_policy_decision(trace: TraceWriter, decision: object) -> None:
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


def emit_model_error(
    trace: TraceWriter, provider: str, model: str, exc: BaseException
) -> None:
    """Record a normalized model error without provider payloads."""

    trace.emit(
        "model_error",
        status="error",
        payload={
            "provider": provider,
            "model": model,
            "error_code": getattr(exc, "code", "PA_MODEL_002"),
            "error_class": exc.__class__.__name__,
            "retryable": False,
            "message": str(exc).splitlines()[0],
        },
    )


def build_model_request(
    *,
    question: str,
    evidence: tuple[EvidenceChunk, ...],
    provider: str,
    model: str,
    conversation_context: ContextAdmission | None = None,
    workflow_stage_context: Mapping[str, Any] | None = None,
) -> ModelRequest:
    evidence_text = "\n\n".join(getattr(chunk, "content") for chunk in evidence)
    citation_instruction_text = _citation_instruction_text(evidence)
    context_text = ""
    if conversation_context is not None and conversation_context.admitted:
        context_text = (
            "Conversation context admitted for follow-up resolution only. "
            "Do not treat it as evidence:\n"
            f"{conversation_context.summary}\n\n"
        )
    workflow_stage_context_text = _workflow_stage_context_text(workflow_stage_context)
    messages = (
        ModelMessage(
            role=ModelRole.SYSTEM,
            content=(
                "Answer using only accepted evidence. Refuse when evidence is insufficient. "
                "Call submit_final_answer with the answer in message and exact allowed "
                "citation refs in citations."
            ),
        ),
        ModelMessage(
            role=ModelRole.USER,
            content=(
                f"{context_text}{workflow_stage_context_text}"
                f"Question: {question}\n\nEvidence:\n{evidence_text}"
                f"{citation_instruction_text}"
            ),
        ),
    )
    return ModelRequest(
        provider=provider,
        model=model,
        messages=messages,
        response_format="json",
        function_schema=_final_answer_function_schema(),
        metadata={
            "question": question,
            "conversation_context_admitted": bool(
                conversation_context and conversation_context.admitted
            ),
        },
        evidence_sources=tuple(getattr(chunk, "source") for chunk in evidence),
    )


def _citation_instruction_text(evidence: tuple[EvidenceChunk, ...]) -> str:
    refs = _allowed_citation_refs(evidence)
    if not refs:
        return ""
    bullet_list = "\n".join(f"- {ref}" for ref in refs)
    return (
        "\n\nAllowed citation refs:\n"
        f"{bullet_list}\n"
        "Copy at least one allowed citation ref exactly when making factual claims. "
        "Put citation refs in the structured citations field only."
    )


def _allowed_citation_refs(evidence: tuple[EvidenceChunk, ...]) -> tuple[str, ...]:
    refs: list[str] = []
    for chunk in evidence:
        for value in (chunk.citation, chunk.source):
            if isinstance(value, str) and value.strip() and value not in refs:
                refs.append(value)
    return tuple(refs)


def _workflow_stage_context_text(
    workflow_stage_context: Mapping[str, Any] | None,
) -> str:
    if not workflow_stage_context:
        return ""
    addendum = workflow_stage_context.get("business_context_addendum")
    if isinstance(addendum, Mapping):
        addendum_text = str(addendum.get("text", "") or "").strip()
    else:
        addendum_text = str(addendum or "").strip()
    structured_context = workflow_stage_context.get("structured_control_context")
    structured_text = ""
    if isinstance(structured_context, Mapping) and structured_context:
        structured_text = json.dumps(
            structured_context,
            ensure_ascii=True,
            sort_keys=True,
        )
    if not addendum_text and not structured_text:
        return ""

    sections = ["Workflow stage business context addendum:"]
    if addendum_text:
        sections.append(addendum_text)
    if structured_text:
        sections.append("Structured control context:")
        sections.append(structured_text)
    return "\n".join(sections) + "\n\n"


def validate_model_output(
    *,
    response: ModelResponse,
    outcome: ReceiptOutcome,
    evidence: tuple[EvidenceChunk, ...],
    observation_records: tuple[Mapping[str, Any], ...] = (),
) -> tuple[ValidationResult, ...]:
    output, parse_error = structured_final_answer_output(response.content, outcome=outcome)
    if parse_error is not None:
        return (
            ValidationResult(
                validator_name="schema",
                status=ValidationStatus.FAILED,
                reason="Final answer model output schema is invalid.",
                metadata={"parse_error_code": parse_error},
            ),
            validate_no_secret_strings(response.content),
            validate_citation_refs_supported_by_evidence(
                (),
                evidence,
                observation_records=observation_records,
                require_supported_citation=bool(evidence),
            ),
        )

    return (
        validate_final_output_schema(output),
        validate_no_secret_strings(str(output["message"])),
        validate_citation_refs_supported_by_evidence(
            tuple(output["citations"]),
            evidence,
            observation_records=observation_records,
            require_supported_citation=bool(evidence),
        ),
    )


def structured_final_answer_output(
    content: str,
    *,
    outcome: ReceiptOutcome,
) -> tuple[dict[str, Any], str | None]:
    raw, parse_error = _model_content_json(content)
    if parse_error is not None:
        return {}, parse_error
    if not isinstance(raw, Mapping):
        return {}, "model_output_json_not_object"
    message = raw.get("message")
    citations = raw.get("citations")
    if not isinstance(message, str):
        return {}, "model_output_missing_message"
    if not isinstance(citations, list | tuple) or not all(
        isinstance(item, str) for item in citations
    ):
        return {}, "model_output_invalid_citations"
    return {
        "outcome": outcome.value,
        "message": message,
        "citations": tuple(citations),
    }, None


def _model_content_json(content: str) -> tuple[Any | None, str | None]:
    stripped = content.strip()
    if not stripped:
        return None, "empty_model_output"
    try:
        return json.loads(stripped), None
    except json.JSONDecodeError:
        return None, "model_output_json_parse_failed"


def _final_answer_function_schema() -> ModelFunctionSchema:
    return ModelFunctionSchema(
        name=_FINAL_ANSWER_FUNCTION_SCHEMA_NAME,
        description=(
            "Submit the governed final answer. Put user-visible prose in message and "
            "put exact accepted evidence citation refs in citations."
        ),
        parameters_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["message", "citations"],
            "properties": {
                "message": {"type": "string"},
                "citations": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        },
        strict=True,
    )


def finalize_run(
    *,
    trace: TraceWriter,
    receipt_path: Path,
    trace_path: Path,
    agent_name: str,
    question: str,
    outcome: ReceiptOutcome,
    message: str,
    store: RunStore | None = None,
    run_purpose: RunPurpose = RunPurpose.PRODUCTION,
    agent_id: str | None = None,
    agent_version_id: str | None = None,
    draft_id: str | None = None,
    error_code: str | None = None,
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
            run_purpose=run_purpose,
            agent_id=agent_id,
            agent_version_id=agent_version_id,
            draft_id=draft_id,
            error_code=error_code,
        )
        history_dir = store.history_dir.parent
        update_latest_symlink(store.history_dir / trace.run_id, history_dir)
    return result


def cost_class(provider: str) -> str:
    if provider == "deterministic":
        return "local"
    if provider == "azure_openai":
        return "enterprise"
    return "remote"


def model_response_payload(response: ModelResponse) -> dict[str, object]:
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


def system_prompt_length(request: ModelRequest) -> int:
    return sum(len(message.content) for message in request.messages if message.role == ModelRole.SYSTEM)


def is_model_error(exc: BaseException) -> bool:
    """Return true when a composition error came from model provider resolution."""

    return str(getattr(exc, "code", "")).startswith("PA_MODEL")
