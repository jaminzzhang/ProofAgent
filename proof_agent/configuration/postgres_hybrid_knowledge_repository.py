"""PostgreSQL authority adapter for fenced Hybrid Knowledge publication."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import json
from typing import Any, Iterator, cast
from uuid import uuid4

from proof_agent.capabilities.knowledge.hybrid.publication import (
    HybridPublicationRequest,
    HybridPublicationValidationAuthority,
    PublicationCommit,
    PublicationConflict,
    PublicationAuthorityContext,
)
from proof_agent.capabilities.knowledge.hybrid.manifest import (
    PersistedRuleUnitManifestShard,
    RuleUnitManifestMaterialization,
)
from proof_agent.capabilities.knowledge.hybrid.versioning import stable_digest
from proof_agent.capabilities.knowledge.hybrid.ports import (
    ProjectionAuthorityDocument,
    SearchIndexIdentity,
)
from proof_agent.capabilities.knowledge.hybrid.recovery import (
    GenerationRebuildAuthority,
    OrphanProjection,
    RebuildProjectionAuthority,
    RetainedManifestAuthority,
)
from proof_agent.contracts.knowledge_index import (
    ExactArtifactRef,
    HybridKnowledgePublicationRecord,
    KnowledgeIndexGeneration,
    KnowledgeProjectionAttestation,
    KnowledgePublicationAttempt,
    RuleUnitManifestEntry,
    RuleUnitManifestRoot,
    RuleUnitManifestShard,
)
from proof_agent.contracts.insurance_rules import (
    ApprovedInsuranceRuleMetadataRevision,
    InsuranceRuleUnitRevision,
)


class PostgresHybridKnowledgeRepository:
    """Short-transaction implementation; network projection never occurs here."""

    def __init__(self, *, pool: Any) -> None:
        self._pool = pool

    def close(self) -> None:
        close = getattr(self._pool, "close", None)
        if close is not None:
            close()

    @classmethod
    def from_dsn(cls, dsn: str) -> PostgresHybridKnowledgeRepository:
        try:
            from psycopg_pool import ConnectionPool
        except ImportError as exc:  # pragma: no cover - optional production dependency
            raise RuntimeError(
                "Hybrid PostgreSQL authority requires the 'production' extra"
            ) from exc
        return cls(pool=ConnectionPool(dsn, min_size=1, max_size=4, open=True))

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        with self._pool.connection() as connection:
            with connection.transaction():
                yield connection

    def register_source(
        self,
        *,
        source_id: str,
        source_draft_version_id: str,
        candidate_digest: str,
        generation: KnowledgeIndexGeneration,
    ) -> None:
        now = datetime.now(UTC)
        generation_json = _canonical_json(generation.model_dump(mode="json"))
        generation_digest = stable_digest(generation.model_dump(mode="json"))
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO hybrid_knowledge_source_authority
                  (source_id, draft_version_id, candidate_digest, updated_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (source_id) DO NOTHING
                """,
                (source_id, source_draft_version_id, candidate_digest, now),
            )
            connection.execute(
                """
                INSERT INTO hybrid_knowledge_generation
                  (generation_id, source_id, identity_digest, mapping_sha256,
                   generation_json, created_at)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                ON CONFLICT (generation_id) DO NOTHING
                """,
                (
                    generation.generation_id,
                    source_id,
                    generation_digest,
                    generation.mapping_sha256,
                    generation_json,
                    now,
                ),
            )

    def register_validation(self, validation: HybridPublicationValidationAuthority) -> None:
        """Persist a trusted passed validation before a publication can claim it."""

        payload = validation.model_dump(mode="python")
        with self._connection() as connection:
            inserted = connection.execute(
                """
                INSERT INTO hybrid_knowledge_publication_validation
                  (validation_id, source_id, source_draft_version_id,
                   candidate_digest, generation_id, status, validated_at, validated_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (validation_id) DO NOTHING
                RETURNING validation_id
                """,
                (
                    validation.validation_id,
                    validation.source_id,
                    validation.source_draft_version_id,
                    validation.candidate_digest,
                    validation.generation_id,
                    validation.status,
                    validation.validated_at,
                    validation.validated_by,
                ),
            ).fetchone()
            if inserted is not None:
                return
            existing = connection.execute(
                """
                SELECT validation_id, source_id, source_draft_version_id,
                       candidate_digest, generation_id, status,
                       validated_at, validated_by
                  FROM hybrid_knowledge_publication_validation
                 WHERE validation_id = %s
                """,
                (validation.validation_id,),
            ).fetchone()
            if existing is None:
                raise PublicationConflict("VALIDATION_CONFLICT")
            stored = HybridPublicationValidationAuthority(
                validation_id=existing[0],
                source_id=existing[1],
                source_draft_version_id=existing[2],
                candidate_digest=existing[3],
                generation_id=existing[4],
                status=existing[5],
                validated_at=existing[6],
                validated_by=existing[7],
            )
            if stored.model_dump(mode="python") != payload:
                raise PublicationConflict("VALIDATION_CONFLICT")

    def advance_source_candidate(
        self,
        *,
        source_id: str,
        expected_source_draft_version_id: str,
        expected_candidate_digest: str,
        source_draft_version_id: str,
        candidate_digest: str,
    ) -> None:
        """CAS a trusted Source draft/candidate authority between publications."""

        with self._connection() as connection:
            updated = connection.execute(
                """
                UPDATE hybrid_knowledge_source_authority
                   SET draft_version_id=%s, candidate_digest=%s, updated_at=%s
                 WHERE source_id=%s AND draft_version_id=%s AND candidate_digest=%s
                   AND live_attempt_id IS NULL
                """,
                (
                    source_draft_version_id,
                    candidate_digest,
                    datetime.now(UTC),
                    source_id,
                    expected_source_draft_version_id,
                    expected_candidate_digest,
                ),
            )
            if updated.rowcount != 1:
                raise PublicationConflict("SOURCE_CANDIDATE_CAS_LOST")

    def begin_attempt(self, request: HybridPublicationRequest) -> KnowledgePublicationAttempt:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT draft_version_id, candidate_digest, next_publication_seq,
                       next_fencing_token, live_attempt_id
                  FROM hybrid_knowledge_source_authority
                 WHERE source_id = %s FOR UPDATE
                """,
                (request.source_id,),
            ).fetchone()
            if row is None:
                raise PublicationConflict("SOURCE_NOT_FOUND")
            draft, candidate, sequence, fence, live_attempt = row
            if live_attempt is not None:
                raise PublicationConflict("CONCURRENT_ATTEMPT")
            if draft != request.source_draft_version_id:
                raise PublicationConflict("STALE_DRAFT")
            if candidate != request.candidate_digest:
                raise PublicationConflict("STALE_CANDIDATE")
            generation = connection.execute(
                """
                SELECT identity_digest, generation_json
                  FROM hybrid_knowledge_generation
                 WHERE generation_id = %s AND source_id = %s
                """,
                (request.generation.generation_id, request.source_id),
            ).fetchone()
            expected_generation_digest = stable_digest(request.generation.model_dump(mode="json"))
            if generation is None or generation[0] != expected_generation_digest:
                raise PublicationConflict("GENERATION_MISMATCH")
            validation = connection.execute(
                """
                SELECT v.source_id, v.source_draft_version_id, v.candidate_digest,
                       v.generation_id, v.status, c.attempt_id
                  FROM hybrid_knowledge_publication_validation v
                  LEFT JOIN hybrid_knowledge_publication_validation_claim c
                    ON c.validation_id = v.validation_id
                 WHERE v.validation_id = %s
                   FOR UPDATE OF v
                """,
                (request.validation_id,),
            ).fetchone()
            if validation is None:
                raise PublicationConflict("VALIDATION_NOT_FOUND")
            if validation[5] is not None:
                raise PublicationConflict("VALIDATION_REUSED")
            if (
                validation[0] != request.source_id
                or validation[1] != request.source_draft_version_id
                or validation[2] != request.candidate_digest
                or validation[3] != request.generation.generation_id
                or validation[4] != "passed"
            ):
                raise PublicationConflict("STALE_VALIDATION")
            attempt_id = f"attempt-{uuid4().hex}"
            now = datetime.now(UTC)
            connection.execute(
                """
                INSERT INTO hybrid_projection_operation
                  (operation_id, source_id, generation_id, operation_kind,
                   state, created_at, updated_at)
                VALUES (%s,%s,%s,'PUBLICATION','BUILDING',%s,%s)
                """,
                (attempt_id, request.source_id, request.generation.generation_id, now, now),
            )
            connection.execute(
                """
                INSERT INTO hybrid_knowledge_publication_attempt
                  (attempt_id, source_id, reserved_sequence, fencing_token,
                   source_draft_version_id, candidate_digest, generation_id,
                   validation_id, state, started_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'BUILDING',%s,%s)
                """,
                (
                    attempt_id,
                    request.source_id,
                    sequence,
                    fence,
                    draft,
                    candidate,
                    request.generation.generation_id,
                    request.validation_id,
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO hybrid_knowledge_publication_validation_claim
                  (validation_id, source_id, generation_id, attempt_id, claimed_at)
                VALUES (%s,%s,%s,%s,%s)
                """,
                (
                    request.validation_id,
                    request.source_id,
                    request.generation.generation_id,
                    attempt_id,
                    now,
                ),
            )
            connection.execute(
                """
                UPDATE hybrid_knowledge_source_authority
                   SET next_publication_seq = next_publication_seq + 1,
                       next_fencing_token = next_fencing_token + 1,
                       live_attempt_id = %s, updated_at = %s
                 WHERE source_id = %s
                """,
                (attempt_id, now, request.source_id),
            )
            return KnowledgePublicationAttempt(
                attempt_id=attempt_id,
                source_id=request.source_id,
                source_draft_version_id=draft,
                candidate_digest=candidate,
                reserved_publication_seq=sequence,
                fencing_token=fence,
                generation_id=request.generation.generation_id,
                validation_id=request.validation_id,
                state="BUILDING",
                started_at=now,
                updated_at=now,
            )

    def mark_validated(self, attempt_id: str) -> KnowledgePublicationAttempt:
        now = datetime.now(UTC)
        with self._connection() as connection:
            row = connection.execute(
                """
                UPDATE hybrid_knowledge_publication_attempt
                   SET state = 'VALIDATED', updated_at = %s
                 WHERE attempt_id = %s AND state = 'BUILDING'
             RETURNING attempt_id, source_id, source_draft_version_id,
                       candidate_digest, reserved_sequence, fencing_token,
                       generation_id, validation_id, state, started_at, updated_at
                """,
                (now, attempt_id),
            ).fetchone()
            if row is not None:
                connection.execute(
                    """UPDATE hybrid_projection_operation
                          SET state='VALIDATED', updated_at=%s
                        WHERE operation_id=%s AND state='BUILDING'""",
                    (now, attempt_id),
                )
        if row is None:
            raise PublicationConflict("ATTEMPT_STATE")
        return _attempt_from_row(row)

    def publication_authority_context(
        self, attempt: KnowledgePublicationAttempt
    ) -> PublicationAuthorityContext:
        with self._connection() as connection:
            publication_row = connection.execute(
                """
                SELECT p.publication_json, m.manifest_json,
                       ar.artifact_uri, ar.version_id, ar.sha256,
                       ar.size_bytes, ar.media_type
                  FROM hybrid_knowledge_publication p
                  JOIN hybrid_rule_unit_manifest m
                    ON m.root_sha256 = p.manifest_root_sha256
                  JOIN hybrid_knowledge_artifact_reference ar
                    ON ar.artifact_ref_id = m.root_artifact_ref_id
                 WHERE p.source_id = %s AND p.generation_id = %s
                 ORDER BY p.source_publication_seq DESC
                 LIMIT 1
                """,
                (attempt.source_id, attempt.generation_id),
            ).fetchone()
            projection_row = connection.execute(
                """
                SELECT a.attestation_json
                  FROM hybrid_generation_projection gp
                  JOIN hybrid_projection_attestation a
                    ON a.attestation_sha256 = gp.attestation_sha256
                 WHERE gp.source_id = %s AND gp.generation_id = %s
                """,
                (attempt.source_id, attempt.generation_id),
            ).fetchone()
            parent = (
                KnowledgeProjectionAttestation.model_validate(_json_object(projection_row[0]))
                if projection_row is not None
                else None
            )
            retained = (
                _load_retained_projection_authority(
                    connection,
                    source_id=attempt.source_id,
                    generation_id=attempt.generation_id,
                    attestation=parent,
                )
                if parent is not None
                else ()
            )
            previous = (
                _load_manifest_materialization(connection, publication_row)
                if publication_row is not None
                else None
            )
        return PublicationAuthorityContext(
            previous_manifest=previous,
            parent_attestation=parent,
            retained_projection_documents=retained,
        )

    def record_scheduler_metrics(
        self,
        attempt_id: str,
        *,
        queue_time_ms: float,
        service_time_ms: float,
    ) -> None:
        with self._connection() as connection:
            result = connection.execute(
                """
                UPDATE hybrid_knowledge_publication_attempt
                   SET queue_time_ms = %s, service_time_ms = %s
                 WHERE attempt_id = %s AND state IN ('BUILDING','VALIDATED')
                """,
                (queue_time_ms, service_time_ms, attempt_id),
            )
            if result.rowcount != 1:
                raise PublicationConflict("ATTEMPT_LOST")

    def stage_commit(self, commit: PublicationCommit) -> None:
        """Persist and verify immutable material before the final Source-row CAS."""

        attestation = commit.attestation
        with self._connection() as connection:
            self._insert_projection_authority(connection, commit)
            self._insert_manifest(connection, commit)
            connection.execute(
                """
                INSERT INTO hybrid_projection_attestation
                  (attestation_sha256, source_id, generation_id, publication_attempt_id,
                   index_uuid, mapping_sha256, manifest_root_sha256,
                   parent_attestation_sha256, attestation_json, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
                ON CONFLICT (attestation_sha256) DO NOTHING
                """,
                (
                    attestation.attestation_sha256,
                    commit.attempt.source_id,
                    commit.attempt.generation_id,
                    commit.attempt.attempt_id,
                    attestation.index_uuid,
                    attestation.mapping_sha256,
                    attestation.manifest_root_sha256,
                    attestation.parent_attestation_sha256,
                    _canonical_json(attestation.model_dump(mode="json")),
                    datetime.now(UTC),
                ),
            )
            stored = connection.execute(
                """SELECT attestation_json FROM hybrid_projection_attestation
                    WHERE attestation_sha256=%s AND source_id=%s AND generation_id=%s""",
                (
                    attestation.attestation_sha256,
                    commit.attempt.source_id,
                    commit.attempt.generation_id,
                ),
            ).fetchone()
            if stored is None or _json_object(stored[0]) != attestation.model_dump(mode="json"):
                raise PublicationConflict("STAGED_COMMIT_MISMATCH")

    def commit_if_current(self, commit: PublicationCommit) -> HybridKnowledgePublicationRecord:
        """Advance publication pointers in one short Source-row CAS transaction."""

        attempt = commit.attempt
        root = commit.manifest.root
        attestation = commit.attestation
        self._validate_staged_commit(commit)
        with self._connection() as connection:
            source = connection.execute(
                """
                SELECT draft_version_id, candidate_digest, live_attempt_id
                  FROM hybrid_knowledge_source_authority
                 WHERE source_id = %s FOR UPDATE
                """,
                (attempt.source_id,),
            ).fetchone()
            if source is None:
                raise PublicationConflict("SOURCE_NOT_FOUND")
            if source[2] != attempt.attempt_id:
                raise PublicationConflict("FENCE_LOST")
            live = connection.execute(
                """
                SELECT attempt_id, source_id, source_draft_version_id, candidate_digest,
                       reserved_sequence, fencing_token, generation_id, validation_id,
                       state, started_at, updated_at
                  FROM hybrid_knowledge_publication_attempt
                 WHERE attempt_id = %s FOR UPDATE
                """,
                (attempt.attempt_id,),
            ).fetchone()
            if live is None or _attempt_from_row(live) != attempt or attempt.state != "VALIDATED":
                raise PublicationConflict("FENCE_LOST")
            claim = connection.execute(
                """SELECT attempt_id FROM hybrid_knowledge_publication_validation_claim
                    WHERE validation_id=%s AND source_id=%s AND generation_id=%s""",
                (attempt.validation_id, attempt.source_id, attempt.generation_id),
            ).fetchone()
            if claim != (attempt.attempt_id,):
                raise PublicationConflict("VALIDATION_REUSED")
            if source[0] != attempt.source_draft_version_id:
                raise PublicationConflict("STALE_DRAFT")
            if source[1] != attempt.candidate_digest:
                raise PublicationConflict("STALE_CANDIDATE")
            projection_pointer = connection.execute(
                """SELECT index_uuid, attestation_sha256
                     FROM hybrid_generation_projection
                    WHERE source_id=%s AND generation_id=%s FOR UPDATE""",
                (attempt.source_id, attempt.generation_id),
            ).fetchone()
            expected_parent = projection_pointer[1] if projection_pointer is not None else None
            generation = connection.execute(
                """SELECT identity_digest, mapping_sha256 FROM hybrid_knowledge_generation
                    WHERE generation_id = %s AND source_id = %s""",
                (attempt.generation_id, attempt.source_id),
            ).fetchone()
            if (
                generation is None
                or generation[0] != commit.generation_identity_digest
                or generation[1] != commit.generation.mapping_sha256
                or commit.identity.generation != commit.generation
            ):
                raise PublicationConflict("GENERATION_MISMATCH")
            if (
                root.source_id != attempt.source_id
                or root.source_publication_seq != attempt.reserved_publication_seq
                or root.generation_id != attempt.generation_id
                or root.root_sha256 != commit.manifest.root_ref.sha256
            ):
                raise PublicationConflict("MANIFEST_MISMATCH")
            if (
                attestation.publication_attempt_id != attempt.attempt_id
                or attestation.source_id != attempt.source_id
                or attestation.generation_id != attempt.generation_id
                or attestation.manifest_root_sha256 != root.root_sha256
                or attestation.mapping_sha256 != commit.generation.mapping_sha256
                or attestation.index_uuid != commit.identity.index_uuid
                or attempt.reserved_publication_seq not in attestation.covered_publication_sequences
                or attestation.parent_attestation_sha256 != expected_parent
            ):
                raise PublicationConflict("ATTESTATION_MISMATCH")
            if (
                projection_pointer is not None
                and projection_pointer[0] != commit.identity.index_uuid
            ):
                raise PublicationConflict("FENCE_LOST")
            projection_updated_at = datetime.now(UTC)
            if projection_pointer is None:
                projection_update = connection.execute(
                    """
                    INSERT INTO hybrid_generation_projection
                      (source_id, generation_id, index_uuid, projection_locator,
                       attestation_sha256, fencing_token, updated_at)
                    VALUES (%s,%s,%s,%s,%s,1,%s)
                    ON CONFLICT (source_id, generation_id) DO NOTHING
                    """,
                    (
                        attempt.source_id,
                        attempt.generation_id,
                        attestation.index_uuid,
                        commit.identity.projection_locator,
                        attestation.attestation_sha256,
                        projection_updated_at,
                    ),
                )
            else:
                projection_update = connection.execute(
                    """
                    UPDATE hybrid_generation_projection
                       SET projection_locator=%s,
                           attestation_sha256=%s,
                           fencing_token=fencing_token+1,
                           updated_at=%s
                     WHERE source_id=%s AND generation_id=%s
                       AND index_uuid=%s AND attestation_sha256=%s
                    """,
                    (
                        commit.identity.projection_locator,
                        attestation.attestation_sha256,
                        projection_updated_at,
                        attempt.source_id,
                        attempt.generation_id,
                        projection_pointer[0],
                        expected_parent,
                    ),
                )
            if projection_update.rowcount != 1:
                raise PublicationConflict("FENCE_LOST")
            published_at = datetime.now(UTC)
            publication_id = f"publication-{uuid4().hex}"
            publication = HybridKnowledgePublicationRecord(
                publication_id=publication_id,
                source_id=attempt.source_id,
                source_draft_version_id=attempt.source_draft_version_id,
                source_snapshot_id=root.source_snapshot_id,
                source_publication_seq=attempt.reserved_publication_seq,
                candidate_digest=attempt.candidate_digest,
                generation_id=attempt.generation_id,
                manifest_ref=commit.manifest.root_ref,
                attestation=attestation,
                validation_id=attempt.validation_id,
                published_at=published_at,
                published_by=commit.published_by,
            )
            connection.execute(
                """
                INSERT INTO hybrid_knowledge_publication
                  (publication_id, source_id, source_publication_seq,
                   source_draft_version_id, candidate_digest, generation_id,
                   validation_id, attempt_id, manifest_root_sha256,
                   attestation_sha256, publication_json, published_at, published_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)
                """,
                (
                    publication_id,
                    attempt.source_id,
                    attempt.reserved_publication_seq,
                    attempt.source_draft_version_id,
                    attempt.candidate_digest,
                    attempt.generation_id,
                    attempt.validation_id,
                    attempt.attempt_id,
                    root.root_sha256,
                    attestation.attestation_sha256,
                    _canonical_json(publication.model_dump(mode="json")),
                    published_at,
                    commit.published_by,
                ),
            )
            connection.execute(
                """UPDATE hybrid_knowledge_publication_attempt
                      SET state='PUBLISHED', updated_at=%s
                    WHERE attempt_id=%s AND state='VALIDATED'""",
                (published_at, attempt.attempt_id),
            )
            connection.execute(
                """UPDATE hybrid_projection_operation
                      SET state='COMMITTED', updated_at=%s
                    WHERE operation_id=%s AND state='VALIDATED'""",
                (published_at, attempt.attempt_id),
            )
            updated = connection.execute(
                """
                UPDATE hybrid_knowledge_source_authority
                   SET active_publication_id=%s, live_attempt_id=NULL, updated_at=%s
                 WHERE source_id=%s AND live_attempt_id=%s
                """,
                (publication_id, published_at, attempt.source_id, attempt.attempt_id),
            )
            if updated.rowcount != 1:
                raise PublicationConflict("FENCE_LOST")
            return publication

    def load_active_publication(self, source_id: str) -> HybridKnowledgePublicationRecord | None:
        """Read the authoritative Source publication pointer for verification/operations."""

        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT p.publication_json
                  FROM hybrid_knowledge_source_authority s
                  LEFT JOIN hybrid_knowledge_publication p
                    ON p.publication_id=s.active_publication_id
                 WHERE s.source_id=%s
                """,
                (source_id,),
            ).fetchone()
        if row is None or row[0] is None:
            return None
        return HybridKnowledgePublicationRecord.model_validate(_json_object(row[0]))

    def _validate_staged_commit(self, commit: PublicationCommit) -> None:
        """Verify immutable staged material outside the final Source lock transaction."""

        attempt = commit.attempt
        root = commit.manifest.root
        attestation = commit.attestation
        with self._connection() as connection:
            staged = connection.execute(
                """
                SELECT m.manifest_json, a.attestation_json
                  FROM hybrid_rule_unit_manifest m
                  JOIN hybrid_projection_attestation a
                    ON a.manifest_root_sha256=m.root_sha256
                 WHERE m.root_sha256=%s AND m.source_id=%s AND m.generation_id=%s
                   AND a.attestation_sha256=%s
                   AND a.publication_attempt_id=%s
                """,
                (
                    root.root_sha256,
                    attempt.source_id,
                    attempt.generation_id,
                    attestation.attestation_sha256,
                    attempt.attempt_id,
                ),
            ).fetchone()
        if (
            staged is None
            or _json_object(staged[0]) != root.model_dump(mode="json")
            or _json_object(staged[1]) != attestation.model_dump(mode="json")
        ):
            raise PublicationConflict("STAGED_COMMIT_MISMATCH")

    def fail_attempt(
        self,
        attempt_id: str,
        *,
        failure_code: str,
        projection_identity: Any | None,
    ) -> None:
        now = datetime.now(UTC)
        with self._connection() as connection:
            row = connection.execute(
                """SELECT source_id, generation_id FROM hybrid_knowledge_publication_attempt
                    WHERE attempt_id=%s AND state IN ('BUILDING','VALIDATED') FOR UPDATE""",
                (attempt_id,),
            ).fetchone()
            if row is None:
                return
            connection.execute(
                """UPDATE hybrid_knowledge_publication_attempt
                      SET state='FAILED', failure_code=%s, updated_at=%s
                    WHERE attempt_id=%s""",
                (failure_code, now, attempt_id),
            )
            connection.execute(
                """UPDATE hybrid_projection_operation
                      SET state='FAILED', failure_code=%s, updated_at=%s
                    WHERE operation_id=%s AND state IN ('BUILDING','VALIDATED')""",
                (failure_code, now, attempt_id),
            )
            connection.execute(
                """UPDATE hybrid_knowledge_source_authority SET live_attempt_id=NULL, updated_at=%s
                    WHERE source_id=%s AND live_attempt_id=%s""",
                (now, row[0], attempt_id),
            )
            if projection_identity is not None:
                connection.execute(
                    """
                    INSERT INTO hybrid_projection_orphan_cleanup
                      (attempt_id, source_id, generation_id, index_uuid,
                       projection_locator, state, updated_at)
                    VALUES (%s,%s,%s,%s,%s,'PENDING',%s)
                    ON CONFLICT (attempt_id) DO NOTHING
                    """,
                    (
                        attempt_id,
                        row[0],
                        row[1],
                        projection_identity.index_uuid,
                        projection_identity.projection_locator,
                        now,
                    ),
                )

    def list_orphan_projections(self, source_id: str) -> tuple[OrphanProjection, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT o.attempt_id, o.source_id, o.state, o.index_uuid,
                       g.generation_json, o.projection_locator
                  FROM hybrid_projection_orphan_cleanup o
                  JOIN hybrid_knowledge_generation g ON g.generation_id=o.generation_id
                 WHERE o.source_id=%s AND o.state IN ('PENDING','RETRY')
                 ORDER BY o.attempt_id
                """,
                (source_id,),
            ).fetchall()
        return tuple(
            OrphanProjection(
                attempt_id=row[0],
                source_id=row[1],
                state=row[2],
                identity=SearchIndexIdentity(
                    generation=KnowledgeIndexGeneration.model_validate(_json_object(row[4])),
                    index_uuid=row[3],
                    projection_locator=row[5],
                ),
            )
            for row in rows
        )

    def projection_is_referenced(self, orphan: OrphanProjection) -> bool:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT 1
                  FROM hybrid_generation_projection gp
                 WHERE gp.source_id=%s AND gp.generation_id=%s AND gp.index_uuid=%s
                UNION ALL
                SELECT 1
                  FROM hybrid_knowledge_publication p
                  JOIN hybrid_projection_attestation a
                    ON a.attestation_sha256=p.attestation_sha256
                 WHERE p.source_id=%s AND a.index_uuid=%s
                 LIMIT 1
                """,
                (
                    orphan.source_id,
                    orphan.identity.generation.generation_id,
                    orphan.identity.index_uuid,
                    orphan.source_id,
                    orphan.identity.index_uuid,
                ),
            ).fetchone()
        return row is not None

    def record_orphan_deleted(self, attempt_id: str) -> None:
        with self._connection() as connection:
            connection.execute(
                """UPDATE hybrid_projection_orphan_cleanup
                      SET state='DELETED', last_failure_code=NULL, updated_at=%s
                    WHERE attempt_id=%s AND state IN ('PENDING','RETRY')""",
                (datetime.now(UTC), attempt_id),
            )

    def record_orphan_retry(self, attempt_id: str, failure_code: str) -> None:
        with self._connection() as connection:
            connection.execute(
                """UPDATE hybrid_projection_orphan_cleanup
                      SET state='RETRY', retry_count=retry_count+1,
                          last_failure_code=%s, updated_at=%s
                    WHERE attempt_id=%s AND state IN ('PENDING','RETRY')""",
                (failure_code, datetime.now(UTC), attempt_id),
            )

    def load_generation_rebuild(
        self, source_id: str, generation_id: str
    ) -> GenerationRebuildAuthority:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT p.publication_json, m.manifest_json,
                       root_ref.artifact_uri, root_ref.version_id, root_ref.sha256,
                       root_ref.size_bytes, root_ref.media_type,
                       gp.index_uuid, gp.projection_locator,
                       a.attestation_json, g.generation_json
                  FROM hybrid_generation_projection gp
                  JOIN hybrid_projection_attestation a
                    ON a.attestation_sha256=gp.attestation_sha256
                  JOIN hybrid_rule_unit_manifest m
                    ON m.root_sha256=a.manifest_root_sha256
                  JOIN hybrid_knowledge_artifact_reference root_ref
                    ON root_ref.artifact_ref_id=m.root_artifact_ref_id
                  JOIN hybrid_knowledge_generation g
                    ON g.source_id=gp.source_id AND g.generation_id=gp.generation_id
                  JOIN LATERAL (
                    SELECT publication_json
                      FROM hybrid_knowledge_publication publication
                     WHERE publication.source_id=gp.source_id
                       AND publication.generation_id=gp.generation_id
                     ORDER BY publication.source_publication_seq DESC
                     LIMIT 1
                  ) p ON TRUE
                 WHERE gp.source_id=%s AND gp.generation_id=%s
                """,
                (source_id, generation_id),
            ).fetchone()
            if row is None:
                raise PublicationConflict("GENERATION_NOT_FOUND")
            current_attestation = KnowledgeProjectionAttestation.model_validate(
                _json_object(row[9])
            )
            retained_rows = connection.execute(
                """
                SELECT m.manifest_json,
                       root_ref.artifact_uri, root_ref.version_id, root_ref.sha256,
                       root_ref.size_bytes, root_ref.media_type,
                       shard_ref.artifact_uri, shard_ref.version_id, shard_ref.sha256,
                       shard_ref.size_bytes, shard_ref.media_type,
                       sh.shard_json, mm.ordinal
                  FROM hybrid_rule_unit_manifest m
                  JOIN hybrid_knowledge_artifact_reference root_ref
                    ON root_ref.artifact_ref_id=m.root_artifact_ref_id
                  JOIN hybrid_rule_unit_manifest_member mm
                    ON mm.root_sha256=m.root_sha256
                  JOIN hybrid_rule_unit_manifest_shard sh
                    ON sh.shard_sha256=mm.shard_sha256
                  JOIN hybrid_knowledge_artifact_reference shard_ref
                    ON shard_ref.artifact_ref_id=sh.artifact_ref_id
                 WHERE m.source_id=%s AND m.generation_id=%s
                   AND m.source_publication_seq = ANY(%s)
                 ORDER BY m.source_publication_seq, mm.ordinal
                """,
                (
                    source_id,
                    generation_id,
                    list(current_attestation.covered_publication_sequences),
                ),
            ).fetchall()
            rule_ids = tuple(
                entry.rule_unit_revision_id
                for item in retained_rows
                for entry in RuleUnitManifestShard.model_validate(_json_object(item[11])).entries
            )
            projection_rows = connection.execute(
                """
                SELECT r.rule_unit_json, m.metadata_json, v.visibility_json
                  FROM hybrid_knowledge_rule_unit_revision r
                  JOIN hybrid_approved_rule_metadata m
                    ON m.source_id=r.source_id
                   AND m.metadata_revision_id=r.metadata_revision_id
                  JOIN hybrid_approved_visibility_scope v
                    ON v.source_id=r.source_id
                   AND v.visibility_revision_id=r.visibility_revision_id
                 WHERE r.source_id=%s AND r.rule_unit_revision_id = ANY(%s)
                 ORDER BY r.rule_unit_revision_id
                """,
                (source_id, list(rule_ids)),
            ).fetchall()
        root = RuleUnitManifestRoot.model_validate(_json_object(row[1]))
        generation = KnowledgeIndexGeneration.model_validate(_json_object(row[10]))
        retained_by_root: dict[str, dict[str, object]] = {}
        for item in retained_rows:
            retained_root = RuleUnitManifestRoot.model_validate(_json_object(item[0]))
            bucket = retained_by_root.setdefault(
                retained_root.root_sha256,
                {
                    "root": retained_root,
                    "root_ref": ExactArtifactRef(
                        artifact_uri=item[1],
                        version_id=item[2],
                        sha256=item[3],
                        size_bytes=item[4],
                        media_type=item[5],
                    ),
                    "shard_refs": [],
                },
            )
            cast(list[ExactArtifactRef], bucket["shard_refs"]).append(
                ExactArtifactRef(
                    artifact_uri=item[6],
                    version_id=item[7],
                    sha256=item[8],
                    size_bytes=item[9],
                    media_type=item[10],
                )
            )
        retained_manifests = tuple(
            RetainedManifestAuthority(
                root=cast(RuleUnitManifestRoot, item["root"]),
                root_ref=cast(ExactArtifactRef, item["root_ref"]),
                shard_refs=tuple(cast(list[ExactArtifactRef], item["shard_refs"])),
            )
            for item in sorted(
                retained_by_root.values(),
                key=lambda value: cast(RuleUnitManifestRoot, value["root"]).source_publication_seq,
            )
        )
        current_retained = next(
            (item for item in retained_manifests if item.root.root_sha256 == root.root_sha256),
            None,
        )
        if current_retained is None:
            raise PublicationConflict("AUTHORITY_CHAIN_MISSING")
        return GenerationRebuildAuthority(
            source_id=source_id,
            generation_id=generation_id,
            candidate_digest=_json_string(
                _json_object(row[0])["candidate_digest"],
                field="candidate_digest",
            ),
            manifest_root=root,
            root_ref=ExactArtifactRef(
                artifact_uri=row[2],
                version_id=row[3],
                sha256=row[4],
                size_bytes=row[5],
                media_type=row[6],
            ),
            shard_refs=current_retained.shard_refs,
            current_identity=SearchIndexIdentity(
                generation=generation,
                index_uuid=row[7],
                projection_locator=row[8],
            ),
            current_attestation=current_attestation,
            projection_authority=tuple(
                _rebuild_projection_authority(item) for item in projection_rows
            ),
            retained_manifests=retained_manifests,
        )

    def begin_generation_rebuild(self, authority: GenerationRebuildAuthority) -> str:
        operation_id = f"rebuild-{uuid4().hex}"
        now = datetime.now(UTC)
        with self._connection() as connection:
            current = connection.execute(
                """SELECT index_uuid, attestation_sha256 FROM hybrid_generation_projection
                    WHERE source_id=%s AND generation_id=%s FOR UPDATE""",
                (authority.source_id, authority.generation_id),
            ).fetchone()
            if current != (
                authority.current_identity.index_uuid,
                authority.current_attestation.attestation_sha256,
            ):
                raise PublicationConflict("FENCE_LOST")
            connection.execute(
                """INSERT INTO hybrid_projection_operation
                    (operation_id, source_id, generation_id, operation_kind,
                     state, created_at, updated_at)
                    VALUES (%s,%s,%s,'REBUILD','BUILDING',%s,%s)""",
                (operation_id, authority.source_id, authority.generation_id, now, now),
            )
        return operation_id

    def fail_recovery_operation(
        self,
        operation_id: str,
        failure_code: str,
        projection_identity: SearchIndexIdentity | None = None,
    ) -> None:
        with self._connection() as connection:
            row = connection.execute(
                """SELECT source_id, generation_id FROM hybrid_projection_operation
                    WHERE operation_id=%s AND operation_kind='REBUILD' FOR UPDATE""",
                (operation_id,),
            ).fetchone()
            if row is None:
                return
            connection.execute(
                """UPDATE hybrid_projection_operation
                      SET state='FAILED', failure_code=%s, updated_at=%s
                    WHERE operation_id=%s AND operation_kind='REBUILD'
                      AND state IN ('BUILDING','VALIDATED')""",
                (failure_code, datetime.now(UTC), operation_id),
            )
            if projection_identity is not None:
                connection.execute(
                    """INSERT INTO hybrid_projection_orphan_cleanup
                        (attempt_id, source_id, generation_id, index_uuid,
                         projection_locator, state, updated_at)
                        VALUES (%s,%s,%s,%s,%s,'PENDING',%s)
                        ON CONFLICT (attempt_id) DO NOTHING""",
                    (
                        operation_id,
                        row[0],
                        row[1],
                        projection_identity.index_uuid,
                        projection_identity.projection_locator,
                        datetime.now(UTC),
                    ),
                )

    def swap_generation_projection(
        self,
        *,
        authority: GenerationRebuildAuthority,
        rebuilt_identity: SearchIndexIdentity,
        attestation: KnowledgeProjectionAttestation,
    ) -> None:
        now = datetime.now(UTC)
        with self._connection() as connection:
            current = connection.execute(
                """SELECT index_uuid, attestation_sha256, fencing_token
                    FROM hybrid_generation_projection
                    WHERE source_id=%s AND generation_id=%s FOR UPDATE""",
                (authority.source_id, authority.generation_id),
            ).fetchone()
            if current is None or current[:2] != (
                authority.current_identity.index_uuid,
                authority.current_attestation.attestation_sha256,
            ):
                raise PublicationConflict("FENCE_LOST")
            connection.execute(
                """UPDATE hybrid_projection_operation SET state='VALIDATED', updated_at=%s
                    WHERE operation_id=%s AND source_id=%s AND state='BUILDING'""",
                (now, attestation.publication_attempt_id, authority.source_id),
            )
            connection.execute(
                """
                INSERT INTO hybrid_projection_attestation
                  (attestation_sha256, source_id, generation_id, publication_attempt_id,
                   index_uuid, mapping_sha256, manifest_root_sha256,
                   parent_attestation_sha256, attestation_json, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
                """,
                (
                    attestation.attestation_sha256,
                    authority.source_id,
                    authority.generation_id,
                    attestation.publication_attempt_id,
                    rebuilt_identity.index_uuid,
                    attestation.mapping_sha256,
                    attestation.manifest_root_sha256,
                    attestation.parent_attestation_sha256,
                    _canonical_json(attestation.model_dump(mode="json")),
                    now,
                ),
            )
            updated = connection.execute(
                """UPDATE hybrid_generation_projection
                      SET index_uuid=%s, projection_locator=%s, attestation_sha256=%s,
                          fencing_token=fencing_token+1, updated_at=%s
                    WHERE source_id=%s AND generation_id=%s
                      AND index_uuid=%s AND attestation_sha256=%s""",
                (
                    rebuilt_identity.index_uuid,
                    rebuilt_identity.projection_locator,
                    attestation.attestation_sha256,
                    now,
                    authority.source_id,
                    authority.generation_id,
                    authority.current_identity.index_uuid,
                    authority.current_attestation.attestation_sha256,
                ),
            )
            if updated.rowcount != 1:
                raise PublicationConflict("FENCE_LOST")
            connection.execute(
                """UPDATE hybrid_projection_operation SET state='COMMITTED', updated_at=%s
                    WHERE operation_id=%s AND state='VALIDATED'""",
                (now, attestation.publication_attempt_id),
            )

    def _insert_manifest(self, connection: Any, commit: PublicationCommit) -> None:
        manifest = commit.manifest
        for persisted in (*manifest.shards,):
            ref_id = _artifact_ref_id(persisted.artifact_ref)
            self._insert_artifact_ref(connection, ref_id, persisted.artifact_ref)
            connection.execute(
                """
                INSERT INTO hybrid_rule_unit_manifest_shard
                  (shard_sha256, source_id, generation_id, document_id,
                   artifact_ref_id, rule_unit_count, shard_json, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
                ON CONFLICT (shard_sha256) DO NOTHING
                """,
                (
                    persisted.shard.sha256,
                    manifest.root.source_id,
                    manifest.root.generation_id,
                    persisted.shard.document_id,
                    ref_id,
                    len(persisted.shard.entries),
                    _canonical_json(persisted.shard.model_dump(mode="json")),
                    manifest.root.created_at,
                ),
            )
        root_ref_id = _artifact_ref_id(manifest.root_ref)
        self._insert_artifact_ref(connection, root_ref_id, manifest.root_ref)
        root = manifest.root
        connection.execute(
            """
            INSERT INTO hybrid_rule_unit_manifest
              (root_sha256, source_id, source_snapshot_id, source_publication_seq,
               generation_id, root_artifact_ref_id, manifest_json,
               document_count, rule_unit_count, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)
            ON CONFLICT (root_sha256) DO NOTHING
            """,
            (
                root.root_sha256,
                root.source_id,
                root.source_snapshot_id,
                root.source_publication_seq,
                root.generation_id,
                root_ref_id,
                _canonical_json(root.model_dump(mode="json")),
                root.document_count,
                root.rule_unit_count,
                root.created_at,
            ),
        )
        for ordinal, persisted in enumerate(manifest.shards):
            connection.execute(
                """INSERT INTO hybrid_rule_unit_manifest_member
                     (root_sha256, shard_sha256, source_id, generation_id, ordinal)
                     VALUES (%s,%s,%s,%s,%s)
                     ON CONFLICT (root_sha256, shard_sha256) DO NOTHING""",
                (
                    root.root_sha256,
                    persisted.shard.sha256,
                    root.source_id,
                    root.generation_id,
                    ordinal,
                ),
            )
        stored_root = connection.execute(
            """SELECT manifest_json, root_artifact_ref_id
                 FROM hybrid_rule_unit_manifest WHERE root_sha256=%s""",
            (root.root_sha256,),
        ).fetchone()
        stored_members = connection.execute(
            """SELECT shard_sha256, ordinal FROM hybrid_rule_unit_manifest_member
                WHERE root_sha256=%s ORDER BY ordinal""",
            (root.root_sha256,),
        ).fetchall()
        if (
            stored_root is None
            or _json_object(stored_root[0]) != root.model_dump(mode="json")
            or stored_root[1] != root_ref_id
            or stored_members
            != [
                (persisted.shard.sha256, ordinal)
                for ordinal, persisted in enumerate(manifest.shards)
            ]
        ):
            raise PublicationConflict("STAGED_COMMIT_MISMATCH")

    def _insert_projection_authority(self, connection: Any, commit: PublicationCommit) -> None:
        now = commit.attempt.started_at
        for authority in commit.staged_projection_documents:
            rule = authority.rule_unit
            metadata = authority.approved_metadata
            visibility = rule.visibility_scope
            metadata_sha = stable_digest(metadata.model_dump(mode="json"))
            visibility_sha = stable_digest(visibility.model_dump(mode="json"))
            if rule.authority_sha256 != stable_digest(
                {
                    "approved_metadata": metadata.model_dump(mode="json"),
                    "approved_visibility": visibility.model_dump(mode="json"),
                }
            ):
                raise PublicationConflict("ATTESTATION_MISMATCH")
            connection.execute(
                """INSERT INTO hybrid_approved_rule_metadata
                    (source_id, metadata_revision_id, metadata_sha256, metadata_json, approved_at)
                    VALUES (%s,%s,%s,%s::jsonb,%s) ON CONFLICT DO NOTHING""",
                (
                    rule.lineage.source_id,
                    metadata.metadata_revision_id,
                    metadata_sha,
                    _canonical_json(metadata.model_dump(mode="json")),
                    now,
                ),
            )
            connection.execute(
                """INSERT INTO hybrid_approved_visibility_scope
                    (source_id, visibility_revision_id, visibility_sha256,
                     visibility_json, approved_at)
                    VALUES (%s,%s,%s,%s::jsonb,%s) ON CONFLICT DO NOTHING""",
                (
                    rule.lineage.source_id,
                    visibility.revision_id,
                    visibility_sha,
                    _canonical_json(visibility.model_dump(mode="json")),
                    now,
                ),
            )
            stored_metadata = connection.execute(
                """SELECT metadata_sha256 FROM hybrid_approved_rule_metadata
                    WHERE source_id=%s AND metadata_revision_id=%s""",
                (rule.lineage.source_id, metadata.metadata_revision_id),
            ).fetchone()
            stored_visibility = connection.execute(
                """SELECT visibility_sha256 FROM hybrid_approved_visibility_scope
                    WHERE source_id=%s AND visibility_revision_id=%s""",
                (rule.lineage.source_id, visibility.revision_id),
            ).fetchone()
            if stored_metadata != (metadata_sha,) or stored_visibility != (visibility_sha,):
                raise PublicationConflict("PROJECTION_AUTHORITY_MISMATCH")
            connection.execute(
                """INSERT INTO hybrid_knowledge_document_revision
                    (source_id, document_id, revision_id, structured_build_id,
                     review_state, created_at)
                    VALUES (%s,%s,%s,%s,'NOT_REQUIRED',%s) ON CONFLICT DO NOTHING""",
                (
                    rule.lineage.source_id,
                    rule.document_id,
                    rule.revision_id,
                    rule.structured_build_id,
                    now,
                ),
            )
            connection.execute(
                """INSERT INTO hybrid_knowledge_rule_unit_revision
                    (rule_unit_revision_id, source_id, document_id, revision_id,
                     structured_build_id, metadata_revision_id, visibility_revision_id,
                     content_sha256, authority_sha256, rule_unit_json, approved_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
                    ON CONFLICT DO NOTHING""",
                (
                    rule.rule_unit_revision_id,
                    rule.lineage.source_id,
                    rule.document_id,
                    rule.revision_id,
                    rule.structured_build_id,
                    rule.metadata_revision_id,
                    visibility.revision_id,
                    rule.content_sha256,
                    rule.authority_sha256,
                    _canonical_json(
                        {
                            "rule_unit": rule.model_dump(mode="json"),
                            "projection_id": authority.projection_id,
                            "projection_revision": authority.projection_revision,
                        }
                    ),
                    now,
                ),
            )
            row = connection.execute(
                """SELECT content_sha256, authority_sha256
                    FROM hybrid_knowledge_rule_unit_revision
                    WHERE rule_unit_revision_id=%s AND source_id=%s""",
                (rule.rule_unit_revision_id, rule.lineage.source_id),
            ).fetchone()
            if row != (rule.content_sha256, rule.authority_sha256):
                raise PublicationConflict("PROJECTION_AUTHORITY_MISMATCH")
            connection.execute(
                """
                INSERT INTO hybrid_projection_materialization
                  (source_id, generation_id, projection_id, rule_unit_revision_id,
                   embedding_sha256, projection_material_sha256,
                   immutable_projection_sha256, created_attempt_id, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING
                """,
                (
                    rule.lineage.source_id,
                    commit.attempt.generation_id,
                    authority.projection_id,
                    rule.rule_unit_revision_id,
                    authority.embedding_sha256,
                    authority.projection_material_sha256,
                    authority.immutable_projection_sha256,
                    authority.last_publication_attempt_id,
                    now,
                ),
            )
            material = connection.execute(
                """
                SELECT rule_unit_revision_id, embedding_sha256,
                       projection_material_sha256, immutable_projection_sha256
                  FROM hybrid_projection_materialization
                 WHERE source_id=%s AND generation_id=%s AND projection_id=%s
                """,
                (
                    rule.lineage.source_id,
                    commit.attempt.generation_id,
                    authority.projection_id,
                ),
            ).fetchone()
            if material != (
                rule.rule_unit_revision_id,
                authority.embedding_sha256,
                authority.projection_material_sha256,
                authority.immutable_projection_sha256,
            ):
                raise PublicationConflict("PROJECTION_AUTHORITY_MISMATCH")

    @staticmethod
    def _insert_artifact_ref(connection: Any, ref_id: str, ref: ExactArtifactRef) -> None:
        connection.execute(
            """
            INSERT INTO hybrid_knowledge_artifact_reference
              (artifact_ref_id, artifact_uri, version_id, sha256,
               size_bytes, media_type, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (artifact_ref_id) DO NOTHING
            """,
            (
                ref_id,
                ref.artifact_uri,
                ref.version_id,
                ref.sha256,
                ref.size_bytes,
                ref.media_type,
                datetime.now(UTC),
            ),
        )
        stored = connection.execute(
            """SELECT artifact_uri, version_id, sha256, size_bytes, media_type
                 FROM hybrid_knowledge_artifact_reference WHERE artifact_ref_id=%s""",
            (ref_id,),
        ).fetchone()
        if stored != (
            ref.artifact_uri,
            ref.version_id,
            ref.sha256,
            ref.size_bytes,
            ref.media_type,
        ):
            raise PublicationConflict("STAGED_COMMIT_MISMATCH")


