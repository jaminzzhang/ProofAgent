"""Durable Draft CAS, exact Base plans and queued preparation admission."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg import errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import TypeAdapter, ValidationError

from knowledge_source_service.contracts.base_preparations import (
    BasePreparationAuditEntry,
    BasePreparationRejectionEntry,
    CancelledReleasePreparation,
    ConsumedReleasePreparation,
    ExpiredReleasePreparation,
    FailedReleasePreparation,
    KnowledgeBaseDraft,
    KnowledgeBaseVersion,
    QueuedReleasePreparation,
    ReadyReleasePreparation,
    ReleasePreparationResource,
    PreparationPublicationAuditEntry,
    PreparationWorkerAuditEntry,
)
from knowledge_source_service.domain.base_preparations import (
    BasePreparationCommand,
    BasePreparationError,
    BasePreparationResult,
    ReadySourceVersion,
    PreparationClaim,
    cancel_preparation,
    consume_ready_preparation,
    expire_ready_preparation,
    preparation_admission,
    validate_prepared_candidate,
    validate_publishable_candidate,
)
from knowledge_source_service.domain.identities import content_identifier, sha256_json
from knowledge_source_service.domain.publications import (
    PreparedKnowledgeBaseRelease,
    PublishedKnowledgeBaseRelease,
)
from knowledge_source_service.ports.base_preparations import BasePreparationTransaction
from knowledge_source_service.adapters.postgres.knowledge_catalog import (
    KnowledgeCatalogConflict,
    KnowledgeCatalogIntegrityError,
    exact_release_history_matches,
    put_exact_release,
)


_RESOURCE: TypeAdapter[ReleasePreparationResource] = TypeAdapter(ReleasePreparationResource)
_CANDIDATE: TypeAdapter[PreparedKnowledgeBaseRelease] = TypeAdapter(PreparedKnowledgeBaseRelease)


class _Transaction:
    def __init__(self, connection: psycopg.Connection[dict[str, Any]]) -> None:
        self._connection = connection

    def base_space(self, base_id: str) -> str | None:
        row = self._connection.execute(
            "SELECT knowledge_space_id FROM knowledge_bases WHERE knowledge_base_id = %s",
            (base_id,),
        ).fetchone()
        return None if row is None else str(row["knowledge_space_id"])

    def source_space(self, source_id: str) -> str | None:
        row = self._connection.execute(
            "SELECT knowledge_space_id FROM knowledge_sources WHERE knowledge_source_id = %s",
            (source_id,),
        ).fetchone()
        return None if row is None else str(row["knowledge_space_id"])

    def get_draft(self, base_id: str, revision: int | None = None) -> KnowledgeBaseDraft | None:
        if revision is None:
            # Serialize both first creation and later saves/starts against the existing
            # Base, before reading its Draft head. READ COMMITTED gets a fresh snapshot
            # after a waiting writer finishes; historical revisions are immutable.
            self._connection.execute(
                "SELECT knowledge_base_id FROM knowledge_bases WHERE knowledge_base_id = %s FOR UPDATE",
                (base_id,),
            ).fetchone()
        row = self._connection.execute(
            """SELECT draft_json FROM knowledge_base_drafts
               WHERE knowledge_base_id = %s AND (%s::bigint IS NULL OR revision = %s)
               ORDER BY revision DESC LIMIT 1""",
            (base_id, revision, revision),
        ).fetchone()
        if row is None:
            return None
        draft = _draft(row["draft_json"])
        if draft.knowledge_base_id != base_id or (
            revision is not None and draft.revision != revision
        ):
            raise BasePreparationError("base_preparation_integrity_unavailable")
        return draft

    def put_draft(self, draft: KnowledgeBaseDraft) -> None:
        try:
            self._connection.execute(
                """INSERT INTO knowledge_base_drafts
                   (knowledge_base_id, knowledge_space_id, revision, draft_digest, draft_json)
                   VALUES (%s, %s, %s, %s, %s)""",
                (
                    draft.knowledge_base_id,
                    draft.knowledge_space_id,
                    draft.revision,
                    draft.draft_digest,
                    Jsonb(draft.model_dump(mode="json")),
                ),
            )
        except errors.UniqueViolation:
            raise BasePreparationError("base_draft_revision_conflict") from None

    def ready_versions(
        self, *, knowledge_space_id: str, knowledge_source_ids: tuple[str, ...]
    ) -> tuple[ReadySourceVersion, ...]:
        # One SQL snapshot for every selected Source; no per-Source network/catalog reads.
        rows = self._connection.execute(
            """SELECT knowledge_space_id, knowledge_source_id, knowledge_source_version_id, created_at
               FROM knowledge_source_versions
               WHERE knowledge_space_id = %s AND knowledge_source_id = ANY(%s)""",
            (knowledge_space_id, list(knowledge_source_ids)),
        ).fetchall()
        return tuple(
            ReadySourceVersion(
                knowledge_space_id=row["knowledge_space_id"],
                knowledge_source_id=row["knowledge_source_id"],
                knowledge_source_version_id=row["knowledge_source_version_id"],
                ready_at=row["created_at"],
            )
            for row in rows
        )

    def get_preparation(self, preparation_id: str) -> ReleasePreparationResource | None:
        row = self._connection.execute(
            "SELECT * FROM knowledge_release_preparations WHERE release_preparation_id = %s",
            (preparation_id,),
        ).fetchone()
        if row is None:
            return None
        preparation = _RESOURCE.validate_python(row["resource_json"])
        version = preparation.base_version
        stored = self._connection.execute(
            "SELECT version_json FROM knowledge_base_versions WHERE knowledge_base_version_id = %s",
            (version.knowledge_base_version_id,),
        ).fetchone()
        members = self._connection.execute(
            """SELECT knowledge_source_id, knowledge_source_version_id FROM knowledge_base_version_members
               WHERE knowledge_base_version_id = %s ORDER BY ordinal""",
            (version.knowledge_base_version_id,),
        ).fetchall()
        digest = sha256_json(
            {
                "space": version.knowledge_space_id,
                "base": version.knowledge_base_id,
                "source_versions": tuple(
                    member.knowledge_source_version_id for member in version.members
                ),
            }
        )
        if (
            stored is None
            or KnowledgeBaseVersion.model_validate(stored["version_json"]) != version
            or members != [member.model_dump(mode="json") for member in version.members]
            or version.plan_digest != digest
            or version.knowledge_base_version_id != content_identifier("base-version", digest)
            or (preparation.knowledge_space_id, preparation.knowledge_base_id)
            != (version.knowledge_space_id, version.knowledge_base_id)
        ):
            raise BasePreparationError("base_preparation_integrity_unavailable")
        draft = self.get_draft(preparation.knowledge_base_id, preparation.draft_revision)
        if (
            draft is None
            or draft.draft_digest != preparation.draft_digest
            or draft.knowledge_space_id != preparation.knowledge_space_id
            or len(draft.members) != len(version.members)
            or any(
                selected.knowledge_source_id != resolved.knowledge_source_id
                or (
                    selected.selection == "exact"
                    and selected.knowledge_source_version_id != resolved.knowledge_source_version_id
                )
                for selected, resolved in zip(draft.members, version.members, strict=True)
            )
        ):
            raise BasePreparationError("base_preparation_integrity_unavailable")
        if isinstance(
            preparation,
            (ReadyReleasePreparation, ExpiredReleasePreparation, ConsumedReleasePreparation),
        ):
            candidate = self._candidate(row, preparation)
            if row["candidate_expires_at"] != preparation.expires_at:
                raise BasePreparationError("base_preparation_integrity_unavailable")
            if isinstance(preparation, ReadyReleasePreparation):
                valid_state = (
                    row["terminal_at"] == preparation.completed_at
                    and row["consumed_at"] is None
                    and row["expired_at"] is None
                    and row["published_release_id"] is None
                )
            elif isinstance(preparation, ExpiredReleasePreparation):
                valid_state = (
                    row["terminal_at"] == preparation.expired_at
                    and row["expired_at"] == preparation.expired_at
                    and row["consumed_at"] is None
                    and row["published_release_id"] is None
                    and preparation.expired_at >= preparation.expires_at
                )
            else:
                publication = PublishedKnowledgeBaseRelease(
                    release=candidate.release,
                    release_manifest_artifact=candidate.release_manifest_artifact,
                )
                valid_state = (
                    row["terminal_at"] == preparation.consumed_at
                    and row["consumed_at"] == preparation.consumed_at
                    and row["expired_at"] is None
                    and row["published_release_id"] == preparation.knowledge_base_release_id
                    and preparation.consumed_at < preparation.expires_at
                    and exact_release_history_matches(self._connection, publication)
                )
            if not valid_state:
                raise BasePreparationError("base_preparation_integrity_unavailable")
        elif (
            row["candidate_json"] is not None
            or row["published_release_id"] is not None
            or (
                isinstance(preparation, FailedReleasePreparation)
                and row["terminal_at"] != preparation.failed_at
            )
            or (
                isinstance(preparation, CancelledReleasePreparation)
                and (
                    row["terminal_at"] != preparation.cancelled_at
                    or row["cancelled_at"] != preparation.cancelled_at
                )
            )
        ):
            raise BasePreparationError("base_preparation_integrity_unavailable")
        return preparation

    def _candidate(
        self,
        row: dict[str, Any],
        preparation: ReadyReleasePreparation
        | ExpiredReleasePreparation
        | ConsumedReleasePreparation,
    ) -> PreparedKnowledgeBaseRelease:
        try:
            candidate = _CANDIDATE.validate_python(row["candidate_json"])
            validate_publishable_candidate(preparation_admission(preparation), candidate)
        except (ValidationError, ValueError):
            raise BasePreparationError("base_preparation_integrity_unavailable") from None
        if (
            candidate.release.knowledge_base_release_id != preparation.knowledge_base_release_id
            or candidate.release.release_manifest_digest != preparation.release_manifest_digest
        ):
            raise BasePreparationError("base_preparation_integrity_unavailable")
        return candidate

    def put_preparation(self, preparation: QueuedReleasePreparation) -> None:
        version = preparation.base_version
        inserted = self._connection.execute(
            """INSERT INTO knowledge_base_versions
               (knowledge_base_version_id, knowledge_space_id, knowledge_base_id, plan_digest, version_json)
               VALUES (%s, %s, %s, %s, %s) ON CONFLICT (knowledge_base_version_id) DO NOTHING
               RETURNING knowledge_base_version_id""",
            (
                version.knowledge_base_version_id,
                version.knowledge_space_id,
                version.knowledge_base_id,
                version.plan_digest,
                Jsonb(version.model_dump(mode="json")),
            ),
        ).fetchone()
        if inserted is not None:
            for ordinal, member in enumerate(version.members):
                self._connection.execute(
                    """INSERT INTO knowledge_base_version_members
                       (knowledge_base_version_id, knowledge_space_id, ordinal, knowledge_source_id, knowledge_source_version_id)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (
                        version.knowledge_base_version_id,
                        version.knowledge_space_id,
                        ordinal,
                        member.knowledge_source_id,
                        member.knowledge_source_version_id,
                    ),
                )
        else:
            existing = self._connection.execute(
                "SELECT version_json FROM knowledge_base_versions WHERE knowledge_base_version_id = %s",
                (version.knowledge_base_version_id,),
            ).fetchone()
            if existing is None or existing["version_json"] != version.model_dump(mode="json"):
                raise BasePreparationError("base_version_identity_conflict")
        try:
            self._connection.execute(
                """INSERT INTO knowledge_release_preparations
                   (release_preparation_id, knowledge_space_id, knowledge_base_id, draft_revision,
                    draft_digest, knowledge_base_version_id, state, submitted_at, resource_json)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    preparation.release_preparation_id,
                    preparation.knowledge_space_id,
                    preparation.knowledge_base_id,
                    preparation.draft_revision,
                    preparation.draft_digest,
                    version.knowledge_base_version_id,
                    preparation.state,
                    preparation.submitted_at,
                    Jsonb(preparation.model_dump(mode="json")),
                ),
            )
        except errors.UniqueViolation:
            raise BasePreparationError("base_preparation_identity_conflict") from None

    def replay(self, command: BasePreparationCommand) -> BasePreparationResult | None:
        self._connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"kss-base-preparation:{command.operator_id}:{command.key_digest}",),
        )
        row = self._connection.execute(
            """SELECT * FROM knowledge_base_preparation_commands
               WHERE operator_id = %s AND key_digest = %s""",
            (command.operator_id, command.key_digest),
        ).fetchone()
        if row is None:
            return None
        if row["fingerprint"] != command.fingerprint or row["action"] != command.action:
            raise BasePreparationError("base_preparation_idempotency_conflict")
        return self._receipt_result(row)

    def _receipt_result(self, row: dict[str, Any]) -> BasePreparationResult:
        result = _result(row["action"], row["result_json"])
        if isinstance(result, KnowledgeBaseDraft):
            stored: KnowledgeBaseDraft | ReleasePreparationResource | None = self.get_draft(
                row["knowledge_base_id"], row["draft_revision"]
            )
        else:
            stored = self.get_preparation(row["release_preparation_id"])
            if stored is not None and isinstance(result, QueuedReleasePreparation):
                stored = preparation_admission(stored)
        if result != stored:
            raise BasePreparationError("base_preparation_integrity_unavailable")
        return result

    def record(self, command: BasePreparationCommand, result: BasePreparationResult) -> None:
        self._connection.execute(
            """INSERT INTO knowledge_base_preparation_commands
               (operator_id, key_digest, fingerprint, action, knowledge_base_id, draft_revision,
                release_preparation_id, result_json) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                command.operator_id,
                command.key_digest,
                command.fingerprint,
                command.action,
                result.knowledge_base_id,
                result.revision
                if isinstance(result, KnowledgeBaseDraft)
                else result.draft_revision,
                None if isinstance(result, KnowledgeBaseDraft) else result.release_preparation_id,
                Jsonb(result.model_dump(mode="json")),
            ),
        )

    def audit(self, base_id: str) -> tuple[BasePreparationAuditEntry, ...]:
        rows = self._connection.execute(
            """SELECT * FROM knowledge_base_preparation_commands
               WHERE knowledge_base_id = %s ORDER BY event_sequence""",
            (base_id,),
        ).fetchall()
        events = []
        for row in rows:
            result = self._receipt_result(row)
            events.append(
                BasePreparationAuditEntry(
                    action=row["action"],
                    operator_id=row["operator_id"],
                    knowledge_space_id=result.knowledge_space_id,
                    knowledge_base_id=result.knowledge_base_id,
                    draft_revision=result.revision
                    if isinstance(result, KnowledgeBaseDraft)
                    else result.draft_revision,
                    draft_digest=result.draft_digest,
                    release_preparation_id=None
                    if isinstance(result, KnowledgeBaseDraft)
                    else result.release_preparation_id,
                    knowledge_base_version_id=None
                    if isinstance(result, KnowledgeBaseDraft)
                    else result.base_version.knowledge_base_version_id,
                    recorded_at=result.updated_at
                    if isinstance(result, KnowledgeBaseDraft)
                    else result.cancelled_at
                    if isinstance(result, CancelledReleasePreparation)
                    else result.submitted_at,
                )
            )
        return tuple(events)

    def cancel_preparation(self, preparation_id: str) -> CancelledReleasePreparation:
        row = self._connection.execute(
            "SELECT release_preparation_id FROM knowledge_release_preparations "
            "WHERE release_preparation_id = %s FOR UPDATE",
            (preparation_id,),
        ).fetchone()
        if row is None:
            raise BasePreparationError("base_preparation_not_found")
        resource = self.get_preparation(preparation_id)
        if resource is None:
            raise BasePreparationError("base_preparation_integrity_unavailable")
        cancelled = cancel_preparation(resource, cancelled_at=self._database_time())
        self._connection.execute(
            """UPDATE knowledge_release_preparations
               SET state = 'cancelled', resource_json = %s, terminal_at = %s,
                   cancelled_at = %s, lease_worker_id = NULL, lease_expires_at = NULL
               WHERE release_preparation_id = %s""",
            (
                Jsonb(cancelled.model_dump(mode="json")),
                cancelled.cancelled_at,
                cancelled.cancelled_at,
                preparation_id,
            ),
        )
        return cancelled

    def record_rejection(self, event: BasePreparationRejectionEntry) -> None:
        self._connection.execute(
            "INSERT INTO knowledge_base_preparation_rejections (knowledge_base_id, event_json) VALUES (%s, %s)",
            (event.knowledge_base_id, Jsonb(event.model_dump(mode="json"))),
        )

    def rejections(self, base_id: str) -> tuple[BasePreparationRejectionEntry, ...]:
        rows = self._connection.execute(
            "SELECT event_json FROM knowledge_base_preparation_rejections WHERE knowledge_base_id = %s ORDER BY event_sequence",
            (base_id,),
        ).fetchall()
        return tuple(
            BasePreparationRejectionEntry.model_validate(row["event_json"]) for row in rows
        )

    def claim_next(self, worker_id: str, lease_duration: timedelta) -> PreparationClaim | None:
        row = self._connection.execute(
            """SELECT release_preparation_id, state, lease_fencing_token
               FROM knowledge_release_preparations
               WHERE state = 'queued' OR (state = 'running' AND lease_expires_at <= clock_timestamp())
               ORDER BY submitted_at, release_preparation_id
               FOR UPDATE SKIP LOCKED LIMIT 1"""
        ).fetchone()
        if row is None:
            return None
        resource = self.get_preparation(row["release_preparation_id"])
        if resource is None:
            raise BasePreparationError("base_preparation_integrity_unavailable")
        admission = preparation_admission(resource)
        now = self._database_time()
        claim = PreparationClaim(
            admission=admission,
            worker_id=worker_id,
            fencing_token=row["lease_fencing_token"] + 1,
            lease_expires_at=now + lease_duration,
        )
        self._connection.execute(
            """UPDATE knowledge_release_preparations SET state = 'running',
               resource_json = jsonb_set(resource_json, '{state}', '"running"'),
               lease_worker_id = %s, lease_fencing_token = %s, lease_expires_at = %s
               WHERE release_preparation_id = %s""",
            (
                worker_id,
                claim.fencing_token,
                claim.lease_expires_at,
                admission.release_preparation_id,
            ),
        )
        self._record_worker_event(
            claim, "claimed" if row["state"] == "queued" else "taken_over", now
        )
        return claim

    def _record_worker_event(self, claim: PreparationClaim, action: str, now: datetime) -> None:
        event = PreparationWorkerAuditEntry.model_validate(
            {
                "action": action,
                "knowledge_space_id": claim.admission.knowledge_space_id,
                "knowledge_base_id": claim.admission.knowledge_base_id,
                "release_preparation_id": claim.admission.release_preparation_id,
                "worker_id": claim.worker_id,
                "fencing_token": claim.fencing_token,
                "lease_expires_at": claim.lease_expires_at,
                "recorded_at": now,
            }
        )
        self._connection.execute(
            """INSERT INTO knowledge_preparation_worker_events
               (release_preparation_id, knowledge_base_id, event_json) VALUES (%s, %s, %s)""",
            (
                event.release_preparation_id,
                event.knowledge_base_id,
                Jsonb(event.model_dump(mode="json")),
            ),
        )

    def renew_claim(self, claim: PreparationClaim, lease_duration: timedelta) -> PreparationClaim:
        row = self._connection.execute(
            "SELECT * FROM knowledge_release_preparations WHERE release_preparation_id = %s FOR UPDATE",
            (claim.admission.release_preparation_id,),
        ).fetchone()
        if row is None or row["state"] != "running":
            raise BasePreparationError("base_preparation_stale_claim")
        resource = self.get_preparation(claim.admission.release_preparation_id)
        now = self._database_time()
        if (
            row["lease_worker_id"] != claim.worker_id
            or row["lease_fencing_token"] != claim.fencing_token
            or now >= row["lease_expires_at"]
            or resource is None
            or preparation_admission(resource) != claim.admission
        ):
            raise BasePreparationError("base_preparation_stale_claim")
        renewed = claim.model_copy(
            update={"lease_expires_at": max(row["lease_expires_at"], now + lease_duration)}
        )
        self._connection.execute(
            "UPDATE knowledge_release_preparations SET lease_expires_at = %s WHERE release_preparation_id = %s",
            (renewed.lease_expires_at, claim.admission.release_preparation_id),
        )
        self._record_worker_event(renewed, "renewed", now)
        return renewed

    def complete_claim(
        self,
        claim: PreparationClaim,
        candidate: PreparedKnowledgeBaseRelease,
        candidate_ttl: timedelta,
    ) -> ReadyReleasePreparation:
        row, resource, now = self._lock_current_claim(claim)
        validate_prepared_candidate(claim.admission, candidate)
        release = candidate.release
        ready = ReadyReleasePreparation.model_validate(
            {
                **claim.admission.model_dump(mode="python"),
                "state": "ready",
                "knowledge_base_release_id": release.knowledge_base_release_id,
                "release_manifest_digest": release.release_manifest_digest,
                "completed_at": now,
                "expires_at": now + candidate_ttl,
            }
        )
        self._connection.execute(
            """UPDATE knowledge_release_preparations
               SET state = 'ready', resource_json = %s, candidate_json = %s,
                   terminal_at = %s, candidate_expires_at = %s,
                   lease_worker_id = NULL, lease_expires_at = NULL
               WHERE release_preparation_id = %s""",
            (
                Jsonb(ready.model_dump(mode="json")),
                Jsonb(asdict(candidate)),
                ready.completed_at,
                ready.expires_at,
                claim.admission.release_preparation_id,
            ),
        )
        self._record_worker_event(claim, "ready", now)
        return ready

    def fail_claim(self, claim: PreparationClaim, failure_code: str) -> FailedReleasePreparation:
        _row, _resource, now = self._lock_current_claim(claim)
        failed = FailedReleasePreparation.model_validate(
            {
                **claim.admission.model_dump(mode="python"),
                "state": "failed",
                "failure_code": failure_code,
                "failed_at": now,
            }
        )
        self._connection.execute(
            """UPDATE knowledge_release_preparations
               SET state = 'failed', resource_json = %s, terminal_at = %s,
                   lease_worker_id = NULL, lease_expires_at = NULL
               WHERE release_preparation_id = %s""",
            (
                Jsonb(failed.model_dump(mode="json")),
                failed.failed_at,
                claim.admission.release_preparation_id,
            ),
        )
        self._record_worker_event(claim, "failed", now)
        return failed

    def publish_ready(
        self, preparation_id: str, operator_id: str
    ) -> ConsumedReleasePreparation | ExpiredReleasePreparation:
        row = self._connection.execute(
            "SELECT * FROM knowledge_release_preparations WHERE release_preparation_id = %s FOR UPDATE",
            (preparation_id,),
        ).fetchone()
        if row is None:
            raise BasePreparationError("base_preparation_not_found")
        resource = self.get_preparation(preparation_id)
        if not isinstance(resource, ReadyReleasePreparation):
            raise BasePreparationError("base_preparation_not_ready")
        candidate = self._candidate(row, resource)
        now = self._database_time()
        if now >= resource.expires_at:
            return self._expire_ready(resource, operator_id, expired_at=now)

        publication = PublishedKnowledgeBaseRelease(
            release=candidate.release,
            release_manifest_artifact=candidate.release_manifest_artifact,
        )
        try:
            put_exact_release(self._connection, publication)
        except KnowledgeCatalogConflict:
            raise BasePreparationError("base_preparation_release_conflict") from None
        except (KnowledgeCatalogIntegrityError, errors.ForeignKeyViolation):
            raise BasePreparationError("base_preparation_integrity_unavailable") from None
        consumed = consume_ready_preparation(resource, consumed_at=now)
        self._connection.execute(
            """UPDATE knowledge_release_preparations
               SET state = 'consumed', resource_json = %s, terminal_at = %s,
                   consumed_at = %s, published_release_id = %s
               WHERE release_preparation_id = %s""",
            (
                Jsonb(consumed.model_dump(mode="json")),
                consumed.consumed_at,
                consumed.consumed_at,
                consumed.knowledge_base_release_id,
                preparation_id,
            ),
        )
        self._record_publication_event(consumed, operator_id)
        return consumed

    def expire_next(self, operator_id: str) -> ExpiredReleasePreparation | None:
        row = self._connection.execute(
            """SELECT * FROM knowledge_release_preparations
               WHERE state = 'ready' AND candidate_expires_at <= clock_timestamp()
               ORDER BY candidate_expires_at, release_preparation_id
               FOR UPDATE SKIP LOCKED LIMIT 1"""
        ).fetchone()
        if row is None:
            return None
        preparation_id = str(row["release_preparation_id"])
        resource = self.get_preparation(preparation_id)
        if not isinstance(resource, ReadyReleasePreparation):
            raise BasePreparationError("base_preparation_integrity_unavailable")
        now = self._database_time()
        if now < resource.expires_at:
            return None
        return self._expire_ready(resource, operator_id, expired_at=now)

    def _expire_ready(
        self,
        resource: ReadyReleasePreparation,
        operator_id: str,
        *,
        expired_at: datetime,
    ) -> ExpiredReleasePreparation:
        expired = expire_ready_preparation(resource, expired_at=expired_at)
        self._connection.execute(
            """UPDATE knowledge_release_preparations
               SET state = 'expired', resource_json = %s, terminal_at = %s,
                   expired_at = %s
               WHERE release_preparation_id = %s""",
            (
                Jsonb(expired.model_dump(mode="json")),
                expired.expired_at,
                expired.expired_at,
                resource.release_preparation_id,
            ),
        )
        self._record_publication_event(expired, operator_id)
        return expired

    def _record_publication_event(
        self,
        preparation: ConsumedReleasePreparation | ExpiredReleasePreparation,
        operator_id: str,
    ) -> None:
        recorded_at = (
            preparation.consumed_at
            if isinstance(preparation, ConsumedReleasePreparation)
            else preparation.expired_at
        )
        event = PreparationPublicationAuditEntry(
            action=preparation.state,
            operator_id=operator_id,
            knowledge_space_id=preparation.knowledge_space_id,
            knowledge_base_id=preparation.knowledge_base_id,
            release_preparation_id=preparation.release_preparation_id,
            knowledge_base_release_id=preparation.knowledge_base_release_id,
            release_manifest_digest=preparation.release_manifest_digest,
            recorded_at=recorded_at,
        )
        self._connection.execute(
            """INSERT INTO knowledge_preparation_publication_events
               (release_preparation_id, knowledge_base_id, action, recorded_at, event_json)
               VALUES (%s, %s, %s, %s, %s)""",
            (
                event.release_preparation_id,
                event.knowledge_base_id,
                event.action,
                event.recorded_at,
                Jsonb(event.model_dump(mode="json")),
            ),
        )

    def publication_audit(self, base_id: str) -> tuple[PreparationPublicationAuditEntry, ...]:
        rows = self._connection.execute(
            """SELECT event_json FROM knowledge_preparation_publication_events
               WHERE knowledge_base_id = %s ORDER BY event_sequence""",
            (base_id,),
        ).fetchall()
        return tuple(
            PreparationPublicationAuditEntry.model_validate(row["event_json"]) for row in rows
        )

    def _lock_current_claim(
        self, claim: PreparationClaim
    ) -> tuple[dict[str, Any], ReleasePreparationResource, datetime]:
        row = self._connection.execute(
            "SELECT * FROM knowledge_release_preparations WHERE release_preparation_id = %s FOR UPDATE",
            (claim.admission.release_preparation_id,),
        ).fetchone()
        if row is None or row["state"] != "running":
            raise BasePreparationError("base_preparation_stale_claim")
        resource = self.get_preparation(claim.admission.release_preparation_id)
        now = self._database_time()
        if (
            row["lease_worker_id"] != claim.worker_id
            or row["lease_fencing_token"] != claim.fencing_token
            or now >= row["lease_expires_at"]
            or resource is None
            or preparation_admission(resource) != claim.admission
        ):
            raise BasePreparationError("base_preparation_stale_claim")
        return row, resource, now

    def worker_audit(self, base_id: str) -> tuple[PreparationWorkerAuditEntry, ...]:
        rows = self._connection.execute(
            "SELECT event_json FROM knowledge_preparation_worker_events WHERE knowledge_base_id = %s ORDER BY event_sequence",
            (base_id,),
        ).fetchall()
        return tuple(PreparationWorkerAuditEntry.model_validate(row["event_json"]) for row in rows)

    def _database_time(self) -> datetime:
        row = self._connection.execute("SELECT clock_timestamp() AS now").fetchone()
        if row is None:
            raise BasePreparationError("base_preparation_storage_unavailable")
        now: datetime = row["now"]
        return now


