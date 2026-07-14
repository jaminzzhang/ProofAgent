"""Deterministic reference adapters for hybrid knowledge ports."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat
from threading import RLock
from types import TracebackType
from typing import TYPE_CHECKING, Iterator, Protocol, Self
from urllib.parse import unquote, urlsplit

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised by capability probe at construction
    fcntl = None  # type: ignore[assignment]

from proof_agent.capabilities.knowledge.hybrid.ports import (
    HybridKnowledgeJob,
    HybridKnowledgeJobClaim,
    HybridKnowledgeJobRequest,
    HybridClock,
)
from proof_agent.contracts.knowledge_index import (
    ExactArtifactRef,
    HybridKnowledgePublicationRecord,
    KnowledgeRetrievalProfileRevision,
)

if TYPE_CHECKING:
    from proof_agent.capabilities.knowledge.ingestion.hybrid_worker import (
        HybridArtifactBuildRequest,
        HybridArtifactBuildResult,
    )


class HybridKnowledgeRepositoryError(RuntimeError):
    """Base error for fail-closed reference repository operations."""


class HybridKnowledgeIdempotencyConflict(HybridKnowledgeRepositoryError):
    """An idempotency key was reused for a different immutable request."""


class HybridKnowledgeLeaseError(HybridKnowledgeRepositoryError):
    """A worker attempted an operation without the current active lease."""


class ImmutableArtifactError(HybridKnowledgeRepositoryError):
    """An immutable artifact key or exact reference failed validation."""


@dataclass(frozen=True, slots=True)
class HybridKnowledgeBindingAuthoritySnapshot:
    """Exact immutable Hybrid authority selected for one Draft binding."""

    publication: HybridKnowledgePublicationRecord
    retrieval_profile: KnowledgeRetrievalProfileRevision


class HybridKnowledgeBindingAuthority(Protocol):
    """Read-only seam that resolves an explicit or Source-default profile."""

    def resolve_binding_authority(
        self,
        *,
        source_id: str,
        profile_revision_id: str | None,
    ) -> HybridKnowledgeBindingAuthoritySnapshot | None: ...


def _require_aware(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("clock must return a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _normalized_identifier(value: str, *, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _positive_int(value: int, *, field_name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _validated_job_update(job: HybridKnowledgeJob, **updates: object) -> HybridKnowledgeJob:
    return HybridKnowledgeJob.model_validate({**job.model_dump(), **updates})


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


class InMemoryHybridKnowledgeBindingAuthority:
    """Deterministic authority adapter for validation and offline exercises."""

    def __init__(self) -> None:
        self._active_publications: dict[str, HybridKnowledgePublicationRecord] = {}
        self._profiles: dict[tuple[str, str], KnowledgeRetrievalProfileRevision] = {}
        self._default_profiles: dict[str, str] = {}
        self._lock = RLock()

    def publish(self, publication: HybridKnowledgePublicationRecord) -> None:
        with self._lock:
            current = self._active_publications.get(publication.source_id)
            if current is not None:
                if current == publication:
                    return
                if publication.source_publication_seq <= current.source_publication_seq:
                    raise HybridKnowledgeIdempotencyConflict(
                        "Hybrid publication sequence must advance monotonically"
                    )
            self._active_publications[publication.source_id] = publication

    def publish_retrieval_profile(
        self,
        *,
        source_id: str,
        profile: KnowledgeRetrievalProfileRevision,
        make_default: bool = False,
    ) -> None:
        if any(item.source_id != source_id for item in profile.enabled_degradations):
            raise ValueError("retrieval profile degradations must match the owning Source")
        key = (source_id, profile.profile_revision_id)
        with self._lock:
            existing = self._profiles.get(key)
            if existing is not None and existing != profile:
                raise HybridKnowledgeIdempotencyConflict("Retrieval Profile revision is immutable")
            self._profiles[key] = profile
            if make_default:
                self._default_profiles[source_id] = profile.profile_revision_id

    def resolve_binding_authority(
        self,
        *,
        source_id: str,
        profile_revision_id: str | None,
    ) -> HybridKnowledgeBindingAuthoritySnapshot | None:
        with self._lock:
            publication = self._active_publications.get(source_id)
            selected_profile_id = profile_revision_id or self._default_profiles.get(source_id)
            if publication is None or selected_profile_id is None:
                return None
            profile = self._profiles.get((source_id, selected_profile_id))
            if profile is None:
                return None
            return HybridKnowledgeBindingAuthoritySnapshot(
                publication=publication,
                retrieval_profile=profile,
            )


class InMemoryHybridKnowledgeRepository:
    """Lock-safe global FIFO work scheduler with fencing-token leases."""

    def __init__(self, *, clock: HybridClock | None = None) -> None:
        self._clock = clock or ManualHybridClock()
        self._jobs: dict[str, HybridKnowledgeJob] = {}
        self._claims: dict[str, HybridKnowledgeJobClaim] = {}
        self._idempotency: dict[str, str] = {}
        self._request_identities: dict[str, tuple[str, str]] = {}
        self._build_requests: dict[str, HybridArtifactBuildRequest] = {}
        self._build_results: dict[str, HybridArtifactBuildResult] = {}
        self._sequence: dict[str, int] = {}
        self._next_sequence = 0
        self._last_observed_time: datetime | None = None
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
            now = self._observe_now()
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

    def enqueue_artifact_build(
        self,
        request: HybridKnowledgeJobRequest,
        build_request: HybridArtifactBuildRequest,
    ) -> HybridKnowledgeJob:
        """Atomically bind one exact build payload before it can be claimed."""

        from proof_agent.capabilities.knowledge.ingestion.hybrid_worker import (
            hybrid_build_request_sha256,
        )

        if request.kind != "parse":
            raise ValueError("artifact builds require a parse job")
        if build_request.job_id != request.job_id:
            raise ValueError("build request job identity must match the scheduler request")
        if build_request.request_identity != request.request_identity:
            raise ValueError("build request identity must match the scheduler request")
        if build_request.request_sha256 != request.request_sha256:
            raise ValueError("build request digest must match the scheduler request")
        if hybrid_build_request_sha256(build_request) != request.request_sha256:
            raise ValueError("build request digest must bind its immutable payload")
        with self._lock:
            existing = self._build_requests.get(request.job_id)
            if existing is not None and existing != build_request:
                raise HybridKnowledgeIdempotencyConflict(
                    "job identity is already bound to a different build request"
                )
            job = self.enqueue(request)
            if existing is not None:
                if job.max_auto_retries != build_request.max_auto_retries:
                    raise HybridKnowledgeIdempotencyConflict(
                        "durable retry limit does not match the immutable build request"
                    )
                return job
            job = _validated_job_update(
                job,
                max_auto_retries=build_request.max_auto_retries,
            )
            self._jobs[request.job_id] = job
            self._build_requests[request.job_id] = build_request
            return job

    def load_build_request(self, claim: HybridKnowledgeJobClaim) -> HybridArtifactBuildRequest:
        with self._lock:
            now = self._observe_now()
            self._require_active_claim(claim.job_id, claim.worker_id, claim.fencing_token, now=now)
            request = self._build_requests.get(claim.job_id)
            if request is None:
                raise HybridKnowledgeLeaseError("claimed parse job has no exact build request")
            return request.model_copy(
                update={"auto_retry_count": self._jobs[claim.job_id].auto_retry_count}
            )

    def renew_claim(
        self, claim: HybridKnowledgeJobClaim, *, lease_seconds: int
    ) -> HybridKnowledgeJobClaim:
        return self.renew(
            job_id=claim.job_id,
            worker_id=claim.worker_id,
            fencing_token=claim.fencing_token,
            lease_seconds=lease_seconds,
        )

    def commit_artifact_build(
        self,
        claim: HybridKnowledgeJobClaim,
        result: HybridArtifactBuildResult,
    ) -> HybridKnowledgeJob:
        from proof_agent.capabilities.knowledge.ingestion.hybrid_worker import (
            validate_hybrid_artifact_build_result,
        )

        with self._lock:
            now = self._observe_now()
            self._require_active_claim(claim.job_id, claim.worker_id, claim.fencing_token, now=now)
            request = self._build_requests.get(claim.job_id)
            if request is None:
                raise HybridKnowledgeLeaseError("claimed parse job has no exact build request")
            validate_hybrid_artifact_build_result(request, result)
            self._build_results[claim.job_id] = result
            return self._finish_unlocked(
                claim=claim,
                state="COMPLETED",
                failure_code=None,
                failure_classification=None,
                safe_reason=None,
                now=now,
            )

    def schedule_retry(
        self,
        claim: HybridKnowledgeJobClaim,
        *,
        auto_retry_count: int,
        safe_error: str,
        delay_seconds: int = 5,
    ) -> HybridKnowledgeJob:
        auto_retry_count = _positive_int(auto_retry_count, field_name="auto_retry_count")
        delay_seconds = _positive_int(delay_seconds, field_name="delay_seconds")
        safe_error = _normalized_identifier(safe_error, field_name="safe_error")
        with self._lock:
            now = self._observe_now()
            self._require_active_claim(claim.job_id, claim.worker_id, claim.fencing_token, now=now)
            current = self._jobs[claim.job_id]
            if auto_retry_count != current.auto_retry_count + 1:
                raise HybridKnowledgeLeaseError("retry count must advance exactly once")
            if auto_retry_count > current.max_auto_retries:
                raise HybridKnowledgeLeaseError("retry count exceeds the durable limit")
            job = _validated_job_update(
                current,
                state="RETRY_SCHEDULED",
                auto_retry_count=auto_retry_count,
                next_attempt_at=now + timedelta(seconds=delay_seconds),
                safe_reason=safe_error,
                updated_at=now,
            )
            self._jobs[claim.job_id] = job
            del self._claims[claim.job_id]
            return job

    def require_review(
        self, claim: HybridKnowledgeJobClaim, *, safe_reason: str
    ) -> HybridKnowledgeJob:
        safe_reason = _normalized_identifier(safe_reason, field_name="safe_reason")
        with self._lock:
            now = self._observe_now()
            self._require_active_claim(claim.job_id, claim.worker_id, claim.fencing_token, now=now)
            job = _validated_job_update(
                self._jobs[claim.job_id],
                state="REVIEW_REQUIRED",
                safe_reason=safe_reason,
                updated_at=now,
            )
            self._jobs[claim.job_id] = job
            del self._claims[claim.job_id]
            return job

    def fail_integrity(
        self,
        claim: HybridKnowledgeJobClaim,
        *,
        failure_code: str,
        safe_reason: str,
    ) -> HybridKnowledgeJob:
        failure_code = _normalized_identifier(failure_code, field_name="failure_code")
        safe_reason = _normalized_identifier(safe_reason, field_name="safe_reason")
        with self._lock:
            now = self._observe_now()
            self._require_active_claim(claim.job_id, claim.worker_id, claim.fencing_token, now=now)
            return self._finish_unlocked(
                claim=claim,
                state="FAILED",
                failure_code=failure_code,
                failure_classification="non_recoverable",
                safe_reason=safe_reason,
                now=now,
            )

    def fail_retries_exhausted(
        self,
        claim: HybridKnowledgeJobClaim,
        *,
        failure_code: str,
        safe_reason: str,
    ) -> HybridKnowledgeJob:
        failure_code = _normalized_identifier(failure_code, field_name="failure_code")
        safe_reason = _normalized_identifier(safe_reason, field_name="safe_reason")
        with self._lock:
            now = self._observe_now()
            self._require_active_claim(claim.job_id, claim.worker_id, claim.fencing_token, now=now)
            return self._finish_unlocked(
                claim=claim,
                state="FAILED",
                failure_code=failure_code,
                failure_classification="recoverable_exhausted",
                safe_reason=safe_reason,
                now=now,
            )

    def get_build_result(self, job_id: str) -> HybridArtifactBuildResult | None:
        job_id = _normalized_identifier(job_id, field_name="job_id")
        with self._lock:
            return self._build_results.get(job_id)

    def claim_next(self, *, worker_id: str, lease_seconds: int) -> HybridKnowledgeJobClaim | None:
        worker_id = _normalized_identifier(worker_id, field_name="worker_id")
        lease_seconds = _positive_int(lease_seconds, field_name="lease_seconds")
        with self._lock:
            now = self._observe_now()
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
            self._jobs[job.request.job_id] = _validated_job_update(
                job,
                state="LEASED",
                fencing_token=token,
                next_attempt_at=None,
                safe_reason=None,
                updated_at=now,
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
        job_id = _normalized_identifier(job_id, field_name="job_id")
        worker_id = _normalized_identifier(worker_id, field_name="worker_id")
        fencing_token = _positive_int(fencing_token, field_name="fencing_token")
        lease_seconds = _positive_int(lease_seconds, field_name="lease_seconds")
        with self._lock:
            now = self._observe_now()
            claim = self._require_active_claim(job_id, worker_id, fencing_token, now=now)
            renewed = HybridKnowledgeJobClaim.model_validate(
                {
                    **claim.model_dump(),
                    "lease_expires_at": now + timedelta(seconds=lease_seconds),
                }
            )
            self._claims[job_id] = renewed
            self._jobs[job_id] = _validated_job_update(self._jobs[job_id], updated_at=now)
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
        failure_code = _normalized_identifier(failure_code, field_name="failure_code")
        return self._finish(
            job_id=job_id,
            worker_id=worker_id,
            fencing_token=fencing_token,
            state="FAILED",
            failure_code=failure_code,
        )

    def get(self, job_id: str) -> HybridKnowledgeJob | None:
        job_id = _normalized_identifier(job_id, field_name="job_id")
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
        job_id = _normalized_identifier(job_id, field_name="job_id")
        worker_id = _normalized_identifier(worker_id, field_name="worker_id")
        fencing_token = _positive_int(fencing_token, field_name="fencing_token")
        with self._lock:
            now = self._observe_now()
            claim = self._require_active_claim(job_id, worker_id, fencing_token, now=now)
            return self._finish_unlocked(
                claim=claim,
                state=state,
                failure_code=failure_code,
                failure_classification=("non_recoverable" if state == "FAILED" else None),
                safe_reason=(failure_code if state == "FAILED" else None),
                now=now,
            )

    def _finish_unlocked(
        self,
        *,
        claim: HybridKnowledgeJobClaim,
        state: str,
        failure_code: str | None,
        failure_classification: str | None,
        safe_reason: str | None,
        now: datetime,
    ) -> HybridKnowledgeJob:
        job = _validated_job_update(
            self._jobs[claim.job_id],
            state=state,
            updated_at=now,
            completed_at=now,
            failure_code=failure_code,
            failure_classification=failure_classification,
            safe_reason=safe_reason,
        )
        self._jobs[claim.job_id] = job
        del self._claims[claim.job_id]
        return job

    def _require_active_claim(
        self, job_id: str, worker_id: str, fencing_token: int, *, now: datetime
    ) -> HybridKnowledgeJobClaim:
        job = self._jobs.get(job_id)
        claim = self._claims.get(job_id)
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

    def _observe_now(self) -> datetime:
        now = _require_aware(self._clock.now())
        if self._last_observed_time is not None and now < self._last_observed_time:
            raise ValueError("hybrid clock must not move backwards")
        self._last_observed_time = now
        return now

    def _ready(self, job: HybridKnowledgeJob, now: datetime) -> bool:
        ready_at = job.next_attempt_at or job.request.ready_at or job.created_at
        if ready_at > now or job.state in {"COMPLETED", "FAILED"}:
            return False
        if job.state in {"READY", "RETRY_SCHEDULED"}:
            return True
        claim = self._claims.get(job.request.job_id)
        return job.state == "LEASED" and (claim is None or claim.lease_expires_at <= now)


_KEY_SEGMENT = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9])?$")
_METADATA_SUFFIX = ".proofagent-artifact.json"
_LOCK_SUFFIX = ".proofagent-artifact.lock"


class FileSystemKnowledgeArtifactStore:
    """Immutable exact artifact store confined to one injected filesystem root."""

    def __init__(self, root: Path) -> None:
        self._root_fd = -1
        self._closed = True
        self._lock = RLock()
        required_dir_fd_operations = (os.open, os.mkdir, os.stat, os.unlink)
        if (
            fcntl is None
            or not hasattr(os, "O_DIRECTORY")
            or not hasattr(os, "O_NOFOLLOW")
            or any(operation not in os.supports_dir_fd for operation in required_dir_fd_operations)
            or os.stat not in os.supports_follow_symlinks
        ):
            raise ImmutableArtifactError(
                "filesystem store requires POSIX locking and directory-relative no-follow operations"
            )
        try:
            self._root, self._root_fd = self._acquire_root(root)
            root_stat = os.fstat(self._root_fd)
        except ImmutableArtifactError:
            raise
        except OSError as exc:
            if self._root_fd >= 0:
                os.close(self._root_fd)
                self._root_fd = -1
            raise ImmutableArtifactError("artifact root is unavailable or unsafe") from exc
        if not stat.S_ISDIR(root_stat.st_mode):
            os.close(self._root_fd)
            self._root_fd = -1
            raise ImmutableArtifactError("artifact root must be a directory")
        self._root_identity = (root_stat.st_dev, root_stat.st_ino)
        self._closed = False
        try:
            self._assert_root_path_identity()
        except Exception:
            self.close()
            raise

    def _acquire_root(self, root: Path) -> tuple[Path, int]:
        configured = Path(os.fspath(root))
        if ".." in configured.parts:
            raise ImmutableArtifactError("artifact root must not contain parent traversal")
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        if configured.is_absolute():
            lexical_root = Path(os.path.normpath(os.fspath(configured)))
            anchor_fd = os.open("/", flags)
            components = lexical_root.parts[1:]
        else:
            anchor_fd = os.open(".", flags)
            lexical_root = Path(os.getcwd()).joinpath(configured)
            components = configured.parts
        return lexical_root, self._walk_or_create_root(anchor_fd, components)

    def _walk_or_create_root(self, anchor_fd: int, components: tuple[str, ...]) -> int:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        current_fd = anchor_fd
        try:
            for component in components:
                try:
                    component_stat = os.stat(component, dir_fd=current_fd, follow_symlinks=False)
                except FileNotFoundError:
                    try:
                        os.mkdir(component, mode=0o700, dir_fd=current_fd)
                        self._fsync_directory(current_fd)
                    except FileExistsError:
                        pass
                    component_stat = os.stat(component, dir_fd=current_fd, follow_symlinks=False)
                if not stat.S_ISDIR(component_stat.st_mode):
                    raise ImmutableArtifactError(
                        "artifact root component must be a non-symlink directory"
                    )
                self._before_open_root_component(
                    component=component,
                    parent_fd=current_fd,
                    component_identity=(component_stat.st_dev, component_stat.st_ino),
                )
                try:
                    next_fd = os.open(component, flags, dir_fd=current_fd)
                except OSError as exc:
                    raise ImmutableArtifactError(
                        "artifact root component changed or became unsafe before open"
                    ) from exc
                opened_stat = os.fstat(next_fd)
                if (opened_stat.st_dev, opened_stat.st_ino) != (
                    component_stat.st_dev,
                    component_stat.st_ino,
                ):
                    os.close(next_fd)
                    raise ImmutableArtifactError(
                        "artifact root component identity changed before open"
                    )
                os.close(current_fd)
                current_fd = next_fd
            return current_fd
        except Exception:
            os.close(current_fd)
            raise

    def _before_open_root_component(
        self,
        *,
        component: str,
        parent_fd: int,
        component_identity: tuple[int, int],
    ) -> None:
        """Private deterministic constructor-race hook; production behavior is empty."""

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            os.close(self._root_fd)
            self._root_fd = -1
            self._closed = True

    def __enter__(self) -> Self:
        with self._lock:
            self._require_open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

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
            self._require_open()
            parent_fd, filename = self._open_parent(safe_key, create=True)
            try:
                with self._key_lock(parent_fd, filename):
                    metadata_name = filename + _METADATA_SUFFIX
                    content_exists = self._entry_exists(parent_fd, filename)
                    metadata_exists = self._entry_exists(parent_fd, metadata_name)
                    if content_exists and metadata_exists:
                        existing = self._read_existing(parent_fd, filename)
                        existing_content = self._read_regular_file(parent_fd, filename)
                        if existing != expected or existing_content != content:
                            raise ImmutableArtifactError(
                                "immutable artifact key already has other content"
                            )
                        self._fsync_directory(parent_fd)
                        self._assert_artifact_parent_identity(safe_key, parent_fd)
                        return existing
                    if content_exists:
                        existing_content = self._read_regular_file(parent_fd, filename)
                        if existing_content != content:
                            raise ImmutableArtifactError(
                                "incomplete artifact content conflicts with requested bytes"
                            )
                        self._commit_metadata(parent_fd, filename, expected)
                        self._assert_artifact_parent_identity(safe_key, parent_fd)
                        return expected
                    if metadata_exists:
                        existing = self._read_metadata(parent_fd, metadata_name)
                        if existing != expected:
                            raise ImmutableArtifactError(
                                "incomplete artifact metadata conflicts with requested identity"
                            )
                        self._unlink_if_present(parent_fd, metadata_name)
                        self._fsync_directory(parent_fd)
                    self._commit_content(parent_fd, filename, content)
                    self._commit_metadata(parent_fd, filename, expected)
                    self._assert_artifact_parent_identity(safe_key, parent_fd)
                    return expected
            finally:
                os.close(parent_fd)

    def get_exact(self, ref: ExactArtifactRef) -> bytes:
        safe_key = self._key_from_ref(ref)
        with self._lock:
            self._require_open()
            parent_fd, filename = self._open_parent(safe_key, create=False)
            try:
                with self._key_lock(parent_fd, filename):
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
                    self._assert_artifact_parent_identity(safe_key, parent_fd)
                    return content
            finally:
                os.close(parent_fd)

    def _safe_key(self, key: str) -> PurePosixPath:
        if not key or "\\" in key or "//" in key or key.endswith((_METADATA_SUFFIX, _LOCK_SUFFIX)):
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
            self._assert_root_path_identity()
            current_fd = os.dup(self._root_fd)
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

    def _after_content_fsync(self, *, key: str, parent_fd: int) -> None:
        """Private deterministic crash hook after durable content creation."""

    def _before_metadata_commit(self, *, key: str, parent_fd: int) -> None:
        """Private deterministic crash hook before metadata visibility commit."""

    def _after_metadata_fsync(self, *, key: str, parent_fd: int) -> None:
        """Private deterministic crash hook after metadata file fsync."""

    def _require_open(self) -> None:
        if self._closed or self._root_fd < 0:
            raise ImmutableArtifactError("artifact store is closed")

    def _assert_root_path_identity(self) -> None:
        self._require_open()
        try:
            root_stat = os.stat(self._root, follow_symlinks=False)
        except OSError as exc:
            raise ImmutableArtifactError("configured artifact root path is unavailable") from exc
        if (
            not stat.S_ISDIR(root_stat.st_mode)
            or (root_stat.st_dev, root_stat.st_ino) != self._root_identity
        ):
            raise ImmutableArtifactError(
                "configured artifact root path no longer names the retained directory"
            )

    def _assert_artifact_parent_identity(self, key: PurePosixPath, retained_parent_fd: int) -> None:
        self._assert_root_path_identity()
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        current_fd = os.dup(self._root_fd)
        try:
            for component in key.parts[:-1]:
                try:
                    next_fd = os.open(component, flags, dir_fd=current_fd)
                except OSError as exc:
                    raise ImmutableArtifactError(
                        "artifact parent path no longer names the retained directory"
                    ) from exc
                os.close(current_fd)
                current_fd = next_fd
            current = os.fstat(current_fd)
            retained = os.fstat(retained_parent_fd)
            if (current.st_dev, current.st_ino) != (retained.st_dev, retained.st_ino):
                raise ImmutableArtifactError(
                    "artifact parent path no longer names the retained directory"
                )
        finally:
            os.close(current_fd)

    @contextmanager
    def _key_lock(self, parent_fd: int, filename: str) -> Iterator[None]:
        locking = fcntl
        if locking is None:
            raise ImmutableArtifactError("POSIX artifact key locking is unavailable")
        lock_name = filename + _LOCK_SUFFIX
        descriptor = -1
        try:
            descriptor = self._open_lock_file(parent_fd, lock_name)
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ImmutableArtifactError("artifact lock must be a regular file")
            locking.flock(descriptor, locking.LOCK_EX)
        except Exception as exc:
            if descriptor >= 0:
                os.close(descriptor)
            if isinstance(exc, ImmutableArtifactError):
                raise
            raise ImmutableArtifactError("artifact key lock is unavailable") from exc
        try:
            yield
        finally:
            try:
                locking.flock(descriptor, locking.LOCK_UN)
            finally:
                os.close(descriptor)

    @staticmethod
    def _open_lock_file(parent_fd: int, lock_name: str) -> int:
        open_flags = os.O_RDWR | os.O_NOFOLLOW
        create_flags = open_flags | os.O_CREAT | os.O_EXCL
        for _ in range(4):
            try:
                return os.open(lock_name, open_flags, dir_fd=parent_fd)
            except FileNotFoundError:
                try:
                    return os.open(lock_name, create_flags, 0o600, dir_fd=parent_fd)
                except FileExistsError:
                    continue
        raise ImmutableArtifactError("artifact key lock creation did not converge")

    def _commit_content(self, parent_fd: int, filename: str, content: bytes) -> None:
        self._atomic_create(parent_fd, filename, content)
        self._fsync_directory(parent_fd)
        self._after_content_fsync(key=filename, parent_fd=parent_fd)

    def _commit_metadata(self, parent_fd: int, filename: str, ref: ExactArtifactRef) -> None:
        self._before_metadata_commit(key=filename, parent_fd=parent_fd)
        self._atomic_create(
            parent_fd,
            filename + _METADATA_SUFFIX,
            ref.model_dump_json().encode("utf-8"),
        )
        self._after_metadata_fsync(key=filename, parent_fd=parent_fd)
        self._fsync_directory(parent_fd)

    def _fsync_directory(self, parent_fd: int) -> None:
        try:
            os.fsync(parent_fd)
        except OSError as exc:
            raise ImmutableArtifactError("artifact directory fsync failed") from exc

    def _read_existing(self, parent_fd: int, filename: str) -> ExactArtifactRef:
        if not self._entry_exists(parent_fd, filename) or not self._entry_exists(
            parent_fd, filename + _METADATA_SUFFIX
        ):
            raise ImmutableArtifactError("immutable artifact is incomplete")
        return self._read_metadata(parent_fd, filename + _METADATA_SUFFIX)

    def _read_metadata(self, parent_fd: int, metadata_name: str) -> ExactArtifactRef:
        try:
            return ExactArtifactRef.model_validate_json(
                self._read_regular_file(parent_fd, metadata_name)
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
