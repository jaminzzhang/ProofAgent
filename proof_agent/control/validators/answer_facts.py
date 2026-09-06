"""Bounded source-near consistency checks; not a general entailment judge."""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal

from proof_agent.contracts import (
    EvidenceChunk,
    EvidenceStatus,
    ReceiptOutcome,
    ValidationResult,
    ValidationStatus,
)
from proof_agent.control.knowledge.answer_evidence import answer_evidence_records


MAX_ANSWER_CHARS = 16_000
MAX_EVIDENCE_CHARS = 1_000_000
MAX_STATEMENTS = 2_048
_SPLIT = re.compile(r"[。；;\n]+|\.(?=\s|$)")
_ASSERTION = re.compile(r"\b(?:is|are)\b|[:：=]", re.IGNORECASE)
_CHINESE_ASSERTION = re.compile(r"(?<=.)[为是]")
_NUMBER = re.compile(r"(?<![\w.+-])[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\w.])")


def validate_answer_facts(
    *,
    message: str,
    citations: tuple[str, ...],
    evidence: tuple[EvidenceChunk, ...],
    outcome: ReceiptOutcome,
) -> ValidationResult:
    if outcome is not ReceiptOutcome.ANSWERED_WITH_CITATIONS:
        return _result((), 0, 0, "not_applicable")
    if (
        len(message) > MAX_ANSWER_CHARS
        or len(evidence) > 128
        or sum(len(e.content) for e in evidence) > MAX_EVIDENCE_CHARS
    ):
        return _result(("fact_check_input_limit",), 0, 0, "not_evaluated")

    # Revalidate typed integrity at this public boundary, including unchecked model_copy.
    accepted = tuple(e for e in evidence if e.status is EvidenceStatus.ACCEPTED)
    records = answer_evidence_records(accepted)
    cited = [r for r in records if r["citation"] in citations or r["source"] in citations]
    source_statements: list[str] = []
    literal_values: dict[str, set[str]] = {}
    typed_subjects: set[str] = set()
    typed_count = sum("structured_data" in r for r in cited)
    for record in cited:
        typed = record.get("structured_data")
        if typed is None:
            source_statements.extend(_statements(record["content"]))
            continue
        for field in typed["fields"]:
            value = field["value"]
            rendered = (
                "null"
                if value is None
                else str(value).lower()
                if isinstance(value, bool)
                else str(value)
            )
            unit = field.get("unit") or ""
            field_statement = f"{field['field']} is {rendered} {unit}"
            source_statements.append(f"{typed['record_id']} {field_statement}")
            if typed_count == 1:
                source_statements.append(field_statement)
            subjects = [f"{typed['record_id']} {field['field']}"]
            if typed_count == 1:
                subjects.append(field["field"])
            typed_subjects.update(subjects)
            if field["value_type"] not in {"decimal", "integer"}:
                for subject in subjects:
                    literal_values.setdefault(subject, set()).add(f"{rendered} {unit}".strip())
    answer_statements = _statements(message)
    if len(source_statements) + len(answer_statements) > MAX_STATEMENTS:
        return _result(("fact_check_input_limit",), 0, 0, "not_evaluated")

    known_subjects = tuple(sorted(typed_subjects, key=len, reverse=True))
    supported = {_fact(s, known_subjects) for s in source_statements}
    values_by_subject: dict[str, set[str]] = {}
    for subject, value in supported:
        if subject:
            values_by_subject.setdefault(subject, set()).add(value)
    violations: list[str] = []
    checked = unassessed = 0
    for statement in answer_statements:
        fact = _fact(statement, known_subjects)
        numeric = bool(re.search(r"\d", statement))
        if not numeric and not fact[0]:
            unassessed += 1
            continue
        checked += 1
        subject, raw_value = _parts(statement, known_subjects)
        literal_match = subject not in literal_values or raw_value in literal_values[subject]
        if fact not in supported or not literal_match:
            violations.append(
                "unsupported_numeric_fact" if numeric else "unsupported_explicit_assertion"
            )
        elif fact[0] and (
            len(values_by_subject.get(fact[0], ())) > 1 or len(literal_values.get(subject, ())) > 1
        ):
            violations.append("conflicting_explicit_assertion")
    return _result(
        tuple(dict.fromkeys(violations)), checked, unassessed, "bounded_consistency_only"
    )


def _statements(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFC", text)
    # Ordered-list indices are presentation, not quantities. Keep other digits.
    normalized = re.sub(r"(?m)^[ \t]*\d+[.)][ \t]+", "", normalized)
    return [s.strip() for s in _SPLIT.split(normalized) if s.strip()]


def _fact(statement: str, known_subjects: tuple[str, ...] = ()) -> tuple[str, str]:
    subject, value = _parts(statement, known_subjects)
    return subject, _canonical(value) if subject else value


def _parts(statement: str, known_subjects: tuple[str, ...] = ()) -> tuple[str, str]:
    statement = re.sub(r"^Based on the accepted evidence,\s*", "", statement, flags=re.IGNORECASE)
    # Typed field/record identities may themselves contain is/are, colons or Chinese
    # copulas. Match the known exact subject before interpreting language syntax.
    for subject in known_subjects:
        if statement.startswith(subject):
            suffix = statement[len(subject) :]
            assignment = re.fullmatch(
                r"(?:\s+(?:is|are)\s+|\s*[:：=为是]\s*)(.+)", suffix, re.IGNORECASE
            )
            if assignment:
                return subject, assignment.group(1).strip()
    assertion = next(
        (m for m in _ASSERTION.finditer(statement) if m.start() > 0), None
    ) or _CHINESE_ASSERTION.search(statement)
    if assertion:
        return statement[: assertion.start()].strip(), statement[assertion.end() :].strip()
    return "", statement.strip()


def _canonical(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\b(?:CNY|RMB|yuan)\b", " yuan ", text)

    def decimal_text(match: re.Match[str]) -> str:
        digits = match.group().lstrip("+-")
        if len(digits) > 1 and digits[0] == "0" and digits[1].isdigit():
            return match.group()  # Ambiguous zero-padded codes are not quantities.
        # No float conversion, arithmetic or Decimal.normalize (which uses precision).
        value = format(Decimal(match.group().replace(",", "")), "f")
        if "." in value:
            value = value.rstrip("0").rstrip(".")
        return "0" if Decimal(value) == 0 else value

    text = _NUMBER.sub(decimal_text, text)
    return " ".join(text.split())


def _result(
    codes: tuple[str, ...], checked: int, unassessed: int, coverage: str
) -> ValidationResult:
    return ValidationResult(
        validator_name="answer_facts",
        status=ValidationStatus.FAILED if codes else ValidationStatus.PASSED,
        reason="Answer failed bounded fact consistency checks."
        if codes
        else "Answer passed applicable bounded fact consistency checks; general entailment is not evaluated.",
        metadata={
            "violation_codes": codes,
            "violation_count": len(codes),
            "field_paths": ("message",) if codes else (),
            "checked_statement_count": checked,
            "unassessed_statement_count": unassessed,
            "coverage": coverage,
        },
    )
