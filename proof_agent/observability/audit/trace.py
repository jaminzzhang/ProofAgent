from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Any, Literal

from proof_agent.observability.audit.redaction import redact_payload
from proof_agent.contracts import TraceEvent, TraceEventType


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
            redacted_payload, redaction = redact_payload(payload)
            event_type_value = event_type.value if isinstance(event_type, TraceEventType) else event_type
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
                    json.dumps(_jsonable(event.model_dump(warnings=False)), sort_keys=True)
                    + "\n"
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
