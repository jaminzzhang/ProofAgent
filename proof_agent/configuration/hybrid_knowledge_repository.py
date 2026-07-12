"""Deterministic reference adapters for hybrid knowledge ports."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
from threading import RLock
from urllib.parse import unquote, urlsplit

from proof_agent.capabilities.knowledge.hybrid.ports import (
    HybridKnowledgeJob,
    HybridKnowledgeJobClaim,
    HybridKnowledgeJobRequest,
    HybridClock,
)
from proof_agent.contracts.knowledge_index import ExactArtifactRef


class HybridKnowledgeRepositoryError(RuntimeError):
    """Base error for fail-closed reference repository operations."""


class HybridKnowledgeIdempotencyConflict(HybridKnowledgeRepositoryError):
    """An idempotency key was reused for a different immutable request."""


class HybridKnowledgeLeaseError(HybridKnowledgeRepositoryError):
    """A worker attempted an operation without the current active lease."""


class ImmutableArtifactError(HybridKnowledgeRepositoryError):
    """An immutable artifact key or exact reference failed validation."""


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock timestamps must be timezone-aware")
    return value.astimezone(UTC)


class ManualHybridClock:
    """Thread-safe clock advanced explicitly by deterministic tests or workers."""

    def __init__(self, current: datetime | None = None) -> None:
        self._current = _require_aware(current or datetime(2026, 1, 1, tzinfo=UTC))
        self._lock = RLock()

    def now(self) -> datetime:
        with self._lock:
            return self._current

    def advance(self, *, seconds: int = 0, delta: timedelta | None = None) -> datetime:
        if seconds < 0 or (delta is not None and delta < timedelta(0)):
            raise ValueError("manual clock cannot move backwards")
        with self._lock:
            self._current += delta if delta is not None else timedelta(seconds=seconds)
            return self._current


class InMemoryHybridKnowledgeRepository:
    """Lock-safe global FIFO work scheduler with fencing-token leases."""

    def __init__(self, *, clock: HybridClock | None = None) -> None:
        self._clock = clock or ManualHybridClock()
        self._jobs: dict[str, HybridKnowledgeJob] = {}
        self._claims: dict[str, HybridKnowledgeJobClaim] = {}
        self._idempotency: dict[str, str] = {}
        self._sequence: dict[str, int] = {}
        self._next_sequence = 0
        self._lock = RLock()

    def enqueue(self, request: HybridKnowledgeJobRequest) -> HybridKnowledgeJob:
        with self._lock:
            existing_id = self._idempotency.get(request.idempotency_key)
            if existing_id is not None:
                existing = self._jobs[existing_id]
                if existing.request != request:
                    raise HybridKnowledgeIdempotencyConflict(
                        "idempotency key is bound to a different immutable request"
                    )
                return existing
            if request.job_id in self._jobs:
                raise HybridKnowledgeIdempotencyConflict(
                    "job identity is already bound to a different request"
                )
            now = self._clock.now()
            job = HybridKnowledgeJob(
                request=request,
                state="READY",
                created_at=now,
                updated_at=now,
            )
            self._next_sequence += 1
            self._sequence[request.job_id] = self._next_sequence
            self._jobs[request.job_id] = job
            self._idempotency[request.idempotency_key] = request.job_id
            return job

    def claim_next(self, *, worker_id: str, lease_seconds: int) -> HybridKnowledgeJobClaim | None:
        if not worker_id.strip() or lease_seconds <= 0:
            raise ValueError("worker_id and a positive lease_seconds are required")
        with self._lock:
            now = self._clock.now()
            candidates = [job for job in self._jobs.values() if self._ready(job, now)]
            if not candidates:
                return None
            job = min(
                candidates,
                key=lambda item: (
                    item.request.ready_at or item.created_at,
                    item.created_at,
                    self._sequence[item.request.job_id],
                ),
            )
            token = job.fencing_token + 1
            claim = HybridKnowledgeJobClaim(
                job_id=job.request.job_id,
                request=job.request,
                worker_id=worker_id,
                fencing_token=token,
                claimed_at=now,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
            )
            self._claims[job.request.job_id] = claim
            self._jobs[job.request.job_id] = job.model_copy(
                update={"state": "LEASED", "fencing_token": token, "updated_at": now}
            )
            return claim

    def renew(
        self,
        *,
        job_id: str,
        worker_id: str,
        fencing_token: int,
        lease_seconds: int,
    ) -> HybridKnowledgeJobClaim:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        with self._lock:
            claim = self._require_active_claim(job_id, worker_id, fencing_token)
            now = self._clock.now()
            renewed = claim.model_copy(
                update={"lease_expires_at": now + timedelta(seconds=lease_seconds)}
            )
            self._claims[job_id] = renewed
            self._jobs[job_id] = self._jobs[job_id].model_copy(update={"updated_at": now})
            return renewed

    def complete(self, *, job_id: str, worker_id: str, fencing_token: int) -> HybridKnowledgeJob:
        return self._finish(
            job_id=job_id,
            worker_id=worker_id,
            fencing_token=fencing_token,
            state="COMPLETED",
            failure_code=None,
        )

    def fail(
        self,
        *,
        job_id: str,
        worker_id: str,
        fencing_token: int,
        failure_code: str,
    ) -> HybridKnowledgeJob:
        if not failure_code.strip():
            raise ValueError("failure_code must be non-empty")
        return self._finish(
            job_id=job_id,
            worker_id=worker_id,
            fencing_token=fencing_token,
            state="FAILED",
            failure_code=failure_code,
        )

    def get(self, job_id: str) -> HybridKnowledgeJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> tuple[HybridKnowledgeJob, ...]:
        with self._lock:
            return tuple(
                sorted(self._jobs.values(), key=lambda job: self._sequence[job.request.job_id])
            )

    def _finish(
        self,
        *,
        job_id: str,
        worker_id: str,
        fencing_token: int,
        state: str,
        failure_code: str | None,
    ) -> HybridKnowledgeJob:
        with self._lock:
            self._require_active_claim(job_id, worker_id, fencing_token)
            now = self._clock.now()
            job = self._jobs[job_id].model_copy(
                update={
                    "state": state,
                    "updated_at": now,
                    "completed_at": now,
                    "failure_code": failure_code,
                }
            )
            self._jobs[job_id] = job
            del self._claims[job_id]
            return job

    def _require_active_claim(
        self, job_id: str, worker_id: str, fencing_token: int
    ) -> HybridKnowledgeJobClaim:
        job = self._jobs.get(job_id)
        claim = self._claims.get(job_id)
        now = self._clock.now()
        if (
            job is None
            or job.state != "LEASED"
            or claim is None
            or claim.worker_id != worker_id
            or claim.fencing_token != fencing_token
            or claim.lease_expires_at <= now
        ):
            raise HybridKnowledgeLeaseError("operation requires the current active worker lease")
        return claim

    def _ready(self, job: HybridKnowledgeJob, now: datetime) -> bool:
        ready_at = job.request.ready_at or job.created_at
        if ready_at > now or job.state in {"COMPLETED", "FAILED"}:
            return False
        if job.state == "READY":
            return True
        claim = self._claims.get(job.request.job_id)
        return job.state == "LEASED" and (claim is None or claim.lease_expires_at <= now)


_KEY_SEGMENT = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9])?$")
_METADATA_SUFFIX = ".proofagent-artifact.json"


class FileSystemKnowledgeArtifactStore:
    """Immutable exact artifact store confined to one injected filesystem root."""

    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        if root.is_symlink():
            raise ImmutableArtifactError("artifact root must not be a symlink")
        self._root = root.resolve(strict=True)
        self._lock = RLock()

    def put_immutable(self, *, key: str, content: bytes, media_type: str) -> ExactArtifactRef:
        if type(content) is not bytes:
            raise TypeError("content must be exact bytes")
        digest = hashlib.sha256(content).hexdigest()
        version_id = f"sha256:{digest}"
        with self._lock:
            path = self._path_for_key(key, create_parents=True)
            expected = ExactArtifactRef(
                artifact_uri=path.as_uri(),
                version_id=version_id,
                sha256=digest,
                size_bytes=len(content),
                media_type=media_type,
            )
            metadata_path = path.with_name(path.name + _METADATA_SUFFIX)
            if path.exists() or metadata_path.exists():
                existing = self._read_existing(path, metadata_path)
                if existing != expected or self.get_exact(existing) != content:
                    raise ImmutableArtifactError("immutable artifact key already has other content")
                return existing
            self._atomic_create(path, content)
            try:
                metadata = expected.model_dump_json().encode("utf-8")
                self._atomic_create(metadata_path, metadata)
            except Exception:
                path.unlink(missing_ok=True)
                raise
            return expected

    def get_exact(self, ref: ExactArtifactRef) -> bytes:
        path = self._path_from_ref(ref)
        metadata_path = path.with_name(path.name + _METADATA_SUFFIX)
        with self._lock:
            stored = self._read_existing(path, metadata_path)
            if stored != ref:
                raise ImmutableArtifactError("artifact reference does not match stored identity")
            content = self._read_regular_file(path)
            if len(content) != ref.size_bytes or hashlib.sha256(content).hexdigest() != ref.sha256:
                raise ImmutableArtifactError(
                    "artifact bytes failed exact length or digest validation"
                )
            if ref.version_id != f"sha256:{ref.sha256}":
                raise ImmutableArtifactError("artifact version does not match its digest")
            return content

    def _path_for_key(self, key: str, *, create_parents: bool) -> Path:
        if not key or "\\" in key or "//" in key or key.endswith(_METADATA_SUFFIX):
            raise ImmutableArtifactError("artifact key is invalid or reserved")
        pure = PurePosixPath(key)
        if pure.is_absolute() or any(
            segment in {"", ".", ".."} or _KEY_SEGMENT.fullmatch(segment) is None
            for segment in pure.parts
        ):
            raise ImmutableArtifactError("artifact key must use safe relative path segments")
        current = self._root
        for segment in pure.parts[:-1]:
            current = current / segment
            if current.exists() and (current.is_symlink() or not current.is_dir()):
                raise ImmutableArtifactError("artifact key parent is not a safe directory")
            if create_parents:
                current.mkdir(exist_ok=True)
        path = current / pure.name
        self._require_contained(path)
        if path.is_symlink():
            raise ImmutableArtifactError("artifact path must not be a symlink")
        return path

    def _path_from_ref(self, ref: ExactArtifactRef) -> Path:
        parsed = urlsplit(ref.artifact_uri)
        if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
            raise ImmutableArtifactError("filesystem store accepts only file artifact references")
        path = Path(unquote(parsed.path, errors="strict"))
        self._require_contained(path)
        relative = path.relative_to(self._root)
        return self._path_for_key(relative.as_posix(), create_parents=False)

    def _require_contained(self, path: Path) -> None:
        try:
            path.resolve(strict=False).relative_to(self._root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ImmutableArtifactError("artifact path escapes configured root") from exc

    def _read_existing(self, path: Path, metadata_path: Path) -> ExactArtifactRef:
        if not path.is_file() or not metadata_path.is_file():
            raise ImmutableArtifactError("immutable artifact is incomplete")
        try:
            return ExactArtifactRef.model_validate_json(self._read_regular_file(metadata_path))
        except Exception as exc:
            raise ImmutableArtifactError("immutable artifact metadata is invalid") from exc

    @staticmethod
    def _atomic_create(path: Path, content: bytes) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _read_regular_file(path: Path) -> bytes:
        if path.is_symlink() or not path.is_file():
            raise ImmutableArtifactError("artifact must be a regular non-symlink file")
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            return stream.read()
