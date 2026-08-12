"""Strict snapshot connection registry backed by secret environment handles."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
import ipaddress
import json
import re
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, StringConstraints, TypeAdapter, ValidationError, field_validator

from knowledge_source_service.adapters.http.json_snapshot import (
    HttpJsonSnapshotReader,
)
from knowledge_source_service.adapters.postgres.json_snapshot import (
    PostgresJsonSnapshotReader,
)
from knowledge_source_service.contracts.base import StrictContract
from knowledge_source_service.ports.snapshot_connections import (
    JsonSnapshotConnection,
)
from knowledge_source_service.ports.snapshots import JsonSnapshotReader


_CONNECTION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_SECRET_HANDLE = re.compile(r"^KSS_CONNECTION_SECRET_[A-Z0-9_]+$")
ConnectionId = Annotated[str, StringConstraints(pattern=_CONNECTION_ID.pattern)]
SecretEnvironmentKey = Annotated[
    str,
    StringConstraints(pattern=_SECRET_HANDLE.pattern),
]


class SnapshotConnectionConfigurationError(ValueError):
    """Connection descriptors or referenced secret handles are invalid."""


class SnapshotConnectionResolutionDisabled(RuntimeError):
    """This process may admit connection IDs but may not read upstream data."""


class _HttpJsonConnectionConfiguration(StrictContract):
    connection_id: ConnectionId
    kind: Literal["http_json"]
    endpoint: str
    bearer_token_environment_key: SecretEnvironmentKey | None = None
    allowed_networks: tuple[str, ...] = Field(default=(), max_length=32)
    max_response_bytes: int = Field(ge=1, le=64 * 1024 * 1024)

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or not parsed.path.startswith("/")
            or parsed.path == "/"
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("HTTP snapshot endpoint is invalid")
        return value

    @field_validator("allowed_networks")
    @classmethod
    def validate_allowed_networks(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("HTTP snapshot networks must be unique")
        try:
            tuple(ipaddress.ip_network(value) for value in values)
        except ValueError as error:
            raise ValueError("HTTP snapshot network is invalid") from error
        return values


class _PostgresConnectionConfiguration(StrictContract):
    connection_id: ConnectionId
    kind: Literal["postgresql"]
    dsn_environment_key: SecretEnvironmentKey
    relation: str
    columns: tuple[str, ...] = Field(min_length=1, max_length=256)
    record_key: tuple[str, ...] = Field(min_length=1, max_length=32)
    max_rows: int = Field(ge=1, le=1_000_000)
    max_response_bytes: int = Field(ge=1, le=256 * 1024 * 1024)
    statement_timeout_ms: int = Field(ge=1, le=3_600_000)

    @field_validator("relation")
    @classmethod
    def validate_relation(cls, value: str) -> str:
        parts = tuple(value.split("."))
        if (
            len(parts) not in {1, 2}
            or any(_IDENTIFIER.fullmatch(part) is None for part in parts)
            or parts[0] in {"pg_catalog", "information_schema"}
            or parts[-1].startswith("pg_")
        ):
            raise ValueError("PostgreSQL snapshot relation is invalid")
        return value

    @field_validator("columns")
    @classmethod
    def validate_columns(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values) or any(
            _IDENTIFIER.fullmatch(value) is None for value in values
        ):
            raise ValueError("PostgreSQL snapshot columns are invalid")
        return values

    @field_validator("record_key")
    @classmethod
    def validate_record_key(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values) or any(
            _IDENTIFIER.fullmatch(value) is None for value in values
        ):
            raise ValueError("PostgreSQL snapshot key is invalid")
        return values


SnapshotConnectionConfiguration = Annotated[
    _HttpJsonConnectionConfiguration | _PostgresConnectionConfiguration,
    Field(discriminator="kind"),
]
SnapshotConnectionConfigurationList = Annotated[
    list[SnapshotConnectionConfiguration],
    Field(max_length=100),
]
_CONFIGURATIONS: TypeAdapter[SnapshotConnectionConfigurationList] = TypeAdapter(
    SnapshotConnectionConfigurationList
)


class ConfiguredSnapshotConnectionRegistry:
    """Resolve static descriptors only in the dedicated Knowledge Worker role."""

    def __init__(
        self,
        *,
        configurations: tuple[SnapshotConnectionConfiguration, ...],
        secret_values: Mapping[str, str],
        clock: Callable[[], datetime],
        enable_resolution: bool,
    ) -> None:
        self._configurations = {
            configuration.connection_id: configuration
            for configuration in configurations
        }
        if len(self._configurations) != len(configurations):
            raise SnapshotConnectionConfigurationError(
                "snapshot connection identities must be unique"
            )
        self._secret_values = dict(secret_values)
        self._clock = clock
        self._enable_resolution = enable_resolution

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str],
        *,
        clock: Callable[[], datetime],
        enable_resolution: bool,
    ) -> ConfiguredSnapshotConnectionRegistry:
        raw = environment.get("KSS_SNAPSHOT_CONNECTIONS_JSON", "[]")
        try:
            payload = json.loads(raw)
            configurations = tuple(_CONFIGURATIONS.validate_python(payload))
        except (json.JSONDecodeError, ValidationError) as error:
            raise SnapshotConnectionConfigurationError(
                "snapshot connection configuration is invalid"
            ) from error
        secret_handles = {
            configuration.bearer_token_environment_key
            for configuration in configurations
            if isinstance(configuration, _HttpJsonConnectionConfiguration)
            and configuration.bearer_token_environment_key is not None
        } | {
            configuration.dsn_environment_key
            for configuration in configurations
            if isinstance(configuration, _PostgresConnectionConfiguration)
        }
        secret_values: dict[str, str] = {}
        if enable_resolution:
            missing = tuple(
                sorted(
                    handle
                    for handle in secret_handles
                    if not environment.get(handle, "").strip()
                )
            )
            if missing:
                raise SnapshotConnectionConfigurationError(
                    "one or more snapshot connection secret handles are unavailable"
                )
            secret_values = {handle: environment[handle] for handle in secret_handles}
        return cls(
            configurations=configurations,
            secret_values=secret_values,
            clock=clock,
            enable_resolution=enable_resolution,
        )

    def contains(self, connection_id: str) -> bool:
        return connection_id in self._configurations

    def resolve(self, connection_id: str) -> JsonSnapshotConnection:
        if not self._enable_resolution:
            raise SnapshotConnectionResolutionDisabled
        configuration = self._configurations.get(connection_id)
        if configuration is None:
            raise SnapshotConnectionConfigurationError(
                "snapshot connection is not configured"
            )
        try:
            reader: JsonSnapshotReader
            if isinstance(configuration, _HttpJsonConnectionConfiguration):
                secret_handle = configuration.bearer_token_environment_key
                reader = HttpJsonSnapshotReader(
                    endpoint=configuration.endpoint,
                    bearer_token=(
                        None
                        if secret_handle is None
                        else self._secret_values[secret_handle]
                    ),
                    max_response_bytes=configuration.max_response_bytes,
                    clock=self._clock,
                    allowed_networks=configuration.allowed_networks,
                )
            else:
                reader = PostgresJsonSnapshotReader(
                    dsn=self._secret_values[configuration.dsn_environment_key],
                    relation=configuration.relation,
                    columns=configuration.columns,
                    record_key=configuration.record_key,
                    max_rows=configuration.max_rows,
                    max_response_bytes=configuration.max_response_bytes,
                    statement_timeout_ms=configuration.statement_timeout_ms,
                    clock=self._clock,
                )
        except (KeyError, ValueError) as error:
            raise SnapshotConnectionConfigurationError(
                "snapshot connection could not be activated"
            ) from error
        return JsonSnapshotConnection(
            connection_id=configuration.connection_id,
            connection_kind=configuration.kind,
            reader=reader,
        )
