"""Read-only repeatable PostgreSQL table/view snapshot adapter."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
import json
import re

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from knowledge_source_service.domain.identities import sha256_json
from knowledge_source_service.ports.snapshots import JsonSnapshot


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


class PostgresJsonSnapshotError(RuntimeError):
    """The upstream relation could not produce an admitted immutable snapshot."""


class PostgresJsonSnapshotReader:
    """Capture an allowlisted relation in one bounded read-only repeatable transaction."""

    def __init__(
        self,
        *,
        dsn: str,
        relation: str,
        columns: tuple[str, ...],
        record_key: tuple[str, ...],
        max_rows: int,
        max_response_bytes: int,
        statement_timeout_ms: int,
        clock: Callable[[], datetime],
    ) -> None:
        relation_parts = tuple(relation.split("."))
        if (
            len(relation_parts) not in {1, 2}
            or any(_IDENTIFIER.fullmatch(part) is None for part in relation_parts)
            or relation_parts[0] in {"pg_catalog", "information_schema"}
            or relation_parts[-1].startswith("pg_")
        ):
            raise ValueError("PostgreSQL snapshot relation is not allowlisted")
        if (
            not columns
            or len(columns) > 256
            or len(set(columns)) != len(columns)
            or any(_IDENTIFIER.fullmatch(column) is None for column in columns)
        ):
            raise ValueError("PostgreSQL snapshot columns are invalid")
        if (
            not record_key
            or len(set(record_key)) != len(record_key)
            or any(column not in columns for column in record_key)
        ):
            raise ValueError("PostgreSQL snapshot record key is invalid")
        if max_rows < 1 or max_rows > 1_000_000:
            raise ValueError("PostgreSQL snapshot row bound is invalid")
        if max_response_bytes < 1 or max_response_bytes > 256 * 1024 * 1024:
            raise ValueError("PostgreSQL snapshot byte bound is invalid")
        if statement_timeout_ms < 1 or statement_timeout_ms > 3_600_000:
            raise ValueError("PostgreSQL snapshot timeout is invalid")
        parameters = conninfo_to_dict(dsn.replace("postgresql+psycopg://", "postgresql://", 1))
        self._dsn = dsn.replace("postgresql+psycopg://", "postgresql://", 1)
        self._relation_parts = relation_parts
        self._columns = columns
        self._record_key = record_key
        self._max_rows = max_rows
        self._max_response_bytes = max_response_bytes
        self._statement_timeout_ms = statement_timeout_ms
        self._clock = clock
        self._source_identity_digest = sha256_json(
            {
                "adapter": "postgresql-table-view-snapshot.v1",
                "host": parameters.get("host", ""),
                "port": parameters.get("port", ""),
                "dbname": parameters.get("dbname", ""),
                "relation": relation_parts,
                "columns": columns,
                "record_key": record_key,
            }
        )

    def read(self) -> JsonSnapshot:
        projection = sql.SQL(", ").join(sql.Identifier(column) for column in self._columns)
        ordering = sql.SQL(", ").join(sql.Identifier(column) for column in self._record_key)
        statement = sql.SQL("SELECT {} FROM {} ORDER BY {} LIMIT %s").format(
            projection,
            sql.Identifier(*self._relation_parts),
            ordering,
        )
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                connection.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
                connection.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(self._statement_timeout_ms),),
                )
                snapshot_row = connection.execute(
                    "SELECT pg_current_snapshot()::text AS snapshot_id"
                ).fetchone()
                rows = connection.execute(statement, (self._max_rows + 1,)).fetchall()
        except psycopg.Error as error:
            raise PostgresJsonSnapshotError(
                "PostgreSQL snapshot transaction failed"
            ) from error
        if snapshot_row is None or type(snapshot_row["snapshot_id"]) is not str:
            raise PostgresJsonSnapshotError("PostgreSQL snapshot identity is unavailable")
        if len(rows) > self._max_rows:
            raise PostgresJsonSnapshotError("PostgreSQL snapshot exceeded its row bound")
        if not rows:
            raise PostgresJsonSnapshotError("PostgreSQL snapshot contains no records")
        try:
            content = json.dumps(
                {
                    "records": [
                        {
                            column: _json_value(row[column])
                            for column in self._columns
                        }
                        for row in rows
                    ]
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
                allow_nan=False,
            ).encode("utf-8")
        except (KeyError, TypeError, ValueError) as error:
            raise PostgresJsonSnapshotError(
                "PostgreSQL snapshot contains an unsupported value"
            ) from error
        if len(content) > self._max_response_bytes:
            raise PostgresJsonSnapshotError("PostgreSQL snapshot exceeded its byte bound")
        return JsonSnapshot(
            content=content,
            source_identity_digest=self._source_identity_digest,
            observed_at=self._clock(),
            etag=snapshot_row["snapshot_id"],
            last_modified=None,
        )


def _json_value(value: object) -> object:
    if value is None or type(value) in {str, int, bool}:
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("non-finite PostgreSQL numeric value")
        return format(value, "f")
    if type(value) is float:
        if value != value or value in {float("inf"), float("-inf")}:
            raise ValueError("non-finite PostgreSQL floating value")
        return str(value)
    if type(value) is date:
        return value.isoformat()
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("naive PostgreSQL timestamp value")
        return value.isoformat()
    raise TypeError("unsupported PostgreSQL snapshot value")
