from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

from proof_agent.bootstrap.validation import validate_secret_safe_params
from proof_agent.capabilities.knowledge.ingestion import (
    KnowledgeWorkerClaimSelection,
    KnowledgeWorkerDiagnostic,
    KnowledgeWorkerTaskClaim,
    ParsedKnowledgeDocument,
    ParserMetadata,
    ingestion_config_fingerprint,
    local_index_engine_version,
)
from proof_agent.contracts import (
    ActiveAgentVersion,
    AgentValidationRecord,
    ConfigurationOperation,
    ConfigurationOperationAudit,
    ContractBundle,
    DraftAgent,
    KnowledgeArtifactBuildSpec,
    KnowledgeDocument,
    KnowledgeIngestionJob,
    KnowledgeSource,
    PublishedAgentVersion,
    QuarantinedKnowledgeUpload,
)
from proof_agent.configuration.file_locking import locked, store_lock_path
from proof_agent.errors import ProofAgentError

KNOWLEDGE_SOURCE_DOCUMENT_CAPACITY = 500
STORE_LOCK_TIMEOUT_SECONDS = 5.0


class LocalAgentConfigurationStore:
    """File-backed Agent Configuration Store for local MVP workflows."""

    def __init__(self, root_dir: Path) -> None:
        self._root_dir = root_dir
        self._root_dir.mkdir(parents=True, exist_ok=True)

    @property
    def root_dir(self) -> Path:
        return self._root_dir

    def create_draft(
        self,
        *,
        agent_id: str,
        display_name: str,
        purpose: str,
        contract_bundle: ContractBundle,
        actor: str,
    ) -> DraftAgent:
        now = _now()
        draft = DraftAgent(
            agent_id=agent_id,
            draft_id=f"draft_{uuid4().hex[:8]}",
            display_name=display_name,
            purpose=purpose,
            contract_bundle=contract_bundle,
            created_at=now,
            updated_at=now,
            created_by=actor,
            updated_by=actor,
            operation_audit=(
                _audit(ConfigurationOperation.IMPORTED, actor=actor, summary="Created draft."),
            ),
        )
        self._write_draft(draft)
        return draft

    def get_draft(self, agent_id: str, draft_id: str) -> DraftAgent | None:
        path = self._draft_path(agent_id, draft_id)
        if not path.exists():
            return None
        return DraftAgent.model_validate(_read_json(path))

    def list_drafts(self, agent_id: str | None = None) -> list[DraftAgent]:
        drafts_root = self._root_dir / "agents"
        if not drafts_root.exists():
            return []
        agent_dirs = [drafts_root / agent_id] if agent_id else list(drafts_root.iterdir())
        drafts: list[DraftAgent] = []
        for agent_dir in agent_dirs:
            draft_root = agent_dir / "drafts"
            if not draft_root.exists():
                continue
            for draft_dir in draft_root.iterdir():
                if not draft_dir.is_dir():
                    continue
                draft = self.get_draft(agent_dir.name, draft_dir.name)
                if draft is not None:
                    drafts.append(draft)
        return sorted(drafts, key=lambda draft: draft.created_at)

    def update_draft(
        self,
        *,
        agent_id: str,
        draft_id: str,
        actor: str,
        display_name: str | None = None,
        purpose: str | None = None,
        contract_bundle: ContractBundle | None = None,
    ) -> DraftAgent:
        existing = self._require_draft(agent_id, draft_id)
        updated = DraftAgent(
            agent_id=existing.agent_id,
            draft_id=existing.draft_id,
            display_name=display_name if display_name is not None else existing.display_name,
            purpose=purpose if purpose is not None else existing.purpose,
            contract_bundle=contract_bundle or existing.contract_bundle,
            created_at=existing.created_at,
            updated_at=_now(),
            created_by=existing.created_by,
            updated_by=actor,
            version_id=existing.version_id,
            validation_records=existing.validation_records,
            operation_audit=(
                *existing.operation_audit,
                _audit(ConfigurationOperation.UPDATED, actor=actor, summary="Updated draft."),
            ),
        )
        self._write_draft(updated)
        return updated

    def publish_version(
        self,
        *,
        agent_id: str,
        draft_id: str,
        validation_run_id: str,
        actor: str,
    ) -> PublishedAgentVersion:
        draft = self._require_draft(agent_id, draft_id)
        version = PublishedAgentVersion(
            agent_id=agent_id,
            version_id=f"version_{uuid4().hex[:8]}",
            source_draft_id=draft_id,
            validation_run_id=validation_run_id,
            display_name=draft.display_name,
            purpose=draft.purpose,
            contract_bundle=draft.contract_bundle,
            published_at=_now(),
            published_by=actor,
            operation_audit=(
                _audit(
                    ConfigurationOperation.PUBLISHED,
                    actor=actor,
                    summary=f"Published draft {draft_id}.",
                    metadata={"validation_run_id": validation_run_id},
                ),
            ),
        )
        self._write_version(version)
        active = ActiveAgentVersion(
            agent_id=agent_id,
            version_id=version.version_id,
            activated_at=version.published_at,
            activated_by=actor,
        )
        self._write_active_version(active)
        return version

    def record_validation(
        self,
        *,
        agent_id: str,
        draft_id: str,
        record: AgentValidationRecord,
        actor: str,
    ) -> DraftAgent:
        existing = self._require_draft(agent_id, draft_id)
        updated = DraftAgent(
            agent_id=existing.agent_id,
            draft_id=existing.draft_id,
            display_name=existing.display_name,
            purpose=existing.purpose,
            contract_bundle=existing.contract_bundle,
            created_at=existing.created_at,
            updated_at=_now(),
            created_by=existing.created_by,
            updated_by=actor,
            version_id=existing.version_id,
            validation_records=(*existing.validation_records, record),
            operation_audit=(
                *existing.operation_audit,
                _audit(
                    ConfigurationOperation.VALIDATED,
                    actor=actor,
                    summary=f"Validated draft {draft_id}.",
                    metadata={"run_id": record.run_id, "status": record.status},
                ),
            ),
        )
        self._write_draft(updated)
        return updated

    def get_version(self, agent_id: str, version_id: str) -> PublishedAgentVersion | None:
        path = self._version_path(agent_id, version_id) / "publication.json"
        if not path.exists():
            return None
        return PublishedAgentVersion.model_validate(_read_json(path))

    def list_versions(self, agent_id: str) -> list[PublishedAgentVersion]:
        versions_root = self._root_dir / "agents" / agent_id / "versions"
        if not versions_root.exists():
            return []
        versions = []
        for version_dir in versions_root.iterdir():
            if version_dir.is_dir():
                version = self.get_version(agent_id, version_dir.name)
                if version is not None:
                    versions.append(version)
        return sorted(versions, key=lambda version: version.published_at)

    def get_active_version(self, agent_id: str) -> ActiveAgentVersion | None:
        path = self._active_version_path(agent_id)
        if not path.exists():
            return None
        return ActiveAgentVersion.model_validate(_read_json(path))

    def rollback_active_version(
        self,
        *,
        agent_id: str,
        version_id: str,
        actor: str,
    ) -> ActiveAgentVersion:
        if self.get_version(agent_id, version_id) is None:
            raise KeyError(f"Published Agent Version not found: {agent_id}/{version_id}")
        current = self.get_active_version(agent_id)
        active = ActiveAgentVersion(
            agent_id=agent_id,
            version_id=version_id,
            activated_at=_now(),
            activated_by=actor,
            rollback_from_version_id=current.version_id if current else None,
        )
        self._write_active_version(active)
        return active

    def create_knowledge_source(
        self,
        *,
        source_id: str,
        name: str,
        provider: str,
        params: Mapping[str, Any],
        actor: str,
    ) -> KnowledgeSource:
        validate_secret_safe_params(
            params,
            field_prefix=f"knowledge_sources[{source_id}].params",
        )
        _knowledge_source_worker_concurrency(params)
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            if self.get_knowledge_source(source_id) is not None:
                raise ValueError(f"Knowledge Source already exists: {source_id}")
            now = _now()
            source = KnowledgeSource(
                source_id=source_id,
                name=name,
                provider=provider,
                params=params,
                created_at=now,
                updated_at=now,
            )
            self._write_knowledge_source(source)
        return source

    def get_knowledge_source(self, source_id: str) -> KnowledgeSource | None:
        path = self._knowledge_source_path(source_id)
        if not path.exists():
            return None
        return KnowledgeSource.model_validate(_read_json(path))

    def list_knowledge_sources(self) -> list[KnowledgeSource]:
        sources_root = self._root_dir / "knowledge_sources"
        if not sources_root.exists():
            return []
        sources = []
        for source_dir in sources_root.iterdir():
            if not source_dir.is_dir():
                continue
            source = self.get_knowledge_source(source_dir.name)
            if source is not None:
                sources.append(source)
        return sorted(sources, key=lambda source: source.name)

    def get_knowledge_source_worker_concurrency(self, source_id: str) -> int:
        """Return a validated claim-time concurrency limit for one source."""

        source = self._require_knowledge_source(source_id)
        return _knowledge_source_worker_concurrency(source.params)

    def stage_quarantined_knowledge_upload(
        self,
        *,
        source_id: str,
        filename: str,
        content_type: str,
        content: bytes,
        actor: str,
        lock_timeout_seconds: float = STORE_LOCK_TIMEOUT_SECONDS,
    ) -> QuarantinedKnowledgeUpload:
        """Persist one operator upload for asynchronous validation."""

        with locked(self._store_lock_path(), timeout_seconds=lock_timeout_seconds):
            self._require_knowledge_source(source_id)
            if (
                self._count_reserved_knowledge_document_slots_unlocked(source_id)
                >= KNOWLEDGE_SOURCE_DOCUMENT_CAPACITY
            ):
                raise _knowledge_document_capacity_exceeded(source_id)

            now = _now()
            upload_id = f"upload_{uuid4().hex[:8]}"
            safe_filename = _safe_filename(filename)
            storage_path = (
                Path("knowledge_sources")
                / source_id
                / "quarantined_uploads"
                / upload_id
                / "original-upload.bin"
            )
            upload = QuarantinedKnowledgeUpload(
                upload_id=upload_id,
                source_id=source_id,
                filename=safe_filename,
                content_type=content_type,
                size_bytes=len(content),
                storage_path=storage_path.as_posix(),
                state="queued",
                created_at=now,
                updated_at=now,
            )
            self._publish_quarantined_knowledge_upload(upload, content)
            return upload

    def count_reserved_knowledge_document_slots(self, source_id: str) -> int:
        """Count managed documents plus queued or processing quarantine reservations."""

        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            self._require_knowledge_source(source_id)
            return self._count_reserved_knowledge_document_slots_unlocked(source_id)

    def get_quarantined_knowledge_upload(
        self,
        *,
        source_id: str,
        upload_id: str,
    ) -> QuarantinedKnowledgeUpload | None:
        path = self._quarantined_knowledge_upload_path(source_id, upload_id)
        if not path.exists():
            return None
        return QuarantinedKnowledgeUpload.model_validate(_read_json(path))

    def list_quarantined_knowledge_uploads(
        self, source_id: str
    ) -> list[QuarantinedKnowledgeUpload]:
        uploads_root = self._quarantined_knowledge_uploads_root(source_id)
        if not uploads_root.exists():
            return []
        uploads = []
        for upload_dir in uploads_root.iterdir():
            if not upload_dir.is_dir():
                continue
            upload = self.get_quarantined_knowledge_upload(
                source_id=source_id,
                upload_id=upload_dir.name,
            )
            if upload is not None:
                uploads.append(upload)
        return sorted(uploads, key=lambda upload: upload.created_at)

    def quarantined_knowledge_upload_bytes_path(self, upload: QuarantinedKnowledgeUpload) -> Path:
        return self._root_dir / upload.storage_path

    def accept_quarantined_knowledge_upload(
        self,
        *,
        source_id: str,
        upload_id: str,
        parsed_document: ParsedKnowledgeDocument,
        claim_token: str,
    ) -> tuple[KnowledgeDocument, KnowledgeIngestionJob]:
        """Promote one validated upload into immutable managed ingestion state."""

        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            upload = self._require_quarantined_knowledge_upload(source_id, upload_id)
            _require_owned_processing_claim(upload, claim_token=claim_token)
            if self._upload_promotion_marker_path(source_id, upload_id).exists():
                return self._repair_accepted_upload_projection_unlocked(upload)

            source = self._require_knowledge_source(source_id)
            validate_secret_safe_params(
                source.params,
                field_prefix=f"knowledge_sources[{source_id}].params",
            )
            original_bytes = self.quarantined_knowledge_upload_bytes_path(upload).read_bytes()
            document, job, parser_metadata = self._promoted_knowledge_records(
                upload=upload,
                source=source,
                parsed_document=parsed_document,
                original_bytes=original_bytes,
            )
            revision_dir = self.knowledge_document_original_path(document).parent
            _write_bytes_atomic(self.knowledge_document_original_path(document), original_bytes)
            _write_text_atomic(revision_dir / "parsed-text.txt", parsed_document.text)
            _write_json_atomic(revision_dir / "parser-meta.json", asdict(parser_metadata))
            self._write_knowledge_document(document)
            self._write_knowledge_ingestion_job(job)
            self._write_upload_promotion_marker(upload, document, job)
            self._write_quarantined_knowledge_upload(
                _accepted_upload_projection(upload, document=document, job=job)
            )
            self.quarantined_knowledge_upload_bytes_path(upload).unlink(missing_ok=True)
            return document, job

    def reject_quarantined_knowledge_upload(
        self,
        *,
        source_id: str,
        upload_id: str,
        claim_token: str,
        error_code: str,
        error_message: str,
    ) -> QuarantinedKnowledgeUpload:
        """Reject one validated quarantine upload while retaining bytes for 24 hours."""

        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            upload = self._require_quarantined_knowledge_upload(source_id, upload_id)
            _require_owned_processing_claim(upload, claim_token=claim_token)
            now = datetime.now(UTC)
            rejected = upload.model_copy(
                update={
                    "state": "rejected",
                    "completed_at": _timestamp(now),
                    "error_code": error_code,
                    "error_message": error_message,
                    "expires_at": _timestamp(now + timedelta(hours=24)),
                    "claimed_at": None,
                    "claim_token": None,
                    "lease_expires_at": None,
                    "updated_at": _timestamp(now),
                }
            )
            self._write_quarantined_knowledge_upload(rejected)
            return rejected

    def purge_expired_quarantined_upload_bytes(
        self,
        *,
        now: datetime | None = None,
    ) -> list[QuarantinedKnowledgeUpload]:
        """Delete rejected raw bytes after retention while preserving status records."""

        current_time = now or datetime.now(UTC)
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            purged = []
            for source in self.list_knowledge_sources():
                for upload in self.list_quarantined_knowledge_uploads(source.source_id):
                    if not _is_expired_rejected_upload(upload, now=current_time):
                        continue
                    self.quarantined_knowledge_upload_bytes_path(upload).unlink(missing_ok=True)
                    updated = upload.model_copy(
                        update={
                            "purged_at": _timestamp(current_time),
                            "updated_at": _timestamp(current_time),
                        }
                    )
                    self._write_quarantined_knowledge_upload(updated)
                    purged.append(updated)
            return purged

    def claim_next_quarantined_knowledge_upload(
        self,
        *,
        source_id: str | None = None,
        lease_seconds: int = 300,
    ) -> QuarantinedKnowledgeUpload | None:
        """Claim the oldest eligible quarantine upload, optionally for one Source."""

        selection = self._claim_next_knowledge_worker_task(
            task_kinds={"quarantine_validation"},
            source_id=source_id,
            lease_seconds=lease_seconds,
        )
        if selection.task is None:
            return None
        return selection.task.upload

    def renew_quarantined_knowledge_upload_claim(
        self,
        *,
        source_id: str,
        upload_id: str,
        claim_token: str,
        lease_seconds: int = 300,
    ) -> QuarantinedKnowledgeUpload:
        """Extend one token-owned quarantine-validation lease."""

        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            upload = self._require_quarantined_knowledge_upload(source_id, upload_id)
            _require_owned_processing_claim(upload, claim_token=claim_token)
            renewed = upload.model_copy(update=_renewed_claim_updates(lease_seconds=lease_seconds))
            self._write_quarantined_knowledge_upload(renewed)
            return renewed

    def get_knowledge_ingestion_job(
        self,
        *,
        source_id: str,
        job_id: str,
    ) -> KnowledgeIngestionJob | None:
        path = self._knowledge_ingestion_job_path(source_id, job_id)
        if not path.exists():
            return None
        return KnowledgeIngestionJob.model_validate(_read_json(path))

    def list_knowledge_ingestion_jobs(self, source_id: str) -> list[KnowledgeIngestionJob]:
        jobs_root = self._knowledge_ingestion_jobs_root(source_id)
        if not jobs_root.exists():
            return []
        jobs = []
        for job_dir in jobs_root.iterdir():
            if not job_dir.is_dir():
                continue
            job = self.get_knowledge_ingestion_job(
                source_id=source_id,
                job_id=job_dir.name,
            )
            if job is not None:
                jobs.append(job)
        return sorted(jobs, key=lambda job: job.created_at)

    def claim_next_knowledge_ingestion_job(
        self,
        *,
        source_id: str | None = None,
        lease_seconds: int = 300,
    ) -> KnowledgeIngestionJob | None:
        """Claim the oldest eligible artifact-build job, optionally for one Source."""

        selection = self._claim_next_knowledge_worker_task(
            task_kinds={"artifact_build"},
            source_id=source_id,
            lease_seconds=lease_seconds,
        )
        if selection.task is None:
            return None
        return selection.task.ingestion_job

    def renew_knowledge_ingestion_job_claim(
        self,
        *,
        source_id: str,
        job_id: str,
        claim_token: str,
        lease_seconds: int = 300,
    ) -> KnowledgeIngestionJob:
        """Extend one token-owned artifact-build lease."""

        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            job = self._require_knowledge_ingestion_job(source_id, job_id)
            _require_owned_processing_claim(job, claim_token=claim_token)
            renewed = job.model_copy(update=_renewed_claim_updates(lease_seconds=lease_seconds))
            self._write_knowledge_ingestion_job(renewed)
            return renewed

    def complete_knowledge_ingestion_job(
        self,
        *,
        source_id: str,
        job_id: str,
        claim_token: str,
        artifact_path: str,
    ) -> KnowledgeIngestionJob:
        """Complete one token-owned artifact build with a reusable artifact reference."""

        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            job, document = self._owned_job_and_document_unlocked(
                source_id=source_id,
                job_id=job_id,
                claim_token=claim_token,
            )
            now = _now()
            completed = job.model_copy(
                update={
                    "state": "ready",
                    "artifact_path": artifact_path,
                    "completed_at": now,
                    "error_code": None,
                    "error_message": None,
                    "next_attempt_at": None,
                    **_cleared_claim_updates(),
                    "updated_at": now,
                }
            )
            projected_document = document.model_copy(
                update={
                    "state": "ready",
                    "artifact_path": artifact_path,
                    "error_code": None,
                    "error_message": None,
                    "updated_at": now,
                }
            )
            self._write_knowledge_document(projected_document)
            self._write_knowledge_ingestion_job(completed)
            return completed

    def defer_knowledge_ingestion_job(
        self,
        *,
        source_id: str,
        job_id: str,
        claim_token: str,
    ) -> KnowledgeIngestionJob:
        """Defer one artifact-key lock contention without counting a build failure."""

        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            job, document = self._owned_job_and_document_unlocked(
                source_id=source_id,
                job_id=job_id,
                claim_token=claim_token,
            )
            now = datetime.now(UTC)
            deferred = job.model_copy(
                update={
                    "state": "queued",
                    "next_attempt_at": _timestamp(now + timedelta(seconds=5)),
                    **_cleared_claim_updates(),
                    "updated_at": _timestamp(now),
                }
            )
            projected_document = document.model_copy(
                update={
                    "state": "queued",
                    "updated_at": _timestamp(now),
                }
            )
            self._write_knowledge_document(projected_document)
            self._write_knowledge_ingestion_job(deferred)
            return deferred

    def reschedule_knowledge_ingestion_job(
        self,
        *,
        source_id: str,
        job_id: str,
        claim_token: str,
        error_code: str,
        error_message: str,
        retry_delay_seconds: int | None = None,
    ) -> KnowledgeIngestionJob:
        """Persist one recoverable build failure or exhaust automatic retries."""

        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            job, document = self._owned_job_and_document_unlocked(
                source_id=source_id,
                job_id=job_id,
                claim_token=claim_token,
            )
            now = datetime.now(UTC)
            safe_message = _operator_error_message(error_message)
            auto_retry_count = job.auto_retry_count + 1
            if auto_retry_count > job.max_auto_retries:
                return self._fail_knowledge_ingestion_job_unlocked(
                    job=job,
                    document=document,
                    error_code=error_code,
                    error_message=safe_message,
                    failure_classification="recoverable_exhausted",
                    auto_retry_count=auto_retry_count,
                    completed_at=_timestamp(now),
                )
            rescheduled = job.model_copy(
                update={
                    "state": "queued",
                    "auto_retry_count": auto_retry_count,
                    "last_error_code": error_code,
                    "last_error_message": safe_message,
                    "last_failure_classification": "recoverable",
                    "next_attempt_at": _timestamp(
                        now
                        + timedelta(
                            seconds=retry_delay_seconds
                            if retry_delay_seconds is not None
                            else _default_auto_retry_delay_seconds(auto_retry_count)
                        )
                    ),
                    **_cleared_claim_updates(),
                    "updated_at": _timestamp(now),
                }
            )
            projected_document = document.model_copy(
                update={
                    "state": "queued",
                    "updated_at": _timestamp(now),
                }
            )
            self._write_knowledge_document(projected_document)
            self._write_knowledge_ingestion_job(rescheduled)
            return rescheduled

    def fail_knowledge_ingestion_job(
        self,
        *,
        source_id: str,
        job_id: str,
        claim_token: str,
        error_code: str,
        error_message: str,
    ) -> KnowledgeIngestionJob:
        """Persist one non-recoverable token-owned artifact-build failure."""

        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            job, document = self._owned_job_and_document_unlocked(
                source_id=source_id,
                job_id=job_id,
                claim_token=claim_token,
            )
            return self._fail_knowledge_ingestion_job_unlocked(
                job=job,
                document=document,
                error_code=error_code,
                error_message=_operator_error_message(error_message),
                failure_classification="non_recoverable",
                auto_retry_count=job.auto_retry_count,
                completed_at=_now(),
            )

    def claim_next_knowledge_worker_task(
        self,
        *,
        lease_seconds: int = 300,
    ) -> KnowledgeWorkerClaimSelection:
        """Atomically claim the oldest eligible task across both ingestion queues."""

        return self._claim_next_knowledge_worker_task(
            task_kinds={"quarantine_validation", "artifact_build"},
            source_id=None,
            lease_seconds=lease_seconds,
        )

    def add_knowledge_document(
        self,
        *,
        source_id: str,
        filename: str,
        content_type: str,
        content: bytes,
        state: str,
        provider_document_id: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        actor: str,
    ) -> KnowledgeDocument:
        if self.get_knowledge_source(source_id) is None:
            raise KeyError(f"Knowledge Source not found: {source_id}")
        now = _now()
        document_id = f"doc_{uuid4().hex[:8]}"
        revision_id = f"rev_{uuid4().hex[:8]}"
        safe_filename = _safe_filename(filename)
        storage_path = (
            Path("knowledge_sources")
            / source_id
            / "documents"
            / document_id
            / "revisions"
            / revision_id
            / safe_filename
        )
        original_path = self._root_dir / storage_path
        original_path.parent.mkdir(parents=True, exist_ok=True)
        original_path.write_bytes(content)
        document = KnowledgeDocument(
            document_id=document_id,
            source_id=source_id,
            revision_id=revision_id,
            filename=safe_filename,
            content_type=content_type,
            content_hash=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            state=state,
            storage_path=storage_path.as_posix(),
            provider_document_id=provider_document_id,
            error_code=error_code,
            error_message=error_message,
            created_at=now,
            updated_at=now,
        )
        self._write_knowledge_document(document)
        return document

    def get_knowledge_document(
        self,
        *,
        source_id: str,
        document_id: str,
    ) -> KnowledgeDocument | None:
        path = self._knowledge_document_path(source_id, document_id)
        if not path.exists():
            return None
        return KnowledgeDocument.model_validate(_read_json(path))

    def list_knowledge_documents(self, source_id: str) -> list[KnowledgeDocument]:
        documents_root = self._root_dir / "knowledge_sources" / source_id / "documents"
        if not documents_root.exists():
            return []
        documents = []
        for document_dir in documents_root.iterdir():
            if not document_dir.is_dir():
                continue
            document = self.get_knowledge_document(
                source_id=source_id,
                document_id=document_dir.name,
            )
            if document is not None:
                documents.append(document)
        return sorted(documents, key=lambda document: document.created_at)

    def knowledge_document_original_path(self, document: KnowledgeDocument) -> Path:
        return self._root_dir / document.storage_path

    def _require_knowledge_source(self, source_id: str) -> KnowledgeSource:
        source = self.get_knowledge_source(source_id)
        if source is None:
            raise KeyError(f"Knowledge Source not found: {source_id}")
        return source

    def _require_quarantined_knowledge_upload(
        self,
        source_id: str,
        upload_id: str,
    ) -> QuarantinedKnowledgeUpload:
        upload = self.get_quarantined_knowledge_upload(
            source_id=source_id,
            upload_id=upload_id,
        )
        if upload is None:
            raise KeyError(f"Quarantined Knowledge Upload not found: {source_id}/{upload_id}")
        return upload

    def _require_knowledge_ingestion_job(
        self,
        source_id: str,
        job_id: str,
    ) -> KnowledgeIngestionJob:
        job = self.get_knowledge_ingestion_job(source_id=source_id, job_id=job_id)
        if job is None:
            raise KeyError(f"Knowledge Ingestion Job not found: {source_id}/{job_id}")
        return job

    def _claim_next_knowledge_worker_task(
        self,
        *,
        task_kinds: set[str],
        source_id: str | None,
        lease_seconds: int,
    ) -> KnowledgeWorkerClaimSelection:
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            return self._claim_next_knowledge_worker_task_unlocked(
                task_kinds=task_kinds,
                source_id=source_id,
                lease_seconds=lease_seconds,
            )

    def _owned_job_and_document_unlocked(
        self,
        *,
        source_id: str,
        job_id: str,
        claim_token: str,
    ) -> tuple[KnowledgeIngestionJob, KnowledgeDocument]:
        job = self._require_knowledge_ingestion_job(source_id, job_id)
        _require_owned_processing_claim(job, claim_token=claim_token)
        document = self.get_knowledge_document(
            source_id=source_id,
            document_id=job.document_id,
        )
        if document is None:
            raise _invalid_ingestion_transition(
                f"Knowledge ingestion job {job_id} is missing its document projection."
            )
        return job, document

    def _fail_knowledge_ingestion_job_unlocked(
        self,
        *,
        job: KnowledgeIngestionJob,
        document: KnowledgeDocument,
        error_code: str,
        error_message: str,
        failure_classification: str,
        auto_retry_count: int,
        completed_at: str,
    ) -> KnowledgeIngestionJob:
        failed = job.model_copy(
            update={
                "state": "failed",
                "auto_retry_count": auto_retry_count,
                "completed_at": completed_at,
                "error_code": error_code,
                "error_message": error_message,
                "last_error_code": error_code,
                "last_error_message": error_message,
                "last_failure_classification": failure_classification,
                "next_attempt_at": None,
                **_cleared_claim_updates(),
                "updated_at": completed_at,
            }
        )
        projected_document = document.model_copy(
            update={
                "state": "failed",
                "error_code": error_code,
                "error_message": error_message,
                "updated_at": completed_at,
            }
        )
        self._write_knowledge_document(projected_document)
        self._write_knowledge_ingestion_job(failed)
        return failed

    def _claim_next_knowledge_worker_task_unlocked(
        self,
        *,
        task_kinds: set[str],
        source_id: str | None,
        lease_seconds: int,
    ) -> KnowledgeWorkerClaimSelection:
        now = datetime.now(UTC)
        diagnostics: list[KnowledgeWorkerDiagnostic] = []
        source_limits: dict[str, int] = {}
        for source in self.list_knowledge_sources():
            if source_id is not None and source.source_id != source_id:
                continue
            try:
                source_limits[source.source_id] = _knowledge_source_worker_concurrency(
                    source.params
                )
            except ProofAgentError:
                diagnostics.append(
                    KnowledgeWorkerDiagnostic(
                        source_id=source.source_id,
                        code="PA_INGESTION_001",
                        message="Knowledge Source worker_concurrency is invalid.",
                    )
                )

        active_counts = {
            candidate_source_id: self._active_processing_task_count(
                candidate_source_id,
                now=now,
            )
            for candidate_source_id in source_limits
        }
        candidates: list[
            tuple[
                str,
                Literal["quarantine_validation", "artifact_build"],
                QuarantinedKnowledgeUpload | KnowledgeIngestionJob,
            ]
        ] = []
        if "quarantine_validation" in task_kinds:
            for candidate_source_id in source_limits:
                for upload in self.list_quarantined_knowledge_uploads(candidate_source_id):
                    if _is_ready_for_claim(upload, now=now):
                        candidates.append((upload.created_at, "quarantine_validation", upload))
        if "artifact_build" in task_kinds:
            for candidate_source_id in source_limits:
                for job in self.list_knowledge_ingestion_jobs(candidate_source_id):
                    if self._is_ingestion_job_ready_for_claim(job, now=now):
                        candidates.append((job.created_at, "artifact_build", job))

        for _, task_kind, candidate in sorted(
            candidates,
            key=lambda item: (item[0], item[1], item[2].source_id),
        ):
            if active_counts[candidate.source_id] >= source_limits[candidate.source_id]:
                continue
            if task_kind == "quarantine_validation":
                upload = self._claim_quarantined_knowledge_upload_unlocked(
                    candidate,
                    lease_seconds=lease_seconds,
                )
                return KnowledgeWorkerClaimSelection(
                    task=KnowledgeWorkerTaskClaim(kind=task_kind, upload=upload),
                    diagnostics=tuple(diagnostics),
                )
            job = self._claim_knowledge_ingestion_job_unlocked(
                candidate,
                lease_seconds=lease_seconds,
            )
            return KnowledgeWorkerClaimSelection(
                task=KnowledgeWorkerTaskClaim(kind=task_kind, ingestion_job=job),
                diagnostics=tuple(diagnostics),
            )
        return KnowledgeWorkerClaimSelection(task=None, diagnostics=tuple(diagnostics))

    def _active_processing_task_count(self, source_id: str, *, now: datetime) -> int:
        tasks: tuple[QuarantinedKnowledgeUpload | KnowledgeIngestionJob, ...] = (
            *self.list_quarantined_knowledge_uploads(source_id),
            *self.list_knowledge_ingestion_jobs(source_id),
        )
        return sum(
            task.state == "processing" and _has_active_lease(task, now=now) for task in tasks
        )

    def _claim_quarantined_knowledge_upload_unlocked(
        self,
        upload: QuarantinedKnowledgeUpload | KnowledgeIngestionJob,
        *,
        lease_seconds: int,
    ) -> QuarantinedKnowledgeUpload:
        if not isinstance(upload, QuarantinedKnowledgeUpload):
            raise _invalid_ingestion_transition("Expected one quarantine-validation task.")
        claimed = upload.model_copy(update=_new_claim_updates(upload, lease_seconds=lease_seconds))
        self._write_quarantined_knowledge_upload(claimed)
        return claimed

    def _claim_knowledge_ingestion_job_unlocked(
        self,
        job: QuarantinedKnowledgeUpload | KnowledgeIngestionJob,
        *,
        lease_seconds: int,
    ) -> KnowledgeIngestionJob:
        if not isinstance(job, KnowledgeIngestionJob):
            raise _invalid_ingestion_transition("Expected one artifact-build task.")
        document = self.get_knowledge_document(
            source_id=job.source_id,
            document_id=job.document_id,
        )
        if document is None:
            raise _invalid_ingestion_transition(
                f"Knowledge ingestion job {job.job_id} is missing its document projection."
            )
        updates = _new_claim_updates(job, lease_seconds=lease_seconds)
        claimed_document = document.model_copy(
            update={
                "state": "processing",
                "updated_at": updates["updated_at"],
            }
        )
        claimed_job = job.model_copy(update=updates)
        self._write_knowledge_document(claimed_document)
        self._write_knowledge_ingestion_job(claimed_job)
        return claimed_job

    def _is_ingestion_job_ready_for_claim(
        self,
        job: KnowledgeIngestionJob,
        *,
        now: datetime,
    ) -> bool:
        upload_id = f"upload_{job.job_id.removeprefix('job_')}"
        if not self._upload_promotion_marker_path(job.source_id, upload_id).exists():
            return False
        if job.next_attempt_at is not None and _parse_timestamp(job.next_attempt_at) > now:
            return False
        return _is_ready_for_claim(job, now=now)

    def _promoted_knowledge_records(
        self,
        *,
        upload: QuarantinedKnowledgeUpload,
        source: KnowledgeSource,
        parsed_document: ParsedKnowledgeDocument,
        original_bytes: bytes,
    ) -> tuple[KnowledgeDocument, KnowledgeIngestionJob, ParserMetadata]:
        suffix = upload.upload_id.removeprefix("upload_")
        document_id = f"doc_{suffix}"
        revision_id = f"rev_{suffix}"
        job_id = f"job_{suffix}"
        now = _now()
        content_hash = hashlib.sha256(original_bytes).hexdigest()
        parsed_text_sha256 = hashlib.sha256(parsed_document.text.encode("utf-8")).hexdigest()
        parser_metadata = replace(
            parsed_document.parser_metadata,
            parsed_text_sha256=parsed_text_sha256,
        )
        artifact_build_spec = KnowledgeArtifactBuildSpec(
            provider="local_index",
            engine_name="llama-index-tree",
            engine_version=local_index_engine_version(),
            parser_fingerprint_identity=parser_metadata.fingerprint_identity,
            content_hash=content_hash,
            parsed_text_sha256=parsed_text_sha256,
            declared_ingestion_model=_declared_ingestion_model(source.params),
        )
        storage_path = (
            Path("knowledge_sources")
            / upload.source_id
            / "documents"
            / document_id
            / "revisions"
            / revision_id
            / "original.bin"
        )
        document = KnowledgeDocument(
            document_id=document_id,
            source_id=upload.source_id,
            revision_id=revision_id,
            filename=upload.filename,
            content_type=upload.content_type,
            content_hash=content_hash,
            size_bytes=upload.size_bytes,
            state="queued",
            storage_path=storage_path.as_posix(),
            ingestion_job_id=job_id,
            created_at=now,
            updated_at=now,
        )
        job = KnowledgeIngestionJob(
            job_id=job_id,
            source_id=upload.source_id,
            document_id=document_id,
            revision_id=revision_id,
            state="queued",
            ingestion_config_fingerprint=ingestion_config_fingerprint(artifact_build_spec),
            artifact_build_spec=artifact_build_spec,
            created_at=now,
            updated_at=now,
        )
        return document, job, parser_metadata

    def _repair_accepted_upload_projection_unlocked(
        self,
        upload: QuarantinedKnowledgeUpload,
    ) -> tuple[KnowledgeDocument, KnowledgeIngestionJob]:
        marker = _read_json(self._upload_promotion_marker_path(upload.source_id, upload.upload_id))
        document_id = _required_marker_string(marker, "document_id")
        job_id = _required_marker_string(marker, "job_id")
        document = self.get_knowledge_document(
            source_id=upload.source_id,
            document_id=document_id,
        )
        job = self.get_knowledge_ingestion_job(
            source_id=upload.source_id,
            job_id=job_id,
        )
        if document is None or job is None:
            raise _invalid_ingestion_transition(
                f"Knowledge upload promotion marker for {upload.upload_id} is incomplete."
            )
        self._write_quarantined_knowledge_upload(
            _accepted_upload_projection(upload, document=document, job=job)
        )
        self.quarantined_knowledge_upload_bytes_path(upload).unlink(missing_ok=True)
        return document, job

    def _count_reserved_knowledge_document_slots_unlocked(self, source_id: str) -> int:
        managed_document_count = len(self.list_knowledge_documents(source_id))
        reservation_count = sum(
            upload.state in {"queued", "processing"}
            for upload in self.list_quarantined_knowledge_uploads(source_id)
        )
        return managed_document_count + reservation_count

    def _publish_quarantined_knowledge_upload(
        self,
        upload: QuarantinedKnowledgeUpload,
        content: bytes,
    ) -> None:
        uploads_root = self._quarantined_knowledge_uploads_root(upload.source_id)
        uploads_root.mkdir(parents=True, exist_ok=True)
        temporary_dir = Path(
            tempfile.mkdtemp(
                prefix=f".{upload.upload_id}.",
                dir=uploads_root,
            )
        )
        try:
            (temporary_dir / "original-upload.bin").write_bytes(content)
            _write_json(temporary_dir / "upload.json", upload.model_dump(mode="json"))
            os.replace(temporary_dir, uploads_root / upload.upload_id)
        except Exception:
            shutil.rmtree(temporary_dir, ignore_errors=True)
            raise

    def _require_draft(self, agent_id: str, draft_id: str) -> DraftAgent:
        draft = self.get_draft(agent_id, draft_id)
        if draft is None:
            raise KeyError(f"Draft Agent not found: {agent_id}/{draft_id}")
        return draft

    def _draft_path(self, agent_id: str, draft_id: str) -> Path:
        return self._root_dir / "agents" / agent_id / "drafts" / draft_id / "draft.json"

    def _version_path(self, agent_id: str, version_id: str) -> Path:
        return self._root_dir / "agents" / agent_id / "versions" / version_id

    def _active_version_path(self, agent_id: str) -> Path:
        return self._root_dir / "agents" / agent_id / "active_version.json"

    def _knowledge_source_path(self, source_id: str) -> Path:
        return self._root_dir / "knowledge_sources" / source_id / "source.json"

    def _quarantined_knowledge_uploads_root(self, source_id: str) -> Path:
        return self._root_dir / "knowledge_sources" / source_id / "quarantined_uploads"

    def _quarantined_knowledge_upload_path(self, source_id: str, upload_id: str) -> Path:
        return self._quarantined_knowledge_uploads_root(source_id) / upload_id / "upload.json"

    def _knowledge_ingestion_jobs_root(self, source_id: str) -> Path:
        return self._root_dir / "knowledge_sources" / source_id / "ingestion_jobs"

    def _knowledge_ingestion_job_path(self, source_id: str, job_id: str) -> Path:
        return self._knowledge_ingestion_jobs_root(source_id) / job_id / "job.json"

    def _upload_promotion_marker_path(self, source_id: str, upload_id: str) -> Path:
        return (
            self._root_dir
            / "knowledge_sources"
            / source_id
            / "upload_promotions"
            / f"{upload_id}.json"
        )

    def _store_lock_path(self) -> Path:
        return store_lock_path(self._root_dir)

    def _knowledge_document_path(self, source_id: str, document_id: str) -> Path:
        return (
            self._root_dir
            / "knowledge_sources"
            / source_id
            / "documents"
            / document_id
            / "document.json"
        )

    def _write_draft(self, draft: DraftAgent) -> None:
        _write_json(self._draft_path(draft.agent_id, draft.draft_id), draft.model_dump(mode="json"))

    def _write_version(self, version: PublishedAgentVersion) -> None:
        version_dir = self._version_path(version.agent_id, version.version_id)
        version_dir.mkdir(parents=True, exist_ok=True)
        bundle = version.contract_bundle
        (version_dir / "agent.yaml").write_text(bundle.agent_yaml, encoding="utf-8")
        (version_dir / "policy.yaml").write_text(bundle.policy_yaml, encoding="utf-8")
        (version_dir / "tools.yaml").write_text(bundle.tools_yaml, encoding="utf-8")
        for filename, content in bundle.extra_files.items():
            path = version_dir / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        _write_json(version_dir / "publication.json", version.model_dump(mode="json"))

    def _write_active_version(self, active: ActiveAgentVersion) -> None:
        _write_json(self._active_version_path(active.agent_id), active.model_dump(mode="json"))

    def _write_knowledge_source(self, source: KnowledgeSource) -> None:
        _write_json(self._knowledge_source_path(source.source_id), source.model_dump(mode="json"))

    def _write_knowledge_document(self, document: KnowledgeDocument) -> None:
        _write_json_atomic(
            self._knowledge_document_path(document.source_id, document.document_id),
            document.model_dump(mode="json"),
        )

    def _write_quarantined_knowledge_upload(self, upload: QuarantinedKnowledgeUpload) -> None:
        _write_json_atomic(
            self._quarantined_knowledge_upload_path(upload.source_id, upload.upload_id),
            upload.model_dump(mode="json"),
        )

    def _write_knowledge_ingestion_job(self, job: KnowledgeIngestionJob) -> None:
        _write_json_atomic(
            self._knowledge_ingestion_job_path(job.source_id, job.job_id),
            job.model_dump(mode="json"),
        )

    def _write_upload_promotion_marker(
        self,
        upload: QuarantinedKnowledgeUpload,
        document: KnowledgeDocument,
        job: KnowledgeIngestionJob,
    ) -> None:
        _write_json_atomic(
            self._upload_promotion_marker_path(upload.source_id, upload.upload_id),
            {
                "upload_id": upload.upload_id,
                "document_id": document.document_id,
                "revision_id": document.revision_id,
                "job_id": job.job_id,
            },
        )


