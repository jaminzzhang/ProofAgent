"""PostgreSQL authority adapter for fenced Hybrid Knowledge publication."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import json
from typing import Any, Iterator, cast
from uuid import uuid4

from pydantic import BaseModel

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
from proof_agent.capabilities.knowledge.hybrid.versioning import (
    projection_attestation_fingerprint,
    rebuild_projection_locator,
)
from proof_agent.capabilities.knowledge.hybrid.ports import (
    ProjectionAuthorityDocument,
    SearchIndexIdentity,
)
from proof_agent.configuration.hybrid_knowledge_repository import (
    HybridKnowledgeBindingAuthoritySnapshot,
)
from proof_agent.capabilities.knowledge.hybrid.recovery import (
    GenerationRebuildAuthority,
    GenerationRebuildOperation,
    GenerationRebuildValidation,
    OrphanProjection,
    RebuildProjectionOrphan,
    RebuildProjectionAuthority,
    RebuildSwapResolution,
    RetainedManifestAuthority,
)
from proof_agent.contracts.knowledge_index import (
    ExactArtifactRef,
    HybridKnowledgePublicationRecord,
    KnowledgeIndexGeneration,
    KnowledgeProjectionAttestation,
    KnowledgePublicationAttempt,
    KnowledgeRetrievalProfileRevision,
    RuleUnitManifestEntry,
    RuleUnitManifestRoot,
    RuleUnitManifestShard,
)
from proof_agent.contracts.insurance_rules import (
    ApprovedInsuranceRuleMetadataRevision,
    InsuranceRuleUnitRevision,
)


MAX_AUTHORITY_BATCH_SIZE = 1000


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
                _hydrate_jsonb_model(KnowledgeProjectionAttestation, projection_row[0])
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
        return _hydrate_jsonb_model(HybridKnowledgePublicationRecord, row[0])

    def publish_retrieval_profile(
        self,
        *,
        source_id: str,
        profile: KnowledgeRetrievalProfileRevision,
        make_default: bool = False,
    ) -> None:
        """Persist one immutable query-time profile and optionally select it as default."""

        if any(item.source_id != source_id for item in profile.enabled_degradations):
            raise ValueError("retrieval profile degradations must match the owning Source")
        profile_json = profile.model_dump(mode="json")
        profile_digest = stable_digest(profile_json)
        now = datetime.now(UTC)
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO hybrid_knowledge_retrieval_profile
                  (profile_revision_id, source_id, profile_digest, profile_json, created_at)
                VALUES (%s,%s,%s,%s::jsonb,%s)
                ON CONFLICT (profile_revision_id) DO NOTHING
                """,
                (
                    profile.profile_revision_id,
                    source_id,
                    profile_digest,
                    _canonical_json(profile_json),
                    now,
                ),
            )
            stored = connection.execute(
                """
                SELECT source_id, profile_digest, profile_json
                  FROM hybrid_knowledge_retrieval_profile
                 WHERE profile_revision_id=%s
                """,
                (profile.profile_revision_id,),
            ).fetchone()
            if (
                stored is None
                or stored[0] != source_id
                or stored[1] != profile_digest
                or _json_object(stored[2]) != profile_json
            ):
                raise PublicationConflict("RETRIEVAL_PROFILE_CONFLICT")
            if make_default:
                connection.execute(
                    """
                    INSERT INTO hybrid_knowledge_source_retrieval_profile_default
                      (source_id, profile_revision_id, updated_at)
                    VALUES (%s,%s,%s)
                    ON CONFLICT (source_id) DO UPDATE
                      SET profile_revision_id=EXCLUDED.profile_revision_id,
                          updated_at=EXCLUDED.updated_at
                    """,
                    (source_id, profile.profile_revision_id, now),
                )

    def resolve_binding_authority(
        self,
        *,
        source_id: str,
        profile_revision_id: str | None,
    ) -> HybridKnowledgeBindingAuthoritySnapshot | None:
        """Atomically resolve the active publication and explicit/default profile."""

        with self._connection() as connection:
            selected = connection.execute(
                """
                SELECT source.active_publication_id,
                       COALESCE(%s::text, default_profile.profile_revision_id)
                  FROM hybrid_knowledge_source_authority source
                  LEFT JOIN hybrid_knowledge_source_retrieval_profile_default default_profile
                    ON default_profile.source_id=source.source_id
                 WHERE source.source_id=%s
                """,
                (profile_revision_id, source_id),
            ).fetchone()
            if selected is None or selected[0] is None or selected[1] is None:
                return None
            publication_row = connection.execute(
                """
                SELECT publication_json
                  FROM hybrid_knowledge_publication
                 WHERE publication_id=%s AND source_id=%s
                """,
                (selected[0], source_id),
            ).fetchone()
            profile_row = connection.execute(
                """
                SELECT profile_json
                  FROM hybrid_knowledge_retrieval_profile
                 WHERE profile_revision_id=%s AND source_id=%s
                """,
                (selected[1], source_id),
            ).fetchone()
        if publication_row is None or profile_row is None:
            return None
        return HybridKnowledgeBindingAuthoritySnapshot(
            publication=_hydrate_jsonb_model(
                HybridKnowledgePublicationRecord,
                publication_row[0],
            ),
            retrieval_profile=_hydrate_jsonb_model(
                KnowledgeRetrievalProfileRevision,
                profile_row[0],
            ),
        )

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

    def list_orphan_projections(
        self, source_id: str
    ) -> tuple[OrphanProjection | RebuildProjectionOrphan, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT o.attempt_id, o.source_id, o.state, o.index_uuid,
                       g.generation_json, o.projection_locator, operation.operation_kind,
                       attempt.reserved_sequence
                  FROM hybrid_projection_orphan_cleanup o
                  JOIN hybrid_knowledge_generation g ON g.generation_id=o.generation_id
                  JOIN hybrid_projection_operation operation
                    ON operation.operation_id=o.attempt_id
                  LEFT JOIN hybrid_knowledge_publication_attempt attempt
                    ON attempt.attempt_id=operation.operation_id
                 WHERE o.source_id=%s AND o.state IN ('PENDING','RETRY')
                 ORDER BY o.attempt_id
                """,
                (source_id,),
            ).fetchall()
        result: list[OrphanProjection | RebuildProjectionOrphan] = []
        for row in rows:
            generation = _hydrate_jsonb_model(KnowledgeIndexGeneration, row[4])
            if row[6] == "REBUILD":
                result.append(
                    RebuildProjectionOrphan(
                        attempt_id=row[0],
                        source_id=row[1],
                        state=row[2],
                        generation=generation,
                        index_uuid=row[3],
                        projection_locator=row[5],
                    )
                )
            else:
                if (
                    row[6] != "PUBLICATION"
                    or row[3] is None
                    or type(row[7]) is not int
                    or row[7] <= 0
                ):
                    raise PublicationConflict("PROJECTION_AUTHORITY_MISMATCH")
                result.append(
                    OrphanProjection(
                        attempt_id=row[0],
                        source_id=row[1],
                        state=row[2],
                        identity=SearchIndexIdentity(
                            generation=generation,
                            index_uuid=row[3],
                            projection_locator=row[5],
                        ),
                        reserved_publication_seq=row[7],
                    )
                )
        return tuple(result)

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

    def record_orphan_purged(self, attempt_id: str) -> None:
        with self._connection() as connection:
            updated = connection.execute(
                """UPDATE hybrid_projection_orphan_cleanup
                      SET state='PURGED', last_failure_code=NULL, updated_at=%s
                    WHERE attempt_id=%s AND state IN ('PENDING','RETRY')""",
                (datetime.now(UTC), attempt_id),
            )
            if updated.rowcount != 1:
                raise PublicationConflict("CLEANUP_STATE")

    def record_orphan_resolved(self, attempt_id: str) -> None:
        with self._connection() as connection:
            updated = connection.execute(
                """UPDATE hybrid_projection_orphan_cleanup
                      SET state='RESOLVED', last_failure_code=NULL, updated_at=%s
                    WHERE attempt_id=%s AND state IN ('PENDING','RETRY')""",
                (datetime.now(UTC), attempt_id),
            )
            if updated.rowcount != 1:
                raise PublicationConflict("CLEANUP_STATE")

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
            current_attestation = _hydrate_jsonb_model(KnowledgeProjectionAttestation, row[9])
            retained_rows: list[Any] = []
            for sequence_batch in _bounded_batches(
                current_attestation.covered_publication_sequences
            ):
                retained_rows.extend(
                    connection.execute(
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
                        (source_id, generation_id, list(sequence_batch)),
                    ).fetchall()
                )
            rule_ids = tuple(
                sorted(
                    {
                        entry.rule_unit_revision_id
                        for item in retained_rows
                        for entry in _hydrate_jsonb_model(RuleUnitManifestShard, item[11]).entries
                    }
                )
            )
            projection_documents = _load_retained_projection_authority(
                connection,
                source_id=source_id,
                generation_id=generation_id,
                attestation=current_attestation,
            )
            if {item.rule_unit.rule_unit_revision_id for item in projection_documents} != set(
                rule_ids
            ):
                raise PublicationConflict("PROJECTION_AUTHORITY_MISMATCH")
        root = _hydrate_jsonb_model(RuleUnitManifestRoot, row[1])
        generation = _hydrate_jsonb_model(KnowledgeIndexGeneration, row[10])
        retained_by_root: dict[str, dict[str, object]] = {}
        for item in retained_rows:
            retained_root = _hydrate_jsonb_model(RuleUnitManifestRoot, item[0])
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
                RebuildProjectionAuthority(
                    projection_id=item.projection_id,
                    projection_revision=item.projection_revision,
                    rule_unit=item.rule_unit,
                    approved_metadata=item.approved_metadata,
                    last_publication_attempt_id=item.last_publication_attempt_id,
                )
                for item in projection_documents
            ),
            retained_manifests=retained_manifests,
        )

    def begin_generation_rebuild(
        self, authority: GenerationRebuildAuthority
    ) -> GenerationRebuildOperation:
        operation_id = f"rebuild-{uuid4().hex}"
        locator = rebuild_projection_locator(
            source_id=authority.source_id,
            generation_id=authority.generation_id,
            operation_id=operation_id,
        )
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
            inserted = connection.execute(
                """INSERT INTO hybrid_projection_operation
                    (operation_id, source_id, generation_id, operation_kind,
                     state, projection_locator, created_at, updated_at)
                    VALUES (%s,%s,%s,'REBUILD','BUILDING',%s,%s,%s)""",
                (
                    operation_id,
                    authority.source_id,
                    authority.generation_id,
                    locator,
                    now,
                    now,
                ),
            )
            if inserted.rowcount != 1:
                raise PublicationConflict("REBUILD_OPERATION_CONFLICT")
        return GenerationRebuildOperation(
            operation_id=operation_id,
            source_id=authority.source_id,
            generation_id=authority.generation_id,
            projection_locator=locator,
        )

    def fail_recovery_operation(
        self,
        operation_id: str,
        failure_code: str,
        projection_identity: SearchIndexIdentity | None = None,
        *,
        requires_reconciliation: bool = False,
    ) -> None:
        with self._connection() as connection:
            row = connection.execute(
                """SELECT source_id, generation_id, projection_locator, index_uuid
                    FROM hybrid_projection_operation
                    WHERE operation_id=%s AND operation_kind='REBUILD' FOR UPDATE""",
                (operation_id,),
            ).fetchone()
            if row is None:
                return
            updated = connection.execute(
                """UPDATE hybrid_projection_operation
                      SET state='FAILED', failure_code=%s, updated_at=%s
                    WHERE operation_id=%s AND operation_kind='REBUILD'
                      AND state IN ('BUILDING','VALIDATED')""",
                (failure_code, datetime.now(UTC), operation_id),
            )
            if updated.rowcount not in {0, 1}:
                raise PublicationConflict("REBUILD_OPERATION_STATE")
            if projection_identity is not None and (
                projection_identity.projection_locator != row[2]
                or projection_identity.generation.source_id != row[0]
                or projection_identity.generation.generation_id != row[1]
            ):
                raise PublicationConflict("REBUILD_LOCATOR_MISMATCH")
            index_uuid = (
                projection_identity.index_uuid if projection_identity is not None else row[3]
            )
            if requires_reconciliation and row[2] is not None:
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
                        index_uuid,
                        row[2],
                        datetime.now(UTC),
                    ),
                )

    def resolve_rebuild_swap(
        self,
        *,
        operation: GenerationRebuildOperation,
        authority: GenerationRebuildAuthority,
        rebuilt_identity: SearchIndexIdentity | None,
        attestation: KnowledgeProjectionAttestation | None,
    ) -> RebuildSwapResolution:
        with self._connection() as connection:
            row = connection.execute(
                """SELECT operation.source_id, operation.generation_id,
                          operation.operation_kind, operation.state,
                          operation.projection_locator, operation.index_uuid,
                          gp.index_uuid, gp.projection_locator, gp.attestation_sha256
                     FROM hybrid_projection_operation operation
                     LEFT JOIN hybrid_generation_projection gp
                       ON gp.source_id=operation.source_id
                      AND gp.generation_id=operation.generation_id
                    WHERE operation.operation_id=%s""",
                (operation.operation_id,),
            ).fetchone()
        if (
            row is None
            or row[0] != operation.source_id
            or row[1] != operation.generation_id
            or row[2] != "REBUILD"
            or row[4] != operation.projection_locator
        ):
            return RebuildSwapResolution(state="RECONCILIATION_REQUIRED")
        if (
            rebuilt_identity is not None
            and attestation is not None
            and row[3] == "COMMITTED"
            and row[5] == rebuilt_identity.index_uuid
            and row[6:]
            == (
                rebuilt_identity.index_uuid,
                rebuilt_identity.projection_locator,
                attestation.attestation_sha256,
            )
        ):
            return RebuildSwapResolution(state="COMMITTED")
        if row[3] in {"BUILDING", "VALIDATED"} and row[6:] == (
            authority.current_identity.index_uuid,
            authority.current_identity.projection_locator,
            authority.current_attestation.attestation_sha256,
        ):
            return RebuildSwapResolution(state="PARENT_CURRENT")
        return RebuildSwapResolution(state="RECONCILIATION_REQUIRED")

    def rebuild_orphan_is_active(
        self,
        orphan: RebuildProjectionOrphan,
        identity: SearchIndexIdentity,
    ) -> bool:
        with self._connection() as connection:
            row = connection.execute(
                """SELECT index_uuid, projection_locator
                     FROM hybrid_generation_projection
                    WHERE source_id=%s AND generation_id=%s""",
                (orphan.source_id, orphan.generation.generation_id),
            ).fetchone()
        return bool(row == (identity.index_uuid, identity.projection_locator))

    def record_rebuild_projection_identity(
        self,
        orphan: RebuildProjectionOrphan,
        identity: SearchIndexIdentity,
    ) -> None:
        if (
            identity.generation != orphan.generation
            or identity.projection_locator != orphan.projection_locator
            or (orphan.index_uuid is not None and orphan.index_uuid != identity.index_uuid)
        ):
            raise PublicationConflict("REBUILD_IDENTITY_MISMATCH")
        with self._connection() as connection:
            operation = connection.execute(
                """UPDATE hybrid_projection_operation SET index_uuid=%s, updated_at=%s
                    WHERE operation_id=%s AND source_id=%s AND generation_id=%s
                      AND operation_kind='REBUILD' AND projection_locator=%s
                      AND (index_uuid IS NULL OR index_uuid=%s)""",
                (
                    identity.index_uuid,
                    datetime.now(UTC),
                    orphan.attempt_id,
                    orphan.source_id,
                    orphan.generation.generation_id,
                    orphan.projection_locator,
                    identity.index_uuid,
                ),
            )
            cleanup = connection.execute(
                """UPDATE hybrid_projection_orphan_cleanup SET index_uuid=%s, updated_at=%s
                    WHERE attempt_id=%s AND source_id=%s AND generation_id=%s
                      AND projection_locator=%s AND state IN ('PENDING','RETRY')
                      AND (index_uuid IS NULL OR index_uuid=%s)""",
                (
                    identity.index_uuid,
                    datetime.now(UTC),
                    orphan.attempt_id,
                    orphan.source_id,
                    orphan.generation.generation_id,
                    orphan.projection_locator,
                    identity.index_uuid,
                ),
            )
            if operation.rowcount != 1 or cleanup.rowcount != 1:
                raise PublicationConflict("REBUILD_IDENTITY_MISMATCH")

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
                """SELECT operation.source_id, operation.generation_id,
                          operation.operation_kind, operation.state,
                          operation.projection_locator,
                          operation.index_uuid,
                          validation.parent_attestation_sha256,
                          validation.attestation_sha256,
                          validation.validation_sha256, validation.validation_json,
                          gp.index_uuid, gp.projection_locator, gp.attestation_sha256
                     FROM hybrid_projection_operation operation
                     JOIN hybrid_rebuild_validation validation
                       ON validation.operation_id=operation.operation_id
                      AND validation.source_id=operation.source_id
                      AND validation.generation_id=operation.generation_id
                     JOIN hybrid_generation_projection gp
                       ON gp.source_id=operation.source_id
                      AND gp.generation_id=operation.generation_id
                    WHERE operation.operation_id=%s
                    FOR UPDATE OF operation, gp""",
                (attestation.publication_attempt_id,),
            ).fetchone()
            _validate_staged_rebuild_swap(
                authority=authority,
                rebuilt_identity=rebuilt_identity,
                attestation=attestation,
                database_row=current,
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
            committed = connection.execute(
                """UPDATE hybrid_projection_operation SET state='COMMITTED', updated_at=%s
                    WHERE operation_id=%s AND source_id=%s AND generation_id=%s
                      AND operation_kind='REBUILD' AND state='VALIDATED'
                      AND index_uuid=%s AND projection_locator=%s""",
                (
                    now,
                    attestation.publication_attempt_id,
                    authority.source_id,
                    authority.generation_id,
                    rebuilt_identity.index_uuid,
                    current[4],
                ),
            )
            if committed.rowcount != 1:
                raise PublicationConflict("FENCE_LOST")

    def stage_generation_rebuild_validation(
        self,
        *,
        authority: GenerationRebuildAuthority,
        rebuilt_identity: SearchIndexIdentity,
        attestation: KnowledgeProjectionAttestation,
    ) -> GenerationRebuildValidation:
        """Build and persist DB-derived rebuild authority before the short pointer CAS."""

        operation_id = attestation.publication_attempt_id
        now = datetime.now(UTC)
        with self._connection() as connection:
            immutable_guard = connection.execute(
                """SELECT EXISTS (
                     SELECT 1
                       FROM pg_trigger trigger
                       JOIN pg_class relation ON relation.oid=trigger.tgrelid
                       JOIN pg_namespace namespace ON namespace.oid=relation.relnamespace
                       JOIN pg_proc procedure ON procedure.oid=trigger.tgfoid
                      WHERE namespace.nspname=current_schema()
                        AND relation.relname='hybrid_projection_materialization'
                        AND trigger.tgname='reject_update'
                        AND trigger.tgenabled='O'
                        AND NOT trigger.tgisinternal
                        AND (trigger.tgtype & 24)=24
                        AND procedure.proname='reject_hybrid_immutable_update'
                   )"""
            ).fetchone()
            if immutable_guard is None or immutable_guard[0] is not True:
                raise PublicationConflict("IMMUTABLE_AUTHORITY_GUARD_MISSING")
            current = connection.execute(
                """SELECT operation.source_id, operation.generation_id,
                          operation.operation_kind, operation.state,
                          operation.projection_locator,
                          gp.index_uuid, gp.projection_locator, gp.attestation_sha256,
                          parent.attestation_json, generation.generation_json,
                          publication.candidate_digest, publication.manifest_root_sha256
                     FROM hybrid_projection_operation operation
                     JOIN hybrid_generation_projection gp
                       ON gp.source_id=operation.source_id
                      AND gp.generation_id=operation.generation_id
                     JOIN hybrid_projection_attestation parent
                       ON parent.attestation_sha256=gp.attestation_sha256
                     JOIN hybrid_knowledge_generation generation
                       ON generation.source_id=operation.source_id
                      AND generation.generation_id=operation.generation_id
                     JOIN LATERAL (
                       SELECT candidate_digest, manifest_root_sha256
                         FROM hybrid_knowledge_publication publication
                        WHERE publication.source_id=operation.source_id
                          AND publication.generation_id=operation.generation_id
                        ORDER BY source_publication_seq DESC LIMIT 1
                     ) publication ON TRUE
                    WHERE operation.operation_id=%s""",
                (operation_id,),
            ).fetchone()
            if current is None:
                raise PublicationConflict("FENCE_LOST")
            stored_parent = _hydrate_jsonb_model(KnowledgeProjectionAttestation, current[8])
            stored_documents = _load_retained_projection_authority(
                connection,
                source_id=current[0],
                generation_id=current[1],
                attestation=stored_parent,
            )
            expected_documents = stored_documents
            _validate_stored_projection_materialization(
                expected_documents,
                generation=_hydrate_jsonb_model(KnowledgeIndexGeneration, current[9]),
            )
            expected_projection_sha256 = _projection_authority_digest(expected_documents)
            _validate_rebuild_swap_authority(
                authority=authority,
                rebuilt_identity=rebuilt_identity,
                attestation=attestation,
                database_row=current,
                expected_documents=expected_documents,
                expected_projection_sha256=expected_projection_sha256,
                allowed_operation_states=frozenset({"BUILDING", "VALIDATED"}),
            )
            validation = GenerationRebuildValidation(
                operation_id=operation_id,
                source_id=authority.source_id,
                generation_id=authority.generation_id,
                projection_locator=current[4],
                index_uuid=rebuilt_identity.index_uuid,
                parent_index_uuid=authority.current_identity.index_uuid,
                parent_projection_locator=authority.current_identity.projection_locator,
                parent_attestation_sha256=authority.current_attestation.attestation_sha256,
                candidate_digest=authority.candidate_digest,
                manifest_root_sha256=authority.manifest_root.root_sha256,
                mapping_sha256=attestation.mapping_sha256,
                covered_publication_sequences=attestation.covered_publication_sequences,
                projection_sha256=expected_projection_sha256,
                validated_document_count=len(
                    {item.rule_unit.document_id for item in expected_documents}
                ),
                validated_rule_unit_count=len(expected_documents),
                attestation_sha256=attestation.attestation_sha256,
            )
            validation_sha256 = _rebuild_validation_fingerprint(validation)
            inserted = connection.execute(
                """INSERT INTO hybrid_rebuild_validation
                    (operation_id, source_id, generation_id, projection_locator,
                     index_uuid, parent_attestation_sha256, attestation_sha256,
                     validation_sha256, validation_json, created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
                    ON CONFLICT (operation_id) DO NOTHING""",
                (
                    operation_id,
                    authority.source_id,
                    authority.generation_id,
                    validation.projection_locator,
                    rebuilt_identity.index_uuid,
                    validation.parent_attestation_sha256,
                    validation.attestation_sha256,
                    validation_sha256,
                    _canonical_json(validation.model_dump(mode="json")),
                    now,
                ),
            )
            staged = connection.execute(
                """SELECT source_id, generation_id, projection_locator, index_uuid,
                          parent_attestation_sha256, attestation_sha256,
                          validation_sha256, validation_json
                     FROM hybrid_rebuild_validation WHERE operation_id=%s""",
                (operation_id,),
            ).fetchone()
            _validate_staged_rebuild_record(
                expected=validation,
                expected_validation_sha256=validation_sha256,
                database_row=staged,
            )
            if inserted.rowcount == 1:
                validated = connection.execute(
                    """UPDATE hybrid_projection_operation operation
                          SET state='VALIDATED', index_uuid=%s, updated_at=%s
                        WHERE operation.operation_id=%s
                          AND operation.source_id=%s AND operation.generation_id=%s
                          AND operation.operation_kind='REBUILD'
                          AND operation.state='BUILDING'
                          AND operation.projection_locator=%s
                          AND EXISTS (
                            SELECT 1 FROM hybrid_generation_projection gp
                             WHERE gp.source_id=operation.source_id
                               AND gp.generation_id=operation.generation_id
                               AND gp.index_uuid=%s
                               AND gp.attestation_sha256=%s
                          )""",
                    (
                        rebuilt_identity.index_uuid,
                        now,
                        operation_id,
                        authority.source_id,
                        authority.generation_id,
                        validation.projection_locator,
                        validation.parent_index_uuid,
                        validation.parent_attestation_sha256,
                    ),
                )
                if validated.rowcount != 1:
                    raise PublicationConflict("FENCE_LOST")
            elif inserted.rowcount == 0:
                operation = connection.execute(
                    """SELECT state, index_uuid, projection_locator
                         FROM hybrid_projection_operation WHERE operation_id=%s""",
                    (operation_id,),
                ).fetchone()
                if operation != (
                    "VALIDATED",
                    rebuilt_identity.index_uuid,
                    validation.projection_locator,
                ):
                    raise PublicationConflict("REBUILD_VALIDATION_CONFLICT")
            else:
                raise PublicationConflict("REBUILD_VALIDATION_CONFLICT")
        return validation

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
        authorities = commit.staged_projection_documents
        expected_metadata: dict[str, str] = {}
        expected_visibility: dict[str, str] = {}
        expected_rules: dict[str, tuple[str, str]] = {}
        expected_materials: dict[str, tuple[str, str, str, str]] = {}
        for authority in authorities:
            rule = authority.rule_unit
            metadata = authority.approved_metadata
            visibility = rule.visibility_scope
            metadata_sha = stable_digest(metadata.model_dump(mode="json"))
            visibility_sha = stable_digest(visibility.model_dump(mode="json"))
            if (
                rule.lineage.source_id != commit.attempt.source_id
                or rule.authority_sha256
                != stable_digest(
                    {
                        "approved_metadata": metadata.model_dump(mode="json"),
                        "approved_visibility": visibility.model_dump(mode="json"),
                    }
                )
            ):
                raise PublicationConflict("ATTESTATION_MISMATCH")
            for target, key, value in (
                (expected_metadata, metadata.metadata_revision_id, metadata_sha),
                (expected_visibility, visibility.revision_id, visibility_sha),
            ):
                existing = target.setdefault(key, value)
                if existing != value:
                    raise PublicationConflict("PROJECTION_AUTHORITY_MISMATCH")
            expected_rules[rule.rule_unit_revision_id] = (
                rule.content_sha256,
                rule.authority_sha256,
            )
            expected_materials[authority.projection_id] = (
                rule.rule_unit_revision_id,
                authority.embedding_sha256,
                authority.projection_material_sha256,
                authority.immutable_projection_sha256,
            )

        with connection.cursor() as cursor:
            for batch in _bounded_batches(authorities):
                cursor.executemany(
                    """INSERT INTO hybrid_approved_rule_metadata
                    (source_id, metadata_revision_id, metadata_sha256, metadata_json, approved_at)
                    VALUES (%s,%s,%s,%s::jsonb,%s) ON CONFLICT DO NOTHING""",
                    [
                        (
                            item.rule_unit.lineage.source_id,
                            item.approved_metadata.metadata_revision_id,
                            stable_digest(item.approved_metadata.model_dump(mode="json")),
                            _canonical_json(item.approved_metadata.model_dump(mode="json")),
                            now,
                        )
                        for item in batch
                    ],
                )
                cursor.executemany(
                    """INSERT INTO hybrid_approved_visibility_scope
                    (source_id, visibility_revision_id, visibility_sha256,
                     visibility_json, approved_at)
                    VALUES (%s,%s,%s,%s::jsonb,%s) ON CONFLICT DO NOTHING""",
                    [
                        (
                            item.rule_unit.lineage.source_id,
                            item.rule_unit.visibility_scope.revision_id,
                            stable_digest(item.rule_unit.visibility_scope.model_dump(mode="json")),
                            _canonical_json(
                                item.rule_unit.visibility_scope.model_dump(mode="json")
                            ),
                            now,
                        )
                        for item in batch
                    ],
                )
                cursor.executemany(
                    """INSERT INTO hybrid_knowledge_document_revision
                    (source_id, document_id, revision_id, structured_build_id,
                     review_state, created_at)
                    VALUES (%s,%s,%s,%s,'NOT_REQUIRED',%s) ON CONFLICT DO NOTHING""",
                    [
                        (
                            item.rule_unit.lineage.source_id,
                            item.rule_unit.document_id,
                            item.rule_unit.revision_id,
                            item.rule_unit.structured_build_id,
                            now,
                        )
                        for item in batch
                    ],
                )
                cursor.executemany(
                    """INSERT INTO hybrid_knowledge_rule_unit_revision
                    (rule_unit_revision_id, source_id, document_id, revision_id,
                     structured_build_id, metadata_revision_id, visibility_revision_id,
                     content_sha256, authority_sha256, rule_unit_json, approved_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
                    ON CONFLICT DO NOTHING""",
                    [
                        (
                            item.rule_unit.rule_unit_revision_id,
                            item.rule_unit.lineage.source_id,
                            item.rule_unit.document_id,
                            item.rule_unit.revision_id,
                            item.rule_unit.structured_build_id,
                            item.rule_unit.metadata_revision_id,
                            item.rule_unit.visibility_scope.revision_id,
                            item.rule_unit.content_sha256,
                            item.rule_unit.authority_sha256,
                            _canonical_json(
                                {
                                    "rule_unit": item.rule_unit.model_dump(mode="json"),
                                    "projection_id": item.projection_id,
                                    "projection_revision": item.projection_revision,
                                }
                            ),
                            now,
                        )
                        for item in batch
                    ],
                )
                cursor.executemany(
                    """INSERT INTO hybrid_projection_materialization
                  (source_id, generation_id, projection_id, rule_unit_revision_id,
                   embedding_sha256, projection_material_sha256,
                   immutable_projection_sha256, created_attempt_id, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                    [
                        (
                            item.rule_unit.lineage.source_id,
                            commit.attempt.generation_id,
                            item.projection_id,
                            item.rule_unit.rule_unit_revision_id,
                            item.embedding_sha256,
                            item.projection_material_sha256,
                            item.immutable_projection_sha256,
                            item.last_publication_attempt_id,
                            now,
                        )
                        for item in batch
                    ],
                )

        self._verify_projection_authority_batches(
            connection,
            source_id=commit.attempt.source_id,
            generation_id=commit.attempt.generation_id,
            metadata=expected_metadata,
            visibility=expected_visibility,
            rules=expected_rules,
            materials=expected_materials,
        )

    @staticmethod
    def _verify_projection_authority_batches(
        connection: Any,
        *,
        source_id: str,
        generation_id: str,
        metadata: dict[str, str],
        visibility: dict[str, str],
        rules: dict[str, tuple[str, str]],
        materials: dict[str, tuple[str, str, str, str]],
    ) -> None:
        actual_metadata: dict[str, str] = {}
        for batch in _bounded_batches(tuple(sorted(metadata))):
            rows = connection.execute(
                """SELECT metadata_revision_id, metadata_sha256
                     FROM hybrid_approved_rule_metadata
                    WHERE source_id=%s AND metadata_revision_id = ANY(%s)""",
                (source_id, list(batch)),
            ).fetchall()
            actual_metadata.update(rows)
        actual_visibility: dict[str, str] = {}
        for batch in _bounded_batches(tuple(sorted(visibility))):
            rows = connection.execute(
                """SELECT visibility_revision_id, visibility_sha256
                     FROM hybrid_approved_visibility_scope
                    WHERE source_id=%s AND visibility_revision_id = ANY(%s)""",
                (source_id, list(batch)),
            ).fetchall()
            actual_visibility.update(rows)
        actual_rules: dict[str, tuple[str, str]] = {}
        for batch in _bounded_batches(tuple(sorted(rules))):
            rows = connection.execute(
                """SELECT rule_unit_revision_id, content_sha256, authority_sha256
                     FROM hybrid_knowledge_rule_unit_revision
                    WHERE source_id=%s AND rule_unit_revision_id = ANY(%s)""",
                (source_id, list(batch)),
            ).fetchall()
            actual_rules.update((row[0], (row[1], row[2])) for row in rows)
        actual_materials: dict[str, tuple[str, str, str, str]] = {}
        for batch in _bounded_batches(tuple(sorted(materials))):
            rows = connection.execute(
                """SELECT projection_id, rule_unit_revision_id, embedding_sha256,
                          projection_material_sha256, immutable_projection_sha256
                     FROM hybrid_projection_materialization
                    WHERE source_id=%s AND generation_id=%s
                      AND projection_id = ANY(%s)""",
                (source_id, generation_id, list(batch)),
            ).fetchall()
            actual_materials.update((row[0], tuple(row[1:])) for row in rows)
        if (
            actual_metadata != metadata
            or actual_visibility != visibility
            or actual_rules != rules
            or actual_materials != materials
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
    root = _hydrate_jsonb_model(RuleUnitManifestRoot, publication_row[1])
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
            shard=_hydrate_jsonb_model(RuleUnitManifestShard, item[0]),
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
    rows: list[Any] = []
    for coverage_batch in _bounded_batches(coverage):
        rows.extend(
            connection.execute(
                """
        SELECT m.source_publication_seq, sh.shard_json
          FROM hybrid_rule_unit_manifest m
          JOIN hybrid_rule_unit_manifest_member mm ON mm.root_sha256=m.root_sha256
          JOIN hybrid_rule_unit_manifest_shard sh ON sh.shard_sha256=mm.shard_sha256
         WHERE m.source_id=%s AND m.generation_id=%s
           AND m.source_publication_seq = ANY(%s)
         ORDER BY m.source_publication_seq, mm.ordinal
                """,
                (source_id, generation_id, list(coverage_batch)),
            ).fetchall()
        )
    entries: dict[str, RuleUnitManifestEntry] = {}
    appearances: dict[str, list[int]] = {}
    for sequence, shard_json in rows:
        shard = _hydrate_jsonb_model(RuleUnitManifestShard, shard_json)
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
    attempt_rows: list[Any] = []
    for sequence_batch in _bounded_batches(tuple(sorted(set(last_attempt_sequence.values())))):
        attempt_rows.extend(
            connection.execute(
                """SELECT reserved_sequence, attempt_id
             FROM hybrid_knowledge_publication_attempt
            WHERE source_id=%s AND generation_id=%s AND state='PUBLISHED'
              AND reserved_sequence = ANY(%s)""",
                (source_id, generation_id, list(sequence_batch)),
            ).fetchall()
        )
    attempt_by_sequence = {row[0]: row[1] for row in attempt_rows}
    projection_rows: list[Any] = []
    for rule_batch in _bounded_batches(tuple(sorted(entries))):
        projection_rows.extend(
            connection.execute(
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
                (generation_id, source_id, list(rule_batch)),
            ).fetchall()
        )
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
                rule_unit=_hydrate_jsonb_model(InsuranceRuleUnitRevision, payload["rule_unit"]),
                manifest_entry=entries[rule_id],
                approved_metadata=_hydrate_jsonb_model(
                    ApprovedInsuranceRuleMetadataRevision, row[2]
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


def _attestation_fingerprint(attestation: KnowledgeProjectionAttestation) -> str:
    return projection_attestation_fingerprint(
        source_id=attestation.source_id,
        generation_id=attestation.generation_id,
        publication_attempt_id=attestation.publication_attempt_id,
        index_uuid=attestation.index_uuid,
        refresh_checkpoint=attestation.refresh_checkpoint,
        manifest_root_sha256=attestation.manifest_root_sha256,
        mapping_sha256=attestation.mapping_sha256,
        covered_publication_sequences=attestation.covered_publication_sequences,
        parent_attestation_sha256=attestation.parent_attestation_sha256,
        projection_sha256=attestation.projection_sha256,
        validated_document_count=attestation.validated_document_count,
        validated_rule_unit_count=attestation.validated_rule_unit_count,
    )


def _validate_rebuild_swap_authority(
    *,
    authority: GenerationRebuildAuthority,
    rebuilt_identity: SearchIndexIdentity,
    attestation: KnowledgeProjectionAttestation,
    database_row: Any,
    expected_documents: tuple[ProjectionAuthorityDocument, ...] | None = None,
    expected_projection_sha256: str | None = None,
    allowed_operation_states: frozenset[str] = frozenset({"BUILDING"}),
) -> None:
    if database_row is None:
        raise PublicationConflict("FENCE_LOST")
    operation_id = attestation.publication_attempt_id
    expected_locator = rebuild_projection_locator(
        source_id=authority.source_id,
        generation_id=authority.generation_id,
        operation_id=operation_id,
    )
    parent = authority.current_attestation
    stored_parent = _hydrate_jsonb_model(KnowledgeProjectionAttestation, database_row[8])
    stored_generation = _hydrate_jsonb_model(KnowledgeIndexGeneration, database_row[9])
    digest = _attestation_fingerprint(attestation)
    repairing_current = rebuilt_identity == authority.current_identity
    expected_rebuild_authority = (
        tuple(
            RebuildProjectionAuthority(
                projection_id=item.projection_id,
                projection_revision=item.projection_revision,
                rule_unit=item.rule_unit,
                approved_metadata=item.approved_metadata,
                last_publication_attempt_id=item.last_publication_attempt_id,
            )
            for item in expected_documents
        )
        if expected_documents is not None
        else authority.projection_authority
    )
    expected_document_count = (
        len({item.rule_unit.document_id for item in expected_documents})
        if expected_documents is not None
        else len({item.rule_unit.document_id for item in authority.projection_authority})
    )
    expected_rule_unit_count = (
        len(expected_documents)
        if expected_documents is not None
        else len(authority.projection_authority)
    )
    if (
        database_row[:3]
        != (
            authority.source_id,
            authority.generation_id,
            "REBUILD",
        )
        or database_row[3] not in allowed_operation_states
        or database_row[4:8]
        != (
            expected_locator,
            authority.current_identity.index_uuid,
            authority.current_identity.projection_locator,
            parent.attestation_sha256,
        )
        or stored_parent != parent
        or _attestation_fingerprint(stored_parent) != stored_parent.attestation_sha256
        or stored_generation != authority.current_identity.generation
        or rebuilt_identity.generation != stored_generation
        or (not repairing_current and rebuilt_identity.projection_locator != expected_locator)
        or (
            rebuilt_identity.index_uuid == authority.current_identity.index_uuid
            and not repairing_current
        )
        or database_row[10] != authority.candidate_digest
        or database_row[11] != authority.manifest_root.root_sha256
        or tuple(
            sorted(
                authority.projection_authority,
                key=lambda item: item.rule_unit.rule_unit_revision_id,
            )
        )
        != tuple(
            sorted(
                expected_rebuild_authority,
                key=lambda item: item.rule_unit.rule_unit_revision_id,
            )
        )
        or authority.manifest_root.source_id != authority.source_id
        or authority.manifest_root.generation_id != authority.generation_id
        or attestation.source_id != authority.source_id
        or attestation.generation_id != authority.generation_id
        or attestation.index_uuid != rebuilt_identity.index_uuid
        or attestation.manifest_root_sha256 != authority.manifest_root.root_sha256
        or attestation.mapping_sha256 != stored_generation.mapping_sha256
        or attestation.parent_attestation_sha256 != parent.attestation_sha256
        or attestation.covered_publication_sequences != parent.covered_publication_sequences
        or attestation.validated_document_count != expected_document_count
        or attestation.validated_rule_unit_count != expected_rule_unit_count
        or (
            expected_projection_sha256 is not None
            and attestation.projection_sha256 != expected_projection_sha256
        )
        or digest != attestation.attestation_sha256
        or attestation.attestation_id != f"attestation-{digest}"
    ):
        raise PublicationConflict("ATTESTATION_MISMATCH")


def _projection_authority_digest(
    documents: tuple[ProjectionAuthorityDocument, ...],
) -> str:
    return stable_digest(
        {
            "schema_version": "hybrid-publication-projection.v2",
            "documents": [item.model_dump(mode="json") for item in documents],
        }
    )


def _validate_stored_projection_materialization(
    documents: tuple[ProjectionAuthorityDocument, ...],
    *,
    generation: KnowledgeIndexGeneration,
) -> None:
    projection_ids: set[str] = set()
    rule_ids: set[str] = set()
    for item in documents:
        rule = item.rule_unit
        entry = item.manifest_entry
        expected_material_sha256 = stable_digest(
            {
                "schema_version": "hybrid-projection-material.v1",
                "projection_id": item.projection_id,
                "rule_unit": rule.model_dump(mode="json"),
                "approved_metadata": item.approved_metadata.model_dump(mode="json"),
                "projection_revision": item.projection_revision,
                "embedding_sha256": item.embedding_sha256,
            }
        )
        expected_authority_sha256 = stable_digest(
            {
                "approved_metadata": item.approved_metadata.model_dump(mode="json"),
                "approved_visibility": rule.visibility_scope.model_dump(mode="json"),
            }
        )
        if (
            item.projection_id in projection_ids
            or rule.rule_unit_revision_id in rule_ids
            or rule.lineage.source_id != generation.source_id
            or item.projection_revision != generation.search_projection_version
            or hashlib.sha256(rule.content.encode("utf-8")).hexdigest() != rule.content_sha256
            or expected_authority_sha256 != rule.authority_sha256
            or expected_material_sha256 != item.projection_material_sha256
            or entry.rule_unit_revision_id != rule.rule_unit_revision_id
            or entry.document_id != rule.document_id
            or entry.revision_id != rule.revision_id
            or entry.structured_build_id != rule.structured_build_id
            or entry.metadata_revision_id != rule.metadata_revision_id
            or entry.visibility_revision_id != rule.visibility_scope.revision_id
            or entry.content_sha256 != rule.content_sha256
            or entry.authority_sha256 != rule.authority_sha256
            or entry.citation_uri != rule.citation_uri
        ):
            raise PublicationConflict("PROJECTION_AUTHORITY_MISMATCH")
        projection_ids.add(item.projection_id)
        rule_ids.add(rule.rule_unit_revision_id)


def _rebuild_validation_fingerprint(validation: GenerationRebuildValidation) -> str:
    return stable_digest(
        {
            "schema_version": "hybrid-rebuild-validation-authority.v1",
            "validation": validation.model_dump(mode="json"),
        }
    )


def _validate_staged_rebuild_record(
    *,
    expected: GenerationRebuildValidation,
    expected_validation_sha256: str,
    database_row: Any,
) -> None:
    if database_row is None:
        raise PublicationConflict("REBUILD_VALIDATION_CONFLICT")
    try:
        stored = _hydrate_jsonb_model(GenerationRebuildValidation, database_row[7])
    except (KeyError, TypeError, ValueError) as exc:
        raise PublicationConflict("REBUILD_VALIDATION_CONFLICT") from exc
    if (
        database_row[:7]
        != (
            expected.source_id,
            expected.generation_id,
            expected.projection_locator,
            expected.index_uuid,
            expected.parent_attestation_sha256,
            expected.attestation_sha256,
            expected_validation_sha256,
        )
        or stored != expected
        or _rebuild_validation_fingerprint(stored) != expected_validation_sha256
    ):
        raise PublicationConflict("REBUILD_VALIDATION_CONFLICT")


def _validate_staged_rebuild_swap(
    *,
    authority: GenerationRebuildAuthority,
    rebuilt_identity: SearchIndexIdentity,
    attestation: KnowledgeProjectionAttestation,
    database_row: Any,
) -> None:
    if database_row is None:
        raise PublicationConflict("FENCE_LOST")
    try:
        validation = _hydrate_jsonb_model(GenerationRebuildValidation, database_row[9])
    except (KeyError, TypeError, ValueError) as exc:
        raise PublicationConflict("REBUILD_VALIDATION_CONFLICT") from exc
    digest = _attestation_fingerprint(attestation)
    expected_locator = rebuild_projection_locator(
        source_id=authority.source_id,
        generation_id=authority.generation_id,
        operation_id=attestation.publication_attempt_id,
    )
    repairing_current = rebuilt_identity == authority.current_identity
    if (
        database_row[:9]
        != (
            authority.source_id,
            authority.generation_id,
            "REBUILD",
            "VALIDATED",
            expected_locator,
            rebuilt_identity.index_uuid,
            validation.parent_attestation_sha256,
            validation.attestation_sha256,
            _rebuild_validation_fingerprint(validation),
        )
        or database_row[10:]
        != (
            validation.parent_index_uuid,
            validation.parent_projection_locator,
            validation.parent_attestation_sha256,
        )
        or validation.operation_id != attestation.publication_attempt_id
        or validation.source_id != authority.source_id
        or validation.generation_id != authority.generation_id
        or validation.projection_locator != expected_locator
        or validation.index_uuid != rebuilt_identity.index_uuid
        or validation.parent_index_uuid != authority.current_identity.index_uuid
        or validation.parent_projection_locator != authority.current_identity.projection_locator
        or validation.parent_attestation_sha256 != authority.current_attestation.attestation_sha256
        or validation.candidate_digest != authority.candidate_digest
        or validation.manifest_root_sha256 != authority.manifest_root.root_sha256
        or validation.mapping_sha256 != rebuilt_identity.generation.mapping_sha256
        or validation.covered_publication_sequences
        != authority.current_attestation.covered_publication_sequences
        or validation.projection_sha256 != attestation.projection_sha256
        or validation.validated_document_count != attestation.validated_document_count
        or validation.validated_rule_unit_count != attestation.validated_rule_unit_count
        or validation.attestation_sha256 != attestation.attestation_sha256
        or attestation.source_id != authority.source_id
        or attestation.generation_id != authority.generation_id
        or attestation.index_uuid != rebuilt_identity.index_uuid
        or attestation.parent_attestation_sha256 != authority.current_attestation.attestation_sha256
        or attestation.manifest_root_sha256 != authority.manifest_root.root_sha256
        or attestation.mapping_sha256 != rebuilt_identity.generation.mapping_sha256
        or rebuilt_identity.generation != authority.current_identity.generation
        or (not repairing_current and rebuilt_identity.projection_locator != expected_locator)
        or digest != attestation.attestation_sha256
        or attestation.attestation_id != f"attestation-{digest}"
    ):
        raise PublicationConflict("REBUILD_VALIDATION_CONFLICT")


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _bounded_batches[T](values: tuple[T, ...]) -> Iterator[tuple[T, ...]]:
    for offset in range(0, len(values), MAX_AUTHORITY_BATCH_SIZE):
        yield values[offset : offset + MAX_AUTHORITY_BATCH_SIZE]


def _json_object(value: object) -> dict[str, object]:
    if isinstance(value, str):
        parsed = json.loads(value)
    else:
        parsed = value
    if not isinstance(parsed, dict):
        raise PublicationConflict("AUTHORITY_CHAIN_MISSING")
    return parsed


def _hydrate_jsonb_model[T: BaseModel](model: type[T], value: object) -> T:
    """Hydrate strict contracts using JSON semantics at the PostgreSQL jsonb boundary."""

    return model.model_validate_json(_canonical_json(_json_object(value)))


def _json_string(value: object, *, field: str) -> str:
    if type(value) is not str or not value:
        raise PublicationConflict(f"AUTHORITY_{field.upper()}_MISSING")
    return value


def _artifact_ref_id(ref: ExactArtifactRef) -> str:
    digest = hashlib.sha256(
        _canonical_json(ref.model_dump(mode="json")).encode("utf-8")
    ).hexdigest()
    return f"artifact-ref-{digest}"
