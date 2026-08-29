"""PostgreSQL authority for exact Release references and lifecycle commands."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Literal, cast

import psycopg
from psycopg import errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from knowledge_source_service.contracts.release_references import (
    DeregisteredKnowledgeBaseReleaseReference,
    DeregisteredKnowledgeBaseReleaseReferenceAuditEntry,
    DeprecatedKnowledgeBaseRelease,
    KnowledgeBaseReleaseLifecycleAuditEntry,
    KnowledgeBaseReleaseReference,
    KnowledgeBaseReleaseReferenceAuditEntry,
    RetiredKnowledgeBaseRelease,
    RetiredKnowledgeBaseReleaseAuditEntry,
    RevokedKnowledgeBaseRelease,
    RevokedKnowledgeBaseReleaseAuditEntry,
)
from knowledge_source_service.domain.release_references import (
    ReleaseDeletionFacts,
    ReleaseLifecycleCommand,
    ReleaseLifecycleError,
    ReleaseLifecycleTarget,
    ReleaseReferenceCommand,
    ReleaseReferenceError,
    ReleaseReferenceTarget,
)
from knowledge_source_service.ports.release_references import (
    ReleaseLifecycleTransaction,
    ReleaseReferenceAuditEntry,
    ReleaseReferenceState,
    ReleaseReferenceTransaction,
)


class _Transaction:
    def __init__(self, connection: psycopg.Connection[dict[str, Any]]) -> None:
        self._connection = connection

    def replay(self, command: ReleaseReferenceCommand) -> ReleaseReferenceState | None:
        self._connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"kss-release-reference:{command.authenticated_client_id}:{command.key_digest}",),
        )
        row = self._connection.execute(
            """SELECT fingerprint, release_reference_id, result_json
               FROM knowledge_base_release_reference_commands
               WHERE authenticated_client_id = %s AND key_digest = %s""",
            (command.authenticated_client_id, command.key_digest),
        ).fetchone()
        if row is None:
            return None
        if row["fingerprint"] != command.fingerprint:
            raise ReleaseReferenceError("release_reference_idempotency_conflict")
        result = _reference_state(row["result_json"])
        persisted_row = self._reference_row(result.release_reference_id)
        if persisted_row is None:
            raise ReleaseReferenceError("release_reference_integrity_unavailable")
        persisted = _validated_reference_row(persisted_row)
        if command.action == "register":
            if not isinstance(result, KnowledgeBaseReleaseReference) or not (
                _same_reference_identity(result, persisted)
            ):
                raise ReleaseReferenceError("release_reference_integrity_unavailable")
        elif command.action == "deregister":
            if not isinstance(result, DeregisteredKnowledgeBaseReleaseReference) or (
                persisted != result
            ):
                raise ReleaseReferenceError("release_reference_integrity_unavailable")
        else:
            raise ReleaseReferenceError("release_reference_integrity_unavailable")
        return result

    def lifecycle_replay(
        self, command: ReleaseLifecycleCommand
    ) -> (
        DeprecatedKnowledgeBaseRelease
        | RetiredKnowledgeBaseRelease
        | RevokedKnowledgeBaseRelease
        | None
    ):
        self._connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"kss-release-lifecycle:{command.operator_id}:{command.key_digest}",),
        )
        rows = self._connection.execute(
            """SELECT fingerprint, result_json
               FROM (
                   SELECT event_sequence, fingerprint, result_json
                   FROM knowledge_base_release_lifecycle_commands
                   WHERE operator_id = %s AND key_digest = %s
                   UNION ALL
                   SELECT event_sequence, fingerprint, result_json
                   FROM knowledge_base_release_retirement_commands
                   WHERE operator_id = %s AND key_digest = %s
                   UNION ALL
                   SELECT event_sequence, fingerprint, result_json
                   FROM knowledge_base_release_revocation_commands
                   WHERE operator_id = %s AND key_digest = %s
               ) AS command_receipt
               ORDER BY event_sequence""",
            (
                command.operator_id,
                command.key_digest,
                command.operator_id,
                command.key_digest,
                command.operator_id,
                command.key_digest,
            ),
        ).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise ReleaseLifecycleError("release_lifecycle_integrity_unavailable")
        row = rows[0]
        if row["fingerprint"] != command.fingerprint:
            raise ReleaseLifecycleError("release_lifecycle_idempotency_conflict")
        return _lifecycle_result(row["result_json"])

    def queryable_release(self, knowledge_base_release_id: str) -> ReleaseReferenceTarget | None:
        row = self._connection.execute(
            """SELECT knowledge_space_id, knowledge_base_id, knowledge_base_release_id
               FROM knowledge_base_releases
               WHERE knowledge_base_release_id = %s AND state = 'queryable'
               FOR UPDATE""",
            (knowledge_base_release_id,),
        ).fetchone()
        if row is None:
            return None
        return ReleaseReferenceTarget(
            knowledge_space_id=str(row["knowledge_space_id"]),
            knowledge_base_id=str(row["knowledge_base_id"]),
            knowledge_base_release_id=str(row["knowledge_base_release_id"]),
        )

    def release_for_update(self, knowledge_base_release_id: str) -> ReleaseLifecycleTarget | None:
        row = self._connection.execute(
            """SELECT knowledge_space_id, knowledge_base_id,
                      knowledge_base_release_id, state, deprecated_at,
                      retired_at, revoked_at, revocation_reason_code
               FROM knowledge_base_releases
               WHERE knowledge_base_release_id = %s
               FOR UPDATE""",
            (knowledge_base_release_id,),
        ).fetchone()
        if row is None:
            return None
        state, deprecated_at, _retired_at, _revoked_at = _validated_lifecycle_row(row)
        return ReleaseLifecycleTarget(
            knowledge_space_id=str(row["knowledge_space_id"]),
            knowledge_base_id=str(row["knowledge_base_id"]),
            knowledge_base_release_id=str(row["knowledge_base_release_id"]),
            state=state,
            deprecated_at=deprecated_at,
        )

    def reference_for_external_resource(
        self,
        *,
        authenticated_client_id: str,
        external_resource_kind: str,
        external_resource_id: str,
    ) -> ReleaseReferenceState | None:
        row = self._connection.execute(
            """SELECT * FROM knowledge_base_release_references
               WHERE authenticated_client_id = %s
                 AND external_resource_kind = %s
                 AND external_resource_id = %s
               FOR UPDATE""",
            (authenticated_client_id, external_resource_kind, external_resource_id),
        ).fetchone()
        return None if row is None else _validated_reference_row(row)

    def reference_for_update(self, release_reference_id: str) -> ReleaseReferenceState | None:
        row = self._connection.execute(
            """SELECT * FROM knowledge_base_release_references
               WHERE release_reference_id = %s
               FOR UPDATE""",
            (release_reference_id,),
        ).fetchone()
        return None if row is None else _validated_reference_row(row)

    def database_now(self) -> datetime:
        row = self._connection.execute("SELECT clock_timestamp() AS database_now").fetchone()
        if row is None:
            raise ReleaseReferenceError("release_reference_storage_unavailable")
        return cast(datetime, row["database_now"])

    def persist(
        self,
        reference: KnowledgeBaseReleaseReference,
        command: ReleaseReferenceCommand,
    ) -> KnowledgeBaseReleaseReference:
        self._connection.execute(
            """INSERT INTO knowledge_base_release_references (
                   release_reference_id, authenticated_client_id,
                   external_resource_kind, external_resource_id, purpose,
                   knowledge_space_id, knowledge_base_id, knowledge_base_release_id,
                   state, registered_at, reference_json
               ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                reference.release_reference_id,
                reference.authenticated_client_id,
                reference.external_resource_kind,
                reference.external_resource_id,
                reference.purpose,
                reference.knowledge_space_id,
                reference.knowledge_base_id,
                reference.knowledge_base_release_id,
                reference.state,
                reference.registered_at,
                Jsonb(reference.model_dump(mode="json")),
            ),
        )
        self._connection.execute(
            """INSERT INTO knowledge_base_release_reference_commands (
                   authenticated_client_id, key_digest, fingerprint, action,
                   release_reference_id, knowledge_base_release_id, result_json
               ) VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (
                command.authenticated_client_id,
                command.key_digest,
                command.fingerprint,
                command.action,
                reference.release_reference_id,
                reference.knowledge_base_release_id,
                Jsonb(reference.model_dump(mode="json")),
            ),
        )
        return reference

    def persist_deregistration(
        self,
        reference: DeregisteredKnowledgeBaseReleaseReference,
        command: ReleaseReferenceCommand,
    ) -> DeregisteredKnowledgeBaseReleaseReference:
        updated = self._connection.execute(
            """UPDATE knowledge_base_release_references
               SET state = %s,
                   deregistration_verifier_id = %s,
                   deregistration_verification_id = %s,
                   deregistered_at = %s,
                   reference_json = %s
               WHERE release_reference_id = %s
                 AND authenticated_client_id = %s
                 AND state = 'active'""",
            (
                reference.state,
                reference.deregistration_verifier_id,
                reference.deregistration_verification_id,
                reference.deregistered_at,
                Jsonb(reference.model_dump(mode="json")),
                reference.release_reference_id,
                reference.authenticated_client_id,
            ),
        )
        if updated.rowcount != 1:
            raise ReleaseReferenceError("release_reference_not_deregisterable")
        self._connection.execute(
            """INSERT INTO knowledge_base_release_reference_commands (
                   authenticated_client_id, key_digest, fingerprint, action,
                   release_reference_id, knowledge_base_release_id, result_json
               ) VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (
                command.authenticated_client_id,
                command.key_digest,
                command.fingerprint,
                command.action,
                reference.release_reference_id,
                reference.knowledge_base_release_id,
                Jsonb(reference.model_dump(mode="json")),
            ),
        )
        return reference

    def persist_deprecation(
        self,
        result: DeprecatedKnowledgeBaseRelease,
        command: ReleaseLifecycleCommand,
    ) -> DeprecatedKnowledgeBaseRelease:
        updated = self._connection.execute(
            """UPDATE knowledge_base_releases
               SET state = 'deprecated', deprecated_at = %s
               WHERE knowledge_base_release_id = %s
                 AND knowledge_space_id = %s
                 AND knowledge_base_id = %s
                 AND state = 'queryable'""",
            (
                result.deprecated_at,
                result.knowledge_base_release_id,
                result.knowledge_space_id,
                result.knowledge_base_id,
            ),
        )
        if updated.rowcount != 1:
            raise ReleaseLifecycleError("release_lifecycle_not_deprecatable")
        self._connection.execute(
            """INSERT INTO knowledge_base_release_lifecycle_commands (
                   operator_id, key_digest, fingerprint, action,
                   knowledge_space_id, knowledge_base_id,
                   knowledge_base_release_id, recorded_at, result_json
               ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                command.operator_id,
                command.key_digest,
                command.fingerprint,
                command.action,
                result.knowledge_space_id,
                result.knowledge_base_id,
                result.knowledge_base_release_id,
                result.deprecated_at,
                Jsonb(result.model_dump(mode="json")),
            ),
        )
        return result

    def has_active_references(self, knowledge_base_release_id: str) -> bool:
        row = self._connection.execute(
            """SELECT EXISTS (
                   SELECT 1
                   FROM knowledge_base_release_references
                   WHERE knowledge_base_release_id = %s AND state = 'active'
               ) AS has_active_references""",
            (knowledge_base_release_id,),
        ).fetchone()
        if row is None:
            raise ReleaseLifecycleError("release_lifecycle_storage_unavailable")
        return bool(row["has_active_references"])

    def persist_retirement(
        self,
        result: RetiredKnowledgeBaseRelease,
        command: ReleaseLifecycleCommand,
    ) -> RetiredKnowledgeBaseRelease:
        updated = self._connection.execute(
            """UPDATE knowledge_base_releases
               SET state = 'retired', retired_at = %s
               WHERE knowledge_base_release_id = %s
                 AND knowledge_space_id = %s
                 AND knowledge_base_id = %s
                 AND state = 'deprecated'
                 AND deprecated_at = %s""",
            (
                result.retired_at,
                result.knowledge_base_release_id,
                result.knowledge_space_id,
                result.knowledge_base_id,
                result.deprecated_at,
            ),
        )
        if updated.rowcount != 1:
            raise ReleaseLifecycleError("release_lifecycle_not_retirable")
        self._connection.execute(
            """INSERT INTO knowledge_base_release_retirement_commands (
                   operator_id, key_digest, fingerprint, action,
                   knowledge_space_id, knowledge_base_id,
                   knowledge_base_release_id, retention_policy_id,
                   deprecated_at, retention_eligible_at, retired_at, result_json
               ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                command.operator_id,
                command.key_digest,
                command.fingerprint,
                command.action,
                result.knowledge_space_id,
                result.knowledge_base_id,
                result.knowledge_base_release_id,
                result.retention_policy_id,
                result.deprecated_at,
                result.retention_eligible_at,
                result.retired_at,
                Jsonb(result.model_dump(mode="json")),
            ),
        )
        return result

    def active_reference_count_for_update(self, knowledge_base_release_id: str) -> int:
        rows = self._connection.execute(
            """SELECT release_reference_id
               FROM knowledge_base_release_references
               WHERE knowledge_base_release_id = %s AND state = 'active'
               ORDER BY release_reference_id
               FOR UPDATE""",
            (knowledge_base_release_id,),
        ).fetchall()
        return len(rows)

    def persist_revocation(
        self,
        result: RevokedKnowledgeBaseRelease,
        command: ReleaseLifecycleCommand,
    ) -> RevokedKnowledgeBaseRelease:
        if (
            self.active_reference_count_for_update(result.knowledge_base_release_id)
            != result.affected_active_reference_count
        ):
            raise ReleaseLifecycleError("release_lifecycle_integrity_unavailable")
        updated = self._connection.execute(
            """UPDATE knowledge_base_releases
               SET state = 'revoked',
                   revoked_at = %s,
                   revocation_reason_code = %s
               WHERE knowledge_base_release_id = %s
                 AND knowledge_space_id = %s
                 AND knowledge_base_id = %s
                 AND state IN ('queryable', 'deprecated')""",
            (
                result.revoked_at,
                result.reason_code,
                result.knowledge_base_release_id,
                result.knowledge_space_id,
                result.knowledge_base_id,
            ),
        )
        if updated.rowcount != 1:
            raise ReleaseLifecycleError("release_lifecycle_not_revocable")
        self._connection.execute(
            """INSERT INTO knowledge_base_release_revocation_commands (
                   operator_id, key_digest, fingerprint, action,
                   knowledge_space_id, knowledge_base_id,
                   knowledge_base_release_id, reason_code,
                   affected_active_reference_count, revoked_at, result_json
               ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                command.operator_id,
                command.key_digest,
                command.fingerprint,
                command.action,
                result.knowledge_space_id,
                result.knowledge_base_id,
                result.knowledge_base_release_id,
                result.reason_code,
                result.affected_active_reference_count,
                result.revoked_at,
                Jsonb(result.model_dump(mode="json")),
            ),
        )
        return result

    def _reference_row(self, release_reference_id: str) -> dict[str, Any] | None:
        return self._connection.execute(
            """SELECT * FROM knowledge_base_release_references
               WHERE release_reference_id = %s""",
            (release_reference_id,),
        ).fetchone()


class PostgresReleaseReferenceRepository:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn.replace("postgresql+psycopg://", "postgresql://", 1)

    @classmethod
    def from_dsn(cls, dsn: str) -> "PostgresReleaseReferenceRepository":
        return cls(dsn)

    @contextmanager
    def transaction(self) -> Iterator[ReleaseReferenceTransaction]:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                yield _Transaction(connection)
        except errors.UniqueViolation as error:
            if error.diag.constraint_name == (
                "knowledge_base_release_references_external_resource_key"
            ):
                raise ReleaseReferenceError(
                    "release_reference_external_resource_conflict"
                ) from None
            raise ReleaseReferenceError("release_reference_idempotency_conflict") from None
        except errors.ForeignKeyViolation:
            raise ReleaseReferenceError("release_reference_release_not_admissible") from None
        except psycopg.Error:
            raise ReleaseReferenceError("release_reference_storage_unavailable") from None

    def get(self, release_reference_id: str) -> ReleaseReferenceState | None:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                row = connection.execute(
                    """SELECT * FROM knowledge_base_release_references
                       WHERE release_reference_id = %s""",
                    (release_reference_id,),
                ).fetchone()
        except psycopg.Error:
            raise ReleaseReferenceError("release_reference_storage_unavailable") from None
        return None if row is None else _validated_reference_row(row)

    def audit(self, knowledge_base_release_id: str) -> tuple[ReleaseReferenceAuditEntry, ...]:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                rows = connection.execute(
                    """SELECT authenticated_client_id, action, result_json
                       FROM knowledge_base_release_reference_commands
                       WHERE knowledge_base_release_id = %s
                       ORDER BY event_sequence""",
                    (knowledge_base_release_id,),
                ).fetchall()
        except psycopg.Error:
            raise ReleaseReferenceError("release_reference_storage_unavailable") from None
        events: list[ReleaseReferenceAuditEntry] = []
        for row in rows:
            reference = _reference_state(row["result_json"])
            if reference.authenticated_client_id != row["authenticated_client_id"]:
                raise ReleaseReferenceError("release_reference_integrity_unavailable")
            try:
                if isinstance(reference, KnowledgeBaseReleaseReference):
                    if row["action"] != "register":
                        raise ReleaseReferenceError("release_reference_integrity_unavailable")
                    events.append(
                        KnowledgeBaseReleaseReferenceAuditEntry(
                            action="registered",
                            authenticated_client_id=reference.authenticated_client_id,
                            release_reference_id=reference.release_reference_id,
                            knowledge_space_id=reference.knowledge_space_id,
                            knowledge_base_id=reference.knowledge_base_id,
                            knowledge_base_release_id=reference.knowledge_base_release_id,
                            external_resource_kind=reference.external_resource_kind,
                            external_resource_id=reference.external_resource_id,
                            purpose=reference.purpose,
                            recorded_at=reference.registered_at,
                        )
                    )
                else:
                    if row["action"] != "deregister":
                        raise ReleaseReferenceError("release_reference_integrity_unavailable")
                    events.append(
                        DeregisteredKnowledgeBaseReleaseReferenceAuditEntry(
                            action="deregistered",
                            authenticated_client_id=reference.authenticated_client_id,
                            release_reference_id=reference.release_reference_id,
                            knowledge_space_id=reference.knowledge_space_id,
                            knowledge_base_id=reference.knowledge_base_id,
                            knowledge_base_release_id=reference.knowledge_base_release_id,
                            external_resource_kind=reference.external_resource_kind,
                            external_resource_id=reference.external_resource_id,
                            purpose=reference.purpose,
                            deregistration_verifier_id=(reference.deregistration_verifier_id),
                            deregistration_verification_id=(
                                reference.deregistration_verification_id
                            ),
                            recorded_at=reference.deregistered_at,
                        )
                    )
            except ValueError:
                raise ReleaseReferenceError("release_reference_integrity_unavailable") from None
        return tuple(events)


class PostgresReleaseLifecycleRepository:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn.replace("postgresql+psycopg://", "postgresql://", 1)

    @classmethod
    def from_dsn(cls, dsn: str) -> "PostgresReleaseLifecycleRepository":
        return cls(dsn)

    @contextmanager
    def transaction(self) -> Iterator[ReleaseLifecycleTransaction]:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                yield _Transaction(connection)
        except errors.UniqueViolation:
            raise ReleaseLifecycleError("release_lifecycle_idempotency_conflict") from None
        except errors.ForeignKeyViolation:
            raise ReleaseLifecycleError("release_lifecycle_release_not_found") from None
        except psycopg.Error:
            raise ReleaseLifecycleError("release_lifecycle_storage_unavailable") from None

    def deletion_facts(self, knowledge_base_release_id: str) -> ReleaseDeletionFacts | None:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                row = connection.execute(
                    """SELECT release.knowledge_space_id,
                              release.knowledge_base_id,
                              release.knowledge_base_release_id,
                              release.state,
                              release.deprecated_at,
                              release.retired_at,
                              release.revoked_at,
                              release.revocation_reason_code,
                              (SELECT count(*)
                               FROM knowledge_base_release_references AS reference
                               WHERE reference.knowledge_base_release_id =
                                     release.knowledge_base_release_id
                                 AND reference.state = 'active')
                                  AS active_reference_count,
                              (SELECT count(*)
                               FROM knowledge_base_release_references AS reference
                               WHERE reference.knowledge_base_release_id =
                                     release.knowledge_base_release_id
                                 AND reference.state = 'deregistered')
                                  AS deregistered_reference_count,
                              (SELECT count(*)
                               FROM knowledge_base_release_retirement_commands AS command
                               WHERE command.knowledge_space_id =
                                     release.knowledge_space_id
                                 AND command.knowledge_base_id =
                                     release.knowledge_base_id
                                 AND command.knowledge_base_release_id =
                                     release.knowledge_base_release_id
                                 AND command.deprecated_at = release.deprecated_at
                                 AND command.retired_at = release.retired_at
                                 AND command.retention_eligible_at <= command.retired_at)
                                  AS retirement_command_count,
                              clock_timestamp() AS assessed_at
                       FROM knowledge_base_releases AS release
                       WHERE release.knowledge_base_release_id = %s""",
                    (knowledge_base_release_id,),
                ).fetchone()
        except psycopg.Error:
            raise ReleaseLifecycleError("release_lifecycle_storage_unavailable") from None
        if row is None:
            return None
        state, _deprecated_at, retired_at, revoked_at = _validated_lifecycle_row(row)
        retirement_command_count = int(row["retirement_command_count"])
        if retirement_command_count not in {0, 1}:
            raise ReleaseLifecycleError("release_lifecycle_integrity_unavailable")
        return ReleaseDeletionFacts(
            knowledge_space_id=str(row["knowledge_space_id"]),
            knowledge_base_id=str(row["knowledge_base_id"]),
            knowledge_base_release_id=str(row["knowledge_base_release_id"]),
            state=state,
            managed_retirement=(state == "retired" and retirement_command_count == 1),
            active_reference_count=int(row["active_reference_count"]),
            deregistered_reference_count=int(row["deregistered_reference_count"]),
            retired_at=retired_at,
            revoked_at=revoked_at,
            assessed_at=cast(datetime, row["assessed_at"]),
        )

    def lifecycle_audit(
        self, knowledge_base_release_id: str
    ) -> tuple[
        KnowledgeBaseReleaseLifecycleAuditEntry
        | RetiredKnowledgeBaseReleaseAuditEntry
        | RevokedKnowledgeBaseReleaseAuditEntry,
        ...,
    ]:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                rows = connection.execute(
                    """SELECT operator_id, action, knowledge_space_id,
                              knowledge_base_id, knowledge_base_release_id,
                              recorded_at, result_json
                       FROM (
                           SELECT event_sequence, operator_id, action,
                                  knowledge_space_id, knowledge_base_id,
                                  knowledge_base_release_id,
                                  recorded_at, result_json
                           FROM knowledge_base_release_lifecycle_commands
                           WHERE knowledge_base_release_id = %s
                           UNION ALL
                           SELECT event_sequence, operator_id, action,
                                  knowledge_space_id, knowledge_base_id,
                                  knowledge_base_release_id,
                                  retired_at AS recorded_at, result_json
                           FROM knowledge_base_release_retirement_commands
                           WHERE knowledge_base_release_id = %s
                           UNION ALL
                           SELECT event_sequence, operator_id, action,
                                  knowledge_space_id, knowledge_base_id,
                                  knowledge_base_release_id,
                                  revoked_at AS recorded_at, result_json
                           FROM knowledge_base_release_revocation_commands
                           WHERE knowledge_base_release_id = %s
                       ) AS lifecycle_audit
                       ORDER BY event_sequence""",
                    (
                        knowledge_base_release_id,
                        knowledge_base_release_id,
                        knowledge_base_release_id,
                    ),
                ).fetchall()
        except psycopg.Error:
            raise ReleaseLifecycleError("release_lifecycle_storage_unavailable") from None
        events: list[
            KnowledgeBaseReleaseLifecycleAuditEntry
            | RetiredKnowledgeBaseReleaseAuditEntry
            | RevokedKnowledgeBaseReleaseAuditEntry
        ] = []
        for row in rows:
            result = _lifecycle_result(row["result_json"])
            if (
                result.knowledge_space_id != row["knowledge_space_id"]
                or result.knowledge_base_id != row["knowledge_base_id"]
                or result.knowledge_base_release_id != row["knowledge_base_release_id"]
            ):
                raise ReleaseLifecycleError("release_lifecycle_integrity_unavailable")
            try:
                if isinstance(result, DeprecatedKnowledgeBaseRelease):
                    if row["action"] != "deprecate" or result.deprecated_at != row["recorded_at"]:
                        raise ReleaseLifecycleError("release_lifecycle_integrity_unavailable")
                    events.append(
                        KnowledgeBaseReleaseLifecycleAuditEntry(
                            action="deprecated",
                            operator_id=str(row["operator_id"]),
                            knowledge_space_id=result.knowledge_space_id,
                            knowledge_base_id=result.knowledge_base_id,
                            knowledge_base_release_id=result.knowledge_base_release_id,
                            recorded_at=result.deprecated_at,
                        )
                    )
                elif isinstance(result, RetiredKnowledgeBaseRelease):
                    if row["action"] != "retire" or result.retired_at != row["recorded_at"]:
                        raise ReleaseLifecycleError("release_lifecycle_integrity_unavailable")
                    events.append(
                        RetiredKnowledgeBaseReleaseAuditEntry(
                            action="retired",
                            operator_id=str(row["operator_id"]),
                            knowledge_space_id=result.knowledge_space_id,
                            knowledge_base_id=result.knowledge_base_id,
                            knowledge_base_release_id=result.knowledge_base_release_id,
                            retention_policy_id=result.retention_policy_id,
                            deprecated_at=result.deprecated_at,
                            retention_eligible_at=result.retention_eligible_at,
                            recorded_at=result.retired_at,
                        )
                    )
                else:
                    if row["action"] != "revoke" or result.revoked_at != row["recorded_at"]:
                        raise ReleaseLifecycleError("release_lifecycle_integrity_unavailable")
                    events.append(
                        RevokedKnowledgeBaseReleaseAuditEntry(
                            action="revoked",
                            operator_id=str(row["operator_id"]),
                            knowledge_space_id=result.knowledge_space_id,
                            knowledge_base_id=result.knowledge_base_id,
                            knowledge_base_release_id=result.knowledge_base_release_id,
                            reason_code=result.reason_code,
                            confirmation=result.confirmation,
                            affected_active_reference_count=(
                                result.affected_active_reference_count
                            ),
                            recorded_at=result.revoked_at,
                        )
                    )
            except ValueError:
                raise ReleaseLifecycleError("release_lifecycle_integrity_unavailable") from None
        return tuple(events)


def _validated_lifecycle_row(
    row: dict[str, Any],
) -> tuple[
    Literal["queryable", "deprecated", "retired", "revoked"],
    datetime | None,
    datetime | None,
    datetime | None,
]:
    state = row["state"]
    if state not in {"queryable", "deprecated", "retired", "revoked"}:
        raise ReleaseLifecycleError("release_lifecycle_integrity_unavailable")
    deprecated_at = cast(datetime | None, row["deprecated_at"])
    retired_at = cast(datetime | None, row["retired_at"])
    revoked_at = cast(datetime | None, row["revoked_at"])
    reason_code = row["revocation_reason_code"]
    valid = (
        (
            state == "queryable"
            and deprecated_at is None
            and retired_at is None
            and revoked_at is None
            and reason_code is None
        )
        or (
            state == "deprecated"
            and deprecated_at is not None
            and retired_at is None
            and revoked_at is None
            and reason_code is None
        )
        or (
            state == "retired"
            and revoked_at is None
            and reason_code is None
            and (
                (deprecated_at is None and retired_at is None)
                or (
                    deprecated_at is not None
                    and retired_at is not None
                    and retired_at >= deprecated_at
                )
            )
        )
        or (
            state == "revoked"
            and retired_at is None
            and revoked_at is not None
            and reason_code in {"security_incident", "severe_data_integrity_failure"}
            and (deprecated_at is None or revoked_at >= deprecated_at)
        )
    )
    if not valid:
        raise ReleaseLifecycleError("release_lifecycle_integrity_unavailable")
    return (
        cast(Literal["queryable", "deprecated", "retired", "revoked"], state),
        deprecated_at,
        retired_at,
        revoked_at,
    )


def _reference_state(value: object) -> ReleaseReferenceState:
    if isinstance(value, dict) and value.get("state") == "deregistered":
        try:
            return DeregisteredKnowledgeBaseReleaseReference.model_validate(value)
        except ValueError:
            raise ReleaseReferenceError("release_reference_integrity_unavailable") from None
    try:
        return KnowledgeBaseReleaseReference.model_validate(value)
    except ValueError:
        raise ReleaseReferenceError("release_reference_integrity_unavailable") from None


def _deprecated_release(value: object) -> DeprecatedKnowledgeBaseRelease:
    try:
        return DeprecatedKnowledgeBaseRelease.model_validate(value)
    except ValueError:
        raise ReleaseLifecycleError("release_lifecycle_integrity_unavailable") from None


def _lifecycle_result(
    value: object,
) -> DeprecatedKnowledgeBaseRelease | RetiredKnowledgeBaseRelease | RevokedKnowledgeBaseRelease:
    if isinstance(value, dict) and value.get("state") == "revoked":
        try:
            return RevokedKnowledgeBaseRelease.model_validate(value)
        except ValueError:
            raise ReleaseLifecycleError("release_lifecycle_integrity_unavailable") from None
    if isinstance(value, dict) and value.get("state") == "retired":
        try:
            return RetiredKnowledgeBaseRelease.model_validate(value)
        except ValueError:
            raise ReleaseLifecycleError("release_lifecycle_integrity_unavailable") from None
    return _deprecated_release(value)


def _validated_reference_row(row: dict[str, Any]) -> ReleaseReferenceState:
    reference = _reference_state(row["reference_json"])
    if (
        reference.release_reference_id != row["release_reference_id"]
        or reference.authenticated_client_id != row["authenticated_client_id"]
        or reference.external_resource_kind != row["external_resource_kind"]
        or reference.external_resource_id != row["external_resource_id"]
        or reference.purpose != row["purpose"]
        or reference.knowledge_space_id != row["knowledge_space_id"]
        or reference.knowledge_base_id != row["knowledge_base_id"]
        or reference.knowledge_base_release_id != row["knowledge_base_release_id"]
        or reference.state != row["state"]
        or reference.registered_at != row["registered_at"]
    ):
        raise ReleaseReferenceError("release_reference_integrity_unavailable")
    if isinstance(reference, KnowledgeBaseReleaseReference):
        if (
            row["deregistration_verifier_id"] is not None
            or row["deregistration_verification_id"] is not None
            or row["deregistered_at"] is not None
        ):
            raise ReleaseReferenceError("release_reference_integrity_unavailable")
    elif (
        reference.deregistration_verifier_id != row["deregistration_verifier_id"]
        or reference.deregistration_verification_id != row["deregistration_verification_id"]
        or reference.deregistered_at != row["deregistered_at"]
    ):
        raise ReleaseReferenceError("release_reference_integrity_unavailable")
    return reference


def _same_reference_identity(
    left: ReleaseReferenceState,
    right: ReleaseReferenceState,
) -> bool:
    return (
        left.release_reference_id == right.release_reference_id
        and left.authenticated_client_id == right.authenticated_client_id
        and left.external_resource_kind == right.external_resource_kind
        and left.external_resource_id == right.external_resource_id
        and left.purpose == right.purpose
        and left.knowledge_space_id == right.knowledge_space_id
        and left.knowledge_base_id == right.knowledge_base_id
        and left.knowledge_base_release_id == right.knowledge_base_release_id
        and left.registered_at == right.registered_at
    )