def _audit(
    operation: ConfigurationOperation,
    *,
    actor: str,
    summary: str,
    metadata: Mapping[str, Any] | None = None,
) -> ConfigurationOperationAudit:
    return ConfigurationOperationAudit(
        operation_id=f"op_{uuid4().hex[:8]}",
        operation=operation,
        actor=actor,
        created_at=_now(),
        summary=summary,
        metadata=metadata or {},
    )


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _safe_filename(filename: str) -> str:
    name = Path(filename).name.strip() or "document"
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)


def _knowledge_source_worker_concurrency(params: Mapping[str, Any]) -> int:
    value = params.get("worker_concurrency", 2)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 8:
        raise ProofAgentError(
            "PA_INGESTION_001",
            "Knowledge Source params.worker_concurrency must be an integer from 1 through 8.",
            "Set params.worker_concurrency to an integer from 1 through 8.",
        )
    return value


def _knowledge_document_capacity_exceeded(source_id: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_INGESTION_004",
        f"Knowledge Source {source_id} has reached its document capacity.",
        "Archive an existing document or wait for a pending upload validation to finish.",
    )


def _declared_ingestion_model(params: Mapping[str, Any]) -> Mapping[str, Any] | None:
    value = params.get("ingestion_model")
    return value if isinstance(value, Mapping) else None


