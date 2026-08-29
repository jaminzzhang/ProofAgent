"""Persistence and deployment-owned validation seams for Connection Profiles."""

from typing import Protocol

from knowledge_source_service.contracts.connection_profiles import HttpSnapshotProfile
from knowledge_source_service.contracts.connection_profiles import ConnectionProfileView
from knowledge_source_service.contracts.connection_profiles import ConnectionProfileRejectionEntry
from knowledge_source_service.domain.connection_profiles import (
    ConnectionProfileAuditEvent,
    ConnectionProfileCommand,
    ConnectionProfileReceipt,
    ConnectionProfileRecord,
)
from knowledge_source_service.ports.snapshots import JsonSnapshotReader


class ConnectionProfileRepository(Protocol):
    def get(
        self, profile_id: str, *, revision: int | None = None
    ) -> ConnectionProfileRecord | None: ...

    def get_receipt(self, command: ConnectionProfileCommand) -> ConnectionProfileReceipt | None: ...

    def commit(
        self,
        record: ConnectionProfileRecord,
        *,
        expected_state_version: int,
        command: ConnectionProfileCommand,
    ) -> ConnectionProfileView:
        """Atomically CAS state, persist the idempotency receipt, and append audit."""
        ...

    def audit(self, profile_id: str) -> tuple[ConnectionProfileAuditEvent, ...]: ...

    def record_rejection(self, event: ConnectionProfileRejectionEntry) -> None: ...

    def rejections(self, profile_id: str) -> tuple[ConnectionProfileRejectionEntry, ...]: ...


class ConnectionProfileDeploymentPolicy(Protocol):
    def validate(self, configuration: HttpSnapshotProfile) -> str:
        """Admit connector, secret reference, egress, trust roots and hard limits.

        Return the exact deployment policy revision, or raise. Implementations must
        not return secret values. A schema-only check is not production validation.
        """
        ...


class ConnectionProfileSnapshotReaders(Protocol):
    def open(self, configuration: HttpSnapshotProfile) -> JsonSnapshotReader:
        """Worker-only secret/egress/TLS boundary for an admitted exact configuration.

        Must resolve only the versioned Secret Handle, enforce the deployment's
        egress/trust roots/limits, and fail closed. Never called during API admission.
        """
        ...
