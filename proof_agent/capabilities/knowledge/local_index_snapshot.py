"""Optional-dependency-safe READY snapshot contracts for Local Index runtime loading."""

from __future__ import annotations

from collections.abc import Mapping
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from pydantic import ValidationError

from proof_agent.contracts import (
    KnowledgeSourceSnapshotDocument,
    KnowledgeSourceSnapshotManifest,
)
from proof_agent.errors import ProofAgentError

@dataclass(frozen=True)
class LocalIndexRuntimeDocument:
    """Trace-safe runtime descriptor for one immutable document revision artifact."""

    document_id: str
    revision_id: str
    filename: str
    content_type: str
    content_hash: str
    artifact_path: Path
    routing_metadata: Mapping[str, Any]


@dataclass(frozen=True)
class LocalIndexRuntimeSnapshot:
    """Trace-safe runtime descriptor for one immutable multi-document snapshot."""

    snapshot_id: str
    source_id: str
    state: str
    validation_level: str
    documents: tuple[LocalIndexRuntimeDocument, ...]


def load_ready_snapshot_manifest(
    snapshot_path: Path,
    *,
    artifact_root: Path,
) -> LocalIndexRuntimeSnapshot:
    """Load one immutable local_index.snapshot.v2 manifest before storage access."""

    manifest_path = snapshot_path / "snapshot.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        if (snapshot_path / "artifact_meta.json").exists():
            raise _invalid_snapshot(
                "Local Index runtime does not load historical v1 snapshot directories.",
                "Migrate and publish a local_index.snapshot.v2 manifest before activating this source.",
            ) from exc
        raise _invalid_snapshot(
            f"Local Index snapshot is missing {manifest_path.name}.",
            "Publish a READY local_index.snapshot.v2 manifest before activating this source.",
        ) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _invalid_snapshot(
            f"Local Index snapshot has an unreadable or malformed {manifest_path.name}.",
            "Publish the snapshot again with a valid local_index.snapshot.v2 manifest.",
        ) from exc

    try:
        manifest = KnowledgeSourceSnapshotManifest.model_validate(payload)
    except ValidationError as exc:
        raise _invalid_snapshot(
            "Local Index snapshot.json violates the local_index.snapshot.v2 contract.",
            "Publish the snapshot again with a valid READY local_index.snapshot.v2 manifest.",
        ) from exc

    if not manifest.documents:
        raise _invalid_snapshot(
            "Local Index snapshot.json requires at least one document.",
            "Publish the snapshot again with at least one READY document.",
        )

    try:
        resolved_artifact_root = artifact_root.resolve()
    except (OSError, RuntimeError) as exc:
        raise _invalid_snapshot(
            "Local Index artifact root cannot be resolved.",
            "Configure an accessible artifact root before activating this source.",
        ) from exc

    seen_document_ids: set[str] = set()
    documents = []
    for document in manifest.documents:
        document_id = _required_manifest_document_string(document, "document_id")
        if document_id in seen_document_ids:
            raise _invalid_snapshot(
                f"Local Index snapshot.json contains duplicate document_id {document_id}.",
                "Publish the snapshot again with one descriptor per document_id.",
            )
        seen_document_ids.add(document_id)
        revision_id = _required_manifest_document_string(document, "revision_id")
        filename = _required_manifest_document_string(document, "filename")
        artifact_path = _required_manifest_document_string(document, "artifact_path")
        documents.append(
            LocalIndexRuntimeDocument(
                document_id=document_id,
                revision_id=revision_id,
                filename=filename,
                content_type=document.content_type,
                content_hash=document.content_hash,
                artifact_path=_contained_artifact_path(
                    resolved_artifact_root,
                    artifact_path,
                ),
                routing_metadata=document.routing_metadata,
            )
        )

    return LocalIndexRuntimeSnapshot(
        snapshot_id=manifest.snapshot_id,
        source_id=manifest.source_id,
        state=manifest.state,
        validation_level=manifest.validation_level,
        documents=tuple(sorted(documents, key=lambda document: document.document_id)),
    )


def _required_manifest_document_string(
    document: KnowledgeSourceSnapshotDocument,
    key: str,
) -> str:
    value = getattr(document, key)
    if not isinstance(value, str) or not value.strip():
        raise _invalid_snapshot(
            f"Local Index snapshot.json requires a non-empty document {key}.",
            f"Publish the snapshot again with a non-empty document {key}.",
        )
    return value


def _contained_artifact_path(artifact_root: Path, artifact_path: str) -> Path:
    posix_path = PurePosixPath(artifact_path)
    windows_path = PureWindowsPath(artifact_path)
    if (
        "\\" in artifact_path
        or posix_path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or not posix_path.parts
    ):
        raise _invalid_snapshot(
            "Local Index snapshot.json artifact_path must be a POSIX relative path.",
            "Publish the snapshot again with POSIX artifact references relative to the artifact root.",
        )
    if ".." in posix_path.parts:
        raise _invalid_snapshot(
            "Local Index snapshot.json artifact_path escapes the artifact root.",
            "Publish the snapshot again with contained relative artifact references.",
        )
    relative_path = Path(*posix_path.parts)
    try:
        resolved_path = (artifact_root / relative_path).resolve()
        resolved_path.relative_to(artifact_root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise _invalid_snapshot(
            "Local Index snapshot.json artifact_path escapes the artifact root.",
            "Publish the snapshot again with contained relative artifact references.",
        ) from exc
    return resolved_path


def _invalid_snapshot(message: str, fix: str) -> ProofAgentError:
    return ProofAgentError("PA_KNOWLEDGE_001", message, fix)
