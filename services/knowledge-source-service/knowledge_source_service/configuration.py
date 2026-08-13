"""Fail-closed process configuration without dotenv or secret logging."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import stat


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


def secret_environment_value(environment: Mapping[str, str], key: str) -> str:
    """Resolve one secret from a direct value or a hardened Docker-style file."""

    direct = environment.get(key, "").strip()
    file_value = environment.get(f"{key}_FILE", "").strip()
    if direct and file_value:
        raise ValueError(f"{key} and {key}_FILE cannot both be configured")
    if direct:
        return direct
    if not file_value:
        return ""
    path = Path(file_value)
    if not path.is_absolute():
        raise ValueError(f"{key}_FILE must be an absolute path")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ValueError(f"{key}_FILE is unavailable or unsafe") from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"{key}_FILE must be a regular file")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise ValueError(f"{key}_FILE permissions must be 0600 or stricter")
        if metadata.st_size < 1 or metadata.st_size > 64 * 1024:
            raise ValueError(f"{key}_FILE is outside the size limit")
        payload = os.read(descriptor, metadata.st_size + 1)
    finally:
        os.close(descriptor)
    if len(payload) != metadata.st_size:
        raise ValueError(f"{key}_FILE changed while it was read")
    try:
        value = payload.decode("utf-8").strip()
    except UnicodeDecodeError as error:
        raise ValueError(f"{key}_FILE must contain UTF-8 text") from error
    if not value or "\x00" in value or "\n" in value or "\r" in value:
        raise ValueError(f"{key}_FILE contains an invalid secret value")
    return value


@dataclass(frozen=True)
class ApiRuntimeConfiguration:
    """Authority-bearing API configuration kept out of public projections."""

    postgres_dsn: str
    object_store_uri: str
    search_endpoint: str
    release_identity: str

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> ApiRuntimeConfiguration:
        postgres_dsn = secret_environment_value(environment, "KSS_POSTGRES_DSN")
        values = {
            "KSS_POSTGRES_DSN": postgres_dsn,
            **{
                key: environment.get(key, "").strip()
                for key in _REQUIRED_API_CONFIGURATION
                if key != "KSS_POSTGRES_DSN"
            },
        }
        missing = tuple(
            key for key in _REQUIRED_API_CONFIGURATION if not values[key]
        )
        if missing:
            raise MissingRequiredConfiguration(missing)
        return cls(
            postgres_dsn=values["KSS_POSTGRES_DSN"],
            object_store_uri=values["KSS_OBJECT_STORE_URI"],
            search_endpoint=values["KSS_SEARCH_ENDPOINT"],
            release_identity=values["KSS_RELEASE_IDENTITY"],
        )
