from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
from typing import BinaryIO
from uuid import uuid4

from pydantic import ValidationError

from proof_agent.capabilities.artifacts import ArtifactStoreError
from proof_agent.contracts.artifacts import ArtifactObjectVersion, ArtifactPutRequest


class FilesystemArtifactStore:
    """Development-only immutable adapter with the same exact-read semantics as S3."""

    def __init__(
        self,
        root: Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._root = root.resolve()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._objects = self._root / "objects"
        self._metadata = self._root / "metadata"
        self._objects.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._metadata.mkdir(parents=True, exist_ok=True, mode=0o700)

    def put_immutable(
        self,
        request: ArtifactPutRequest,
        body: BinaryIO,
    ) -> ArtifactObjectVersion:
        content = body.read(request.expected_size_bytes + 1)
        if not isinstance(content, bytes) or len(content) != request.expected_size_bytes:
            raise ArtifactStoreError("artifact body length does not match put request")
        if hashlib.sha256(content).hexdigest() != request.expected_sha256:
            raise ArtifactStoreError("artifact body digest does not match put request")
        object_uuid = uuid4()
        object_key = f"objects/{object_uuid.hex[:2]}/{object_uuid}"
        path = self._safe_path(object_key)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=path.parent,
                prefix=".artifact-",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
            temporary_path.chmod(0o400)
            os.link(temporary_path, path)
        except FileExistsError as exc:  # pragma: no cover - UUID collision
            raise ArtifactStoreError("system-generated artifact key collided") from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        ref = ArtifactObjectVersion(
            object_id=str(object_uuid),
            bucket="local-artifacts",
            object_key=object_key,
            version_id=str(uuid4()),
            sha256=request.expected_sha256,
            size_bytes=request.expected_size_bytes,
            kind=request.kind,
            owner=request.owner,
            content_type=request.content_type,
            created_at=self._clock(),
            expires_at=request.expires_at,
            display_filename=request.display_filename,
        )
        metadata_path = self._metadata_path(ref.object_id)
        try:
            self._write_metadata(metadata_path, ref)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return self.head_exact(ref)

    def head_exact(self, ref: ArtifactObjectVersion) -> ArtifactObjectVersion:
        stored = self._read_metadata(ref.object_id)
        if stored != ref or not self._safe_path(ref.object_key).is_file():
            raise ArtifactStoreError("exact artifact version is unavailable")
        return stored

    def open_exact(self, ref: ArtifactObjectVersion) -> BinaryIO:
        self.head_exact(ref)
        try:
            content = self._safe_path(ref.object_key).read_bytes()
        except OSError as exc:
            raise ArtifactStoreError("exact artifact version is unavailable") from exc
        if len(content) != ref.size_bytes:
            raise ArtifactStoreError("exact artifact length does not match")
        if hashlib.sha256(content).hexdigest() != ref.sha256:
            raise ArtifactStoreError("exact artifact digest does not match")
        return BytesIO(content)

    def delete_exact(self, ref: ArtifactObjectVersion) -> None:
        self.head_exact(ref)
        self._safe_path(ref.object_key).unlink()
        self._metadata_path(ref.object_id).unlink()

    def iter_versions_before(
        self,
        *,
        prefix: str,
        before: datetime,
    ) -> Iterator[ArtifactObjectVersion]:
        if prefix != "objects/" or before.utcoffset() is None:
            raise ValueError("filesystem artifact iteration requires objects/ and aware time")
        refs: list[ArtifactObjectVersion] = []
        for path in self._metadata.glob("*.json"):
            try:
                ref = ArtifactObjectVersion.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValidationError) as exc:
                raise ArtifactStoreError("artifact metadata is corrupt") from exc
            if ref.created_at < before:
                refs.append(ref)
        yield from sorted(refs, key=lambda item: (item.created_at, item.object_id))

    def _safe_path(self, object_key: str) -> Path:
        path = (self._root / object_key).resolve()
        try:
            path.relative_to(self._objects)
        except ValueError as exc:
            raise ArtifactStoreError("artifact key escaped the store root") from exc
        return path

    def _metadata_path(self, object_id: str) -> Path:
        if not object_id or "/" in object_id or "\\" in object_id:
            raise ArtifactStoreError("artifact object identity is invalid")
        return self._metadata / f"{object_id}.json"

    @staticmethod
    def _write_metadata(path: Path, ref: ArtifactObjectVersion) -> None:
        encoded = json.dumps(
            ref.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        try:
            descriptor = os.open(path, flags, 0o400)
        except FileExistsError as exc:  # pragma: no cover - UUID collision
            raise ArtifactStoreError("artifact metadata identity collided") from exc
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())

    def _read_metadata(self, object_id: str) -> ArtifactObjectVersion:
        try:
            return ArtifactObjectVersion.model_validate_json(
                self._metadata_path(object_id).read_text(encoding="utf-8")
            )
        except FileNotFoundError as exc:
            raise ArtifactStoreError("exact artifact version is unavailable") from exc
        except (OSError, ValidationError) as exc:
            raise ArtifactStoreError("artifact metadata is corrupt") from exc


__all__ = ["FilesystemArtifactStore"]
