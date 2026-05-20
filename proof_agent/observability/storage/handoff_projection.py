from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from proof_agent.contracts import HandoffProjection, HandoffReason


CUSTOMER_HANDOFF_EVENT_TYPE = "customer_handoff_created"
HandoffStatus = Literal["open", "reviewing", "closed"]


def extract_handoffs(events: Sequence[Mapping[str, Any]]) -> tuple[HandoffProjection, ...]:
    """Project internal customer handoff events from trace payloads."""

    projections: list[HandoffProjection] = []
    for event in events:
        if event.get("event_type") != CUSTOMER_HANDOFF_EVENT_TYPE:
            continue
        payload = event.get("payload") or {}
        if not isinstance(payload, Mapping):
            continue
        projections.append(
            HandoffProjection(
                handoff_id=str(payload.get("handoff_id") or ""),
                run_id=str(event.get("run_id") or ""),
                conversation_id=str(payload.get("conversation_id") or ""),
                turn_id=str(payload.get("turn_id") or ""),
                created_at=str(event.get("timestamp") or ""),
                reason=HandoffReason(str(payload.get("reason"))),
                question_summary=str(payload.get("question_summary") or ""),
                summary=str(payload.get("summary") or payload.get("question_summary") or ""),
                customer_ref=(
                    str(payload.get("customer_ref")) if payload.get("customer_ref") else None
                ),
                status=_handoff_status(payload.get("status")),
            )
        )
    return tuple(projections)


def _handoff_status(value: Any) -> HandoffStatus:
    if value == "reviewing":
        return "reviewing"
    if value == "closed":
        return "closed"
    return "open"
