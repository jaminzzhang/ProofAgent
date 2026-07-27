"""Explicit one-shot migration from the retired file-backed Knowledge Hub."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, BinaryIO, Literal, Protocol
from uuid import uuid4

from pydantic import Field

from proof_agent.bootstrap.validation import validate_secret_safe_params
from proof_agent.capabilities.knowledge.http_json import HttpJsonProvider
from proof_agent.contracts import (
    AuditActorFacts,
    AuditCategory,
    AuditMetadataRecord,
    AuditOutcome,
    KnowledgeDocument,
    KnowledgeSource,
    KnowledgeSourceLifecycleState,
)
from proof_agent.contracts._base import StrictFrozenModel
from proof_agent.contracts.manifest import KnowledgeConfig


class DevelopmentKnowledgeHubBackupError(RuntimeError):
    """The operator-supplied backup is not an exact source snapshot."""


class DevelopmentKnowledgeHubMigrationTarget(Protocol):
    """Narrow target port; production implementation uses PostgreSQL and V1 intake."""

    def source_exists(self, source_id: str) -> bool: ...

    def create_source(
        self,
        *,
        source_id: str,
        name: str,
        provider: Literal["hybrid_index", "http_json"],
        params: Mapping[str, object],
        actor: AuditActorFacts,
    ) -> int: ...

    def upload_original(
        self,
        *,
        source_id: str,
        legacy_document_id: str,
        legacy_revision_id: str,
        filename: str,
        content_type: str,
        content: BinaryIO,
        content_sha256: str,
        size_bytes: int,
        routing_metadata: Mapping[str, object],
        expected_revision: int,
        idempotency_key: str,
        actor: AuditActorFacts,
    ) -> int: ...

    def finalize_source_lifecycle(
        self,
        *,
        source_id: str,
        lifecycle_state: KnowledgeSourceLifecycleState,
        expected_revision: int,
        actor: AuditActorFacts,
    ) -> int: ...


class PostgresHybridDevelopmentKnowledgeHubMigrationTarget:
    """Production-grade target: PostgreSQL authority plus the V1 Hybrid intake path."""

    def __init__(
        self,
        *,
        persistence: Any,
        intake: Any,
        owned_resources: tuple[object, ...] = (),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._persistence = persistence
        self._intake = intake
        self._owned_resources = owned_resources
        self._clock = clock

    def source_exists(self, source_id: str) -> bool:
        return self._persistence.knowledge.get_source_record(source_id) is not None

    def create_source(
        self,
        *,
        source_id: str,
        name: str,
        provider: Literal["hybrid_index", "http_json"],
        params: Mapping[str, object],
        actor: AuditActorFacts,
    ) -> int:
        if provider == "hybrid_index":
            self._intake.create_source(
                source_id=source_id,
                name=name,
                params=params,
                actor=actor,
            )
        else:
            now = _timestamp(_aware_now(self._clock))
            source = KnowledgeSource(
                source_id=source_id,
                name=name,
                provider="http_json",
                lifecycle_state=KnowledgeSourceLifecycleState.ACTIVE,
                params=params,
                created_at=now,
                updated_at=now,
                source_draft_version_id=str(uuid4()),
            )
            with self._persistence.configuration_uow() as unit_of_work:
                unit_of_work.knowledge.save_source(source, expected_revision=0)
                unit_of_work.audit.append(
                    AuditMetadataRecord(
                        audit_id=str(uuid4()),
                        category=AuditCategory.CONFIGURATION,
                        event_type="development_knowledge_hub.http_json_migrated",
                        outcome=AuditOutcome.SUCCEEDED,
                        actor=actor,
                        occurred_at=now,
                        target_type="knowledge_source",
                        target_id=source_id,
                        metadata={
                            "provider": "http_json",
                            "publication_state": "unpublished",
                            "verification_state": "required",
                        },
                    )
                )
                unit_of_work.commit()
        record = self._persistence.knowledge.get_source_record(source_id)
        if record is None:
            raise RuntimeError("Target Source creation was not visible after commit.")
        return int(record.revision)

    def upload_original(
        self,
        *,
        source_id: str,
        legacy_document_id: str,
        legacy_revision_id: str,
        filename: str,
        content_type: str,
        content: BinaryIO,
        content_sha256: str,
        size_bytes: int,
        routing_metadata: Mapping[str, object],
        expected_revision: int,
        idempotency_key: str,
        actor: AuditActorFacts,
    ) -> int:
        operation = self._intake.upload_document(
            source_id=source_id,
            filename=filename,
            content_type=content_type,
            content=content,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            actor=actor,
        )
        now = _timestamp(_aware_now(self._clock))
        with self._persistence.configuration_uow() as unit_of_work:
            unit_of_work.audit.append(
                AuditMetadataRecord(
                    audit_id=str(uuid4()),
                    category=AuditCategory.CONFIGURATION,
                    event_type="development_knowledge_hub.original_admitted",
                    outcome=AuditOutcome.SUCCEEDED,
                    actor=actor,
                    occurred_at=now,
                    target_type="knowledge_source_operation",
                    target_id=operation.operation_id,
                    metadata={
                        "source_id": source_id,
                        "legacy_document_id": legacy_document_id,
                        "legacy_revision_id": legacy_revision_id,
                        "content_sha256": content_sha256,
                        "size_bytes": size_bytes,
                        "routing_metadata": routing_metadata,
                    },
                )
            )
            unit_of_work.commit()
        return int(operation.source_revision)

    def finalize_source_lifecycle(
        self,
        *,
        source_id: str,
        lifecycle_state: KnowledgeSourceLifecycleState,
        expected_revision: int,
        actor: AuditActorFacts,
    ) -> int:
        if lifecycle_state is KnowledgeSourceLifecycleState.ACTIVE:
            return expected_revision
        now = _timestamp(_aware_now(self._clock))
        with self._persistence.configuration_uow() as unit_of_work:
            record = unit_of_work.knowledge.get_source_record(source_id)
            if record is None or record.revision != expected_revision:
                raise RuntimeError("Target Source changed before lifecycle finalization.")
            unit_of_work.knowledge.save_source(
                record.source.model_copy(
                    update={
                        "lifecycle_state": KnowledgeSourceLifecycleState.ARCHIVED,
                        "updated_at": now,
                    }
                ),
                expected_revision=expected_revision,
            )
            unit_of_work.audit.append(
                AuditMetadataRecord(
                    audit_id=str(uuid4()),
                    category=AuditCategory.CONFIGURATION,
                    event_type="development_knowledge_hub.lifecycle_preserved",
                    outcome=AuditOutcome.SUCCEEDED,
                    actor=actor,
                    occurred_at=now,
                    target_type="knowledge_source",
                    target_id=source_id,
                    metadata={
                        "lifecycle_state": KnowledgeSourceLifecycleState.ARCHIVED.value,
                        "previous_revision": expected_revision,
                    },
                )
            )
            unit_of_work.commit()
        return expected_revision + 1

    def close(self) -> None:
        primary: BaseException | None = None
        for resource in reversed(self._owned_resources):
            close = getattr(resource, "close", None)
            if not callable(close):
                continue
            try:
                close()
            except BaseException as exc:
                if primary is None:
                    primary = exc
                else:
                    primary.add_note(
                        f"Additional migration target close failure: {type(exc).__name__}"
                    )
        if primary is not None:
            raise primary


def compose_development_knowledge_hub_migration_target(
    environment: Mapping[str, str],
) -> PostgresHybridDevelopmentKnowledgeHubMigrationTarget:
    """Compose only the authorities needed by the explicit migration command."""

    from proof_agent.capabilities.knowledge.hybrid.s3_artifacts import (
        S3ExactArtifactStore,
    )
    from proof_agent.capabilities.knowledge.ingestion.hybrid_worker import (
        HybridPrivateParserBuildConfig,
    )
    from proof_agent.capabilities.persistence.postgres.bundle import (
        PostgresPersistenceBundle,
    )
    from proof_agent.control.knowledge.production_intake import (
        ProductionHybridKnowledgeIntakeService,
    )

    if environment.get("PROOF_AGENT_MODE", "").strip() != "production":
        raise ValueError("Migration target requires PROOF_AGENT_MODE=production.")
    application_dsn = _required_environment(environment, "PROOF_AGENT_POSTGRES_DSN")
    hybrid_dsn = _required_environment(environment, "HYBRID_POSTGRES_DSN")
    if application_dsn != hybrid_dsn:
        raise ValueError(
            "PROOF_AGENT_POSTGRES_DSN and HYBRID_POSTGRES_DSN must identify one authority."
        )
    build_config = HybridPrivateParserBuildConfig(
        parser_revision=_required_environment(
            environment,
            "PA_KNOWLEDGE_PARSER_REVISION",
        ),
        model_digests=tuple(
            item.strip()
            for item in _required_environment(
                environment,
                "PA_KNOWLEDGE_MODEL_DIGESTS",
            ).split(",")
            if item.strip()
        ),
        configuration_sha256=_required_environment(
            environment,
            "PA_KNOWLEDGE_PARSER_CONFIGURATION_SHA256",
        ),
    )
    persistence = PostgresPersistenceBundle.create(application_dsn)
    resources: list[object] = [persistence]
    try:
        artifact_store = S3ExactArtifactStore.from_environment(
            bucket=_required_environment(environment, "HYBRID_S3_BUCKET"),
            key_prefix=environment.get("HYBRID_S3_KEY_PREFIX", ""),
            endpoint_url=environment.get("HYBRID_S3_ENDPOINT") or None,
            region_name=environment.get("HYBRID_S3_REGION") or None,
            allow_insecure_endpoint=(
                environment.get("HYBRID_S3_ALLOW_INSECURE_ENDPOINT", "").strip()
                == "1"
            ),
        )
        resources.append(artifact_store)
        intake = ProductionHybridKnowledgeIntakeService(
            knowledge=persistence.knowledge,
            ingestion=persistence.hybrid_ingestion,
            unit_of_work_factory=persistence.configuration_uow,
            artifact_store=artifact_store,
            build_config=build_config,
        )
        return PostgresHybridDevelopmentKnowledgeHubMigrationTarget(
            persistence=persistence,
            intake=intake,
            owned_resources=tuple(resources),
        )
    except BaseException:
        for resource in reversed(resources):
            close = getattr(resource, "close", None)
            if callable(close):
                close()
        raise

    def upload_original(
        self,
        *,
        source_id: str,
        legacy_document_id: str,
        legacy_revision_id: str,
        filename: str,
        content_type: str,
        content: BinaryIO,
        content_sha256: str,
        size_bytes: int,
        routing_metadata: Mapping[str, object],
        expected_revision: int,
        idempotency_key: str,
        actor: AuditActorFacts,
    ) -> int: ...


class DevelopmentKnowledgeHubMigrationItem(StrictFrozenModel):
    source_id: str
    source_provider: str
    target_provider: str | None = None
    status: Literal["planned", "migrated", "failed", "skipped"]
    code: str
    detail: str
    document_count: int = Field(default=0, ge=0)
    migrated_document_count: int = Field(default=0, ge=0)
    requires_fresh_verification: bool = False
    target_mutation_started: bool = False


class DevelopmentKnowledgeHubMigrationManifest(StrictFrozenModel):
    schema_version: Literal["development-knowledge-hub-migration.v1"] = (
        "development-knowledge-hub-migration.v1"
    )
    dry_run: bool
    status: Literal["planned", "succeeded", "partial_failure", "failed"]
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    backup_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    backup_verified: bool
    source_file_count: int = Field(ge=0)
    source_total_bytes: int = Field(ge=0)
    started_at: str
    completed_at: str
    items: tuple[DevelopmentKnowledgeHubMigrationItem, ...]
    summary: Mapping[str, int]


@dataclass(frozen=True)
class _TreeIdentity:
    sha256: str
    file_count: int
    total_bytes: int


@dataclass(frozen=True)
class _PreparedDocument:
    document: KnowledgeDocument
    original_path: Path


@dataclass(frozen=True)
class _PreparedSource:
    source: KnowledgeSource
    target_provider: Literal["hybrid_index", "http_json"]
    params: Mapping[str, object]
    documents: tuple[_PreparedDocument, ...]


def migrate_development_knowledge_hub(
    *,
    source_root: Path,
    backup_root: Path,
    target: DevelopmentKnowledgeHubMigrationTarget,
    actor: AuditActorFacts,
    dry_run: bool,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> DevelopmentKnowledgeHubMigrationManifest:
    """Verify an exact backup, read only that snapshot, then migrate items independently."""

    started = _aware_now(clock)
    source_path, backup_path = _validated_roots(source_root, backup_root)
    source_identity = _tree_identity(source_path)
    backup_identity = _tree_identity(backup_path)
    if source_identity != backup_identity:
        raise DevelopmentKnowledgeHubBackupError(
            "Development Knowledge Hub backup does not match the source tree."
        )

    items: list[DevelopmentKnowledgeHubMigrationItem] = []
    for source in _read_sources(backup_path):
        prepared, rejected = _prepare_source(backup_path, source)
        if rejected is not None:
            items.append(rejected)
            continue
        assert prepared is not None
        if target.source_exists(source.source_id):
            items.append(
                _item_failure(
                    source,
                    code="source_id_conflict",
                    detail="The target Source ID already exists; authority was not overwritten.",
                    target_provider=prepared.target_provider,
                    document_count=len(prepared.documents),
                )
            )
            continue
        if dry_run:
            items.append(
                DevelopmentKnowledgeHubMigrationItem(
                    source_id=source.source_id,
                    source_provider=source.provider,
                    target_provider=prepared.target_provider,
                    status="planned",
                    code="migration_planned",
                    detail="The Source passed backup, configuration, and original validation.",
                    document_count=len(prepared.documents),
                    requires_fresh_verification=(
                        prepared.target_provider == "http_json"
                    ),
                )
            )
            continue
        items.append(_apply_source(prepared, target=target, actor=actor))

    completed = _aware_now(clock)
    summary = {
        state: sum(item.status == state for item in items)
        for state in ("planned", "migrated", "failed", "skipped")
    }
    return DevelopmentKnowledgeHubMigrationManifest(
        dry_run=dry_run,
        status=_manifest_status(items, dry_run=dry_run),
        source_sha256=source_identity.sha256,
        backup_sha256=backup_identity.sha256,
        backup_verified=True,
        source_file_count=source_identity.file_count,
        source_total_bytes=source_identity.total_bytes,
        started_at=_timestamp(started),
        completed_at=_timestamp(completed),
        items=tuple(items),
        summary=summary,
    )


def write_development_knowledge_hub_migration_manifest(
    manifest: DevelopmentKnowledgeHubMigrationManifest,
    json_path: Path,
) -> tuple[Path, Path]:
    """Atomically emit machine-readable JSON and a concise operator report."""

    destination = json_path.resolve()
    if destination.suffix.lower() != ".json":
        raise ValueError("Migration manifest path must end in .json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    text_path = destination.with_suffix(".txt")
    _atomic_text(
        destination,
        json.dumps(
            manifest.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
    )
    lines = [
        "Development Knowledge Hub one-shot migration",
        f"status: {manifest.status}",
        f"dry-run: {str(manifest.dry_run).lower()}",
        f"backup verified: {str(manifest.backup_verified).lower()}",
        f"source sha256: {manifest.source_sha256}",
        f"succeeded: {manifest.summary.get('migrated', 0)}",
        *(f"{key}: {value}" for key, value in manifest.summary.items()),
        "",
    ]
    lines.extend(
        f"{item.source_id}: {item.status} ({item.code}) — {item.detail}"
        for item in manifest.items
    )
    _atomic_text(text_path, "\n".join(lines) + "\n")
    return destination, text_path


def _prepare_source(
    backup_root: Path,
    source: KnowledgeSource,
) -> tuple[_PreparedSource | None, DevelopmentKnowledgeHubMigrationItem | None]:
    if source.provider == "local_markdown":
        return None, DevelopmentKnowledgeHubMigrationItem(
            source_id=source.source_id,
            source_provider=source.provider,
            status="skipped",
            code="package_local_markdown_excluded",
            detail="Package-local Markdown remains an Agent package asset.",
        )
    if source.provider not in {"local_index", "http_json"}:
        return None, _item_failure(
            source,
            code="unsupported_legacy_provider",
            detail="Only shared local_index and http_json Sources are supported.",
        )
    try:
        validate_secret_safe_params(
            source.params,
            field_prefix=f"knowledge_sources[{source.source_id}].params",
        )
        _reject_literal_credentials(source.params)
    except Exception:
        return None, _item_failure(
            source,
            code="secret_value_rejected",
            detail="The Source contains a literal credential or invalid credential placement.",
            target_provider=(
                "hybrid_index" if source.provider == "local_index" else "http_json"
            ),
        )

    if source.provider == "http_json":
        try:
            HttpJsonProvider.from_config(
                KnowledgeConfig(provider="http_json", params=source.params)
            )
        except Exception:
            return None, _item_failure(
                source,
                code="http_json_config_invalid",
                detail="The non-secret HTTP JSON adapter configuration is invalid.",
                target_provider="http_json",
            )
        return (
            _PreparedSource(
                source=source,
                target_provider="http_json",
                params=_plain_mapping(source.params),
                documents=(),
            ),
            None,
        )

    documents: list[_PreparedDocument] = []
    for document in _read_documents(backup_root, source.source_id):
        if (
            document.content_type.partition(";")[0].strip().lower()
            != "application/pdf"
            or not document.filename.lower().endswith(".pdf")
        ):
            return None, _item_failure(
                source,
                code="document_media_unsupported",
                detail="A legacy original is not an admissible PDF and was not converted.",
                target_provider="hybrid_index",
                document_count=len(documents) + 1,
            )
        original = (backup_root / document.storage_path).resolve()
        if (
            not original.is_relative_to(backup_root)
            or not original.is_file()
            or original.is_symlink()
        ):
            return None, _item_failure(
                source,
                code="document_original_missing",
                detail="A declared document original is missing from the verified backup.",
                target_provider="hybrid_index",
                document_count=len(documents) + 1,
            )
        digest, size = _file_identity(original)
        if digest != document.content_hash or size != document.size_bytes:
            return None, _item_failure(
                source,
                code="document_original_identity_mismatch",
                detail="A document original does not match its declared hash and size.",
                target_provider="hybrid_index",
                document_count=len(documents) + 1,
            )
        documents.append(_PreparedDocument(document=document, original_path=original))
    return (
        _PreparedSource(
            source=source,
            target_provider="hybrid_index",
            params=_hybrid_intake_params(source.params),
            documents=tuple(documents),
        ),
        None,
    )


def _apply_source(
    prepared: _PreparedSource,
    *,
    target: DevelopmentKnowledgeHubMigrationTarget,
    actor: AuditActorFacts,
) -> DevelopmentKnowledgeHubMigrationItem:
    source = prepared.source
    mutated = False
    migrated_documents = 0
    try:
        revision = target.create_source(
            source_id=source.source_id,
            name=source.name,
            provider=prepared.target_provider,
            params=prepared.params,
            actor=actor,
        )
        mutated = True
        for prepared_document in prepared.documents:
            document = prepared_document.document
            idempotency_key = "migration-" + hashlib.sha256(
                (
                    f"{source.source_id}\0{document.document_id}\0"
                    f"{document.revision_id}\0{document.content_hash}"
                ).encode("utf-8")
            ).hexdigest()
            with prepared_document.original_path.open("rb") as content:
                revision = target.upload_original(
                    source_id=source.source_id,
                    legacy_document_id=document.document_id,
                    legacy_revision_id=document.revision_id,
                    filename=document.filename,
                    content_type=document.content_type,
                    content=content,
                    content_sha256=document.content_hash,
                    size_bytes=document.size_bytes,
                    routing_metadata=dict(document.routing_metadata),
                    expected_revision=revision,
                    idempotency_key=idempotency_key,
                    actor=actor,
                )
            migrated_documents += 1
        target.finalize_source_lifecycle(
            source_id=source.source_id,
            lifecycle_state=source.lifecycle_state,
            expected_revision=revision,
            actor=actor,
        )
    except Exception:
        return _item_failure(
            source,
            code="target_mutation_failed",
            detail=(
                "Target admission failed; inspect target audit and queued operations "
                "before retrying this one-shot migration."
            ),
            target_provider=prepared.target_provider,
            document_count=len(prepared.documents),
            migrated_document_count=migrated_documents,
            target_mutation_started=mutated,
        )
    return DevelopmentKnowledgeHubMigrationItem(
        source_id=source.source_id,
        source_provider=source.provider,
        target_provider=prepared.target_provider,
        status="migrated",
        code="migration_admitted",
        detail=(
            "Originals were admitted for fresh ingestion."
            if prepared.target_provider == "hybrid_index"
            else "Non-secret adapter configuration was created as unpublished Draft state."
        ),
        document_count=len(prepared.documents),
        migrated_document_count=migrated_documents,
        requires_fresh_verification=prepared.target_provider == "http_json",
        target_mutation_started=True,
    )


def _item_failure(
    source: KnowledgeSource,
    *,
    code: str,
    detail: str,
    target_provider: str | None = None,
    document_count: int = 0,
    migrated_document_count: int = 0,
    target_mutation_started: bool = False,
) -> DevelopmentKnowledgeHubMigrationItem:
    return DevelopmentKnowledgeHubMigrationItem(
        source_id=source.source_id,
        source_provider=source.provider,
        target_provider=target_provider,
        status="failed",
        code=code,
        detail=detail,
        document_count=document_count,
        migrated_document_count=migrated_document_count,
        target_mutation_started=target_mutation_started,
    )


def _read_sources(root: Path) -> tuple[KnowledgeSource, ...]:
    sources_root = root / "knowledge_sources"
    if not sources_root.exists():
        return ()
    sources: list[KnowledgeSource] = []
    for directory in sorted(sources_root.iterdir(), key=lambda item: item.name):
        path = directory / "source.json"
        if not directory.is_dir() or not path.is_file() or path.is_symlink():
            continue
        payload = _read_json_object(path)
        payload.setdefault("lifecycle_state", KnowledgeSourceLifecycleState.ACTIVE.value)
        sources.append(KnowledgeSource.model_validate(payload))
    return tuple(sorted(sources, key=lambda item: item.source_id))


def _read_documents(root: Path, source_id: str) -> tuple[KnowledgeDocument, ...]:
    documents_root = root / "knowledge_sources" / source_id / "documents"
    if not documents_root.exists():
        return ()
    documents: list[KnowledgeDocument] = []
    for directory in sorted(documents_root.iterdir(), key=lambda item: item.name):
        path = directory / "document.json"
        if not directory.is_dir() or not path.is_file() or path.is_symlink():
            continue
        documents.append(KnowledgeDocument.model_validate(_read_json_object(path)))
    return tuple(sorted(documents, key=lambda item: (item.created_at, item.document_id)))


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path.name}")
    return payload


def _hybrid_intake_params(params: Mapping[str, Any]) -> dict[str, object]:
    allowed = {
        "max_file_bytes",
        "max_pdf_pages",
        "max_batch_files",
        "max_source_documents",
    }
    return {str(key): value for key, value in params.items() if key in allowed}


def _plain_mapping(value: Mapping[str, Any]) -> dict[str, object]:
    def thaw(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {str(key): thaw(nested) for key, nested in item.items()}
        if isinstance(item, list | tuple):
            return [thaw(nested) for nested in item]
        return item

    return {str(key): thaw(item) for key, item in value.items()}


def _reject_literal_credentials(value: Any, *, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, Mapping):
        header_name = value.get("name")
        if (
            isinstance(header_name, str)
            and header_name.lower()
            in {"authorization", "proxy-authorization", "x-api-key", "api-key"}
            and "value" in value
        ):
            raise ValueError("sensitive static header")
        for raw_key, item in value.items():
            key = str(raw_key)
            normalized = key.lower().replace("-", "_")
            reference = normalized.endswith(("_env", "_ref", "_handle"))
            if (
                not reference
                and any(
                    token in normalized
                    for token in (
                        "password",
                        "secret",
                        "access_token",
                        "api_key",
                        "authorization",
                        "credential_value",
                    )
                )
            ):
                raise ValueError("literal credential field")
            _reject_literal_credentials(item, path=(*path, normalized))
        return
    if isinstance(value, list | tuple):
        for item in value:
            _reject_literal_credentials(item, path=path)
        return
    if not isinstance(value, str):
        return
    if path and path[-1].endswith(("_env", "_ref", "_handle", "prefix")):
        return
    if (
        "-----BEGIN PRIVATE KEY-----" in value
        or re.search(r"\bBearer\s+\S{8,}", value, flags=re.IGNORECASE)
        or re.fullmatch(r"AKIA[A-Z0-9]{16}", value)
        or re.fullmatch(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", value)
        or re.match(r"https?://[^/@:\s]+:[^/@\s]+@", value)
    ):
        raise ValueError("literal credential value")


def _validated_roots(source_root: Path, backup_root: Path) -> tuple[Path, Path]:
    source = source_root.resolve()
    backup = backup_root.resolve()
    if not source.is_dir():
        raise DevelopmentKnowledgeHubBackupError(
            "Development Knowledge Hub source root is not a directory."
        )
    if not backup.is_dir():
        raise DevelopmentKnowledgeHubBackupError(
            "Development Knowledge Hub backup root is not a directory."
        )
    if source == backup or source.is_relative_to(backup) or backup.is_relative_to(source):
        raise DevelopmentKnowledgeHubBackupError(
            "Source and backup roots must be distinct, non-nested directories."
        )
    return source, backup


def _tree_identity(root: Path) -> _TreeIdentity:
    digest = hashlib.sha256()
    count = 0
    total = 0
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_symlink():
            raise DevelopmentKnowledgeHubBackupError(
                "Development Knowledge Hub snapshots cannot contain symbolic links."
            )
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix().encode("utf-8")
        file_digest, size = _file_identity(path)
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(size.to_bytes(8, "big"))
        digest.update(bytes.fromhex(file_digest))
        count += 1
        total += size
    return _TreeIdentity(digest.hexdigest(), count, total)


def _file_identity(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _manifest_status(
    items: list[DevelopmentKnowledgeHubMigrationItem],
    *,
    dry_run: bool,
) -> Literal["planned", "succeeded", "partial_failure", "failed"]:
    failures = sum(item.status == "failed" for item in items)
    completed = sum(item.status in {"planned", "migrated", "skipped"} for item in items)
    if failures and completed:
        return "partial_failure"
    if failures:
        return "failed"
    return "planned" if dry_run else "succeeded"


def _aware_now(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Migration clock must be timezone-aware")
    return value


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _required_environment(environment: Mapping[str, str], key: str) -> str:
    value = environment.get(key, "").strip()
    if not value:
        raise ValueError(f"{key} is required for the migration target.")
    return value


def _atomic_text(path: Path, content: str) -> None:
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
        text=True,
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


__all__ = [
    "DevelopmentKnowledgeHubBackupError",
    "DevelopmentKnowledgeHubMigrationItem",
    "DevelopmentKnowledgeHubMigrationManifest",
    "DevelopmentKnowledgeHubMigrationTarget",
    "PostgresHybridDevelopmentKnowledgeHubMigrationTarget",
    "compose_development_knowledge_hub_migration_target",
    "migrate_development_knowledge_hub",
    "write_development_knowledge_hub_migration_manifest",
]
