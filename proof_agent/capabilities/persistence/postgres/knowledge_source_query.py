"""Bounded opaque keyset queries for the Knowledge Source collection."""

from __future__ import annotations

import base64
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
from typing import Any, Literal

import sqlalchemy as sa

from proof_agent.capabilities.persistence.postgres._common import (
    ConnectionSource,
    read_connection,
    timestamp_text,
    timestamp_value,
)
from proof_agent.capabilities.persistence.postgres.schema import knowledge_sources
from proof_agent.contracts.agent_configuration import KnowledgeSource
from proof_agent.contracts.knowledge_source_api import (
    KnowledgeSourceCursorError,
    KnowledgeSourceCursorPage,
    KnowledgeSourceCursorPageInfo,
    KnowledgeSourceListItemProjection,
)


_RESOURCE = "knowledge_sources"
_SORT = "updated_at_desc"


class PostgresKnowledgeSourceQuery:
    """Query Sources with a signed cursor bound to normalized filters."""

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
        limit: int = 50,
        cursor: str | None = None,
        lifecycle_state: Literal["active", "archived"] | None = None,
    ) -> KnowledgeSourceCursorPage[KnowledgeSourceListItemProjection]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if lifecycle_state not in {None, "active", "archived"}:
            raise ValueError("lifecycle_state filter is invalid")
        now = self._now()
        boundary = (
            None
            if cursor is None
            else self._decode_cursor(
                cursor,
                lifecycle_state=lifecycle_state,
                now=now,
            )
        )
        conditions: list[Any] = []
        if lifecycle_state is not None:
            conditions.append(
                knowledge_sources.c.lifecycle_state == lifecycle_state.upper()
            )
        if boundary is not None:
            boundary_time, boundary_id = boundary
            conditions.append(
                sa.or_(
                    knowledge_sources.c.updated_at < boundary_time,
                    sa.and_(
                        knowledge_sources.c.updated_at == boundary_time,
                        knowledge_sources.c.source_id < boundary_id,
                    ),
                )
            )
        statement = (
            sa.select(knowledge_sources)
            .where(*conditions)
            .order_by(
                knowledge_sources.c.updated_at.desc(),
                knowledge_sources.c.source_id.desc(),
            )
            .limit(limit + 1)
        )
        filtered_count_conditions = (
            ()
            if lifecycle_state is None
            else (knowledge_sources.c.lifecycle_state == lifecycle_state.upper(),)
        )
        with read_connection(self._connection_source) as connection:
            rows = connection.execute(statement).mappings().all()
            total = int(
                connection.execute(
                    sa.select(sa.func.count())
                    .select_from(knowledge_sources)
                    .where(*filtered_count_conditions)
                ).scalar_one()
            )
            lifecycle_counts = connection.execute(
                sa.select(
                    knowledge_sources.c.lifecycle_state,
                    sa.func.count().label("count"),
                ).group_by(knowledge_sources.c.lifecycle_state)
            ).all()
        has_more = len(rows) > limit
        visible_rows = rows[:limit]
        data = tuple(
            KnowledgeSourceListItemProjection(
                source=KnowledgeSource.model_validate(row["configuration_json"]),
                revision=int(row["revision"]),
            )
            for row in visible_rows
        )
        next_cursor = None
        if has_more:
            last = visible_rows[-1]
            next_cursor = self._encode_cursor(
                lifecycle_state=lifecycle_state,
                updated_at=last["updated_at"],
                source_id=str(last["source_id"]),
                expires_at=now + self._cursor_ttl,
            )
        summary = {
            str(state).casefold(): int(count)
            for state, count in lifecycle_counts
        }
        return KnowledgeSourceCursorPage[KnowledgeSourceListItemProjection](
            data=data,
            page=KnowledgeSourceCursorPageInfo(
                limit=limit,
                next_cursor=next_cursor,
                has_more=has_more,
            ),
            summary={"total": total, **summary},
        )

    def _encode_cursor(
        self,
        *,
        lifecycle_state: str | None,
        updated_at: datetime,
        source_id: str,
        expires_at: datetime,
    ) -> str:
        payload = json.dumps(
            {
                "v": 1,
                "resource": _RESOURCE,
                "sort": _SORT,
                "filters": {"lifecycle_state": lifecycle_state},
                "last_updated_at": timestamp_text(updated_at),
                "last_source_id": source_id,
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
        lifecycle_state: str | None,
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
                or decoded.get("sort") != _SORT
                or decoded.get("filters")
                != {"lifecycle_state": lifecycle_state}
                or type(decoded.get("exp")) is not int
                or decoded["exp"] < int(now.timestamp())
                or not isinstance(decoded.get("last_source_id"), str)
            ):
                raise ValueError
            return (
                timestamp_value(
                    decoded["last_updated_at"],
                    field="cursor.last_updated_at",
                ),
                decoded["last_source_id"],
            )
        except (
            KeyError,
            TypeError,
            UnicodeDecodeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            raise KnowledgeSourceCursorError(
                "Knowledge Source cursor is invalid or expired"
            ) from exc

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("cursor clock must be timezone-aware")
        return value


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
    "PostgresKnowledgeSourceQuery",
]
