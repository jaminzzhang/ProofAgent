"""Bounded trace-safe PostgreSQL projections for the Source workspace."""

from __future__ import annotations

import base64
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
from typing import Any, Literal, cast

import sqlalchemy as sa

from proof_agent.capabilities.persistence.postgres._common import (
    ConnectionSource,
    read_connection,
    timestamp_text,
    timestamp_value,
)
from proof_agent.capabilities.persistence.postgres.schema import (
    audit_events,
    hybrid_document_candidates,
    hybrid_ingestion_jobs,
    hybrid_publication_preparation_jobs,
    prepared_knowledge_publications,
)
from proof_agent.contracts.knowledge_source_api import (
    KnowledgeSourceAuditProjection,
    KnowledgeSourceCursorError,
    KnowledgeSourceCursorPage,
    KnowledgeSourceCursorPageInfo,
    KnowledgeSourceDocumentProjection,
    KnowledgeSourcePublicationProjection,
    KnowledgeSourcePublicationValidationProjection,
)

_HYBRID_PUBLICATIONS = sa.table(
    "hybrid_knowledge_publication",
    sa.column("publication_id", sa.Text()),
    sa.column("source_id", sa.Text()),
    sa.column("source_publication_seq", sa.BigInteger()),
    sa.column("source_draft_version_id", sa.Text()),
    sa.column("generation_id", sa.Text()),
    sa.column("validation_id", sa.Text()),
    sa.column("publication_json"),
    sa.column("published_at", sa.DateTime(timezone=True)),
    sa.column("published_by", sa.Text()),
)


