"""Bounded opaque keyset queries for Knowledge Source operations."""

from __future__ import annotations

import base64
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
from typing import Any

import sqlalchemy as sa

from proof_agent.capabilities.persistence.postgres._common import (
    ConnectionSource,
    read_connection,
    timestamp_text,
    timestamp_value,
)
from proof_agent.capabilities.persistence.postgres.schema import (
    knowledge_source_operations,
)
from proof_agent.contracts.knowledge_source_api import (
    KnowledgeSourceCursorError,
    KnowledgeSourceCursorPage,
    KnowledgeSourceCursorPageInfo,
    KnowledgeSourceOperation,
)


_RESOURCE = "knowledge_source_operations"
_SORT = "created_at_desc"


class PostgresKnowledgeSourceOperationQuery:
    """Read operation pages without materializing an entire Source history."""

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

    def list_page(
        self,
        *,
        source_id: str,
        limit: int = 50,
        cursor: str | None = None,
    ) -> KnowledgeSourceCursorPage[KnowledgeSourceOperation]:
        if not source_id.strip():
            raise ValueError("source_id must be non-empty")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        now = self._now()
        boundary = (
            None
            if cursor is None
            else self._decode_cursor(cursor, source_id=source_id, now=now)
        )
        statement = sa.select(knowledge_source_operations).where(
            knowledge_source_operations.c.source_id == source_id
        )
        if boundary is not None:
            boundary_time, boundary_id = boundary
            statement = statement.where(
                sa.or_(
                    knowledge_source_operations.c.created_at < boundary_time,
                    sa.and_(
                        knowledge_source_operations.c.created_at == boundary_time,
                        knowledge_source_operations.c.operation_id < boundary_id,
                    ),
                )
            )
        statement = statement.order_by(
            knowledge_source_operations.c.created_at.desc(),
            knowledge_source_operations.c.operation_id.desc(),
        ).limit(limit + 1)
        with read_connection(self._connection_source) as connection:
            rows = connection.execute(statement).mappings().all()
            status_counts = connection.execute(
                sa.select(
                    knowledge_source_operations.c.status,
                    sa.func.count().label("count"),
                )
                .where(knowledge_source_operations.c.source_id == source_id)
                .group_by(knowledge_source_operations.c.status)
            ).all()
        has_more = len(rows) > limit
        visible_rows = rows[:limit]
        operations = tuple(
            KnowledgeSourceOperation.model_validate(row["operation_json"])
            for row in visible_rows
        )
        next_cursor = None
        if has_more:
            last = visible_rows[-1]
            next_cursor = self._encode_cursor(
                source_id=source_id,
                created_at=last["created_at"],
                operation_id=str(last["operation_id"]),
                expires_at=now + self._cursor_ttl,
            )
        summary = {str(status): int(count) for status, count in status_counts}
        summary = {"total": sum(summary.values()), **summary}
        return KnowledgeSourceCursorPage[KnowledgeSourceOperation](
            data=operations,
            page=KnowledgeSourceCursorPageInfo(
                limit=limit,
                next_cursor=next_cursor,
                has_more=has_more,
            ),
            summary=summary,
        )

    def _encode_cursor(
        self,
        *,
        source_id: str,
        created_at: datetime,
        operation_id: str,
        expires_at: datetime,
    ) -> str:
        payload = json.dumps(
            {
                "v": 1,
                "resource": _RESOURCE,
                "source_id": source_id,
                "sort": _SORT,
                "last_created_at": timestamp_text(created_at),
                "last_operation_id": operation_id,
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
                or decoded.get("resource") != _RESOURCE
                or decoded.get("source_id") != source_id
                or decoded.get("sort") != _SORT
                or type(decoded.get("exp")) is not int
                or decoded["exp"] < int(now.timestamp())
                or not isinstance(decoded.get("last_operation_id"), str)
            ):
                raise ValueError
            boundary = timestamp_value(
                decoded["last_created_at"],
                field="cursor.last_created_at",
            )
            return boundary, decoded["last_operation_id"]
        except (KeyError, TypeError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            raise KnowledgeSourceCursorError(
                "Knowledge Source cursor is invalid or expired"
            ) from exc

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("cursor clock must be timezone-aware")
        return now


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_base64url(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(
        f"{value}{padding}",
        altchars=b"-_",
        validate=True,
    )


__all__ = [
    "KnowledgeSourceCursorError",
    "PostgresKnowledgeSourceOperationQuery",
]
