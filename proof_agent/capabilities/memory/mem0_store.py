from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import os
from typing import Any, Protocol, cast

from proof_agent.contracts import (
    MemoryCandidate,
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    MemorySensitivity,
    MemoryStatus,
)
from proof_agent.errors import ProofAgentError


class Mem0Client(Protocol):
    """Small subset of the Mem0 client API used by Proof Agent."""

    def add(self, messages: object, **kwargs: object) -> object: ...

    def search(self, query: str, **kwargs: object) -> object: ...

    def delete_all(self, **kwargs: object) -> object: ...


class Mem0MemoryStore:
    """Memory Provider Adapter backed by Mem0."""

    def __init__(self, *, client: Mem0Client | None = None) -> None:
        self._client = client or _create_default_client()

    def append(self, candidate: MemoryCandidate) -> MemoryRecord:
        metadata = _metadata_from_candidate(candidate)
        kwargs = _entity_kwargs_from_candidate(candidate)
        kwargs.update(
            {
                "metadata": metadata,
                "infer": False,
                "expiration_date": _expiration_date(candidate.expires_at),
            }
        )
        response = self._client.add([{"role": "assistant", "content": candidate.summary}], **kwargs)
        memory_id = _memory_id_from_response(response)
        return MemoryRecord(
            memory_id=memory_id,
            scope=candidate.scope,
            case_id=candidate.case_id,
            subject_ref=candidate.subject_ref,
            agent_id=candidate.agent_id,
            summary=candidate.summary,
            facts=candidate.facts,
            source_run_id=candidate.source_run_id,
            source_turn_id=candidate.source_turn_id,
            created_at=_now(),
            expires_at=candidate.expires_at,
            sensitivity=candidate.sensitivity,
            status=MemoryStatus.ACTIVE,
        )

    def read(self, query: MemoryQuery) -> tuple[MemoryRecord, ...]:
        if query.scope == MemoryScope.CASE:
            response = self._client.search(
                query.query_text or query.case_id,
                filters=_filters_from_query(query),
                top_k=query.max_records,
                show_expired=False,
            )
        elif query.scope == MemoryScope.USER:
            response = self._client.search(
                query.query_text or query.subject_ref,
                filters=_filters_from_query(query),
                top_k=query.max_records,
                show_expired=False,
            )
        else:
            return ()
        records = [_record_from_result(result) for result in _results_from_response(response)]
        now = _now()
        return tuple(
            record
            for record in records
            if record is not None
            and record.status == MemoryStatus.ACTIVE
            and record.expires_at > now
            and record.agent_id == query.agent_id
            and (
                (query.scope == MemoryScope.CASE and record.case_id == query.case_id)
                or (query.scope == MemoryScope.USER and record.subject_ref == query.subject_ref)
            )
        )[: query.max_records]

    def soft_delete_case(self, *, agent_id: str, case_id: str) -> int:
        existing_records = self.read(
            MemoryQuery(
                scope=MemoryScope.CASE,
                agent_id=agent_id,
                case_id=case_id,
                max_records=10_000,
            )
        )
        self._client.delete_all(
            run_id=case_id,
            metadata=_metadata_scope_filter(agent_id=agent_id, scope=MemoryScope.CASE),
        )
        return len(existing_records)

    def export_subject(self, *, agent_id: str, subject_ref: str) -> tuple[MemoryRecord, ...]:
        return self.read(
            MemoryQuery(
                scope=MemoryScope.USER,
                agent_id=agent_id,
                subject_ref=subject_ref,
                max_records=10_000,
            )
        )

    def soft_delete_subject(self, *, agent_id: str, subject_ref: str) -> int:
        existing_records = self.export_subject(agent_id=agent_id, subject_ref=subject_ref)
        self._client.delete_all(
            user_id=subject_ref,
            metadata=_metadata_scope_filter(agent_id=agent_id, scope=MemoryScope.USER),
        )
        return len(existing_records)


def _create_default_client() -> Mem0Client:
    try:
        if api_key := os.getenv("MEM0_API_KEY"):
            from mem0 import MemoryClient  # type: ignore[import-not-found]

            return cast(Mem0Client, MemoryClient(api_key=api_key))
        from mem0 import Memory
    except ImportError as exc:
        raise ProofAgentError(
            "PA_CONFIG_002",
            "Mem0 memory provider requires the mem0ai package.",
            "Install mem0ai or inject a compatible Mem0 client before using memory.provider: mem0.",
        ) from exc
    return cast(Mem0Client, Memory())