def _load_manifest_materialization(
    connection: Any,
    publication_row: Any,
) -> RuleUnitManifestMaterialization:
    root = RuleUnitManifestRoot.model_validate(_json_object(publication_row[1]))
    root_ref = ExactArtifactRef(
        artifact_uri=publication_row[2],
        version_id=publication_row[3],
        sha256=publication_row[4],
        size_bytes=publication_row[5],
        media_type=publication_row[6],
    )
    shard_rows = connection.execute(
        """
        SELECT sh.shard_json, ar.artifact_uri, ar.version_id, ar.sha256,
               ar.size_bytes, ar.media_type
          FROM hybrid_rule_unit_manifest_member mm
          JOIN hybrid_rule_unit_manifest_shard sh
            ON sh.shard_sha256 = mm.shard_sha256
          JOIN hybrid_knowledge_artifact_reference ar
            ON ar.artifact_ref_id = sh.artifact_ref_id
         WHERE mm.root_sha256 = %s ORDER BY mm.ordinal
        """,
        (root.root_sha256,),
    ).fetchall()
    shards = tuple(
        PersistedRuleUnitManifestShard(
            shard=RuleUnitManifestShard.model_validate(_json_object(item[0])),
            artifact_ref=ExactArtifactRef(
                artifact_uri=item[1],
                version_id=item[2],
                sha256=item[3],
                size_bytes=item[4],
                media_type=item[5],
            ),
        )
        for item in shard_rows
    )
    if not shards:
        raise PublicationConflict("AUTHORITY_CHAIN_MISSING")
    return RuleUnitManifestMaterialization(root=root, root_ref=root_ref, shards=shards)


