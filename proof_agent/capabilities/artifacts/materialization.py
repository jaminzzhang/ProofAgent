from __future__ import annotations

from collections.abc import Mapping
import hashlib
import os
from pathlib import Path
import stat
import tempfile
from typing import BinaryIO, Protocol

from filelock import FileLock, Timeout

from proof_agent.contracts.artifacts import ArtifactManifest, ArtifactObjectVersion


class ExactArtifactReader(Protocol):
    def head_exact(self, ref: ArtifactObjectVersion) -> ArtifactObjectVersion: ...

    def open_exact(self, ref: ArtifactObjectVersion) -> BinaryIO: ...


class MaterializationError(RuntimeError):
    """An exact artifact could not be safely materialized."""


class VerifiedArtifactMaterializer:
    """Digest-keyed read-only cache populated only after full exact verification."""

    def __init__(
        self,
        store: ExactArtifactReader,
        *,
        cache_root: Path,
        lock_timeout_seconds: float = 30.0,
    ) -> None:
        if lock_timeout_seconds <= 0:
            raise ValueError("materialization lock timeout must be positive")
        self._store = store
        self._root = cache_root.resolve()
        self._content = self._root / "sha256"
        self._temporary = self._root / ".tmp"
        self._locks = self._root / ".locks"
        for directory in (self._content, self._temporary, self._locks):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._lock_timeout_seconds = lock_timeout_seconds

    def materialize(self, ref: ArtifactObjectVersion) -> Path:
        target = self._content / ref.sha256
        if self._valid_cached(target, ref):
            return target
        lock = FileLock(self._locks / f"{ref.sha256}.lock")
        try:
            lock.acquire(timeout=self._lock_timeout_seconds)
        except Timeout as exc:
            raise MaterializationError("timed out waiting for artifact materialization") from exc
        try:
            if self._valid_cached(target, ref):
                return target
            target.unlink(missing_ok=True)
            self._download(ref, target)
            if not self._valid_cached(target, ref):
                target.unlink(missing_ok=True)
                raise MaterializationError("materialized artifact failed final verification")
            return target
        finally:
            lock.release()

    def materialize_manifest(self, manifest: ArtifactManifest) -> Mapping[str, Path]:
        paths: dict[str, Path] = {}
        for member in manifest.members:
            paths[member.member_id] = self.materialize(member.artifact)
        if len(paths) != len(manifest.members):
            raise MaterializationError("artifact manifest member set is incomplete")
        return paths

    def _download(self, ref: ArtifactObjectVersion, target: Path) -> None:
        temporary_path: Path | None = None
        try:
            if self._store.head_exact(ref) != ref:
                raise MaterializationError("artifact exact head does not match authority")
            with tempfile.NamedTemporaryFile(
                dir=self._temporary,
                prefix=f"{ref.sha256}.",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                digest = hashlib.sha256()
                length = 0
                with self._store.open_exact(ref) as source:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        if not isinstance(chunk, bytes):
                            raise MaterializationError("artifact reader returned non-bytes")
                        length += len(chunk)
                        if length > ref.size_bytes:
                            raise MaterializationError("artifact download exceeds authority length")
                        digest.update(chunk)
                        temporary.write(chunk)
                if length != ref.size_bytes or digest.hexdigest() != ref.sha256:
                    raise MaterializationError("artifact download failed length or digest check")
                temporary.flush()
                os.fsync(temporary.fileno())
            temporary_path.chmod(0o400)
            os.replace(temporary_path, target)
            temporary_path = None
            directory_descriptor = os.open(self._content, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except MaterializationError:
            raise
        except Exception as exc:
            raise MaterializationError("artifact download or materialization failed") from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _valid_cached(path: Path, ref: ArtifactObjectVersion) -> bool:
        try:
            metadata = path.stat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != ref.size_bytes:
                return False
            if metadata.st_mode & 0o222:
                return False
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest() == ref.sha256
        except OSError:
            return False


__all__ = ["MaterializationError", "VerifiedArtifactMaterializer"]