def _entity_kwargs_from_candidate(candidate: MemoryCandidate) -> dict[str, object]:
    if candidate.scope == MemoryScope.USER:
        return {"user_id": candidate.subject_ref}
    if candidate.scope == MemoryScope.CASE:
        return {"run_id": candidate.case_id}
    raise ProofAgentError(
        "PA_CONFIG_002",
        f"unsupported Mem0 memory scope: {candidate.scope.value}",
        "Use case or user memory scopes for the Mem0 memory provider.",
    )


def _filters_from_query(query: MemoryQuery) -> dict[str, object]:
    if query.scope == MemoryScope.CASE:
        return {
            "AND": [
                {"run_id": query.case_id},
                {"metadata": _metadata_scope_filter(agent_id=query.agent_id, scope=query.scope)},
            ]
        }
    if query.scope == MemoryScope.USER:
        return {
            "AND": [
                {"user_id": query.subject_ref},
                {"metadata": _metadata_scope_filter(agent_id=query.agent_id, scope=query.scope)},
            ]
        }
    return {"AND": [{"agent_id": query.agent_id}]}


def _metadata_scope_filter(*, agent_id: str, scope: MemoryScope) -> dict[str, str]:
    return {
        "proof_agent_agent_id": agent_id,
        "proof_agent_scope": scope.value,
    }


def _metadata_from_candidate(candidate: MemoryCandidate) -> dict[str, object]:
    return {
        "proof_agent_scope": candidate.scope.value,
        "proof_agent_case_id": candidate.case_id,
        "proof_agent_subject_ref": candidate.subject_ref,
        "proof_agent_agent_id": candidate.agent_id,
        "proof_agent_source_run_id": candidate.source_run_id,
        "proof_agent_source_turn_id": candidate.source_turn_id,
        "proof_agent_expires_at": candidate.expires_at,
        "proof_agent_sensitivity": candidate.sensitivity.value,
        "proof_agent_status": MemoryStatus.ACTIVE.value,
        "proof_agent_facts": _plain_mapping(candidate.facts),
    }


def _record_from_result(result: object) -> MemoryRecord | None:
    if not isinstance(result, Mapping):
        return None
    metadata = result.get("metadata")
    if not isinstance(metadata, Mapping):
        return None
    return MemoryRecord(
        memory_id=str(result.get("id") or result.get("memory_id") or ""),
        scope=MemoryScope(str(metadata.get("proof_agent_scope") or MemoryScope.CASE.value)),
        case_id=str(metadata.get("proof_agent_case_id") or ""),
        subject_ref=str(metadata.get("proof_agent_subject_ref") or ""),
        agent_id=str(metadata.get("proof_agent_agent_id") or ""),
        summary=str(result.get("memory") or result.get("content") or ""),
        facts=_mapping_or_empty(metadata.get("proof_agent_facts")),
        source_run_id=str(metadata.get("proof_agent_source_run_id") or ""),
        source_turn_id=str(metadata.get("proof_agent_source_turn_id") or ""),
        created_at=str(result.get("created_at") or _now()),
        expires_at=str(metadata.get("proof_agent_expires_at") or ""),
        sensitivity=MemorySensitivity(
            str(metadata.get("proof_agent_sensitivity") or MemorySensitivity.INTERNAL.value)
        ),
        status=MemoryStatus(str(metadata.get("proof_agent_status") or MemoryStatus.ACTIVE.value)),
    )


def _memory_id_from_response(response: object) -> str:
    if isinstance(response, Mapping):
        raw_id = response.get("id") or response.get("memory_id")
        if raw_id is not None:
            return str(raw_id)
        event_id = response.get("event_id")
        if event_id is not None:
            return f"mem0_event_{event_id}"
        for key in ("results", "memories"):
            nested = response.get(key)
            if isinstance(nested, list) and nested:
                nested_id = _memory_id_from_response(nested[0])
                if nested_id != "mem0_unknown":
                    return nested_id
    if isinstance(response, list) and response:
        nested_id = _memory_id_from_response(response[0])
        if nested_id != "mem0_unknown":
            return nested_id
    return "mem0_unknown"


def _results_from_response(response: object) -> list[object]:
    if isinstance(response, Mapping):
        results = response.get("results") or response.get("memories") or []
        if isinstance(results, list):
            return results
    if isinstance(response, list):
        return response
    return []


def _mapping_or_empty(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _plain_mapping(value: Mapping[str, Any]) -> dict[str, object]:
    plain: dict[str, object] = {}
    for key, item in value.items():
        if isinstance(item, Mapping):
            plain[str(key)] = _plain_mapping(item)
        elif isinstance(item, list | tuple):
            plain[str(key)] = list(item)
        else:
            plain[str(key)] = item
    return plain


def _expiration_date(expires_at: str) -> str:
    try:
        return datetime.fromisoformat(expires_at.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return expires_at[:10]


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
