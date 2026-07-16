from __future__ import annotations

from uuid import uuid4

import sqlalchemy as sa

from proof_agent.capabilities.persistence.postgres._common import (
    ConnectionSource,
    model_json,
    read_connection,
    timestamp_value,
    uuid_value,
    write_connection,
)
from proof_agent.capabilities.persistence.postgres.schema import case_memory_records
from proof_agent.contracts.memory import (
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    MemorySensitivity,
    MemoryStatus,
)
from proof_agent.contracts.persistence import CaseMemoryAdmission


class PostgresCaseMemoryRepository:
    """Initial-production Case Memory with query-time expiry enforcement."""

    def __init__(self, connection_source: ConnectionSource) -> None:
        self._connection_source = connection_source

    def admit(self, admission: CaseMemoryAdmission) -> MemoryRecord:
        candidate = admission.candidate
        memory_id = uuid4()
        record = MemoryRecord(
            memory_id=str(memory_id),
            scope=candidate.scope,
            case_id=candidate.case_id,
            subject_ref=candidate.subject_ref,
            agent_id=candidate.agent_id,
            summary=candidate.summary,
            facts=candidate.facts,
            source_run_id=candidate.source_run_id,
            source_turn_id=candidate.source_turn_id,
            created_at=admission.admitted_at,
            expires_at=candidate.expires_at,
            sensitivity=candidate.sensitivity,
            status=MemoryStatus.ACTIVE,
        )
        with write_connection(self._connection_source) as connection:
            connection.execute(
                sa.insert(case_memory_records).values(
                    memory_id=memory_id,
                    case_id=uuid_value(candidate.case_id, field="case_id"),
                    agent_id=candidate.agent_id,
                    source_run_id=uuid_value(
                        candidate.source_run_id, field="source_run_id"
                    ),
                    source_turn_id=uuid_value(
                        candidate.source_turn_id, field="source_turn_id"
                    ),
                    status=record.status.value,
                    memory_json=model_json(record),
                    created_at=timestamp_value(
                        admission.admitted_at, field="admitted_at"
                    ),
                    expires_at=timestamp_value(candidate.expires_at, field="expires_at"),
                )
            )
        return record

    def read(self, query: MemoryQuery, *, as_of: str) -> tuple[MemoryRecord, ...]:
        if query.scope is not MemoryScope.CASE or not query.case_id:
            return ()
        filters: list[sa.ColumnElement[bool]] = [
            case_memory_records.c.case_id == uuid_value(query.case_id, field="case_id"),
            case_memory_records.c.agent_id == query.agent_id,
            case_memory_records.c.status == MemoryStatus.ACTIVE.value,
            case_memory_records.c.expires_at > timestamp_value(as_of, field="as_of"),
        ]
        if not query.allow_restricted:
            filters.append(
                case_memory_records.c.memory_json["sensitivity"].astext
                != MemorySensitivity.RESTRICTED.value
            )
        statement = (
            sa.select(case_memory_records.c.memory_json)
            .where(*filters)
            .order_by(case_memory_records.c.created_at.desc())
            .limit(query.max_records)
        )
        with read_connection(self._connection_source) as connection:
            payloads = connection.execute(statement).scalars().all()
        return tuple(MemoryRecord.model_validate(payload) for payload in payloads)

    def expire_due(self, *, as_of: str) -> int:
        as_of_value = timestamp_value(as_of, field="as_of")
        with write_connection(self._connection_source) as connection:
            due = connection.execute(
                sa.select(
                    case_memory_records.c.memory_id,
                    case_memory_records.c.memory_json,
                )
                .where(
                    case_memory_records.c.status == MemoryStatus.ACTIVE.value,
                    case_memory_records.c.expires_at <= as_of_value,
                )
                .with_for_update()
            ).mappings().all()
            for row in due:
                record = MemoryRecord.model_validate(row["memory_json"]).model_copy(
                    update={"status": MemoryStatus.DELETED}
                )
                connection.execute(
                    sa.update(case_memory_records)
                    .where(case_memory_records.c.memory_id == row["memory_id"])
                    .values(
                        status=MemoryStatus.DELETED.value,
                        memory_json=model_json(record),
                    )
                )
        return len(due)
