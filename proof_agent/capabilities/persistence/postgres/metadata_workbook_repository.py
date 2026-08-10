"""PostgreSQL authority for one-use Insurance Metadata Workbook V2 resources."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import json
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import null, select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.sql.elements import ColumnElement

from proof_agent.capabilities.knowledge.hybrid.metadata_review import (
    MetadataReviewValidationError,
)
from proof_agent.capabilities.knowledge.hybrid.metadata_workbook import (
    MetadataWorkbookApplyCommitV2,
    MetadataWorkbookExportAuthorityV2,
    MetadataWorkbookExportManifestV2,
    MetadataWorkbookImportPreviewAuthorityV2,
    MetadataWorkbookImportPreviewV2,
    MetadataWorkbookValidationReportV2,
)
from proof_agent.capabilities.knowledge.hybrid.metadata_workbook_jobs import (
    MetadataWorkbookJobClaimV2,
    MetadataWorkbookJobV2,
)
from proof_agent.capabilities.persistence.postgres._common import (
    ConnectionSource,
    model_json,
    read_connection,
    write_connection,
)
from proof_agent.capabilities.persistence.postgres.knowledge_repository import (
    PostgresKnowledgeAssetRepository,
)
from proof_agent.capabilities.persistence.postgres.metadata_review_repository import (
    PostgresInsuranceMetadataReviewRepository,
)
from proof_agent.capabilities.persistence.postgres.prepared_knowledge_publication_repository import (
    PostgresPreparedKnowledgePublicationRepository,
)
from proof_agent.capabilities.persistence.postgres.publication_preparation_repository import (
    PostgresPublicationPreparationRepository,
)
from proof_agent.capabilities.persistence.postgres.schema import (
    hybrid_metadata_workbook_exports,
    hybrid_metadata_workbook_jobs,
    hybrid_metadata_workbook_previews,
)
from proof_agent.contracts.knowledge_index import ExactArtifactRef
from proof_agent.contracts.persistence import PersistenceInvariantError


class MetadataWorkbookAuthorityConflictError(RuntimeError):
    """A Workbook resource is stale, consumed, expired, or identity-mismatched."""


class MetadataWorkbookJobClaimRejectedError(RuntimeError):
    """A Workbook V2 job claim is missing, stale, expired, or fenced."""


class PostgresMetadataWorkbookV2Repository:
    """Persist exact Export/Preview resources and atomically consume Apply."""

    def __init__(
        self,
        connection_source: ConnectionSource,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._connection_source = connection_source
        self._clock = clock

    def enqueue_job(self, job: MetadataWorkbookJobV2) -> MetadataWorkbookJobV2:
        if job.state != "READY" or job.fencing_token != 0:
            raise ValueError("new Metadata Workbook jobs must be unfenced and READY")
        document_id, revision_id = _revision_uuids(job.document_id, job.revision_id)
        values = _job_values(job, document_id=document_id, revision_id=revision_id)
        with write_connection(self._connection_source) as connection:
            inserted = connection.execute(
                postgres_insert(hybrid_metadata_workbook_jobs)
                .values(**values)
                .on_conflict_do_nothing()
                .returning(hybrid_metadata_workbook_jobs.c.job_id)
            ).scalar_one_or_none()
            if inserted is None:
                existing = connection.execute(
                    select(hybrid_metadata_workbook_jobs).where(
                        sa.or_(
                            hybrid_metadata_workbook_jobs.c.job_id == UUID(job.job_id),
                            hybrid_metadata_workbook_jobs.c.operation_id
                            == job.operation_id,
                        )
                    )
                ).mappings().one_or_none()
                if existing is None or _job(existing) != job:
                    raise MetadataWorkbookAuthorityConflictError(
                        "Metadata Workbook job identity already exists"
                    )
        persisted = self.get_job(job.job_id)
        if persisted is None:
            raise RuntimeError("Metadata Workbook job disappeared after admission")
        return persisted

    def get_job(self, job_id: str) -> MetadataWorkbookJobV2 | None:
        with read_connection(self._connection_source) as connection:
            row = connection.execute(
                select(hybrid_metadata_workbook_jobs).where(
                    hybrid_metadata_workbook_jobs.c.job_id == UUID(job_id)
                )
            ).mappings().one_or_none()
        return None if row is None else _job(row)

    def claim_next_job(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> MetadataWorkbookJobClaimV2 | None:
        normalized_worker = _nonblank(worker_id, "worker_id")
        if len(normalized_worker) > 512:
            raise ValueError("Metadata Workbook worker_id is too long")
        if not 1 <= lease_seconds <= 300:
            raise ValueError("Metadata Workbook lease is outside its bound")
        now = self._timestamp(None)
        expiry = now + timedelta(seconds=lease_seconds)
        with write_connection(self._connection_source) as connection:
            row = connection.execute(
                select(hybrid_metadata_workbook_jobs)
                .where(
                    sa.or_(
                        hybrid_metadata_workbook_jobs.c.state == "READY",
                        sa.and_(
                            hybrid_metadata_workbook_jobs.c.state == "CLAIMED",
                            hybrid_metadata_workbook_jobs.c.lease_expires_at <= now,
                        ),
                    )
                )
                .order_by(
                    hybrid_metadata_workbook_jobs.c.created_at,
                    hybrid_metadata_workbook_jobs.c.job_id,
                )
                .with_for_update(skip_locked=True)
                .limit(1)
            ).mappings().one_or_none()
            if row is None:
                return None
            current = _job(row)
            claimed = current.model_copy(
                update={
                    "state": "CLAIMED",
                    "fencing_token": current.fencing_token + 1,
                    "worker_id": normalized_worker,
                    "claimed_at": now,
                    "lease_expires_at": expiry,
                    "updated_at": now,
                    "failure_code": None,
                    "safe_reason": None,
                    "completed_at": None,
                }
            )
            connection.execute(
                update(hybrid_metadata_workbook_jobs)
                .where(hybrid_metadata_workbook_jobs.c.job_id == row["job_id"])
                .values(**_job_mutable_values(claimed))
            )
        return MetadataWorkbookJobClaimV2(
            job_id=claimed.job_id,
            operation_id=claimed.operation_id,
            worker_id=normalized_worker,
            fencing_token=claimed.fencing_token,
            claimed_at=now,
            lease_expires_at=expiry,
        )

    def require_job_claim(
        self,
        claim: MetadataWorkbookJobClaimV2,
    ) -> MetadataWorkbookJobV2:
        now = self._timestamp(None)
        with read_connection(self._connection_source) as connection:
            row = connection.execute(
                select(hybrid_metadata_workbook_jobs).where(
                    hybrid_metadata_workbook_jobs.c.job_id == UUID(claim.job_id),
                    hybrid_metadata_workbook_jobs.c.operation_id == claim.operation_id,
                    hybrid_metadata_workbook_jobs.c.state == "CLAIMED",
                    hybrid_metadata_workbook_jobs.c.worker_id == claim.worker_id,
                    hybrid_metadata_workbook_jobs.c.fencing_token
                    == claim.fencing_token,
                    hybrid_metadata_workbook_jobs.c.lease_expires_at > now,
                )
            ).mappings().one_or_none()
        if row is None:
            raise MetadataWorkbookJobClaimRejectedError(
                "Metadata Workbook operation requires the current active claim"
            )
        return _job(row)

    def complete_job(
        self,
        claim: MetadataWorkbookJobClaimV2,
        *,
        completed_at: datetime | None = None,
    ) -> MetadataWorkbookJobV2:
        timestamp = self._timestamp(completed_at)
        with write_connection(self._connection_source) as connection:
            current = self._claimed_job(connection, claim, timestamp=timestamp)
            completed = current.model_copy(
                update={
                    "state": "COMPLETED",
                    "worker_id": None,
                    "claimed_at": None,
                    "lease_expires_at": None,
                    "failure_code": None,
                    "safe_reason": None,
                    "updated_at": timestamp,
                    "completed_at": timestamp,
                }
            )
            changed = connection.execute(
                update(hybrid_metadata_workbook_jobs)
                .where(_claim_conditions(claim, timestamp=timestamp))
                .values(**_job_mutable_values(completed))
            )
            if changed.rowcount != 1:
                raise MetadataWorkbookJobClaimRejectedError(
                    "Metadata Workbook completion lost its claim"
                )
        return completed

    def fail_job(
        self,
        claim: MetadataWorkbookJobClaimV2,
        *,
        failure_code: str,
        safe_reason: str,
        completed_at: datetime | None = None,
    ) -> MetadataWorkbookJobV2:
        timestamp = self._timestamp(completed_at)
        code = _nonblank(failure_code, "failure_code")
        detail = _nonblank(safe_reason, "safe_reason")
        with write_connection(self._connection_source) as connection:
            current = self._claimed_job(connection, claim, timestamp=timestamp)
            failed = current.model_copy(
                update={
                    "state": "FAILED",
                    "worker_id": None,
                    "claimed_at": None,
                    "lease_expires_at": None,
                    "failure_code": code,
                    "safe_reason": detail,
                    "updated_at": timestamp,
                    "completed_at": timestamp,
                }
            )
            changed = connection.execute(
                update(hybrid_metadata_workbook_jobs)
                .where(_claim_conditions(claim, timestamp=timestamp))
                .values(**_job_mutable_values(failed))
            )
            if changed.rowcount != 1:
                raise MetadataWorkbookJobClaimRejectedError(
                    "Metadata Workbook failure lost its claim"
                )
        return failed

    @staticmethod
    def _claimed_job(
        connection: object,
        claim: MetadataWorkbookJobClaimV2,
        *,
        timestamp: datetime,
    ) -> MetadataWorkbookJobV2:
        row = connection.execute(  # type: ignore[attr-defined]
            select(hybrid_metadata_workbook_jobs)
            .where(_claim_conditions(claim, timestamp=timestamp))
            .with_for_update()
        ).mappings().one_or_none()
        if row is None:
            raise MetadataWorkbookJobClaimRejectedError(
                "Metadata Workbook operation requires the current active claim"
            )
        return _job(row)

    def put_export(
        self,
        manifest: MetadataWorkbookExportManifestV2,
        *,
        artifact_ref: ExactArtifactRef,
        actor: str,
    ) -> MetadataWorkbookExportAuthorityV2:
        created_by = _nonblank(actor, "actor")
        document_id, revision_id = _revision_uuids(
            manifest.document_id,
            manifest.revision_id,
        )
        authority = MetadataWorkbookExportAuthorityV2(
            manifest=manifest,
            artifact_ref=artifact_ref,
            state="available",
            created_by=created_by,
        )
        with write_connection(self._connection_source) as connection:
            existing = connection.execute(
                select(hybrid_metadata_workbook_exports.c.authority_json).where(
                    hybrid_metadata_workbook_exports.c.source_id == manifest.source_id,
                    hybrid_metadata_workbook_exports.c.export_id == manifest.export_id,
                )
            ).scalar_one_or_none()
            if existing is not None:
                persisted = _export_authority(existing)
                if persisted != authority:
                    raise MetadataWorkbookAuthorityConflictError(
                        "Workbook Export identity already exists"
                    )
                return persisted
            connection.execute(
                hybrid_metadata_workbook_exports.insert().values(
                    source_id=manifest.source_id,
                    export_id=manifest.export_id,
                    document_id=document_id,
                    revision_id=revision_id,
                    profile_revision_id=manifest.profile_revision_id,
                    review_set_id=manifest.review_set_id,
                    review_set_identity=manifest.review_set_identity,
                    review_set_generation=manifest.review_set_generation,
                    state=authority.state,
                    manifest_json=model_json(manifest),
                    artifact_ref_json=model_json(artifact_ref),
                    authority_json=model_json(authority),
                    created_by=created_by,
                    created_at=manifest.exported_at,
                    expires_at=manifest.expires_at,
                    downloaded_at=None,
                    consumed_at=None,
                )
            )
        return authority

    def get_export(
        self,
        *,
        source_id: str,
        export_id: str,
    ) -> MetadataWorkbookExportAuthorityV2 | None:
        with read_connection(self._connection_source) as connection:
            payload = connection.execute(
                select(hybrid_metadata_workbook_exports.c.authority_json).where(
                    hybrid_metadata_workbook_exports.c.source_id == source_id,
                    hybrid_metadata_workbook_exports.c.export_id == export_id,
                )
            ).scalar_one_or_none()
        return None if payload is None else _export_authority(payload)

    def put_preview(
        self,
        preview: MetadataWorkbookImportPreviewV2,
        *,
        original_ref: ExactArtifactRef,
        actor: str,
        expires_at: datetime,
    ) -> MetadataWorkbookImportPreviewAuthorityV2:
        created_by = _nonblank(actor, "actor")
        expiry = _aware(expires_at, "expires_at")
        if expiry <= preview.previewed_at:
            raise MetadataReviewValidationError(
                "Workbook Preview expiry must follow creation"
            )
        document_id, revision_id = _revision_uuids(
            preview.document_id,
            preview.revision_id,
        )
        authority = MetadataWorkbookImportPreviewAuthorityV2(
            preview_id=preview.preview_id,
            source_id=preview.source_id,
            export_id=preview.export_id,
            original_ref=original_ref,
            state=preview.state,
            preview=preview,
            created_by=created_by,
            created_at=preview.previewed_at,
            expires_at=expiry,
        )
        with write_connection(self._connection_source) as connection:
            export_row = connection.execute(
                select(hybrid_metadata_workbook_exports)
                .where(
                    hybrid_metadata_workbook_exports.c.source_id == preview.source_id,
                    hybrid_metadata_workbook_exports.c.export_id == preview.export_id,
                )
                .with_for_update()
            ).mappings().one_or_none()
            if (
                export_row is None
                or export_row["state"] != "available"
                or export_row["expires_at"] < preview.previewed_at
            ):
                raise MetadataWorkbookAuthorityConflictError(
                    "Workbook Export is unavailable for Preview"
                )
            existing = connection.execute(
                select(hybrid_metadata_workbook_previews.c.authority_json).where(
                    hybrid_metadata_workbook_previews.c.source_id == preview.source_id,
                    hybrid_metadata_workbook_previews.c.preview_id == preview.preview_id,
                )
            ).scalar_one_or_none()
            if existing is not None:
                persisted = _preview_authority(existing)
                if persisted != authority:
                    raise MetadataWorkbookAuthorityConflictError(
                        "Workbook Preview identity already exists"
                    )
                return persisted
            connection.execute(
                hybrid_metadata_workbook_previews.insert().values(
                    source_id=preview.source_id,
                    preview_id=preview.preview_id,
                    export_id=preview.export_id,
                    document_id=document_id,
                    revision_id=revision_id,
                    preview_identity=preview.preview_identity,
                    current_review_set_identity=preview.current_review_set_identity,
                    current_review_set_generation=preview.current_review_set_generation,
                    state=authority.state,
                    preview_json=model_json(preview),
                    validation_report_json=null(),
                    original_ref_json=model_json(original_ref),
                    authority_json=model_json(authority),
                    created_by=created_by,
                    created_at=preview.previewed_at,
                    expires_at=expiry,
                    applied_at=None,
                )
            )
        return authority

    def put_validation_report(
        self,
        *,
        source_id: str,
        export_id: str,
        preview_id: str,
        original_ref: ExactArtifactRef,
        report: MetadataWorkbookValidationReportV2,
        actor: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> MetadataWorkbookImportPreviewAuthorityV2:
        created_by = _nonblank(actor, "actor")
        created = _aware(created_at, "created_at")
        expiry = _aware(expires_at, "expires_at")
        if expiry <= created:
            raise MetadataReviewValidationError(
                "Workbook Preview expiry must follow creation"
            )
        with write_connection(self._connection_source) as connection:
            export_row = connection.execute(
                select(hybrid_metadata_workbook_exports)
                .where(
                    hybrid_metadata_workbook_exports.c.source_id == source_id,
                    hybrid_metadata_workbook_exports.c.export_id == export_id,
                )
                .with_for_update()
            ).mappings().one_or_none()
            if (
                export_row is None
                or export_row["state"] != "available"
                or export_row["expires_at"] < created
            ):
                raise MetadataWorkbookAuthorityConflictError(
                    "Workbook Export is unavailable for Preview"
                )
            manifest = MetadataWorkbookExportManifestV2.model_validate_json(
                json.dumps(
                    export_row["manifest_json"],
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
            document_id, revision_id = _revision_uuids(
                manifest.document_id,
                manifest.revision_id,
            )
            authority = MetadataWorkbookImportPreviewAuthorityV2(
                preview_id=preview_id,
                source_id=source_id,
                export_id=export_id,
                original_ref=original_ref,
                state="validation_failed",
                validation_report=report,
                created_by=created_by,
                created_at=created,
                expires_at=expiry,
            )
            existing = connection.execute(
                select(hybrid_metadata_workbook_previews.c.authority_json).where(
                    hybrid_metadata_workbook_previews.c.source_id == source_id,
                    hybrid_metadata_workbook_previews.c.preview_id == preview_id,
                )
            ).scalar_one_or_none()
            if existing is not None:
                persisted = _preview_authority(existing)
                if persisted != authority:
                    raise MetadataWorkbookAuthorityConflictError(
                        "Workbook Preview identity already exists"
                    )
                return persisted
            connection.execute(
                hybrid_metadata_workbook_previews.insert().values(
                    source_id=source_id,
                    preview_id=preview_id,
                    export_id=export_id,
                    document_id=document_id,
                    revision_id=revision_id,
                    preview_identity=None,
                    current_review_set_identity=None,
                    current_review_set_generation=None,
                    state="validation_failed",
                    preview_json=null(),
                    validation_report_json=model_json(report),
                    original_ref_json=model_json(original_ref),
                    authority_json=model_json(authority),
                    created_by=created_by,
                    created_at=created,
                    expires_at=expiry,
                    applied_at=None,
                )
            )
        return authority

    def get_preview(
        self,
        *,
        source_id: str,
        preview_id: str,
    ) -> MetadataWorkbookImportPreviewAuthorityV2 | None:
        with read_connection(self._connection_source) as connection:
            payload = connection.execute(
                select(hybrid_metadata_workbook_previews.c.authority_json).where(
                    hybrid_metadata_workbook_previews.c.source_id == source_id,
                    hybrid_metadata_workbook_previews.c.preview_id == preview_id,
                )
            ).scalar_one_or_none()
        return None if payload is None else _preview_authority(payload)

    def apply_preview(
        self,
        *,
        source_id: str,
        preview_id: str,
        expected_preview_identity: str,
        actor: str,
        reason: str,
        expected_source_revision: int | None = None,
        applied_at: datetime | None = None,
    ) -> MetadataWorkbookApplyCommitV2:
        applied_by = _nonblank(actor, "actor")
        decision_reason = _nonblank(reason, "reason")
        timestamp = self._timestamp(applied_at)
        with write_connection(self._connection_source) as connection:
            preview_row = connection.execute(
                select(hybrid_metadata_workbook_previews)
                .where(
                    hybrid_metadata_workbook_previews.c.source_id == source_id,
                    hybrid_metadata_workbook_previews.c.preview_id == preview_id,
                )
                .with_for_update()
            ).mappings().one_or_none()
            if preview_row is None:
                raise KeyError(preview_id)
            authority = _preview_authority(preview_row["authority_json"])
            if authority.preview is None:
                raise MetadataWorkbookAuthorityConflictError(
                    "Workbook Preview has no merge projection"
                )
            if (
                authority.state != "ready_to_apply"
                or authority.preview.preview_identity != expected_preview_identity
                or authority.expires_at < timestamp
            ):
                raise MetadataWorkbookAuthorityConflictError(
                    "Workbook Preview is stale, expired, conflicting, or consumed"
                )
            export_row = connection.execute(
                select(hybrid_metadata_workbook_exports)
                .where(
                    hybrid_metadata_workbook_exports.c.source_id == source_id,
                    hybrid_metadata_workbook_exports.c.export_id == authority.export_id,
                )
                .with_for_update()
            ).mappings().one_or_none()
            if (
                export_row is None
                or export_row["state"] != "available"
                or export_row["expires_at"] < timestamp
            ):
                raise MetadataWorkbookAuthorityConflictError(
                    "Workbook Export is stale, expired, or consumed"
                )
            applied = PostgresInsuranceMetadataReviewRepository(
                connection,
                clock=lambda: timestamp,
            ).apply_workbook_preview(
                authority.preview,
                expected_preview_identity=expected_preview_identity,
                actor=applied_by,
                reason=decision_reason,
            )
            knowledge = PostgresKnowledgeAssetRepository(connection)
            source_record = knowledge.get_source_record(source_id)
            if source_record is None:
                raise KeyError(source_id)
            if (
                expected_source_revision is not None
                and source_record.revision != expected_source_revision
            ):
                raise MetadataWorkbookAuthorityConflictError(
                    "Workbook Apply Source revision changed"
                )
            source_version = knowledge.save_source(
                source_record.source.model_copy(
                    update={
                        "source_draft_version_id": str(uuid4()),
                        "updated_at": timestamp.astimezone(UTC).isoformat(),
                    }
                ),
                expected_revision=source_record.revision,
            )
            PostgresPreparedKnowledgePublicationRepository(
                connection
            ).invalidate_source(source_id)
            PostgresPublicationPreparationRepository(
                connection,
                clock=lambda: timestamp,
            ).invalidate_source(
                source_id,
                invalidated_at=timestamp,
            )
            updated_preview = authority.model_copy(
                update={"state": "applied", "applied_at": timestamp}
            )
            changed_preview = connection.execute(
                update(hybrid_metadata_workbook_previews)
                .where(
                    hybrid_metadata_workbook_previews.c.source_id == source_id,
                    hybrid_metadata_workbook_previews.c.preview_id == preview_id,
                    hybrid_metadata_workbook_previews.c.state == "ready_to_apply",
                    hybrid_metadata_workbook_previews.c.preview_identity
                    == expected_preview_identity,
                )
                .values(
                    state="applied",
                    authority_json=model_json(updated_preview),
                    applied_at=timestamp,
                )
            )
            if changed_preview.rowcount != 1:
                raise MetadataWorkbookAuthorityConflictError(
                    "Workbook Preview lost its Apply fence"
                )
            export_authority = _export_authority(export_row["authority_json"])
            consumed_export = export_authority.model_copy(
                update={"state": "consumed", "consumed_at": timestamp}
            )
            changed_export = connection.execute(
                update(hybrid_metadata_workbook_exports)
                .where(
                    hybrid_metadata_workbook_exports.c.source_id == source_id,
                    hybrid_metadata_workbook_exports.c.export_id
                    == authority.export_id,
                    hybrid_metadata_workbook_exports.c.state == "available",
                )
                .values(
                    state="consumed",
                    authority_json=model_json(consumed_export),
                    consumed_at=timestamp,
                )
            )
            if changed_export.rowcount != 1:
                raise MetadataWorkbookAuthorityConflictError(
                    "Workbook Export lost its consumption fence"
                )
        return MetadataWorkbookApplyCommitV2(
            source_revision=source_version.revision,
            review_set=applied.review_set,
            decisions=applied.decisions,
            preview=updated_preview,
        )

    def _timestamp(self, value: datetime | None) -> datetime:
        return _aware(self._clock() if value is None else value, "timestamp")


def _revision_uuids(document_id: str, revision_id: str) -> tuple[UUID, UUID]:
    try:
        return UUID(document_id), UUID(revision_id)
    except ValueError as exc:
        raise MetadataReviewValidationError(
            "production Workbook authority requires UUID document revisions"
        ) from exc


def _job_values(
    job: MetadataWorkbookJobV2,
    *,
    document_id: UUID,
    revision_id: UUID,
) -> dict[str, object]:
    return {
        "job_id": UUID(job.job_id),
        "operation_id": job.operation_id,
        "source_id": job.source_id,
        "document_id": document_id,
        "revision_id": revision_id,
        "source_revision": job.source_revision,
        "command": job.command,
        "resource_id": job.resource_id,
        "request_sha256": job.request_sha256,
        **_job_mutable_values(job),
        "created_by": job.created_by,
        "created_at": job.created_at,
    }


def _job_mutable_values(job: MetadataWorkbookJobV2) -> dict[str, object]:
    return {
        "state": job.state,
        "fencing_token": job.fencing_token,
        "worker_id": job.worker_id,
        "claimed_at": job.claimed_at,
        "lease_expires_at": job.lease_expires_at,
        "failure_code": job.failure_code,
        "safe_reason": job.safe_reason,
        "job_json": model_json(job),
        "updated_at": job.updated_at,
        "completed_at": job.completed_at,
    }


def _job(row: RowMapping) -> MetadataWorkbookJobV2:
    return MetadataWorkbookJobV2.model_validate_json(_json(row["job_json"]))


def _claim_conditions(
    claim: MetadataWorkbookJobClaimV2,
    *,
    timestamp: datetime,
) -> ColumnElement[bool]:
    return sa.and_(
        hybrid_metadata_workbook_jobs.c.job_id == UUID(claim.job_id),
        hybrid_metadata_workbook_jobs.c.operation_id == claim.operation_id,
        hybrid_metadata_workbook_jobs.c.state == "CLAIMED",
        hybrid_metadata_workbook_jobs.c.worker_id == claim.worker_id,
        hybrid_metadata_workbook_jobs.c.fencing_token == claim.fencing_token,
        hybrid_metadata_workbook_jobs.c.lease_expires_at > timestamp,
    )


def _export_authority(payload: object) -> MetadataWorkbookExportAuthorityV2:
    return MetadataWorkbookExportAuthorityV2.model_validate_json(_json(payload))


def _preview_authority(
    payload: object,
) -> MetadataWorkbookImportPreviewAuthorityV2:
    return MetadataWorkbookImportPreviewAuthorityV2.model_validate_json(_json(payload))


def _json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _nonblank(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise MetadataReviewValidationError(f"{field} must be nonblank")
    return normalized


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PersistenceInvariantError(f"Workbook {field} must be timezone-aware")
    return value.astimezone(UTC)


__all__ = [
    "MetadataWorkbookAuthorityConflictError",
    "MetadataWorkbookJobClaimRejectedError",
    "PostgresMetadataWorkbookV2Repository",
]