def _load_retained_projection_authority(
    connection: Any,
    *,
    source_id: str,
    generation_id: str,
    attestation: KnowledgeProjectionAttestation,
) -> tuple[ProjectionAuthorityDocument, ...]:
    coverage = tuple(attestation.covered_publication_sequences)
    rows = connection.execute(
        """
        SELECT m.source_publication_seq, sh.shard_json
          FROM hybrid_rule_unit_manifest m
          JOIN hybrid_rule_unit_manifest_member mm ON mm.root_sha256=m.root_sha256
          JOIN hybrid_rule_unit_manifest_shard sh ON sh.shard_sha256=mm.shard_sha256
         WHERE m.source_id=%s AND m.generation_id=%s
           AND m.source_publication_seq = ANY(%s)
         ORDER BY m.source_publication_seq, mm.ordinal
        """,
        (source_id, generation_id, list(coverage)),
    ).fetchall()
    entries: dict[str, RuleUnitManifestEntry] = {}
    appearances: dict[str, list[int]] = {}
    for sequence, shard_json in rows:
        shard = RuleUnitManifestShard.model_validate(_json_object(shard_json))
        for entry in shard.entries:
            previous = entries.setdefault(entry.rule_unit_revision_id, entry)
            previous_body = previous.model_dump(mode="json")
            entry_body = entry.model_dump(mode="json")
            previous_body.pop("publication_seq_to", None)
            entry_body.pop("publication_seq_to", None)
            if previous_body != entry_body:
                raise PublicationConflict("MANIFEST_MISMATCH")
            appearances.setdefault(entry.rule_unit_revision_id, []).append(sequence)
    position = {sequence: ordinal for ordinal, sequence in enumerate(coverage)}
    last_attempt_sequence: dict[str, int] = {}
    for rule_id, sequences in appearances.items():
        positions = [position[sequence] for sequence in sequences]
        if positions != list(range(positions[0], positions[-1] + 1)):
            raise PublicationConflict("MEMBERSHIP_INTERVAL_AMBIGUOUS")
        next_position = positions[-1] + 1
        if next_position < len(coverage):
            close_publication_sequence = coverage[next_position]
            entries[rule_id] = entries[rule_id].model_copy(
                update={"publication_seq_to": close_publication_sequence - 1}
            )
            last_attempt_sequence[rule_id] = close_publication_sequence
        else:
            entries[rule_id] = entries[rule_id].model_copy(update={"publication_seq_to": None})
            last_attempt_sequence[rule_id] = entries[rule_id].publication_seq_from
    attempt_rows = connection.execute(
        """SELECT reserved_sequence, attempt_id
             FROM hybrid_knowledge_publication_attempt
            WHERE source_id=%s AND generation_id=%s AND state='PUBLISHED'
              AND reserved_sequence = ANY(%s)""",
        (source_id, generation_id, list(set(last_attempt_sequence.values()))),
    ).fetchall()
    attempt_by_sequence = {row[0]: row[1] for row in attempt_rows}
    projection_rows = connection.execute(
        """
        SELECT r.rule_unit_revision_id, r.rule_unit_json, m.metadata_json,
               p.embedding_sha256, p.projection_material_sha256,
               p.immutable_projection_sha256
          FROM hybrid_knowledge_rule_unit_revision r
          JOIN hybrid_approved_rule_metadata m
            ON m.source_id=r.source_id AND m.metadata_revision_id=r.metadata_revision_id
          JOIN hybrid_projection_materialization p
            ON p.source_id=r.source_id AND p.generation_id=%s
           AND p.rule_unit_revision_id=r.rule_unit_revision_id
         WHERE r.source_id=%s AND r.rule_unit_revision_id = ANY(%s)
         ORDER BY r.rule_unit_revision_id
        """,
        (generation_id, source_id, list(entries)),
    ).fetchall()
    result: list[ProjectionAuthorityDocument] = []
    for row in projection_rows:
        rule_id = row[0]
        payload = _json_object(row[1])
        attempt_id = attempt_by_sequence.get(last_attempt_sequence[rule_id])
        if attempt_id is None:
            raise PublicationConflict("AUTHORITY_CHAIN_MISSING")
        result.append(
            ProjectionAuthorityDocument(
                projection_id=_json_string(payload["projection_id"], field="projection_id"),
                rule_unit=InsuranceRuleUnitRevision.model_validate_json(
                    _canonical_json(_json_object(payload["rule_unit"]))
                ),
                manifest_entry=entries[rule_id],
                approved_metadata=ApprovedInsuranceRuleMetadataRevision.model_validate_json(
                    _canonical_json(_json_object(row[2]))
                ),
                projection_revision=_json_string(
                    payload["projection_revision"], field="projection_revision"
                ),
                embedding_sha256=row[3],
                projection_material_sha256=row[4],
                immutable_projection_sha256=row[5],
                last_publication_attempt_id=attempt_id,
            )
        )
    if len(result) != len(entries):
        raise PublicationConflict("PROJECTION_AUTHORITY_MISMATCH")
    return tuple(result)


