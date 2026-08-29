"""Internal immutable records; configuration never enters a public view."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from knowledge_source_service.contracts.connection_profiles import (
    ConnectionProfileView,
    HttpSnapshotProfile,
)


class ConnectionProfileError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ConnectionProfileRecord:
    view: ConnectionProfileView
    configuration: HttpSnapshotProfile = field(repr=False)
    validation_policy_revision: str | None = None
    state_version: int = 1


ProfileAction = Literal["create", "revise", "validate", "publish"]


@dataclass(frozen=True)
class ConnectionProfileCommand:
    operator_id: str
    key_digest: str
    fingerprint: str
    action: ProfileAction


@dataclass(frozen=True)
class ConnectionProfileReceipt:
    command: ConnectionProfileCommand
    view: ConnectionProfileView


@dataclass(frozen=True)
class ConnectionProfileAuditEvent:
    action: ProfileAction
    operator_id: str
    connection_profile_id: str
    revision: int
    configuration_digest: str
    recorded_at: datetime
