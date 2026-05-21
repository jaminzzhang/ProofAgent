from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
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


class Mem0MemoryStore:
    """Memory Provider Adapter backed by Mem0."""

    def __init__(self, *, client: Mem0Client | None = None) -> None:
        self._client = client or _create_default_client()

    def append(self, candidate: MemoryCandidate) -> MemoryRecord:
        metadata = _metadata_from_candidate(candidate)
        response = self._client.add(
            [{"role": "assistant", "content": candidate.summary}],
            agent_id=candidate.agent_id,
            run_id=candidate.case_id,
            metadata=metadata,
        )
        memory_id = _memory_id_from_response(response)
        return MemoryRecord(
            memory_id=memory_id,
            scope=candidate.scope,
            case_id=candidate.case_id,
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
        if query.scope != MemoryScope.CASE:
            return ()
        response = self._client.search(
            query.query_text or query.case_id,
            agent_id=query.agent_id,
            run_id=query.case_id,
            filters={
                "AND": [
                    {"agent_id": query.agent_id},
                    {"run_id": query.case_id},
                ]
            },
            top_k=query.max_records,
        )
        records = [_record_from_result(result) for result in _results_from_response(response)]
        now = _now()
        return tuple(
            record
            for record in records
            if record is not None
            and record.status == MemoryStatus.ACTIVE
            and record.expires_at > now
            and record.agent_id == query.agent_id
            and record.case_id == query.case_id
        )[: query.max_records]

    def soft_delete_case(self, *, agent_id: str, case_id: str) -> int:
        _ = (agent_id, case_id)
        raise NotImplementedError("Mem0 case soft delete is not implemented in Stage 2.")


def _create_default_client() -> Mem0Client:
    try:
        from mem0 import Memory  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ProofAgentError(
            "PA_CONFIG_002",
            "Mem0 memory provider requires the mem0ai package.",
            "Install the optional Mem0 extra before using memory.provider: mem0.",
        ) from exc
    return cast(Mem0Client, Memory())


def _metadata_from_candidate(candidate: MemoryCandidate) -> dict[str, object]:
    return {
        "proof_agent_scope": candidate.scope.value,
        "proof_agent_case_id": candidate.case_id,
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


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
