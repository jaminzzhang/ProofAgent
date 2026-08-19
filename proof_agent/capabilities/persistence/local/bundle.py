from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from types import TracebackType
from typing import Any

from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.configuration.file_locking import (
    locked,
    replaceable_store_lock_path,
    store_lock_path,
)
from proof_agent.contracts.conversation import ConversationRecord, ConversationTurn
from proof_agent.capabilities.memory.local_store import LocalMemoryStore
from proof_agent.contracts.memory import MemoryQuery, MemoryRecord
from proof_agent.observability.storage.conversation_store import ConversationStore
from proof_agent.contracts.agent_configuration import (
    ActiveAgentVersion,
    DraftAgent,
    SharedModelConnection,
    ToolSource,
    PublishedAgentVersion,
)
from proof_agent.contracts.persistence import (
    AgentActivationRecord,
    AgentDraftRecord,
    AgentPublicationRecord,
    AuditMetadataRecord,
    CaseMemoryAdmission,
    PersistenceConflictError,
    PersistenceInvariantError,
    PersistenceNotFoundError,
    RunAttemptMetadataRecord,
    RunMetadataRecord,
)
from proof_agent.contracts.shared_assets import SharedAssetKind, SharedAssetVersionRef


class _LocalAgentLifecycleRepository:
    """Focused Agent lifecycle adapter over the development filesystem store."""

    def __init__(self, store: LocalAgentConfigurationStore) -> None:
        self._store = store

    def get_draft(self, agent_id: str, draft_id: str) -> AgentDraftRecord | None:
        return self._store.get_draft_record(agent_id, draft_id)

    def list_drafts(
        self,
        agent_id: str | None = None,
    ) -> tuple[AgentDraftRecord, ...]:
        records = (
            self._store.get_draft_record(draft.agent_id, draft.draft_id)
            for draft in self._store.list_drafts(agent_id)
        )
        return tuple(record for record in records if record is not None)

    def save_draft(
        self,
        draft: DraftAgent,
        *,
        expected_revision: int,
    ) -> AgentDraftRecord:
        return self._store.save_draft_record(
            draft,
            expected_revision=expected_revision,
        )

    def publish_version(
        self,
        publication: AgentPublicationRecord,
        *,
        expected_draft_revision: int,
    ) -> AgentPublicationRecord:
        return self._store.publish_version_record(
            publication,
            expected_draft_revision=expected_draft_revision,
        )

    def activate_version(
        self,
        activation: AgentActivationRecord,
    ) -> AgentActivationRecord:
        return self._store.activate_version_record(activation)

    def get_published(
        self,
        agent_id: str,
        version_id: str,
    ) -> PublishedAgentVersion | None:
        return self._store.get_version(agent_id, version_id)

    def list_published(self, agent_id: str) -> tuple[PublishedAgentVersion, ...]:
        return tuple(self._store.list_versions(agent_id))

    def get_active(self, agent_id: str) -> ActiveAgentVersion | None:
        return self._store.get_active_version(agent_id)

    def list_active(self) -> tuple[ActiveAgentVersion, ...]:
        agents_root = self._store.root_dir / "agents"
        if not agents_root.exists():
            return ()
        return tuple(
            active
            for path in sorted(agents_root.iterdir())
            if path.is_dir()
            and (active := self._store.get_active_version(path.name)) is not None
        )


class _LocalModelAssetRepository:
    def __init__(self, store: LocalAgentConfigurationStore) -> None:
        self._store = store

    def get_model_connection(self, connection_id: str) -> SharedModelConnection | None:
        return self._store.get_model_connection(connection_id)

    def resolve_version(
        self,
        asset_id: str,
        *,
        version_id: str | None = None,
    ) -> SharedAssetVersionRef | None:
        connection = self.get_model_connection(asset_id)
        if connection is None:
            return None
        digest = _sha256_value(connection.model_dump(mode="json"))
        resolved_version_id = f"model:{digest}"
        if version_id is not None and version_id != resolved_version_id:
            return None
        return SharedAssetVersionRef(
            kind=SharedAssetKind.MODEL_CONNECTION,
            asset_id=asset_id,
            version_id=resolved_version_id,
            revision=1,
            content_digest=digest,
        )


class _LocalToolAssetRepository:
    def __init__(self, store: LocalAgentConfigurationStore) -> None:
        self._store = store

    def get_tool_source(self, source_id: str) -> ToolSource | None:
        return self._store.get_tool_source(source_id)

    def resolve_version(
        self,
        asset_id: str,
        *,
        version_id: str | None = None,
    ) -> SharedAssetVersionRef | None:
        source = self.get_tool_source(asset_id)
        if source is None:
            return None
        digest = _sha256_value(source.model_dump(mode="json"))
        resolved_version_id = f"tool:{source.config_revision}:{digest}"
        if version_id is not None and version_id != resolved_version_id:
            return None
        return SharedAssetVersionRef(
            kind=SharedAssetKind.TOOL_SOURCE,
            asset_id=asset_id,
            version_id=resolved_version_id,
            revision=source.config_revision,
            content_digest=digest,
        )


