"""Deterministic quotation binding, separate from model-assessed reasoning."""
from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import json
import re
from typing import Any

from proof_agent.contracts import EvidenceChunk, EvidenceStatus, ReceiptOutcome, ValidationResult, ValidationStatus
from proof_agent.control.knowledge.answer_requirements import answer_requirements


MAX_QUOTES = 16
MAX_QUOTE_CHARS = 6_000
MAX_OUTPUT_CHARS = 32_000
COVERAGE_STATUSES = ("answered", "needs_evidence", "needs_user_input")


def _space(text: str) -> str:
    return " ".join(text.split())


def quoted_answer_properties() -> dict[str, Any]:
    return {
        "quotes": {"type": "array", "minItems": 1, "maxItems": MAX_QUOTES, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["claim", "text", "citation"], "properties": {
                "claim": {"type": "string", "minLength": 1, "maxLength": 4_000},
                "text": {"type": "string", "minLength": 1, "maxLength": MAX_QUOTE_CHARS},
                "citation": {"type": "string", "minLength": 1},
            }}},
        "coverage": {"type": "array", "maxItems": 16, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["requirement_id", "status"], "properties": {
                "requirement_id": {"type": "string"},
                "status": {"type": "string", "enum": list(COVERAGE_STATUSES)},
            }}},
    }


def validate_quoted_answer(output: Mapping[str, Any], *, evidence: tuple[EvidenceChunk, ...],
                           question: str) -> ValidationResult:
    """A real quote is not proof that its associated analysis is correct."""
    errors: list[str] = []
    message = output.get("message")
    citations = output.get("citations")
    quotes = output.get("quotes")
    coverage = output.get("coverage")
    if (not isinstance(message, str) or not message.strip() or len(message) > 16_000
            or not isinstance(citations, (list, tuple))
            or any(not isinstance(c, str) for c in citations)):
        return _result(["invalid_quoted_answer"], 0)
    if not isinstance(quotes, (list, tuple)) or not 1 <= len(quotes) <= MAX_QUOTES:
        return _result(["invalid_quote_count"], 0)
    sources: dict[str, list[str]] = {}
    for chunk in evidence:
        if chunk.status is EvidenceStatus.ACCEPTED and chunk.citation:
            sources.setdefault(chunk.citation, []).append(_space(chunk.content))
    bound_citations = set()
    total_chars = len(message)
    for item in quotes:
        if (not isinstance(item, Mapping) or set(item) != {"claim", "text", "citation"}
                or any(not isinstance(item[k], str) or not item[k].strip() for k in item)):
            errors.append("invalid_quote")
            continue
        claim, text, citation = item["claim"], item["text"], item["citation"]
        total_chars += len(text) + len(claim)
        if len(text) > MAX_QUOTE_CHARS or len(claim) > 4_000:
            errors.append("quote_size_limit")
        if citation not in citations or citation not in sources:
            errors.append("unsupported_quote_citation")
        elif not any(_space(text) in source for source in sources[citation]):
            errors.append("quote_not_in_source")
        else:
            # Relaxing prose matching must not erase an existing deterministic
            # conflict between literal values of the same cited source subject.
            from proof_agent.control.validators.answer_facts import validate_answer_facts
            source_check = validate_answer_facts(message=text, citations=(citation,),
                evidence=evidence, outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS)
            if "conflicting_explicit_assertion" in source_check.metadata.get("violation_codes", ()):
                errors.append("conflicting_explicit_assertion")
        bound_citations.add(citation)
    if (not bound_citations.issubset(citations) or any(c not in sources for c in citations)
            or len(citations) != len(set(citations))):
        errors.append("citation_quote_mismatch")
    if total_chars > MAX_OUTPUT_CHARS:
        errors.append("quoted_answer_size_limit")
    expected = {r.requirement_id for r in answer_requirements(question)}
    if not isinstance(coverage, (list, tuple)) or len(coverage) != len(expected):
        errors.append("missing_requirement_coverage")
    else:
        ids = []
        for row in coverage:
            if (not isinstance(row, Mapping) or set(row) != {"requirement_id", "status"}
                    or not isinstance(row.get("requirement_id"), str)
                    or row.get("status") not in COVERAGE_STATUSES):
                errors.append("invalid_requirement_coverage")
                continue
            ids.append(row["requirement_id"])
        if set(ids) != expected or len(ids) != len(set(ids)):
            errors.append("invalid_requirement_coverage")
    return _result(errors, len(quotes))


