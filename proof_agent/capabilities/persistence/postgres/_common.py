from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import Enum
from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import Connection, Engine

from proof_agent.contracts.persistence import PersistenceInvariantError


ConnectionSource = Engine | Connection


@contextmanager
def read_connection(source: ConnectionSource) -> Iterator[Connection]:
    if isinstance(source, Engine):
        with source.connect() as connection:
            yield connection
        return
    yield source


@contextmanager
def write_connection(source: ConnectionSource) -> Iterator[Connection]:
    if isinstance(source, Engine):
        with source.begin() as connection:
            yield connection
        return
    yield source


def uuid_value(value: str, *, field: str) -> UUID:
    try:
        return UUID(value)
    except (ValueError, AttributeError) as exc:
        raise PersistenceInvariantError(f"{field} must be a full UUID") from exc


def timestamp_value(value: str, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PersistenceInvariantError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PersistenceInvariantError(f"{field} must be timezone-aware")
    return parsed


def timestamp_text(value: datetime) -> str:
    """Return one canonical UTC representation for adapter-neutral string DTOs."""

    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def model_json(model: BaseModel) -> dict[str, Any]:
    value = _plain_json_value(model.model_dump(mode="python", warnings=False))
    return cast(dict[str, Any], value)


def _plain_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain_json_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain_json_value(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value
