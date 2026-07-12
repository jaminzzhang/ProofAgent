"""Deterministic reference adapters for hybrid knowledge ports."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat
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
        self._request_identities: dict[str, tuple[str, str]] = {}
        self._sequence: dict[str, int] = {}
        self._next_sequence = 0
        self._lock = RLock()

    def enqueue(self, request: HybridKnowledgeJobRequest) -> HybridKnowledgeJob:
        with self._lock:
            request_binding = (request.request_sha256, request.kind)
            existing_binding = self._request_identities.get(request.request_identity)
            if existing_binding is not None and existing_binding != request_binding:
                raise HybridKnowledgeIdempotencyConflict(
                    "request identity is bound to a different digest or job kind"
                )
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
            self._request_identities[request.request_identity] = request_binding
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
        required_dir_fd_operations = (os.open, os.mkdir, os.unlink)
        if (
            not hasattr(os, "O_DIRECTORY")
            or not hasattr(os, "O_NOFOLLOW")
            or any(operation not in os.supports_dir_fd for operation in required_dir_fd_operations)
        ):
            raise ImmutableArtifactError(
                "filesystem store requires directory-relative no-follow operations"
            )
        root.mkdir(parents=True, exist_ok=True)
        if root.is_symlink():
            raise ImmutableArtifactError("artifact root must not be a symlink")
        self._root = root.resolve(strict=True)
        self._lock = RLock()

    def put_immutable(self, *, key: str, content: bytes, media_type: str) -> ExactArtifactRef:
        if type(content) is not bytes:
            raise TypeError("content must be exact bytes")
        safe_key = self._safe_key(key)
        digest = hashlib.sha256(content).hexdigest()
        version_id = f"sha256:{digest}"
        artifact_path = self._root.joinpath(*safe_key.parts)
        expected = ExactArtifactRef(
            artifact_uri=artifact_path.as_uri(),
            version_id=version_id,
            sha256=digest,
            size_bytes=len(content),
            media_type=media_type,
        )
        with self._lock:
            parent_fd, filename = self._open_parent(safe_key, create=True)
            try:
                metadata_name = filename + _METADATA_SUFFIX
                content_exists = self._entry_exists(parent_fd, filename)
                metadata_exists = self._entry_exists(parent_fd, metadata_name)
                if content_exists or metadata_exists:
                    existing = self._read_existing(parent_fd, filename)
                    existing_content = self._read_regular_file(parent_fd, filename)
                    if existing != expected or existing_content != content:
                        raise ImmutableArtifactError(
                            "immutable artifact key already has other content"
                        )
                    return existing
                self._atomic_create(parent_fd, filename, content)
                try:
                    metadata = expected.model_dump_json().encode("utf-8")
                    self._atomic_create(parent_fd, metadata_name, metadata)
                except Exception:
                    self._unlink_if_present(parent_fd, filename)
                    raise
                return expected
            finally:
                os.close(parent_fd)

    def get_exact(self, ref: ExactArtifactRef) -> bytes:
        safe_key = self._key_from_ref(ref)
        with self._lock:
            parent_fd, filename = self._open_parent(safe_key, create=False)
            try:
                stored = self._read_existing(parent_fd, filename)
                if stored != ref:
                    raise ImmutableArtifactError(
                        "artifact reference does not match stored identity"
                    )
                content = self._read_regular_file(parent_fd, filename)
                if (
                    len(content) != ref.size_bytes
                    or hashlib.sha256(content).hexdigest() != ref.sha256
                ):
                    raise ImmutableArtifactError(
                        "artifact bytes failed exact length or digest validation"
                    )
                if ref.version_id != f"sha256:{ref.sha256}":
                    raise ImmutableArtifactError("artifact version does not match its digest")
                return content
            finally:
                os.close(parent_fd)

    def _safe_key(self, key: str) -> PurePosixPath:
        if not key or "\\" in key or "//" in key or key.endswith(_METADATA_SUFFIX):
            raise ImmutableArtifactError("artifact key is invalid or reserved")
        pure = PurePosixPath(key)
        if pure.is_absolute() or any(
            segment in {"", ".", ".."} or _KEY_SEGMENT.fullmatch(segment) is None
            for segment in pure.parts
        ):
            raise ImmutableArtifactError("artifact key must use safe relative path segments")
        return pure

    def _key_from_ref(self, ref: ExactArtifactRef) -> PurePosixPath:
        parsed = urlsplit(ref.artifact_uri)
        if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
            raise ImmutableArtifactError("filesystem store accepts only file artifact references")
        path = Path(unquote(parsed.path, errors="strict"))
        try:
            relative = path.relative_to(self._root)
        except ValueError as exc:
            raise ImmutableArtifactError("artifact path escapes configured root") from exc
        return self._safe_key(relative.as_posix())

    def _open_parent(self, key: PurePosixPath, *, create: bool) -> tuple[int, str]:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        try:
            current_fd = os.open(self._root, flags)
        except OSError as exc:
            raise ImmutableArtifactError("artifact root is unavailable or unsafe") from exc
        try:
            for component in key.parts[:-1]:
                if create:
                    try:
                        os.mkdir(component, mode=0o700, dir_fd=current_fd)
                    except FileExistsError:
                        pass
                self._before_open_parent_component(
                    key=key.as_posix(), component=component, parent_fd=current_fd
                )
                try:
                    next_fd = os.open(component, flags, dir_fd=current_fd)
                except OSError as exc:
                    raise ImmutableArtifactError(
                        "artifact parent is unavailable, non-directory, or a symlink"
                    ) from exc
                os.close(current_fd)
                current_fd = next_fd
            self._after_open_parent(key=key.as_posix(), parent_fd=current_fd)
            return current_fd, key.name
        except Exception:
            os.close(current_fd)
            raise

    def _before_open_parent_component(self, *, key: str, component: str, parent_fd: int) -> None:
        """Private deterministic race hook; production behavior is intentionally empty."""

    def _after_open_parent(self, *, key: str, parent_fd: int) -> None:
        """Private deterministic race hook; production behavior is intentionally empty."""

    def _read_existing(self, parent_fd: int, filename: str) -> ExactArtifactRef:
        if not self._entry_exists(parent_fd, filename) or not self._entry_exists(
            parent_fd, filename + _METADATA_SUFFIX
        ):
            raise ImmutableArtifactError("immutable artifact is incomplete")
        try:
            return ExactArtifactRef.model_validate_json(
                self._read_regular_file(parent_fd, filename + _METADATA_SUFFIX)
            )
        except Exception as exc:
            raise ImmutableArtifactError("immutable artifact metadata is invalid") from exc

    @staticmethod
    def _entry_exists(parent_fd: int, filename: str) -> bool:
        try:
            descriptor = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise ImmutableArtifactError("artifact entry is unsafe") from exc
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ImmutableArtifactError("artifact entry must be a regular file")
            return True
        finally:
            os.close(descriptor)

    @staticmethod
    def _atomic_create(parent_fd: int, filename: str, content: bytes) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        descriptor = os.open(filename, flags, 0o600, dir_fd=parent_fd)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = -1
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            FileSystemKnowledgeArtifactStore._unlink_if_present(parent_fd, filename)
            raise
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    @staticmethod
    def _read_regular_file(parent_fd: int, filename: str) -> bytes:
        try:
            descriptor = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
        except OSError as exc:
            raise ImmutableArtifactError("artifact entry is unavailable or unsafe") from exc
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ImmutableArtifactError("artifact entry must be a regular file")
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = -1
                return stream.read()
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    @staticmethod
    def _unlink_if_present(parent_fd: int, filename: str) -> None:
        try:
            os.unlink(filename, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
