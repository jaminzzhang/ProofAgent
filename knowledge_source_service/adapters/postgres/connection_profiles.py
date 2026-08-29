"""Durable Profile CAS, idempotency receipts and success audit in one transaction."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast

import psycopg
from psycopg import errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from knowledge_source_service.contracts.connection_profiles import (
    ConnectionProfileRejectionEntry,
    ConnectionProfileView,
    HttpSnapshotProfile,
)
from knowledge_source_service.domain.connection_profiles import (
    ConnectionProfileAuditEvent,
    ConnectionProfileCommand,
    ConnectionProfileError,
    ConnectionProfileReceipt,
    ConnectionProfileRecord,
    ProfileAction,
)


class PostgresConnectionProfileRepository:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn.replace("postgresql+psycopg://", "postgresql://", 1)

    @classmethod
    def from_dsn(cls, dsn: str) -> "PostgresConnectionProfileRepository":
        return cls(dsn)

    @contextmanager
    def _connection(self) -> Iterator[psycopg.Connection[dict[str, Any]]]:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                yield connection
        except errors.ForeignKeyViolation:
            raise ConnectionProfileError("connection_profile_scope_mismatch") from None
        except errors.UniqueViolation:
            raise ConnectionProfileError("connection_profile_revision_conflict") from None
        except psycopg.Error:
            raise ConnectionProfileError("connection_profile_storage_unavailable") from None

    def get(
        self, profile_id: str, *, revision: int | None = None
    ) -> ConnectionProfileRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT revisions.* FROM knowledge_connection_profile_revisions AS revisions
                JOIN knowledge_connection_profiles AS profiles USING (connection_profile_id)
                WHERE connection_profile_id = %s
                  AND revision = COALESCE(%s, profiles.head_revision)
                """,
                (profile_id, revision),
            ).fetchone()
        if row is None:
            return None
        return ConnectionProfileRecord(
            view=ConnectionProfileView.model_validate(row["view_json"]),
            configuration=HttpSnapshotProfile.model_validate(row["configuration_json"]),
            validation_policy_revision=row["validation_policy_revision"],
            state_version=row["state_version"],
        )

    def get_receipt(self, command: ConnectionProfileCommand) -> ConnectionProfileReceipt | None:
        with self._connection() as connection:
            return self._receipt(connection, command)

    @staticmethod
    def _receipt(
        connection: psycopg.Connection[dict[str, Any]], command: ConnectionProfileCommand
    ) -> ConnectionProfileReceipt | None:
        row = connection.execute(
            """SELECT fingerprint, view_json FROM knowledge_connection_profile_commands
               WHERE operator_id = %s AND key_digest = %s""",
            (command.operator_id, command.key_digest),
        ).fetchone()
        if row is None:
            return None
        if row["fingerprint"] != command.fingerprint:
            raise ConnectionProfileError("connection_profile_idempotency_conflict")
        return ConnectionProfileReceipt(
            command, ConnectionProfileView.model_validate(row["view_json"])
        )

    def commit(
        self,
        record: ConnectionProfileRecord,
        *,
        expected_state_version: int,
        command: ConnectionProfileCommand,
    ) -> ConnectionProfileView:
        view = record.view
        if record.state_version != expected_state_version + 1:
            raise ConnectionProfileError("connection_profile_revision_conflict")
        with self._connection() as connection:
            # Serialize only the same operator/key, including concurrent creates
            # whose generated profile identities differ. No external calls here.
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"kss-profile:{command.operator_id}:{command.key_digest}",),
            )
            receipt = self._receipt(connection, command)
            if receipt is not None:
                return receipt.view
            if expected_state_version == 0:
                connection.execute(
                    """INSERT INTO knowledge_connection_profiles
                       (connection_profile_id, knowledge_space_id, knowledge_source_id,
                        head_revision, state_version) VALUES (%s, %s, %s, %s, %s)""",
                    (
                        view.connection_profile_id,
                        view.knowledge_space_id,
                        view.knowledge_source_id,
                        view.revision,
                        record.state_version,
                    ),
                )
            else:
                updated = connection.execute(
                    """UPDATE knowledge_connection_profiles SET head_revision = %s, state_version = %s
                       WHERE connection_profile_id = %s AND state_version = %s
                         AND knowledge_space_id = %s AND knowledge_source_id = %s
                       RETURNING connection_profile_id""",
                    (
                        view.revision,
                        record.state_version,
                        view.connection_profile_id,
                        expected_state_version,
                        view.knowledge_space_id,
                        view.knowledge_source_id,
                    ),
                ).fetchone()
                if updated is None:
                    raise ConnectionProfileError("connection_profile_revision_conflict")
            persisted = connection.execute(
                """INSERT INTO knowledge_connection_profile_revisions AS revision
                   (connection_profile_id, revision, state, state_version, configuration_digest,
                    configuration_json, view_json, validation_policy_revision)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (connection_profile_id, revision) DO UPDATE SET
                       state = EXCLUDED.state, state_version = EXCLUDED.state_version,
                       view_json = EXCLUDED.view_json,
                       validation_policy_revision = EXCLUDED.validation_policy_revision
                   WHERE revision.state <> 'published'
                     AND revision.configuration_digest = EXCLUDED.configuration_digest
                     AND revision.state_version = %s
                   RETURNING connection_profile_id""",
                (
                    view.connection_profile_id,
                    view.revision,
                    view.state,
                    record.state_version,
                    view.configuration_digest,
                    Jsonb(record.configuration.model_dump(mode="json")),
                    Jsonb(view.model_dump(mode="json")),
                    record.validation_policy_revision,
                    expected_state_version,
                ),
            ).fetchone()
            if persisted is None:
                raise ConnectionProfileError("connection_profile_revision_conflict")
            connection.execute(
                """INSERT INTO knowledge_connection_profile_commands
                   (operator_id, key_digest, fingerprint, action, connection_profile_id, revision, view_json)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (
                    command.operator_id,
                    command.key_digest,
                    command.fingerprint,
                    command.action,
                    view.connection_profile_id,
                    view.revision,
                    Jsonb(view.model_dump(mode="json")),
                ),
            )
        return view

    def audit(self, profile_id: str) -> tuple[ConnectionProfileAuditEvent, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT action, operator_id, view_json FROM knowledge_connection_profile_commands
                   WHERE connection_profile_id = %s ORDER BY event_sequence""",
                (profile_id,),
            ).fetchall()
        events = []
        for row in rows:
            view = ConnectionProfileView.model_validate(row["view_json"])
            events.append(
                ConnectionProfileAuditEvent(
                    action=cast(ProfileAction, row["action"]),
                    operator_id=row["operator_id"],
                    connection_profile_id=view.connection_profile_id,
                    revision=view.revision,
                    configuration_digest=view.configuration_digest,
                    recorded_at=view.updated_at,
                )
            )
        return tuple(events)

    def record_rejection(self, event: ConnectionProfileRejectionEntry) -> None:
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO knowledge_connection_profile_rejections
                   (connection_profile_id, event_json) VALUES (%s, %s)""",
                (event.connection_profile_id, Jsonb(event.model_dump(mode="json"))),
            )

    def rejections(self, profile_id: str) -> tuple[ConnectionProfileRejectionEntry, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT event_json FROM knowledge_connection_profile_rejections
                   WHERE connection_profile_id = %s ORDER BY event_sequence""",
                (profile_id,),
            ).fetchall()
        return tuple(
            ConnectionProfileRejectionEntry.model_validate(row["event_json"]) for row in rows
        )