def _accepted_upload_projection(
    upload: QuarantinedKnowledgeUpload,
    *,
    document: KnowledgeDocument,
    job: KnowledgeIngestionJob,
) -> QuarantinedKnowledgeUpload:
    now = _now()
    return upload.model_copy(
        update={
            "state": "accepted",
            "completed_at": now,
            "promoted_document_id": document.document_id,
            "promoted_revision_id": document.revision_id,
            "ingestion_job_id": job.job_id,
            "claimed_at": None,
            "claim_token": None,
            "lease_expires_at": None,
            "updated_at": now,
        }
    )


def _is_expired_rejected_upload(
    upload: QuarantinedKnowledgeUpload,
    *,
    now: datetime,
) -> bool:
    if upload.state != "rejected" or upload.expires_at is None or upload.purged_at is not None:
        return False
    expires_at = datetime.fromisoformat(upload.expires_at.replace("Z", "+00:00"))
    return expires_at <= now


def _required_marker_string(marker: Mapping[str, Any], key: str) -> str:
    value = marker.get(key)
    if not isinstance(value, str) or not value:
        raise _invalid_ingestion_transition(f"Knowledge upload promotion marker requires {key}.")
    return value


def _invalid_ingestion_transition(message: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_INGESTION_004",
        message,
        "Retry the operation after refreshing the persisted knowledge ingestion state.",
    )