class _LocalRunMetadataRepository:
    """Trace-safe Run metadata isolated from local raw run artifacts."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self._attempts_root = root / "attempts"
        self._attempts_root.mkdir(parents=True, exist_ok=True)

    def append(self, record: RunMetadataRecord) -> None:
        path = _record_path(self._root, record.run_id)
        with locked(store_lock_path(self._root), timeout_seconds=5.0):
            if path.exists():
                current = self.get(record.run_id)
                raise PersistenceConflictError(
                    resource_type="run",
                    resource_id=record.run_id,
                    expected_revision=0,
                    actual_revision=None if current is None else current.state_version,
                )
            _write_model_atomic(path, record)

    def get(self, run_id: str) -> RunMetadataRecord | None:
        path = _record_path(self._root, run_id)
        if not path.exists():
            return None
        try:
            return RunMetadataRecord.model_validate_json(path.read_bytes())
        except (OSError, ValueError) as exc:
            raise PersistenceInvariantError("local Run metadata is malformed") from exc

    def transition(
        self,
        record: RunMetadataRecord,
        *,
        expected_state_version: int,
    ) -> RunMetadataRecord:
        if record.state_version != expected_state_version + 1:
            raise PersistenceInvariantError(
                "Run transition must increment state_version exactly once"
            )
        path = _record_path(self._root, record.run_id)
        with locked(store_lock_path(self._root), timeout_seconds=5.0):
            current = self.get(record.run_id)
            actual = None if current is None else current.state_version
            if current is None or actual != expected_state_version:
                raise PersistenceConflictError(
                    resource_type="run",
                    resource_id=record.run_id,
                    expected_revision=expected_state_version,
                    actual_revision=actual,
                )
            if _run_identity(current) != _run_identity(record):
                raise PersistenceInvariantError(
                    "Run transition cannot change immutable request metadata"
                )
            _write_model_atomic(path, record)
        return record

    def append_attempt(self, record: RunAttemptMetadataRecord) -> None:
        if record.state_version != 1:
            raise PersistenceInvariantError("new Attempt state_version must be 1")
        path = _record_path(self._attempts_root, record.attempt_id)
        with locked(store_lock_path(self._root), timeout_seconds=5.0):
            if path.exists():
                raise PersistenceConflictError(
                    resource_type="run_attempt",
                    resource_id=record.attempt_id,
                    expected_revision=0,
                    actual_revision=1,
                )
            _write_model_atomic(path, record)

    def get_attempt(self, attempt_id: str) -> RunAttemptMetadataRecord | None:
        path = _record_path(self._attempts_root, attempt_id)
        if not path.exists():
            return None
        try:
            return RunAttemptMetadataRecord.model_validate_json(path.read_bytes())
        except (OSError, ValueError) as exc:
            raise PersistenceInvariantError("local Attempt metadata is malformed") from exc

    def transition_attempt(
        self,
        record: RunAttemptMetadataRecord,
        *,
        expected_state_version: int,
        expected_fencing_token: int,
    ) -> RunAttemptMetadataRecord:
        if record.state_version != expected_state_version + 1:
            raise PersistenceInvariantError(
                "Attempt transition must increment state_version exactly once"
            )
        if record.fencing_token != expected_fencing_token:
            raise PersistenceInvariantError(
                "Attempt transition cannot change its fencing token"
            )
        path = _record_path(self._attempts_root, record.attempt_id)
        with locked(store_lock_path(self._root), timeout_seconds=5.0):
            current = self.get_attempt(record.attempt_id)
            actual = None if current is None else current.state_version
            if current is None or actual != expected_state_version:
                raise PersistenceConflictError(
                    resource_type="run_attempt",
                    resource_id=record.attempt_id,
                    expected_revision=expected_state_version,
                    actual_revision=actual,
                )
            if _attempt_identity(current) != _attempt_identity(record):
                raise PersistenceInvariantError(
                    "Attempt transition cannot change immutable request metadata"
                )
            _write_model_atomic(path, record)
        return record


class _LocalConversationRepository:
    def __init__(self, store: ConversationStore) -> None:
        self._store = store

    def create(self, record: ConversationRecord) -> None:
        self._store.create_record(record)

    def get(self, conversation_id: str) -> ConversationRecord | None:
        return self._store.get_conversation(conversation_id)

    def list(self, *, limit: int = 200) -> tuple[ConversationRecord, ...]:
        return tuple(self._store.list_conversations()[:limit])

    def update(self, record: ConversationRecord) -> None:
        current = self._store.get_conversation(record.conversation_id)
        if current is None:
            raise PersistenceNotFoundError(
                resource_type="conversation", resource_id=record.conversation_id
            )
        self._store.update_conversation(
            record.conversation_id,
            title=record.title,
            pinned=record.pinned,
        )

    def delete(self, conversation_id: str) -> bool:
        return self._store.delete_conversation(conversation_id)

    def append_turn(
        self,
        conversation_id: str,
        turn: ConversationTurn,
        *,
        expected_turn_count: int,
    ) -> ConversationRecord:
        return self._store.append_turn_expected(
            conversation_id,
            turn,
            expected_turn_count=expected_turn_count,
        )


class _LocalCaseMemoryRepository:
    def __init__(self, store: LocalMemoryStore) -> None:
        self._store = store

    def admit(self, admission: CaseMemoryAdmission) -> MemoryRecord:
        return self._store.admit_case_memory(admission)

    def read(self, query: MemoryQuery, *, as_of: str) -> tuple[MemoryRecord, ...]:
        return self._store.read_at(query, as_of=as_of)

    def expire_due(self, *, as_of: str) -> int:
        return self._store.expire_due(as_of=as_of)


class _LocalAuditRepository:
    def __init__(self, root: Path, *, transition_lock_path: Path | None = None) -> None:
        self._root = root
        self._transition_lock_path = transition_lock_path or store_lock_path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def append(self, event: AuditMetadataRecord) -> None:
        path = _record_path(self._root, event.audit_id)
        with locked(self._transition_lock_path, timeout_seconds=5.0):
            if path.exists():
                raise PersistenceConflictError(
                    resource_type="audit_event",
                    resource_id=event.audit_id,
                    expected_revision=0,
                    actual_revision=1,
                )
            _write_model_atomic(path, event)

    def get(self, audit_id: str) -> AuditMetadataRecord | None:
        path = _record_path(self._root, audit_id)
        if not path.exists():
            return None
        try:
            return AuditMetadataRecord.model_validate_json(path.read_bytes())
        except (OSError, ValueError) as exc:
            raise PersistenceInvariantError("local audit metadata is malformed") from exc


def _sha256_value(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _run_identity(record: RunMetadataRecord) -> tuple[object, ...]:
    return (
        record.run_id,
        record.run_purpose,
        record.agent_id,
        record.agent_version_id,
        record.submitted_by,
        record.created_at,
    )


def _attempt_identity(record: RunAttemptMetadataRecord) -> tuple[object, ...]:
    return (
        record.attempt_id,
        record.run_id,
        record.attempt_number,
        record.fencing_token,
        record.created_at,
    )


def _record_path(root: Path, record_id: str) -> Path:
    if (
        not record_id
        or record_id.strip() != record_id
        or Path(record_id).name != record_id
        or record_id in {".", ".."}
        or "/" in record_id
        or "\\" in record_id
    ):
        raise PersistenceInvariantError("persistence record id must be one safe path segment")
    return root / f"{record_id}.json"


def _write_model_atomic(path: Path, model: Any) -> None:
    content = json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _directory_state_digest(root: Path) -> str:
    """Fingerprint one locked directory snapshot before whole-tree replacement."""

    digest = hashlib.sha256()
    if not root.exists():
        digest.update(b"missing")
        return digest.hexdigest()
    paths = (root, *sorted(root.rglob("*"), key=lambda item: item.as_posix()))
    for path in paths:
        relative = "." if path == root else path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        if path.is_symlink():
            digest.update(b"symlink")
            digest.update(os.readlink(path).encode("utf-8"))
            continue
        if path.is_dir():
            digest.update(b"directory")
            continue
        if path.is_file():
            digest.update(b"file")
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            continue
        digest.update(b"other")
    return digest.hexdigest()


class _LocalConfigurationUnitOfWork:
    """Stage local configuration changes and install them only after commit."""

    _DIRECTORIES = ("configuration", "audit_metadata")

    def __init__(
        self,
        root: Path,
        *,
        configuration_root: Path | None = None,
        audit_root: Path | None = None,
    ) -> None:
        self._root = root
        self._targets = {
            "configuration": configuration_root or root / "configuration",
            "audit_metadata": audit_root or root / "audit_metadata",
        }
        self._transition_lock_path = replaceable_store_lock_path(
            self._targets["configuration"]
        )
        self._root.mkdir(parents=True, exist_ok=True)
        self._staging_root = Path(
            tempfile.mkdtemp(prefix=".configuration-uow-", dir=self._root)
        )
        self._base_state: dict[str, str] = {}
        with locked(self._transition_lock_path, timeout_seconds=5.0):
            for directory_name in self._DIRECTORIES:
                source = self._targets[directory_name]
                destination = self._staging_root / directory_name
                self._base_state[directory_name] = _directory_state_digest(source)
                if source.exists():
                    shutil.copytree(source, destination)
                else:
                    destination.mkdir(parents=True)
        configuration_store = LocalAgentConfigurationStore(
            self._staging_root / "configuration"
        )
        self.agents = _LocalAgentLifecycleRepository(configuration_store)
        self.models = _LocalModelAssetRepository(configuration_store)
        self.tools = _LocalToolAssetRepository(configuration_store)
        self.audit = _LocalAuditRepository(self._staging_root / "audit_metadata")
        self._commit_requested = False
        self._closed = False

    def __enter__(self) -> "_LocalConfigurationUnitOfWork":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is not None or not self._commit_requested:
            self.rollback()
            return
        try:
            self._install_staged_directories()
        except Exception:
            self.rollback()
            raise

    def commit(self) -> None:
        if self._closed:
            raise PersistenceInvariantError("local configuration unit of work is closed")
        self._commit_requested = True

    def rollback(self) -> None:
        if self._closed:
            return
        shutil.rmtree(self._staging_root, ignore_errors=True)
        self._closed = True

    def _install_staged_directories(self) -> None:
        backup_root = self._staging_root / "backups"
        backup_root.mkdir()
        backed_up: list[str] = []
        installed: list[str] = []
        with locked(self._transition_lock_path, timeout_seconds=5.0):
            for directory_name in self._DIRECTORIES:
                if (
                    _directory_state_digest(self._targets[directory_name])
                    != self._base_state[directory_name]
                ):
                    raise PersistenceConflictError(
                        resource_type="configuration_transaction",
                        resource_id=directory_name,
                        expected_revision=1,
                        actual_revision=2,
                    )
            try:
                for directory_name in self._DIRECTORIES:
                    current = self._targets[directory_name]
                    backup = backup_root / directory_name
                    current.parent.mkdir(parents=True, exist_ok=True)
                    if current.exists():
                        os.replace(current, backup)
                        backed_up.append(directory_name)
                    os.replace(self._staging_root / directory_name, current)
                    installed.append(directory_name)
            except Exception:
                for directory_name in reversed(installed):
                    shutil.rmtree(self._targets[directory_name], ignore_errors=True)
                for directory_name in reversed(backed_up):
                    os.replace(
                        backup_root / directory_name,
                        self._targets[directory_name],
                    )
                raise
        shutil.rmtree(self._staging_root, ignore_errors=True)
        self._closed = True


@dataclass(frozen=True)
class LocalPersistenceBundle:
    """Explicit development-only persistence composition root."""

    _root: Path
    _configuration_root: Path
    _audit_root: Path
    agents: _LocalAgentLifecycleRepository
    models: _LocalModelAssetRepository
    tools: _LocalToolAssetRepository
    runs: _LocalRunMetadataRepository
    conversations: _LocalConversationRepository
    case_memory: _LocalCaseMemoryRepository
    audit: _LocalAuditRepository

    def close(self) -> None:
        """Local adapters own no pooled resources."""

    def configuration_uow(self) -> _LocalConfigurationUnitOfWork:
        return _LocalConfigurationUnitOfWork(
            self._root,
            configuration_root=self._configuration_root,
            audit_root=self._audit_root,
        )

    @classmethod
    def create(
        cls,
        root: Path,
        *,
        configuration_root: Path | None = None,
        audit_root: Path | None = None,
    ) -> "LocalPersistenceBundle":
        resolved_configuration_root = configuration_root or root / "configuration"
        resolved_audit_root = audit_root or root / "audit_metadata"
        configuration_store = LocalAgentConfigurationStore(resolved_configuration_root)
        conversation_store = ConversationStore(root / "conversations")
        memory_store = LocalMemoryStore(root / "case_memory")
        return cls(
            _root=root,
            _configuration_root=resolved_configuration_root,
            _audit_root=resolved_audit_root,
            agents=_LocalAgentLifecycleRepository(configuration_store),
            models=_LocalModelAssetRepository(configuration_store),
            tools=_LocalToolAssetRepository(configuration_store),
            runs=_LocalRunMetadataRepository(root / "run_metadata"),
            conversations=_LocalConversationRepository(conversation_store),
            case_memory=_LocalCaseMemoryRepository(memory_store),
            audit=_LocalAuditRepository(
                resolved_audit_root,
                transition_lock_path=replaceable_store_lock_path(
                    resolved_configuration_root
                ),
            ),
        )