def _result(action: str, payload: object) -> BasePreparationResult:
    if action == "save_draft":
        return _draft(payload)
    if action == "start":
        return QueuedReleasePreparation.model_validate(payload)
    if action == "cancel":
        return CancelledReleasePreparation.model_validate(payload)
    raise BasePreparationError("base_preparation_integrity_unavailable")


def _draft(payload: object) -> KnowledgeBaseDraft:
    draft = KnowledgeBaseDraft.model_validate(payload)
    digest = sha256_json(
        draft.model_dump(mode="json", exclude={"revision", "draft_digest", "updated_at"})
    )
    if draft.draft_digest != digest:
        raise BasePreparationError("base_preparation_integrity_unavailable")
    return draft


class PostgresBasePreparationRepository:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn.replace("postgresql+psycopg://", "postgresql://", 1)

    @classmethod
    def from_dsn(cls, dsn: str) -> "PostgresBasePreparationRepository":
        return cls(dsn)

    @contextmanager
    def transaction(self) -> Iterator[BasePreparationTransaction]:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                connection.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
                connection.execute("SET LOCAL lock_timeout = '5s'")
                connection.execute("SET LOCAL statement_timeout = '15s'")
                yield _Transaction(connection)
        except errors.ForeignKeyViolation:
            raise BasePreparationError("base_scope_mismatch") from None
        except ValidationError:
            raise BasePreparationError("base_preparation_integrity_unavailable") from None
        except psycopg.Error:
            raise BasePreparationError("base_preparation_storage_unavailable") from None
