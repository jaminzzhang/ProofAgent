from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from proof_agent.contracts import EvaluationSubject, ReceiptOutcome
from proof_agent.evaluation.errors import EvaluationInputError


@dataclass(frozen=True)
class EvaluationTraceEvent:
    event_type: str
    status: str | None
    payload: Mapping[str, Any]
    redaction: Mapping[str, Any]
    event_id: str | None = None
    run_id: str | None = None
    sequence: int | None = None


@dataclass(frozen=True)
class EvaluationArtifacts:
    trace_events: tuple[EvaluationTraceEvent, ...]
    receipt_markdown: str
    response_text: str
    run_meta: Mapping[str, Any] | None
    actual_outcome: ReceiptOutcome | None
    receipt_outcome: ReceiptOutcome | None
    trace_final_outcome: ReceiptOutcome | None
    trace_sha256: str
    receipt_sha256: str
    response_sha256: str
    run_meta_sha256: str | None


def read_evaluation_artifacts(subject: EvaluationSubject) -> EvaluationArtifacts:
    """Read completed-run artifacts referenced by an Evaluation Subject."""

    # Parse and verify the same byte snapshots; never reopen files for hashing.
    trace_bytes = subject.trace.ref.read_bytes()
    receipt_bytes = subject.receipt.ref.read_bytes()
    response_bytes = _read_response_projection(subject)
    run_meta_bytes = subject.run_meta.ref.read_bytes() if subject.run_meta is not None else None
    trace_events = _parse_trace(trace_bytes.decode("utf-8"), subject.trace.ref)
    receipt_markdown = receipt_bytes.decode("utf-8")
    response_text = response_bytes.decode("utf-8")
    run_meta = (
        _parse_run_meta(run_meta_bytes.decode("utf-8")) if run_meta_bytes is not None else None
    )
    final_event = next(
        (event for event in reversed(trace_events) if event.event_type == "final_output"), None
    )
    return EvaluationArtifacts(
        trace_events=trace_events,
        receipt_markdown=receipt_markdown,
        response_text=response_text,
        run_meta=run_meta,
        actual_outcome=_actual_outcome(trace_events, run_meta),
        receipt_outcome=_receipt_outcome(receipt_markdown),
        trace_final_outcome=(
            _receipt_outcome_value(final_event.payload.get("outcome")) if final_event else None
        ),
        trace_sha256=hashlib.sha256(trace_bytes).hexdigest(),
        receipt_sha256=hashlib.sha256(receipt_bytes).hexdigest(),
        response_sha256=hashlib.sha256(response_bytes).hexdigest(),
        run_meta_sha256=hashlib.sha256(run_meta_bytes).hexdigest()
        if run_meta_bytes is not None
        else None,
    )


def _parse_trace(text: str, path: Path) -> tuple[EvaluationTraceEvent, ...]:
    events: list[EvaluationTraceEvent] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvaluationInputError(
                f"Invalid trace JSONL at {path}:{line_number}: {exc.msg}"
            ) from exc
        if not isinstance(raw, dict):
            raise EvaluationInputError(f"Trace event at {path}:{line_number} must be a mapping.")
        event_type = raw.get("event_type")
        if not isinstance(event_type, str):
            raise EvaluationInputError(f"Trace event at {path}:{line_number} missing event_type.")
        events.append(
            EvaluationTraceEvent(
                event_type=event_type,
                status=_optional_str(raw.get("status")),
                payload=_mapping(raw.get("payload")),
                redaction=_mapping(raw.get("redaction")),
                event_id=_optional_str(raw.get("event_id")),
                run_id=_optional_str(raw.get("run_id")),
                sequence=_optional_int(raw.get("sequence")),
            )
        )
    return tuple(events)


def _parse_run_meta(text: str) -> Mapping[str, Any]:
    raw = json.loads(text)
    if not isinstance(raw, dict):
        raise EvaluationInputError("run_meta artifact must be a JSON object.")
    return raw


def _read_response_projection(subject: EvaluationSubject) -> bytes:
    projection = subject.response_projection
    if projection.ref is not None:
        return projection.ref.read_bytes()
    if projection.text is not None:
        return projection.text.encode("utf-8")
    raise EvaluationInputError("Evaluation response projection must provide ref or text.")


def _actual_outcome(
    trace_events: tuple[EvaluationTraceEvent, ...],
    run_meta: Mapping[str, Any] | None,
) -> ReceiptOutcome | None:
    for event in reversed(trace_events):
        if event.event_type != "final_output":
            continue
        outcome = _receipt_outcome_value(event.payload.get("outcome"))
        if outcome is not None:
            return outcome
    if run_meta is not None:
        return _receipt_outcome_value(run_meta.get("outcome"))
    return None


def _receipt_outcome(markdown: str) -> ReceiptOutcome | None:
    lines = markdown.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != "## Final Outcome":
            continue
        for candidate in lines[index + 1 :]:
            stripped = candidate.strip()
            if stripped:
                return _receipt_outcome_value(stripped)
    return None


def _receipt_outcome_value(value: Any) -> ReceiptOutcome | None:
    if not isinstance(value, str):
        return None
    try:
        return ReceiptOutcome(value)
    except ValueError:
        return None


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) else None
