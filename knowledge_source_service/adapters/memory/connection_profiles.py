"""Test-only Profile persistence; never a production fallback."""

from threading import RLock

from knowledge_source_service.contracts.connection_profiles import (
    ConnectionProfileRejectionEntry,
    ConnectionProfileView,
)
from knowledge_source_service.domain.connection_profiles import (
    ConnectionProfileAuditEvent,
    ConnectionProfileCommand,
    ConnectionProfileError,
    ConnectionProfileReceipt,
    ConnectionProfileRecord,
)


class InMemoryConnectionProfileRepository:
    def __init__(self) -> None:
        self._records: dict[tuple[str, int], ConnectionProfileRecord] = {}
        self._receipts: dict[tuple[str, str], ConnectionProfileReceipt] = {}
        self._events: list[ConnectionProfileAuditEvent] = []
        self._rejections: list[ConnectionProfileRejectionEntry] = []
        self._lock = RLock()

    def get(
        self, profile_id: str, *, revision: int | None = None
    ) -> ConnectionProfileRecord | None:
        with self._lock:
            if revision is None:
                revision = max((rev for key, rev in self._records if key == profile_id), default=0)
            return self._records.get((profile_id, revision))

    def get_receipt(self, command: ConnectionProfileCommand) -> ConnectionProfileReceipt | None:
        with self._lock:
            receipt = self._receipts.get((command.operator_id, command.key_digest))
            if receipt is not None and receipt.command.fingerprint != command.fingerprint:
                raise ConnectionProfileError("connection_profile_idempotency_conflict")
            return receipt

    def commit(
        self,
        record: ConnectionProfileRecord,
        *,
        expected_state_version: int,
        command: ConnectionProfileCommand,
    ) -> ConnectionProfileView:
        with self._lock:
            receipt = self.get_receipt(command)
            if receipt is not None:
                return receipt.view
            current = self.get(record.view.connection_profile_id)
            current_version = 0 if current is None else current.state_version
            if current_version != expected_state_version:
                raise ConnectionProfileError("connection_profile_revision_conflict")
            if record.state_version != current_version + 1:
                raise ConnectionProfileError("connection_profile_revision_conflict")
            self._records[(record.view.connection_profile_id, record.view.revision)] = record
            self._receipts[(command.operator_id, command.key_digest)] = ConnectionProfileReceipt(
                command=command, view=record.view
            )
            self._events.append(
                ConnectionProfileAuditEvent(
                    action=command.action,
                    operator_id=command.operator_id,
                    connection_profile_id=record.view.connection_profile_id,
                    revision=record.view.revision,
                    configuration_digest=record.view.configuration_digest,
                    recorded_at=record.view.updated_at,
                )
            )
            return record.view

    def audit(self, profile_id: str) -> tuple[ConnectionProfileAuditEvent, ...]:
        with self._lock:
            return tuple(
                event for event in self._events if event.connection_profile_id == profile_id
            )

    def record_rejection(self, event: ConnectionProfileRejectionEntry) -> None:
        with self._lock:
            self._rejections.append(event)

    def rejections(self, profile_id: str) -> tuple[ConnectionProfileRejectionEntry, ...]:
        with self._lock:
            return tuple(
                event for event in self._rejections if event.connection_profile_id == profile_id
            )