def _new_claim_updates(
    task: QuarantinedKnowledgeUpload | KnowledgeIngestionJob,
    *,
    lease_seconds: int,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "state": "processing",
        "attempt_count": task.attempt_count + 1,
        "claimed_at": _timestamp(now),
        "claim_token": f"claim_{uuid4().hex}",
        "lease_expires_at": _timestamp(now + timedelta(seconds=lease_seconds)),
        "updated_at": _timestamp(now),
    }


def _renewed_claim_updates(*, lease_seconds: int) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "lease_expires_at": _timestamp(now + timedelta(seconds=lease_seconds)),
        "updated_at": _timestamp(now),
    }


def _cleared_claim_updates() -> dict[str, Any]:
    return {
        "claimed_at": None,
        "claim_token": None,
        "lease_expires_at": None,
    }


def _require_owned_processing_claim(
    task: QuarantinedKnowledgeUpload | KnowledgeIngestionJob,
    *,
    claim_token: str,
) -> None:
    if task.state != "processing" or task.claim_token != claim_token:
        raise _invalid_ingestion_transition(
            "Knowledge ingestion task is not owned by the current worker claim."
        )


def _is_ready_for_claim(
    task: QuarantinedKnowledgeUpload | KnowledgeIngestionJob,
    *,
    now: datetime,
) -> bool:
    return task.state == "queued" or (
        task.state == "processing" and not _has_active_lease(task, now=now)
    )


def _has_active_lease(
    task: QuarantinedKnowledgeUpload | KnowledgeIngestionJob,
    *,
    now: datetime,
) -> bool:
    return task.lease_expires_at is not None and _parse_timestamp(task.lease_expires_at) > now


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _operator_error_message(message: str) -> str:
    first_line = message.strip().splitlines()[0] if message.strip() else ""
    if not first_line or first_line.startswith("Traceback"):
        return "Local Index artifact build failed."
    return first_line[:500]


def _default_auto_retry_delay_seconds(auto_retry_count: int) -> int:
    return 30 if auto_retry_count == 1 else 120


def _read_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_jsonable(payload), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    content = json.dumps(_jsonable(payload), indent=2, sort_keys=True).encode("utf-8")
    _write_bytes_atomic(path, content)


def _write_text_atomic(path: Path, content: str) -> None:
    _write_bytes_atomic(path, content.encode("utf-8"))


def _write_bytes_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as handle:
            handle.write(content)
        os.replace(temporary_path, path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value
