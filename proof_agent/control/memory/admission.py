from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from proof_agent.contracts import (
    MemoryAdmission,
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    MemorySensitivity,
    MemoryStatus,
)


def admit_memory(
    records: tuple[MemoryRecord, ...],
    *,
    query: MemoryQuery,
) -> MemoryAdmission:
    """Admit same-case memory through deterministic Control Plane rules."""

    included: list[MemoryRecord] = []
    rejected: dict[str, str] = {}
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    for record in records:
        reason = _rejection_reason(record, query=query, now=now)
        if reason is None:
            included.append(record)
        else:
            rejected[record.memory_id] = reason

    facts = _merge_facts(included)
    summary = " | ".join(record.summary for record in included)
    return MemoryAdmission(
        admitted=bool(included),
        included_memory_ids=tuple(record.memory_id for record in included),
        summary=summary,
        facts=facts,
        rejected_memory_ids=tuple(rejected),
        rejection_reasons=rejected,
    )


def _rejection_reason(record: MemoryRecord, *, query: MemoryQuery, now: str) -> str | None:
    if record.scope != query.scope:
        return "scope_mismatch"
    if query.scope == MemoryScope.CASE:
        if record.case_id != query.case_id:
            return "case_id_mismatch"
    elif query.scope == MemoryScope.USER:
        if not query.consent_granted:
            return "consent_required"
        if record.subject_ref != query.subject_ref:
            return "subject_ref_mismatch"
    else:
        return "scope_mismatch"
    if record.agent_id != query.agent_id:
        return "agent_id_mismatch"
    if record.status != MemoryStatus.ACTIVE:
        return "inactive"
    if record.expires_at <= now:
        return "expired"
    if record.sensitivity == MemorySensitivity.RESTRICTED and not query.allow_restricted:
        return "restricted"
    return None


def _merge_facts(records: list[MemoryRecord]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for record in records:
        for key, value in record.facts.items():
            if key not in merged:
                merged[key] = value
                continue
            if isinstance(merged[key], list):
                values = merged[key]
            else:
                values = [merged[key]]
            if isinstance(value, list | tuple):
                for item in value:
                    if item not in values:
                        values.append(item)
            elif value not in values:
                values.append(value)
            merged[key] = values
    return merged
