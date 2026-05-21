from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from proof_agent.contracts import (
    CustomerSafeResponse,
    MemoryCandidate,
    MemoryScope,
    MemorySensitivity,
)


def candidate_from_customer_turn(
    *,
    case_id: str,
    agent_id: str,
    question: str,
    safe_response: CustomerSafeResponse,
    source_run_id: str,
    source_turn_id: str,
    retention_days: int = 30,
) -> MemoryCandidate | None:
    """Build a Case Memory candidate from customer-safe governed run facts."""

    if not source_run_id:
        return None
    facts = _extract_facts(question, safe_response)
    summary = _summary_from_facts(facts)
    if not summary:
        return None
    return MemoryCandidate(
        scope=MemoryScope.CASE,
        case_id=case_id,
        agent_id=agent_id,
        summary=summary,
        facts=facts,
        source_run_id=source_run_id,
        source_turn_id=source_turn_id,
        expires_at=_expires_at(retention_days),
        sensitivity=MemorySensitivity.INTERNAL,
    )


def _extract_facts(question: str, safe_response: CustomerSafeResponse) -> dict[str, Any]:
    normalized = question.lower()
    facts: dict[str, Any] = {}
    policy_ids = _unique(re.findall(r"\bPOL-\d+\b", question, flags=re.IGNORECASE))
    claim_ids = _unique(re.findall(r"\bCLM-\d+\b", question, flags=re.IGNORECASE))
    if policy_ids:
        facts["policy_ids"] = policy_ids
    if claim_ids:
        facts["claim_ids"] = claim_ids

    topics: list[str] = []
    if "inpatient" in normalized:
        topics.append("inpatient")
    if "claim" in normalized:
        topics.append("claim")
    if "reimbursement" in normalized:
        topics.append("reimbursement")
    if "document" in normalized:
        topics.append("documents")
    if "report" in normalized:
        topics.append("report")
    if topics:
        facts["focus_topics"] = topics

    if "table" in normalized:
        facts["requested_view"] = "summary_table"
    elif "trend" in normalized:
        facts["requested_view"] = "trend"

    if "please provide" in safe_response.message.lower():
        facts["last_state"] = "waiting_for_customer_detail"
    else:
        facts["last_state"] = "answered_or_acknowledged"
    return facts


def _summary_from_facts(facts: dict[str, Any]) -> str:
    topics = facts.get("focus_topics")
    if isinstance(topics, list) and topics:
        return f"Case focus: {' '.join(str(topic) for topic in topics)}."
    policy_ids = facts.get("policy_ids")
    if isinstance(policy_ids, list) and policy_ids:
        return f"Known policy id: {policy_ids[0]}."
    claim_ids = facts.get("claim_ids")
    if isinstance(claim_ids, list) and claim_ids:
        return f"Known claim id: {claim_ids[0]}."
    return ""


def _unique(values: list[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        normalized = value.upper()
        if normalized not in seen:
            seen.append(normalized)
    return seen


def _expires_at(retention_days: int) -> str:
    return (datetime.now(UTC) + timedelta(days=retention_days)).isoformat().replace("+00:00", "Z")
