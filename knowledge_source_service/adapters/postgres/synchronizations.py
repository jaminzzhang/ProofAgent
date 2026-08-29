"""PostgreSQL authority and fenced queue for Source Synchronizations."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg import errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import TypeAdapter

from knowledge_source_service.contracts.synchronizations import (
    KnowledgeSourceSynchronization,
    ProfileSourceSynchronization,
    SourceSynchronizationRequest,
    SourceSynchronizationResource,
)
from knowledge_source_service.domain.synchronizations import (
    KnowledgeSourceSynchronizationClaim,
    KnowledgeSourceSynchronizationPersistenceConflict,
    KnowledgeSourceSynchronizationRecord,
    StaleKnowledgeSourceSynchronizationClaim,
)


_REQUEST: TypeAdapter[SourceSynchronizationRequest] = TypeAdapter(SourceSynchronizationRequest)
_RESOURCE: TypeAdapter[SourceSynchronizationResource] = TypeAdapter(SourceSynchronizationResource)


class PostgresKnowledgeSourceSynchronizationRepository:
    """Persist Source work in short PostgreSQL transactions."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    @classmethod
    def from_dsn(
        cls,
        dsn: str,
    ) -> PostgresKnowledgeSourceSynchronizationRepository:
        return cls(dsn.replace("postgresql+psycopg://", "postgresql://", 1))

    def close(self) -> None:
        """Each operation owns its PostgreSQL connection."""

    def add(self, record: KnowledgeSourceSynchronizationRecord) -> None:
        synchronization = record.synchronization
        profile = (
            synchronization.connection_profile
            if isinstance(synchronization, ProfileSourceSynchronization)
            else None
        )
        parameters = {
            "synchronization_id": (synchronization.knowledge_source_synchronization_id),
            "operator_id": record.operator_id,
            "idempotency_key": record.idempotency_key,
            "request_fingerprint": record.request_fingerprint,
            "knowledge_space_id": synchronization.knowledge_space_id,
            "knowledge_source_id": synchronization.knowledge_source_id,
            "connection_id": synchronization.connection_id
            if isinstance(synchronization, KnowledgeSourceSynchronization)
            else None,
            "profile_id": None if profile is None else profile.connection_profile_id,
            "profile_revision": None if profile is None else profile.revision,
            "profile_digest": None if profile is None else profile.configuration_digest,
            "state": synchronization.state,
            "request_json": Jsonb(record.request.model_dump(mode="json")),
            "resource_json": Jsonb(synchronization.model_dump(mode="json")),
            "submitted_at": synchronization.submitted_at,
        }
        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.transaction():
                    connection.execute(
                        """
                        INSERT INTO knowledge_source_synchronizations (
                            knowledge_source_synchronization_id,
                            operator_id,
                            idempotency_key,
                            request_fingerprint,
                            knowledge_space_id,
                            knowledge_source_id,
                            connection_id,
                            connection_profile_id,
                            connection_profile_revision,
                            connection_profile_digest,
                            state,
                            request_json,
                            resource_json,
                            submitted_at
                        ) VALUES (
                            %(synchronization_id)s,
                            %(operator_id)s,
                            %(idempotency_key)s,
                            %(request_fingerprint)s,
                            %(knowledge_space_id)s,
                            %(knowledge_source_id)s,
                            %(connection_id)s,
                            %(profile_id)s,
                            %(profile_revision)s,
                            %(profile_digest)s,
                            %(state)s,
                            %(request_json)s,
                            %(resource_json)s,
                            %(submitted_at)s
                        )
                        """,
                        parameters,
                    )
                    connection.execute(
                        """
                        INSERT INTO knowledge_source_synchronization_outbox (
                            event_id,
                            knowledge_source_synchronization_id,
                            event_type,
                            payload_json
                        ) VALUES (%s, %s, 'knowledge_source_synchronization.created', %s)
                        """,
                        (
                            f"{parameters['synchronization_id']}:created",
                            parameters["synchronization_id"],
                            Jsonb(
                                {
                                    "knowledge_source_synchronization_id": parameters[
                                        "synchronization_id"
                                    ]
                                }
                            ),
                        ),
                    )
        except (errors.UniqueViolation, errors.ForeignKeyViolation) as error:
            raise KnowledgeSourceSynchronizationPersistenceConflict(
                "synchronization authority conflicts with durable catalog"
            ) from error

    def get(
        self,
        synchronization_id: str,
    ) -> KnowledgeSourceSynchronizationRecord | None:
        return self._fetch_one(
            """
            SELECT * FROM knowledge_source_synchronizations
            WHERE knowledge_source_synchronization_id = %s
            """,
            (synchronization_id,),
        )

    def get_by_idempotency(
        self,
        *,
        operator_id: str,
        idempotency_key: str,
    ) -> KnowledgeSourceSynchronizationRecord | None:
        return self._fetch_one(
            """
            SELECT * FROM knowledge_source_synchronizations
            WHERE operator_id = %s AND idempotency_key = %s
            """,
            (operator_id, idempotency_key),
        )

    def claim_next_queued(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_duration: timedelta,
    ) -> KnowledgeSourceSynchronizationClaim | None:
        if not worker_id.strip() or lease_duration <= timedelta(0):
            raise ValueError("synchronization claim configuration is invalid")
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            with connection.transaction():
                row = connection.execute(
                    """
                    WITH candidate AS (
                        SELECT knowledge_source_synchronization_id
                        FROM knowledge_source_synchronizations
                        WHERE state IN ('queued', 'running')
                          AND (lease_owner IS NULL OR lease_expires_at <= %(now)s)
                        ORDER BY submitted_at, knowledge_source_synchronization_id
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    UPDATE knowledge_source_synchronizations AS synchronization
                    SET lease_owner = %(worker_id)s,
                        lease_expires_at = %(lease_expires_at)s,
                        fencing_token = synchronization.fencing_token + 1,
                        updated_at = clock_timestamp()
                    FROM candidate
                    WHERE synchronization.knowledge_source_synchronization_id =
                        candidate.knowledge_source_synchronization_id
                    RETURNING synchronization.*
                    """,
                    {
                        "worker_id": worker_id,
                        "now": now,
                        "lease_expires_at": now + lease_duration,
                    },
                ).fetchone()
        if row is None:
            return None
        return KnowledgeSourceSynchronizationClaim(
            record=self._record_from_row(row),
            worker_id=worker_id,
            fencing_token=int(row["fencing_token"]),
            lease_expires_at=row["lease_expires_at"],
        )

    def renew_claim(
        self,
        claim: KnowledgeSourceSynchronizationClaim,
        *,
        now: datetime,
        lease_duration: timedelta,
    ) -> None:
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        with psycopg.connect(self._dsn) as connection:
            persisted = connection.execute(
                """
                UPDATE knowledge_source_synchronizations
                SET lease_expires_at = GREATEST(lease_expires_at, %(expires_at)s),
                    updated_at = clock_timestamp()
                WHERE knowledge_source_synchronization_id = %(synchronization_id)s
                  AND state = 'running'
                  AND lease_owner = %(worker_id)s
                  AND fencing_token = %(fencing_token)s
                  AND lease_expires_at > %(now)s
                RETURNING knowledge_source_synchronization_id
                """,
                {
                    "expires_at": now + lease_duration,
                    "synchronization_id": (
                        claim.record.synchronization.knowledge_source_synchronization_id
                    ),
                    "worker_id": claim.worker_id,
                    "fencing_token": claim.fencing_token,
                    "now": now,
                },
            ).fetchone()
        if persisted is None:
            raise StaleKnowledgeSourceSynchronizationClaim

    def save_claim(
        self,
        claim: KnowledgeSourceSynchronizationClaim,
        record: KnowledgeSourceSynchronizationRecord,
        *,
        now: datetime,
    ) -> None:
        _validate_immutable_claim(claim, record)
        synchronization = _RESOURCE.validate_python(
            record.synchronization.model_dump(mode="python")
        )
        terminal = synchronization.state in {"succeeded", "failed"}
        with psycopg.connect(self._dsn) as connection:
            with connection.transaction():
                persisted = connection.execute(
                    """
                    UPDATE knowledge_source_synchronizations
                    SET state = %(state)s,
                        resource_json = %(resource_json)s,
                        materialized_knowledge_source_version_id = %(version_id)s,
                        state_version = state_version + 1,
                        lease_owner = CASE WHEN %(terminal)s THEN NULL ELSE lease_owner END,
                        lease_expires_at = CASE
                            WHEN %(terminal)s THEN NULL ELSE lease_expires_at
                        END,
                        updated_at = clock_timestamp()
                    WHERE knowledge_source_synchronization_id = %(synchronization_id)s
                      AND lease_owner = %(worker_id)s
                      AND fencing_token = %(fencing_token)s
                      AND lease_expires_at > %(now)s
                    RETURNING state_version
                    """,
                    {
                        "state": synchronization.state,
                        "resource_json": Jsonb(synchronization.model_dump(mode="json")),
                        "version_id": (synchronization.materialized_knowledge_source_version_id),
                        "terminal": terminal,
                        "synchronization_id": (synchronization.knowledge_source_synchronization_id),
                        "worker_id": claim.worker_id,
                        "fencing_token": claim.fencing_token,
                        "now": now,
                    },
                ).fetchone()
                if persisted is None:
                    raise StaleKnowledgeSourceSynchronizationClaim
                if terminal:
                    connection.execute(
                        """
                        INSERT INTO knowledge_source_synchronization_outbox (
                            event_id,
                            knowledge_source_synchronization_id,
                            event_type,
                            payload_json
                        ) VALUES (%s, %s, %s, %s)
                        ON CONFLICT (event_id) DO NOTHING
                        """,
                        (
                            (
                                f"{synchronization.knowledge_source_synchronization_id}:"
                                f"{synchronization.state}"
                            ),
                            synchronization.knowledge_source_synchronization_id,
                            (f"knowledge_source_synchronization.{synchronization.state}"),
                            Jsonb(
                                {
                                    "knowledge_source_synchronization_id": (
                                        synchronization.knowledge_source_synchronization_id
                                    ),
                                    "state": synchronization.state,
                                }
                            ),
                        ),
                    )

    def _fetch_one(
        self,
        statement: str,
        parameters: tuple[object, ...],
    ) -> KnowledgeSourceSynchronizationRecord | None:
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            row = connection.execute(statement, parameters).fetchone()
        return None if row is None else self._record_from_row(row)

    @staticmethod
    def _record_from_row(row: dict[str, Any]) -> KnowledgeSourceSynchronizationRecord:
        request = _REQUEST.validate_python(row["request_json"])
        synchronization = _RESOURCE.validate_python(row["resource_json"])
        return KnowledgeSourceSynchronizationRecord(
            synchronization=synchronization,
            request=request,
            operator_id=str(row["operator_id"]),
            idempotency_key=str(row["idempotency_key"]),
            request_fingerprint=str(row["request_fingerprint"]),
            state_version=int(row["state_version"]),
        )


def _validate_immutable_claim(
    claim: KnowledgeSourceSynchronizationClaim,
    record: KnowledgeSourceSynchronizationRecord,
) -> None:
    claimed = claim.record
    if (
        record.synchronization.knowledge_source_synchronization_id
        != claimed.synchronization.knowledge_source_synchronization_id
        or record.synchronization.knowledge_space_id != claimed.synchronization.knowledge_space_id
        or record.synchronization.knowledge_source_id != claimed.synchronization.knowledge_source_id
        or record.synchronization.model_dump(
            exclude={
                "state",
                "started_at",
                "completed_at",
                "materialized_knowledge_source_version_id",
                "problem",
            }
        )
        != claimed.synchronization.model_dump(
            exclude={
                "state",
                "started_at",
                "completed_at",
                "materialized_knowledge_source_version_id",
                "problem",
            }
        )
        or record.request != claimed.request
        or record.operator_id != claimed.operator_id
        or record.idempotency_key != claimed.idempotency_key
        or record.request_fingerprint != claimed.request_fingerprint
    ):
        raise ValueError("synchronization claim cannot mutate immutable authority")
