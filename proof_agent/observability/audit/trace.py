from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Any, Literal, Protocol

from proof_agent.observability.audit.redaction import redact_payload
from proof_agent.contracts import TraceEvent, TraceEventType


_HYBRID_RETRIEVAL_SAFE_FIELDS = frozenset(
    {
        "binding_id",
        "source_id",
        "source_publication_seq",
        "profile_revision_id",
        "generation_id",
        "manifest_sha256",
        "attestation_id",
        "searched_query_count",
        "fused_candidate_count",
        "reranked_candidate_count",
        "excluded_count",
        "embedding_queue_time_ms",
        "embedding_service_time_ms",
        "reranker_queue_time_ms",
        "reranker_service_time_ms",
        "degradation_mode",
        "authority_outcome",
        "authority_passed_count",
        "authority_rejected_count",
        "evidence_slots_complete",
        "satisfied_evidence_slot_count",
        "missing_evidence_slot_count",
        "citation_count",
    }
)


def safe_trace_payload(
    event_type: TraceEventType | str,
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Project sensitive event families onto their production-safe audit schema."""

    value = event_type.value if isinstance(event_type, TraceEventType) else event_type
    if value != TraceEventType.HYBRID_RETRIEVAL_SUMMARY.value:
        return dict(payload), ()
    projected = {
        str(key): item for key, item in payload.items() if str(key) in _HYBRID_RETRIEVAL_SAFE_FIELDS
    }
    removed = tuple(sorted(str(key) for key in payload if str(key) not in projected))
    return projected, removed


class TraceEmitter(Protocol):
    def emit(
        self,
        event_type: TraceEventType | str,
        *,
        status: Literal["ok", "blocked", "waiting", "error"],
        payload: Mapping[str, Any],
    ) -> object: ...


class TraceWriter:
    """Writes ordered, redacted audit events to a JSONL trace file."""

    def __init__(self, trace_path: Path, *, run_id: str, initial_sequence: int = 0) -> None:
        self.trace_path = trace_path
        self.run_id = run_id
        self._sequence = initial_sequence
        self._lock = Lock()

    def emit(
        self,
        event_type: TraceEventType | str,
        *,
        status: Literal["ok", "blocked", "waiting", "error"],
        payload: Mapping[str, Any],
        span_id: str | None = None,
        parent_span_id: str | None = None,
    ) -> TraceEvent:
        """Append a trace.v1 event after redacting sensitive payload fields."""

        with self._lock:
            self._sequence += 1
            event_type_value = (
                event_type.value if isinstance(event_type, TraceEventType) else event_type
            )
            projected_payload, omitted_fields = safe_trace_payload(event_type_value, payload)
            redacted_payload, redaction = redact_payload(projected_payload)
            if omitted_fields:
                redaction = {
                    "applied": True,
                    "fields": [*redaction["fields"], *omitted_fields],
                }
            event = TraceEvent(
                run_id=self.run_id,
                event_id=f"evt_{self._sequence:04d}",
                sequence=self._sequence,
                timestamp=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                event_type=TraceEventType(event_type_value),
                span_id=span_id or f"span_{event_type_value}",
                parent_span_id=parent_span_id,
                status=status,
                payload=redacted_payload,
                redaction=redaction,
            )
            self.trace_path.parent.mkdir(parents=True, exist_ok=True)
            # JSONL keeps the trace stream append-friendly and easy to inspect in CLI tools.
            with self.trace_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(_jsonable(event.model_dump(warnings=False)), sort_keys=True) + "\n"
                )
            return event


def _jsonable(value: Any) -> Any:
    """Convert frozen contract values into plain JSON-compatible containers."""

    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value
