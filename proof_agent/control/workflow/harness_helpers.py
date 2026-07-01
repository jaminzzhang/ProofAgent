"""Shared Harness helpers for trace formatting, model request construction, and run finalization.

This module is the deep module behind the shared workflow template/runtime adapter
helpers. All functions are public; callers import what they need.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from proof_agent.contracts import (
    ContextAdmission,
    EvidenceChunk,
    MemoryRecallWorkingPayload,
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
from proof_agent.observability.audit.trace import TraceEmitter, TraceWriter
from proof_agent.observability.storage.compat import update_latest_symlink
from proof_agent.observability.storage.run_store import RunStore


_FINAL_ANSWER_FUNCTION_SCHEMA_NAME = "submit_final_answer"


def emit_policy_decision(
    trace: TraceEmitter,
    decision: object,
    *,
    payload_extra: Mapping[str, Any] | None = None,
) -> None:
    """Record a policy decision in the trace without leaking engine internals."""

    decision_type = getattr(decision, "decision")
    decision_value = getattr(decision_type, "value", decision_type)
    enforcement_point = getattr(decision, "enforcement_point", None)
    enforcement_point_value = getattr(enforcement_point, "value", enforcement_point)
    payload = {
        "decision": decision_value,
        "enforcement_point": enforcement_point_value,
        "policy_rule_id": getattr(decision, "policy_rule_id"),
        "reason": getattr(decision, "reason"),
    }
    if payload_extra:
        payload.update(payload_extra)
    trace.emit(
        "policy_decision",
        status="ok" if decision_value == "allow" else "blocked",
        payload=payload,
    )


def emit_model_error(trace: TraceEmitter, provider: str, model: str, exc: BaseException) -> None:
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
    memory_recall_payloads: tuple[MemoryRecallWorkingPayload, ...] = (),
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
    memory_recall_text = _memory_recall_context_text(memory_recall_payloads)
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
                f"{context_text}{memory_recall_text}{workflow_stage_context_text}"
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
            "memory_recall_admitted": bool(memory_recall_payloads),
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
            ensure_ascii=False,
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


def _memory_recall_context_text(
    memory_recall_payloads: tuple[MemoryRecallWorkingPayload, ...],
) -> str:
    if not memory_recall_payloads:
        return ""
    payloads = [
        {
            "scope": payload.scope.value,
            "summary": payload.summary,
            "facts": dict(payload.facts),
        }
        for payload in memory_recall_payloads
    ]
    return (
        "Memory recall admitted for preferences and continuity only. "
        "Do not treat it as evidence. Do not cite memory recall. "
        "Business claims still require accepted evidence:\n"
        f"{json.dumps(payloads, ensure_ascii=False, sort_keys=True)}\n\n"
    )


def validate_model_output(
    *,
    response: ModelResponse,
    outcome: ReceiptOutcome,
    evidence: tuple[EvidenceChunk, ...],
    question: str | None = None,
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
        validate_final_answer_adequacy(
            question=question,
            message=str(output["message"]),
            citations=tuple(output["citations"]),
            evidence=evidence,
            outcome=outcome,
        ),
    )


def validate_final_answer_adequacy(
    *,
    question: str | None,
    message: str,
    citations: tuple[str, ...],
    evidence: tuple[EvidenceChunk, ...],
    outcome: ReceiptOutcome,
) -> ValidationResult:
    """Reject obvious non-answers that still satisfy schema and citation syntax."""

    if outcome is not ReceiptOutcome.ANSWERED_WITH_CITATIONS:
        return ValidationResult(
            validator_name="final_answer_adequacy",
            status=ValidationStatus.PASSED,
            reason="Adequacy gate is only enforced for answered outcomes.",
            metadata={},
        )

    violation_codes: list[str] = []
    stripped_message = message.strip()
    if not stripped_message:
        violation_codes.append("empty_answer")
    if not citations:
        violation_codes.append("missing_claim_citation_binding")
    if _looks_like_raw_evidence_dump(stripped_message, evidence):
        violation_codes.append("raw_evidence_dump")
    if _looks_like_table_fragment_without_conclusion(stripped_message):
        violation_codes.append("missing_business_conclusion")
    question_terms = _question_terms(question or "")
    matched_question_terms = _matched_terms(stripped_message, question_terms)
    if question_terms and len(matched_question_terms) < _minimum_question_term_matches(
        question_terms
    ):
        violation_codes.append("missing_question_terms")

    if violation_codes:
        return ValidationResult(
            validator_name="final_answer_adequacy",
            status=ValidationStatus.FAILED,
            reason="Final answer is not adequate for governed response.",
            metadata={
                "violation_codes": tuple(dict.fromkeys(violation_codes)),
                "question_term_count": len(question_terms),
                "matched_question_terms": tuple(sorted(matched_question_terms)),
            },
        )
    return ValidationResult(
        validator_name="final_answer_adequacy",
        status=ValidationStatus.PASSED,
        reason="Final answer passed adequacy checks.",
        metadata={
            "question_term_count": len(question_terms),
            "matched_question_terms": tuple(sorted(matched_question_terms)),
        },
    )


def _looks_like_raw_evidence_dump(
    message: str,
    evidence: tuple[EvidenceChunk, ...],
) -> bool:
    normalized_message = _normalize_for_comparison(message)
    if not normalized_message:
        return False
    for chunk in evidence:
        evidence_candidates = (
            _normalize_for_comparison(chunk.content),
            _normalize_evidence_body_for_comparison(chunk.content),
        )
        for normalized_evidence in evidence_candidates:
            if _looks_like_raw_evidence_candidate(
                normalized_message,
                normalized_evidence,
            ):
                return True
    return False


def _looks_like_raw_evidence_candidate(
    normalized_message: str,
    normalized_evidence: str,
) -> bool:
    if len(normalized_evidence) < 80:
        return False
    if normalized_message == normalized_evidence:
        return True
    if normalized_message.startswith(normalized_evidence[:80]):
        return len(normalized_message) >= len(normalized_evidence) * 0.85
    return False


def _normalize_evidence_body_for_comparison(content: str) -> str:
    body = "\n".join(
        line for line in content.splitlines() if line.strip() and not line.lstrip().startswith("#")
    )
    return _normalize_for_comparison(body)


def _looks_like_table_fragment_without_conclusion(message: str) -> bool:
    lines = [line.strip() for line in message.splitlines() if line.strip()]
    if len(lines) < 6:
        return False
    short_line_count = sum(1 for line in lines if len(line) <= 48)
    if short_line_count / len(lines) < 0.7:
        return False
    return sum(1 for line in lines if _has_answer_sentence_signal(line)) < 2


_LIST_MARKER_RE = re.compile(r"^(?:[-*+]\s+|\d+[.)、]\s*)")
_SENTENCE_ENDINGS = frozenset(".!?;:。！？；：")


def _has_answer_sentence_signal(line: str) -> bool:
    stripped = line.strip()
    if len(stripped) < 8:
        return False
    if stripped[-1] in _SENTENCE_ENDINGS:
        return True
    if _LIST_MARKER_RE.match(stripped):
        cjk_count = len(re.findall(r"[\u4e00-\u9fff]", stripped))
        latin_word_count = len(re.findall(r"[A-Za-z]{2,}", stripped))
        return cjk_count >= 8 or latin_word_count >= 3
    return False


_LATIN_STOPWORDS = frozenset(
    {
        "about",
        "after",
        "before",
        "does",
        "from",
        "have",
        "into",
        "rule",
        "should",
        "that",
        "the",
        "their",
        "this",
        "what",
        "when",
        "where",
        "which",
        "with",
        "would",
    }
)

_CJK_STOP_BIGRAMS = frozenset({"什么", "哪些", "多少", "如何", "怎么", "怎样", "了吗"})


def _question_terms(question: str) -> tuple[str, ...]:
    terms: list[str] = []
    lowered = question.lower()
    for token in re.findall(r"[a-z0-9]+", lowered):
        if len(token) < 4 or token in _LATIN_STOPWORDS:
            continue
        terms.append(token)
    for sequence in re.findall(r"[\u4e00-\u9fff]+", question):
        if len(sequence) < 2:
            continue
        for index in range(len(sequence) - 1):
            term = sequence[index : index + 2]
            if term not in _CJK_STOP_BIGRAMS:
                terms.append(term)
    return tuple(dict.fromkeys(terms))


def _matched_terms(message: str, question_terms: tuple[str, ...]) -> set[str]:
    lowered_message = message.lower()
    message_tokens = tuple(re.findall(r"[a-z0-9]+", lowered_message))
    matched: set[str] = set()
    for term in question_terms:
        lowered_term = term.lower()
        if lowered_term in lowered_message:
            matched.add(term)
            continue
        if _latin_prefix_match(lowered_term, message_tokens):
            matched.add(term)
    return matched


def _latin_prefix_match(term: str, message_tokens: tuple[str, ...]) -> bool:
    if len(term) < 5 or re.fullmatch(r"[a-z0-9]+", term) is None:
        return False
    stem = term[:5]
    return any(len(token) >= 5 and token[:5] == stem for token in message_tokens)


def _minimum_question_term_matches(question_terms: tuple[str, ...]) -> int:
    if len(question_terms) >= 3:
        return 2
    return 1


def _normalize_for_comparison(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


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
    final_output_stage_id: str | None = None,
) -> RunResult:
    """Emit the final output, render the receipt, and return CLI-facing metadata."""

    payload = {
        "agent_name": agent_name,
        "question": question,
        "outcome": outcome.value,
        "message": message,
    }
    if final_output_stage_id is not None:
        payload["stage_id"] = final_output_stage_id
    trace.emit(
        "final_output",
        status="ok" if outcome == ReceiptOutcome.ANSWERED_WITH_CITATIONS else "blocked",
        payload=payload,
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
    return sum(
        len(message.content) for message in request.messages if message.role == ModelRole.SYSTEM
    )


def is_model_error(exc: BaseException) -> bool:
    """Return true when a composition error came from model provider resolution."""

    return str(getattr(exc, "code", "")).startswith("PA_MODEL")