def _result(errors: list[str], count: int) -> ValidationResult:
    return ValidationResult(validator_name="answer_facts",
        status=ValidationStatus.FAILED if errors else ValidationStatus.PASSED,
        reason="Quoted source binding checked; analysis requires separate review.",
        metadata={"violation_codes": tuple(dict.fromkeys(errors)), "verification_kind": "quote_binding_only",
                  "checked_statement_count": count, "unassessed_statement_count": 0})


def validate_source_bound_answer(*, message: str, citations: tuple[str, ...],
                                 evidence: tuple[EvidenceChunk, ...], outcome: ReceiptOutcome) -> ValidationResult:
    """The prior literal form must not become a no-quotes route for free analysis."""
    from proof_agent.control.validators.answer_facts import validate_answer_facts, _canonical, _cjk_spacing, _statements
    from proof_agent.control.knowledge.answer_evidence import answer_evidence_records
    from proof_agent.control.knowledge.business_assessment import verified_business_body
    from proof_agent.control.knowledge.source_tables import table_source_statements
    result = validate_answer_facts(message=message, citations=citations, evidence=evidence, outcome=outcome)
    if result.status is ValidationStatus.FAILED or outcome is not ReceiptOutcome.ANSWERED_WITH_CITATIONS:
        return result
    records = [r for r in answer_evidence_records(evidence)
               if r["citation"] in citations or r["source"] in citations]
    if any("structured_data" in r for r in records) and not result.metadata.get("unassessed_statement_count"):
        return result
    if verified_business_body(message, evidence) is not None:
        return result
    def literal_key(text: str) -> str:
        text = re.sub(r"^Based on the accepted evidence,\s*", "", text, flags=re.IGNORECASE)
        return _canonical(_cjk_spacing(text.rstrip("。.")))

    originals = {literal_key(s) for r in records for s in (
        *_statements(r["content"], source=True), *table_source_statements(r["content"]),
    )}
    if any(literal_key(s) not in originals for s in _statements(message)):
        return ValidationResult(validator_name="answer_facts", status=ValidationStatus.FAILED,
            reason="Nonliteral analysis requires bound original quotes and grounding review.",
            metadata={"violation_codes": ("analysis_quotes_required",), "verification_kind": "literal_source_binding"})
    return result


def render_quoted_answer(output: Mapping[str, Any]) -> str:
    """Render source text as literal code blocks, never executable Markdown/HTML."""
    message = str(output["message"])
    anchors: dict[int, list[int]] = {}
    for index, item in enumerate(output["quotes"], 1):
        position = message.find(item["claim"])
        if position >= 0:
            anchors.setdefault(position + len(item["claim"]), []).append(index)
    for position in sorted(anchors, reverse=True):
        marker = "〔原文 " + "、".join(str(i) for i in anchors[position]) + "〕"
        message = message[:position] + marker + message[position:]
    parts = [message.strip(), "\n**引用原文**"]
    for index, item in enumerate(output["quotes"], 1):
        text = item["text"]
        fence = "`" * max(3, 1 + max((len(s) for s in re.findall(r"`+", text)), default=0))
        # A semantic label need not repeat the body verbatim. Display it literally;
        # model review, not string matching, validates its relation to the body.
        claim = item["claim"]
        label_fence = "`" * max(3, 1 + max((len(s) for s in re.findall(r"`+", claim)), default=0))
        label = f"对应结论：\n\n{label_fence}text\n{claim}\n{label_fence}"
        parts.extend([f"\n原文 {index}：", label, f"{fence}text\n{text}\n{fence}"])
    return "\n\n".join(parts)


def answer_binding(message: str, evidence: tuple[EvidenceChunk, ...]) -> dict[str, str]:
    records = sorted({json.dumps((e.citation or "", e.content, e.status.value,
                      e.model_dump(mode="json").get("structured_data")), ensure_ascii=False, sort_keys=True)
                      for e in evidence if e.status is EvidenceStatus.ACCEPTED})
    return {"message_sha256": sha256(message.encode()).hexdigest(),
            "evidence_sha256": sha256(json.dumps(records, ensure_ascii=False, sort_keys=True).encode()).hexdigest()}
