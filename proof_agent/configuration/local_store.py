from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from proof_agent.bootstrap.validation import validate_secret_safe_params
from proof_agent.contracts import (
    ActiveAgentVersion,
    AgentValidationRecord,
    ConfigurationOperation,
    ConfigurationOperationAudit,
    ContractBundle,
    DraftAgent,
    KnowledgeDocument,
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
        _write_json(
            self._knowledge_document_path(document.source_id, document.document_id),
            document.model_dump(mode="json"),
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


def _read_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_jsonable(payload), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value
