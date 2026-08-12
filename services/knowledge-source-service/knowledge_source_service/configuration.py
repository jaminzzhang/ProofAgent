"""Fail-closed process configuration without dotenv or secret logging."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


_REQUIRED_API_CONFIGURATION = (
    "KSS_OBJECT_STORE_URI",
    "KSS_POSTGRES_DSN",
    "KSS_RELEASE_IDENTITY",
    "KSS_SEARCH_ENDPOINT",
)


class MissingRequiredConfiguration(ValueError):
    """One or more required configuration keys are absent or blank."""

    def __init__(self, keys: tuple[str, ...]) -> None:
        self.keys = keys
        super().__init__(f"missing required configuration: {', '.join(keys)}")


@dataclass(frozen=True)
class ApiRuntimeConfiguration:
    """Authority-bearing API configuration kept out of public projections."""

    postgres_dsn: str
    object_store_uri: str
    search_endpoint: str
    release_identity: str

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> ApiRuntimeConfiguration:
        missing = tuple(
            key for key in _REQUIRED_API_CONFIGURATION if not environment.get(key, "").strip()
        )
        if missing:
            raise MissingRequiredConfiguration(missing)
        return cls(
            postgres_dsn=environment["KSS_POSTGRES_DSN"],
            object_store_uri=environment["KSS_OBJECT_STORE_URI"],
            search_endpoint=environment["KSS_SEARCH_ENDPOINT"],
            release_identity=environment["KSS_RELEASE_IDENTITY"],
        )