def _attempt_from_row(row: Any) -> KnowledgePublicationAttempt:
    return KnowledgePublicationAttempt(
        attempt_id=row[0],
        source_id=row[1],
        source_draft_version_id=row[2],
        candidate_digest=row[3],
        reserved_publication_seq=row[4],
        fencing_token=row[5],
        generation_id=row[6],
        validation_id=row[7],
        state=row[8],
        started_at=row[9],
        updated_at=row[10],
    )


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _json_object(value: object) -> dict[str, object]:
    if isinstance(value, str):
        parsed = json.loads(value)
    else:
        parsed = value
    if not isinstance(parsed, dict):
        raise PublicationConflict("AUTHORITY_CHAIN_MISSING")
    return parsed


def _json_string(value: object, *, field: str) -> str:
    if type(value) is not str or not value:
        raise PublicationConflict(f"AUTHORITY_{field.upper()}_MISSING")
    return value


def _artifact_ref_id(ref: ExactArtifactRef) -> str:
    digest = hashlib.sha256(
        _canonical_json(ref.model_dump(mode="json")).encode("utf-8")
    ).hexdigest()
    return f"artifact-ref-{digest}"


def _rebuild_projection_authority(row: Any) -> RebuildProjectionAuthority:
    payload = _json_object(row[0])
    rule = InsuranceRuleUnitRevision.model_validate(payload["rule_unit"])
    visibility = _json_object(row[2])
    if rule.visibility_scope.model_dump(mode="json") != visibility:
        raise PublicationConflict("PROJECTION_AUTHORITY_MISMATCH")
    return RebuildProjectionAuthority(
        projection_id=_json_string(payload["projection_id"], field="projection_id"),
        projection_revision=_json_string(
            payload["projection_revision"], field="projection_revision"
        ),
        rule_unit=rule,
        approved_metadata=ApprovedInsuranceRuleMetadataRevision.model_validate(
            _json_object(row[1])
        ),
    )