class PostgresKnowledgeSourceWorkspaceQuery:
    """Query workspace resources with Source-bound expiring signed cursors."""

    def __init__(
        self,
        connection_source: ConnectionSource,
        *,
        cursor_secret: bytes,
        clock: Callable[[], datetime] | None = None,
        cursor_ttl: timedelta = timedelta(minutes=15),
    ) -> None:
        if len(cursor_secret) < 32:
            raise ValueError("cursor_secret must contain at least 32 bytes")
        if cursor_ttl <= timedelta(0) or cursor_ttl > timedelta(hours=24):
            raise ValueError("cursor_ttl must be positive and at most 24 hours")
        self._connection_source = connection_source
        self._cursor_secret = cursor_secret
        self._clock = clock or (lambda: datetime.now(UTC))
        self._cursor_ttl = cursor_ttl

    def list_documents(
        self,
        *,
        source_id: str,
        limit: int = 50,
        cursor: str | None = None,
    ) -> KnowledgeSourceCursorPage[KnowledgeSourceDocumentProjection]:
        self._validate(source_id=source_id, limit=limit)
        now = self._now()
        boundary = self._boundary(
            cursor,
            resource="documents",
            source_id=source_id,
            now=now,
        )
        candidate_state = sa.case(
            (
                hybrid_document_candidates.c.candidate_revision_id
                == hybrid_ingestion_jobs.c.revision_id,
                "candidate",
            ),
            (
                hybrid_document_candidates.c.pending_revision_id
                == hybrid_ingestion_jobs.c.revision_id,
                "pending",
            ),
            (
                hybrid_ingestion_jobs.c.state.in_(("FAILED", "CANCELLED")),
                "unselected",
            ),
            else_="superseded",
        ).label("candidate_state")
        statement = (
            sa.select(
                hybrid_ingestion_jobs.c.job_id,
                hybrid_ingestion_jobs.c.document_id,
                hybrid_ingestion_jobs.c.revision_id,
                hybrid_ingestion_jobs.c.filename,
                hybrid_ingestion_jobs.c.request_json,
                hybrid_ingestion_jobs.c.state,
                hybrid_ingestion_jobs.c.safe_reason,
                hybrid_ingestion_jobs.c.created_at,
                hybrid_ingestion_jobs.c.updated_at,
                candidate_state,
            )
            .outerjoin(
                hybrid_document_candidates,
                sa.and_(
                    hybrid_document_candidates.c.source_id
                    == hybrid_ingestion_jobs.c.source_id,
                    hybrid_document_candidates.c.document_id
                    == hybrid_ingestion_jobs.c.document_id,
                ),
            )
            .where(hybrid_ingestion_jobs.c.source_id == source_id)
        )
        if boundary is not None:
            statement = statement.where(
                _before(
                    hybrid_ingestion_jobs.c.updated_at,
                    hybrid_ingestion_jobs.c.job_id,
                    boundary,
                )
            )
        statement = statement.order_by(
            hybrid_ingestion_jobs.c.updated_at.desc(),
            hybrid_ingestion_jobs.c.job_id.desc(),
        ).limit(limit + 1)
        with read_connection(self._connection_source) as connection:
            rows = connection.execute(statement).mappings().all()
            counts = connection.execute(
                sa.select(
                    hybrid_ingestion_jobs.c.state,
                    sa.func.count().label("count"),
                )
                .where(hybrid_ingestion_jobs.c.source_id == source_id)
                .group_by(hybrid_ingestion_jobs.c.state)
            ).all()
        visible = rows[:limit]
        data = tuple(
            KnowledgeSourceDocumentProjection(
                document_id=str(row["document_id"]),
                revision_id=str(row["revision_id"]),
                filename=str(row["filename"]),
                content_type=str(
                    _mapping(row["request_json"]).get(
                        "content_type",
                        "application/octet-stream",
                    )
                ),
                state=str(row["state"]),
                candidate_state=cast(
                    Literal["candidate", "pending", "superseded", "unselected"],
                    str(row["candidate_state"]),
                ),
                safe_reason=(
                    None if row["safe_reason"] is None else str(row["safe_reason"])
                ),
                created_at=timestamp_text(row["created_at"]),
                updated_at=timestamp_text(row["updated_at"]),
            )
            for row in visible
        )
        summary = {str(state).casefold(): int(count) for state, count in counts}
        return self._page(
            data=data,
            rows=visible,
            row_count=len(rows),
            limit=limit,
            resource="documents",
            source_id=source_id,
            now=now,
            last_id_key="job_id",
            summary={"total": sum(summary.values()), **summary},
        )

    def list_publication_validations(
        self,
        *,
        source_id: str,
        limit: int = 50,
        cursor: str | None = None,
    ) -> KnowledgeSourceCursorPage[KnowledgeSourcePublicationValidationProjection]:
        self._validate(source_id=source_id, limit=limit)
        now = self._now()
        boundary = self._boundary(
            cursor,
            resource="publication_validations",
            source_id=source_id,
            now=now,
        )
        statement = (
            sa.select(
                hybrid_publication_preparation_jobs.c.preparation_job_id,
                hybrid_publication_preparation_jobs.c.validation_id,
                hybrid_publication_preparation_jobs.c.source_revision,
                hybrid_publication_preparation_jobs.c.source_draft_version_id,
                hybrid_publication_preparation_jobs.c.state.label("job_state"),
                hybrid_publication_preparation_jobs.c.fencing_token.label("job_fence"),
                hybrid_publication_preparation_jobs.c.safe_reason,
                hybrid_publication_preparation_jobs.c.created_at,
                hybrid_publication_preparation_jobs.c.updated_at,
                prepared_knowledge_publications.c.state.label("authority_state"),
                prepared_knowledge_publications.c.fencing_token.label(
                    "authority_fence"
                ),
                prepared_knowledge_publications.c.generation_id,
            )
            .outerjoin(
                prepared_knowledge_publications,
                prepared_knowledge_publications.c.validation_id
                == hybrid_publication_preparation_jobs.c.validation_id,
            )
            .where(hybrid_publication_preparation_jobs.c.source_id == source_id)
        )
        if boundary is not None:
            statement = statement.where(
                _before(
                    hybrid_publication_preparation_jobs.c.updated_at,
                    hybrid_publication_preparation_jobs.c.preparation_job_id,
                    boundary,
                )
            )
        statement = statement.order_by(
            hybrid_publication_preparation_jobs.c.updated_at.desc(),
            hybrid_publication_preparation_jobs.c.preparation_job_id.desc(),
        ).limit(limit + 1)
        with read_connection(self._connection_source) as connection:
            rows = connection.execute(statement).mappings().all()
            counts = connection.execute(
                sa.select(
                    hybrid_publication_preparation_jobs.c.state,
                    sa.func.count().label("count"),
                )
                .where(hybrid_publication_preparation_jobs.c.source_id == source_id)
                .group_by(hybrid_publication_preparation_jobs.c.state)
            ).all()
        visible = rows[:limit]
        data = tuple(_validation_projection(row) for row in visible)
        summary = {str(state).casefold(): int(count) for state, count in counts}
        return self._page(
            data=data,
            rows=visible,
            row_count=len(rows),
            limit=limit,
            resource="publication_validations",
            source_id=source_id,
            now=now,
            last_id_key="preparation_job_id",
            summary={"total": sum(summary.values()), **summary},
        )

    def list_audit(
        self,
        *,
        source_id: str,
        limit: int = 50,
        cursor: str | None = None,
    ) -> KnowledgeSourceCursorPage[KnowledgeSourceAuditProjection]:
        self._validate(source_id=source_id, limit=limit)
        now = self._now()
        boundary = self._boundary(
            cursor,
            resource="audit",
            source_id=source_id,
            now=now,
        )
        source_condition = sa.or_(
            sa.and_(
                audit_events.c.target_type == "knowledge_source",
                audit_events.c.target_id == source_id,
            ),
            audit_events.c.metadata_json["source_id"].astext == source_id,
        )
        statement = sa.select(audit_events).where(source_condition)
        if boundary is not None:
            statement = statement.where(
                _before(
                    audit_events.c.occurred_at,
                    audit_events.c.audit_id,
                    boundary,
                )
            )
        statement = statement.order_by(
            audit_events.c.occurred_at.desc(),
            audit_events.c.audit_id.desc(),
        ).limit(limit + 1)
        with read_connection(self._connection_source) as connection:
            rows = connection.execute(statement).mappings().all()
            total = int(
                connection.execute(
                    sa.select(sa.func.count())
                    .select_from(audit_events)
                    .where(source_condition)
                ).scalar_one()
            )
        visible = rows[:limit]
        data = tuple(
            KnowledgeSourceAuditProjection(
                audit_id=str(row["audit_id"]),
                event_type=str(row["event_type"]),
                outcome=str(row["outcome"]),
                actor_subject=str(_mapping(row["actor_json"]).get("subject", "unknown")),
                occurred_at=timestamp_text(row["occurred_at"]),
                target_type=str(row["target_type"]),
                target_id=str(row["target_id"]),
                metadata=_safe_audit_metadata(_mapping(row["metadata_json"])),
            )
            for row in visible
        )
        return self._page(
            data=data,
            rows=visible,
            row_count=len(rows),
            limit=limit,
            resource="audit",
            source_id=source_id,
            now=now,
            last_id_key="audit_id",
            summary={"total": total},
            time_key="occurred_at",
        )

    def list_publications(
        self,
        *,
        source_id: str,
        limit: int = 50,
        cursor: str | None = None,
    ) -> KnowledgeSourceCursorPage[KnowledgeSourcePublicationProjection]:
        self._validate(source_id=source_id, limit=limit)
        now = self._now()
        boundary = self._boundary(
            cursor,
            resource="publications",
            source_id=source_id,
            now=now,
        )
        statement = sa.select(_HYBRID_PUBLICATIONS).where(
            _HYBRID_PUBLICATIONS.c.source_id == source_id
        )
        if boundary is not None:
            statement = statement.where(
                _before(
                    _HYBRID_PUBLICATIONS.c.published_at,
                    _HYBRID_PUBLICATIONS.c.publication_id,
                    boundary,
                )
            )
        statement = statement.order_by(
            _HYBRID_PUBLICATIONS.c.published_at.desc(),
            _HYBRID_PUBLICATIONS.c.publication_id.desc(),
        ).limit(limit + 1)
        with read_connection(self._connection_source) as connection:
            rows = connection.execute(statement).mappings().all()
            total = int(
                connection.execute(
                    sa.select(sa.func.count())
                    .select_from(_HYBRID_PUBLICATIONS)
                    .where(_HYBRID_PUBLICATIONS.c.source_id == source_id)
                ).scalar_one()
            )
        visible = rows[:limit]
        data = tuple(_publication_projection(row) for row in visible)
        return self._page(
            data=data,
            rows=visible,
            row_count=len(rows),
            limit=limit,
            resource="publications",
            source_id=source_id,
            now=now,
            last_id_key="publication_id",
            summary={"total": total},
            time_key="published_at",
        )

    def _page(
        self,
        *,
        data: tuple[Any, ...],
        rows: Sequence[Any],
        row_count: int,
        limit: int,
        resource: str,
        source_id: str,
        now: datetime,
        last_id_key: str,
        summary: dict[str, int],
        time_key: str = "updated_at",
    ) -> KnowledgeSourceCursorPage[Any]:
        has_more = row_count > limit
        next_cursor = None
        if has_more:
            last = rows[-1]
            next_cursor = self._encode_cursor(
                resource=resource,
                source_id=source_id,
                last_at=last[time_key],
                last_id=str(last[last_id_key]),
                expires_at=now + self._cursor_ttl,
            )
        return KnowledgeSourceCursorPage[Any](
            data=data,
            page=KnowledgeSourceCursorPageInfo(
                limit=limit,
                next_cursor=next_cursor,
                has_more=has_more,
            ),
            summary=summary,
        )

    def _boundary(
        self,
        cursor: str | None,
        *,
        resource: str,
        source_id: str,
        now: datetime,
    ) -> tuple[datetime, str] | None:
        return (
            None
            if cursor is None
            else self._decode_cursor(
                cursor,
                resource=resource,
                source_id=source_id,
                now=now,
            )
        )

    def _encode_cursor(
        self,
        *,
        resource: str,
        source_id: str,
        last_at: datetime,
        last_id: str,
        expires_at: datetime,
    ) -> str:
        payload = json.dumps(
            {
                "v": 1,
                "resource": resource,
                "source_id": source_id,
                "last_at": timestamp_text(last_at),
                "last_id": last_id,
                "exp": int(expires_at.timestamp()),
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        signature = hmac.new(self._cursor_secret, payload, hashlib.sha256).digest()
        return f"{_base64url(payload)}.{_base64url(signature)}"

    def _decode_cursor(
        self,
        cursor: str,
        *,
        resource: str,
        source_id: str,
        now: datetime,
    ) -> tuple[datetime, str]:
        try:
            if len(cursor) > 4_096:
                raise ValueError
            payload_part, signature_part = cursor.split(".", 1)
            payload = _decode_base64url(payload_part)
            signature = _decode_base64url(signature_part)
            expected = hmac.new(self._cursor_secret, payload, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            decoded: Any = json.loads(payload)
            if (
                not isinstance(decoded, dict)
                or decoded.get("v") != 1
                or decoded.get("resource") != resource
                or decoded.get("source_id") != source_id
                or type(decoded.get("exp")) is not int
                or decoded["exp"] < int(now.timestamp())
                or not isinstance(decoded.get("last_id"), str)
                or not isinstance(decoded.get("last_at"), str)
            ):
                raise ValueError
            return (
                timestamp_value(decoded["last_at"], field="cursor.last_at"),
                decoded["last_id"],
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise KnowledgeSourceCursorError("invalid Knowledge Source cursor") from exc

    def _validate(self, *, source_id: str, limit: int) -> None:
        if not source_id.strip():
            raise ValueError("source_id must be non-empty")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("cursor clock must be timezone-aware")
        return value.astimezone(UTC)


def _validation_projection(row: Any) -> KnowledgeSourcePublicationValidationProjection:
    job_state = str(row["job_state"])
    authority_state = (
        None if row["authority_state"] is None else str(row["authority_state"])
    )
    state = cast(
        Literal["queued", "running", "prepared", "failed", "consumed"],
        {
        "READY": "queued",
        "CLAIMED": "running",
        "PREPARED": "prepared",
        "FAILED": "failed",
        }[job_state],
    )
    if authority_state == "consumed":
        state = "consumed"
    return KnowledgeSourcePublicationValidationProjection(
        validation_id=str(row["validation_id"]),
        state=state,
        source_revision=int(row["source_revision"]),
        fencing_token=int(
            row["authority_fence"]
            if row["authority_fence"] is not None
            else row["job_fence"]
        ),
        source_draft_version_id=str(row["source_draft_version_id"]),
        generation_id=(
            None if row["generation_id"] is None else str(row["generation_id"])
        ),
        safe_reason=(
            None if row["safe_reason"] is None else str(row["safe_reason"])
        ),
        created_at=timestamp_text(row["created_at"]),
        updated_at=timestamp_text(row["updated_at"]),
    )


def _publication_projection(row: Any) -> KnowledgeSourcePublicationProjection:
    payload = _mapping(row["publication_json"])
    return KnowledgeSourcePublicationProjection(
        publication_id=str(row["publication_id"]),
        source_publication_seq=int(row["source_publication_seq"]),
        source_draft_version_id=str(row["source_draft_version_id"]),
        source_snapshot_id=str(payload["source_snapshot_id"]),
        generation_id=str(row["generation_id"]),
        validation_id=str(row["validation_id"]),
        published_at=timestamp_text(row["published_at"]),
        published_by=str(row["published_by"]),
    )


def _before(
    time_column: Any,
    id_column: Any,
    boundary: tuple[datetime, str],
) -> Any:
    boundary_time, boundary_id = boundary
    return sa.or_(
        time_column < boundary_time,
        sa.and_(
            time_column == boundary_time,
            sa.cast(id_column, sa.Text()) < boundary_id,
        ),
    )


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _safe_audit_metadata(value: dict[str, Any]) -> dict[str, object]:
    allowed = {
        "source_id",
        "document_id",
        "revision_id",
        "operation_id",
        "validation_id",
        "source_draft_version_id",
        "size_bytes",
        "content_sha256",
        "attempt_number",
        "failure_code",
    }
    return {key: value[key] for key in sorted(allowed & value.keys())}


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode_base64url(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + ("=" * (-len(value) % 4)))


__all__ = ["PostgresKnowledgeSourceWorkspaceQuery"]
