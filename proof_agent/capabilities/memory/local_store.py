from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from proof_agent.contracts import (
    MemoryCandidate,
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
)


class LocalMemoryStore:
    """Local append-only memory store for Stage 1 Case Memory."""

    def __init__(self, memory_dir: Path) -> None:
        self._memory_dir = memory_dir
        self._memory_dir.mkdir(parents=True, exist_ok=True)

    def append(self, candidate: MemoryCandidate) -> MemoryRecord:
        now = _now()
        record = MemoryRecord(
            memory_id=f"mem_{uuid4().hex[:8]}",
            scope=candidate.scope,
            case_id=candidate.case_id,
            agent_id=candidate.agent_id,
            summary=candidate.summary,
            facts=candidate.facts,
            source_run_id=candidate.source_run_id,
            source_turn_id=candidate.source_turn_id,
            created_at=now,
            expires_at=candidate.expires_at,
            sensitivity=candidate.sensitivity,
            status=MemoryStatus.ACTIVE,
        )
        path = self._record_path(record)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                _jsonable(record.model_dump(mode="python", warnings=False)),
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return record

    def read(self, query: MemoryQuery) -> tuple[MemoryRecord, ...]:
        if query.scope != MemoryScope.CASE:
            return ()
        case_dir = self._case_dir(query.agent_id, query.case_id)
        if not case_dir.exists():
            return ()
        now = _now()
        records: list[MemoryRecord] = []
        for path in case_dir.glob("*.json"):
            try:
                record = MemoryRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, ValueError):
                continue
            if record.status != MemoryStatus.ACTIVE:
                continue
            if record.expires_at <= now:
                continue
            records.append(record)
        records.sort(key=lambda item: item.created_at, reverse=True)
        return tuple(records[: query.max_records])

    def soft_delete_case(self, *, agent_id: str, case_id: str) -> int:
        deleted = 0
        for record in self.read(
            MemoryQuery(
                scope=MemoryScope.CASE, agent_id=agent_id, case_id=case_id, max_records=10_000
            )
        ):
            updated = MemoryRecord(
                memory_id=record.memory_id,
                scope=record.scope,
                case_id=record.case_id,
                agent_id=record.agent_id,
                summary=record.summary,
                facts=record.facts,
                source_run_id=record.source_run_id,
                source_turn_id=record.source_turn_id,
                created_at=record.created_at,
                expires_at=record.expires_at,
                sensitivity=record.sensitivity,
                status=MemoryStatus.DELETED,
            )
            self._record_path(record).write_text(
                json.dumps(
                    _jsonable(updated.model_dump(mode="python", warnings=False)),
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            deleted += 1
        return deleted

    def _record_path(self, record: MemoryRecord) -> Path:
        return self._case_dir(record.agent_id, record.case_id) / f"{record.memory_id}.json"

    def _case_dir(self, agent_id: str, case_id: str) -> Path:
        return self._memory_dir / "case" / _safe_path_part(agent_id) / _safe_path_part(case_id)


def _safe_path_part(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value
