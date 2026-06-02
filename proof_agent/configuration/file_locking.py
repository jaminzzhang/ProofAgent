"""Local-filesystem advisory locking for knowledge ingestion state."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path

from filelock import FileLock, Timeout

from proof_agent.errors import ProofAgentError


def store_lock_path(store_root: Path) -> Path:
    """Return the single store-transition lock path."""

    return store_root / ".locks" / "store.lock"


def artifact_lock_path(store_root: Path, artifact_key: str) -> Path:
    """Return a content-keyed artifact lock outside atomically renamed directories."""

    lock_name = f"{sha256(artifact_key.encode('utf-8')).hexdigest()}.lock"
    return store_root / ".locks" / "artifacts" / lock_name


@contextmanager
def locked(path: Path, *, timeout_seconds: float) -> Iterator[None]:
    """Acquire one blocking advisory lock or raise a stable persistence error."""

    path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(path)
    try:
        lock.acquire(timeout=timeout_seconds)
    except Timeout as exc:
        raise ProofAgentError(
            "PA_INGESTION_004",
            "Knowledge ingestion state is busy.",
            "Retry the operation after the active local store transition completes.",
        ) from exc
    try:
        yield
    finally:
        lock.release()


@contextmanager
def try_locked(path: Path) -> Iterator[bool]:
    """Attempt one non-blocking advisory lock acquisition."""

    path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(path)
    try:
        lock.acquire(timeout=0)
    except Timeout:
        yield False
        return
    try:
        yield True
    finally:
        lock.release()
