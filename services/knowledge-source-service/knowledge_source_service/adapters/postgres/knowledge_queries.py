"""PostgreSQL persistence for admitted Knowledge Query resources."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
import json
from typing import Any

import psycopg
from psycopg import errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from knowledge_source_service.contracts.knowledge_query import (
    CreateKnowledgeQueryRequest,
    KnowledgeQuery,
)
from knowledge_source_service.contracts.results import KnowledgeQueryResult
from knowledge_source_service.domain.artifacts import ExactArtifactReference
from knowledge_source_service.domain.knowledge_queries import (
    KnowledgeQueryClaim,
    KnowledgeQueryPersistenceConflict,
    KnowledgeQueryRecord,
    StaleKnowledgeQueryClaim,
)
from knowledge_source_service.ports.authorization import KnowledgeQueryAdmission
from knowledge_source_service.ports.artifacts import ImmutableArtifactStore


class PostgresKnowledgeQueryRepository:
    """Persist Query authority in short PostgreSQL transactions."""

    def __init__(
        self,
        dsn: str,
        *,
        artifacts: ImmutableArtifactStore | None = None,
    ) -> None:
        self._dsn = dsn
        self._artifacts = artifacts

    @classmethod
    def from_dsn(
        cls,
        dsn: str,
        *,
        artifacts: ImmutableArtifactStore | None = None,
    ) -> PostgresKnowledgeQueryRepository:
        return cls(_psycopg_dsn(dsn), artifacts=artifacts)

    def close(self) -> None:
        """Retain a symmetric lifecycle API; each operation owns its connection."""

    def add(self, record: KnowledgeQueryRecord) -> None:
        query = record.query
        parameters = {
            "knowledge_query_id": query.knowledge_query_id,
            "client_id": record.client_id,
            "idempotency_key": record.idempotency_key,
            "request_fingerprint": record.request_fingerprint,
            "knowledge_space_id": record.admission.knowledge_space_id,
            "client_grant_id": record.admission.client_grant_id,
            "effective_access_scope_digest": (
                record.admission.effective_access_scope_digest
            ),
            "knowledge_base_release_id": query.knowledge_base_release_id,
            "state": query.state,
            "state_version": record.state_version,
            "request_json": Jsonb(record.request.model_dump(mode="json")),
            "query_json": Jsonb(query.model_dump(mode="json")),
            "admission_json": Jsonb(asdict(record.admission)),
            "submitted_at": query.submitted_at,
            "deadline_at": query.deadline_at,
        }
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                with connection.transaction():
                    persisted = connection.execute(
                        """
                        INSERT INTO knowledge_queries (
                            knowledge_query_id,
                            client_id,
                            idempotency_key,
                            request_fingerprint,
                            knowledge_space_id,
                            client_grant_id,
                            effective_access_scope_digest,
                            knowledge_base_release_id,
                            state,
                            state_version,
                            request_json,
                            query_json,
                            admission_json,
                            submitted_at,
                            deadline_at
                        ) VALUES (
                            %(knowledge_query_id)s,
                            %(client_id)s,
                            %(idempotency_key)s,
                            %(request_fingerprint)s,
                            %(knowledge_space_id)s,
                            %(client_grant_id)s,
                            %(effective_access_scope_digest)s,
                            %(knowledge_base_release_id)s,
                            %(state)s,
                            %(state_version)s,
                            %(request_json)s,
                            %(query_json)s,
                            %(admission_json)s,
                            %(submitted_at)s,
                            %(deadline_at)s
                        )
                        ON CONFLICT (knowledge_query_id) DO UPDATE SET
                            state = EXCLUDED.state,
                            query_json = EXCLUDED.query_json,
                            state_version = knowledge_queries.state_version + 1,
                            lease_owner = CASE
                                WHEN EXCLUDED.state IN (
                                    'succeeded', 'failed', 'cancelled', 'expired'
                                ) THEN NULL
                                ELSE knowledge_queries.lease_owner
                            END,
                            lease_expires_at = CASE
                                WHEN EXCLUDED.state IN (
                                    'succeeded', 'failed', 'cancelled', 'expired'
                                ) THEN NULL
                                ELSE knowledge_queries.lease_expires_at
                            END,
                            updated_at = clock_timestamp()
                        WHERE knowledge_queries.client_id = EXCLUDED.client_id
                          AND knowledge_queries.idempotency_key = EXCLUDED.idempotency_key
                          AND knowledge_queries.request_fingerprint = EXCLUDED.request_fingerprint
                          AND knowledge_queries.knowledge_space_id = EXCLUDED.knowledge_space_id
                          AND knowledge_queries.client_grant_id = EXCLUDED.client_grant_id
                          AND knowledge_queries.effective_access_scope_digest =
                              EXCLUDED.effective_access_scope_digest
                          AND knowledge_queries.knowledge_base_release_id =
                              EXCLUDED.knowledge_base_release_id
                          AND knowledge_queries.request_json = EXCLUDED.request_json
                          AND knowledge_queries.admission_json = EXCLUDED.admission_json
                          AND knowledge_queries.state_version = EXCLUDED.state_version
                        RETURNING knowledge_query_id
                        """,
                        parameters,
                    ).fetchone()
                    if persisted is None:
                        raise KnowledgeQueryPersistenceConflict(
                            "Knowledge Query immutable fields cannot be changed"
                        )
                    connection.execute(
                        """
                        INSERT INTO knowledge_query_outbox (
                            event_id,
                            knowledge_query_id,
                            event_type,
                            payload_json
                        ) VALUES (%s, %s, 'knowledge_query.created', %s)
                        ON CONFLICT (event_id) DO NOTHING
                        """,
                        (
                            f"{query.knowledge_query_id}:created",
                            query.knowledge_query_id,
                            Jsonb(
                                {
                                    "knowledge_query_id": query.knowledge_query_id,
                                    "knowledge_base_release_id": (
                                        query.knowledge_base_release_id
                                    ),
                                }
                            ),
                        ),
                    )
        except errors.UniqueViolation as error:
            raise KnowledgeQueryPersistenceConflict(
                "client-scoped idempotency identity already exists"
            ) from error

    def get(self, knowledge_query_id: str) -> KnowledgeQueryRecord | None:
        return self._fetch_one(
            "SELECT * FROM knowledge_queries WHERE knowledge_query_id = %s",
            (knowledge_query_id,),
        )

    def get_by_idempotency(
        self,
        *,
        client_id: str,
        idempotency_key: str,
    ) -> KnowledgeQueryRecord | None:
        return self._fetch_one(
            """
            SELECT *
            FROM knowledge_queries
            WHERE client_id = %s AND idempotency_key = %s
            """,
            (client_id, idempotency_key),
        )

    def expire_available_results(self, *, now: datetime, limit: int) -> int:
        """Detach expired Result authority; object lifecycle removes resulting orphans."""

        if limit < 1 or limit > 10_000:
            raise ValueError("result expiration limit must be between 1 and 10000")
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            with connection.transaction():
                rows = connection.execute(
                    """
                    WITH candidates AS (
                        SELECT knowledge_query_id
                        FROM knowledge_queries
                        WHERE state = 'succeeded'
                          AND query_json ->> 'result_availability' = 'available'
                          AND (query_json ->> 'result_expires_at')::timestamptz
                              <= %(now)s
                        ORDER BY updated_at, knowledge_query_id
                        FOR UPDATE SKIP LOCKED
                        LIMIT %(limit)s
                    )
                    UPDATE knowledge_queries AS query
                    SET query_json = jsonb_set(
                            jsonb_set(
                                query.query_json,
                                '{result_availability}',
                                '"expired"'::jsonb
                            ),
                            '{result}',
                            'null'::jsonb
                        ),
                        result_artifact_json = NULL,
                        result_digest = NULL,
                        result_candidate_count = NULL,
                        state_version = query.state_version + 1,
                        updated_at = clock_timestamp()
                    FROM candidates
                    WHERE query.knowledge_query_id = candidates.knowledge_query_id
                    RETURNING query.knowledge_query_id
                    """,
                    {"now": now, "limit": limit},
                ).fetchall()
                for row in rows:
                    query_id = str(row["knowledge_query_id"])
                    connection.execute(
                        """
                        INSERT INTO knowledge_query_outbox (
                            event_id,
                            knowledge_query_id,
                            event_type,
                            payload_json
                        ) VALUES (%s, %s, 'knowledge_query.result_expired', %s)
                        ON CONFLICT (event_id) DO NOTHING
                        """,
                        (
                            f"{query_id}:result-expired",
                            query_id,
                            Jsonb({"knowledge_query_id": query_id}),
                        ),
                    )
        return len(rows)

    def claim_next_queued(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_duration: timedelta,
    ) -> KnowledgeQueryClaim | None:
        if not worker_id.strip():
            raise ValueError("worker_id must not be blank")
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        lease_expires_at = now + lease_duration
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            with connection.transaction():
                row = connection.execute(
                    """
                    WITH candidate AS (
                        SELECT knowledge_query_id
                        FROM knowledge_queries
                        WHERE state IN ('queued', 'running')
                          AND (
                              lease_owner IS NULL
                              OR lease_expires_at <= %(now)s
                          )
                        ORDER BY submitted_at, knowledge_query_id
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    UPDATE knowledge_queries AS query
                    SET lease_owner = %(worker_id)s,
                        lease_expires_at = %(lease_expires_at)s,
                        fencing_token = query.fencing_token + 1,
                        updated_at = clock_timestamp()
                    FROM candidate
                    WHERE query.knowledge_query_id = candidate.knowledge_query_id
                    RETURNING query.*
                    """,
                    {
                        "worker_id": worker_id,
                        "now": now,
                        "lease_expires_at": lease_expires_at,
                    },
                ).fetchone()
        if row is None:
            return None
        return KnowledgeQueryClaim(
            record=self._record_from_row(row),
            worker_id=worker_id,
            fencing_token=int(row["fencing_token"]),
            lease_expires_at=row["lease_expires_at"],
        )

    def save_claim(
        self,
        claim: KnowledgeQueryClaim,
        record: KnowledgeQueryRecord,
    ) -> None:
        _validate_claim_record_identity(claim, record)
        query = KnowledgeQuery.model_validate(record.query.model_dump(mode="python"))
        terminal = query.state in {"succeeded", "failed", "cancelled", "expired"}
        storage_payload = query.model_dump(mode="json")
        result_reference: ExactArtifactReference | None = None
        result_candidate_count: int | None = None
        if query.state == "succeeded" and query.result_availability == "available":
            if query.result is None or self._artifacts is None:
                raise KnowledgeQueryPersistenceIntegrityError(
                    "available Query Result requires immutable artifact authority"
                )
            result_content = _canonical_result_bytes(query.result)
            result_reference = self._artifacts.put_immutable(
                object_key=(
                    f"spaces/{record.admission.knowledge_space_id}/queries/"
                    f"{query.knowledge_query_id}/result.json"
                ),
                content=result_content,
                media_type="application/vnd.knowledge.query-result+json",
            )
            if self._artifacts.get_exact(result_reference) != result_content:
                raise KnowledgeQueryPersistenceIntegrityError(
                    "immutable Query Result failed exact verification"
                )
            result_candidate_count = sum(
                len(group.candidate_evidence) for group in query.result.evidence_groups
            )
            storage_payload["result"] = None
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            with connection.transaction():
                persisted = connection.execute(
                    """
                    UPDATE knowledge_queries
                    SET state = %(state)s,
                        query_json = %(query_json)s,
                        result_artifact_json = %(result_artifact_json)s,
                        result_digest = %(result_digest)s,
                        result_candidate_count = %(result_candidate_count)s,
                        state_version = state_version + 1,
                        lease_owner = CASE
                            WHEN %(terminal)s THEN NULL
                            ELSE lease_owner
                        END,
                        lease_expires_at = CASE
                            WHEN %(terminal)s THEN NULL
                            ELSE lease_expires_at
                        END,
                        updated_at = clock_timestamp()
                    WHERE knowledge_query_id = %(knowledge_query_id)s
                      AND lease_owner = %(worker_id)s
                      AND fencing_token = %(fencing_token)s
                    RETURNING knowledge_query_id
                    """,
                    {
                        "state": query.state,
                        "query_json": Jsonb(storage_payload),
                        "result_artifact_json": (
                            None if result_reference is None else Jsonb(asdict(result_reference))
                        ),
                        "result_digest": (
                            None if result_reference is None else result_reference.sha256
                        ),
                        "result_candidate_count": result_candidate_count,
                        "terminal": terminal,
                        "knowledge_query_id": query.knowledge_query_id,
                        "worker_id": claim.worker_id,
                        "fencing_token": claim.fencing_token,
                    },
                ).fetchone()
                if persisted is None:
                    raise StaleKnowledgeQueryClaim(
                        "Knowledge Query execution claim is no longer current"
                    )

    def renew_claim(
        self,
        claim: KnowledgeQueryClaim,
        *,
        now: datetime,
        lease_duration: timedelta,
    ) -> None:
        """Extend a live running claim without changing its fencing token."""

        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        with psycopg.connect(self._dsn) as connection:
            persisted = connection.execute(
                """
                UPDATE knowledge_queries
                SET lease_expires_at = GREATEST(
                        lease_expires_at,
                        %(lease_expires_at)s
                    ),
                    updated_at = clock_timestamp()
                WHERE knowledge_query_id = %(knowledge_query_id)s
                  AND state = 'running'
                  AND lease_owner = %(worker_id)s
                  AND fencing_token = %(fencing_token)s
                  AND lease_expires_at > %(now)s
                RETURNING knowledge_query_id
                """,
                {
                    "lease_expires_at": now + lease_duration,
                    "knowledge_query_id": claim.record.query.knowledge_query_id,
                    "worker_id": claim.worker_id,
                    "fencing_token": claim.fencing_token,
                    "now": now,
                },
            ).fetchone()
        if persisted is None:
            raise StaleKnowledgeQueryClaim(
                "Knowledge Query execution claim is no longer current"
            )

    def _fetch_one(
        self,
        statement: str,
        parameters: tuple[object, ...],
    ) -> KnowledgeQueryRecord | None:
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            row = connection.execute(statement, parameters).fetchone()
        return self._record_from_row(row) if row is not None else None

    def _record_from_row(self, row: dict[str, Any]) -> KnowledgeQueryRecord:
        query_payload_value = row["query_json"]
        if type(query_payload_value) is not dict:
            raise KnowledgeQueryPersistenceIntegrityError(
                "persisted Knowledge Query resource is invalid"
            )
        query_payload = dict(query_payload_value)
        if query_payload.get("result_availability") == "available":
            if self._artifacts is None:
                raise KnowledgeQueryPersistenceIntegrityError(
                    "available Query Result cannot be read without artifact authority"
                )
            reference = _artifact_reference(row["result_artifact_json"])
            if row["result_digest"] != reference.sha256:
                raise KnowledgeQueryPersistenceIntegrityError(
                    "persisted Query Result digest does not match artifact reference"
                )
            try:
                result_payload = json.loads(self._artifacts.get_exact(reference))
                result = KnowledgeQueryResult.model_validate(result_payload)
            except Exception as error:
                raise KnowledgeQueryPersistenceIntegrityError(
                    "immutable Query Result artifact is invalid"
                ) from error
            if result.retrieval_lineage.knowledge_base_release_id != row[
                "knowledge_base_release_id"
            ]:
                raise KnowledgeQueryPersistenceIntegrityError(
                    "Query Result artifact references another Release"
                )
            query_payload["result"] = result.model_dump(mode="json")
        elif any(
            row[field] is not None
            for field in (
                "result_artifact_json",
                "result_digest",
                "result_candidate_count",
            )
        ):
            raise KnowledgeQueryPersistenceIntegrityError(
                "non-available Query has unexpected result artifact authority"
            )
        return _record_from_payload(row, query_payload)


class KnowledgeQueryPersistenceIntegrityError(RuntimeError):
    """Persisted Query metadata and immutable artifact authority disagree."""


def _record_from_payload(
    row: dict[str, Any],
    query_payload: dict[str, Any],
) -> KnowledgeQueryRecord:
    return KnowledgeQueryRecord(
        query=KnowledgeQuery.model_validate(query_payload),
        request=CreateKnowledgeQueryRequest.model_validate(row["request_json"]),
        client_id=str(row["client_id"]),
        idempotency_key=str(row["idempotency_key"]),
        request_fingerprint=str(row["request_fingerprint"]),
        admission=KnowledgeQueryAdmission(**row["admission_json"]),
        state_version=int(row["state_version"]),
    )


def _canonical_result_bytes(result: KnowledgeQueryResult) -> bytes:
    return json.dumps(
        result.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _artifact_reference(value: object) -> ExactArtifactReference:
    if type(value) is not dict:
        raise KnowledgeQueryPersistenceIntegrityError(
            "persisted Query Result artifact reference is missing"
        )
    try:
        return ExactArtifactReference(**value)
    except (TypeError, ValueError) as error:
        raise KnowledgeQueryPersistenceIntegrityError(
            "persisted Query Result artifact reference is invalid"
        ) from error


def _validate_claim_record_identity(
    claim: KnowledgeQueryClaim,
    record: KnowledgeQueryRecord,
) -> None:
    expected = claim.record
    if (
        record.query.knowledge_query_id != expected.query.knowledge_query_id
        or record.request != expected.request
        or record.client_id != expected.client_id
        or record.idempotency_key != expected.idempotency_key
        or record.request_fingerprint != expected.request_fingerprint
        or record.admission != expected.admission
    ):
        raise KnowledgeQueryPersistenceConflict(
            "a claim cannot mutate immutable Knowledge Query authority"
        )


def _psycopg_dsn(dsn: str) -> str:
    return dsn.replace("postgresql+psycopg://", "postgresql://", 1)
