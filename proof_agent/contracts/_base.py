from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict


class FrozenDict(Mapping[str, Any]):
    """Read-only mapping used inside frozen Pydantic contracts.

    Pydantic's `frozen=True` protects model attributes, but nested dicts would
    still be mutable unless we recursively freeze them at validation time.
    """

    def __init__(self, items: Mapping[str, Any] | None = None) -> None:
        self._data = dict(items or {})

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return repr(self._data)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Mapping):
            return bool(_json_equivalent(self) == _json_equivalent(other))
        return False


def _json_equivalent(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_equivalent(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_equivalent(item) for item in value]
    return value


def freeze_value(value: Any) -> Any:
    """Recursively convert mutable containers into immutable contract values."""

    if isinstance(value, FrozenDict):
        return value
    if isinstance(value, Mapping):
        return FrozenDict({str(key): freeze_value(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(freeze_value(item) for item in value)
    return value


class FrozenModel(BaseModel):
    """Base model for public contracts crossing policy, audit, and runtime boundaries."""

    model_config = ConfigDict(frozen=True)
