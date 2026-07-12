from __future__ import annotations

import errno
import json
import os
import secrets
import stat
import threading
from _thread import LockType
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from proof_agent.contracts import (
    ControlledReActRunStateSnapshot,
    ObservationTruthArtifact,
    ObservationTruthKind,
    RetrievalObservationTruth,
    ToolObservationTruth,
)
from proof_agent.control.workflow.controlled_react.artifact_binding import (
    CONTROLLED_REACT_SNAPSHOT_REF_PREFIX as CONTROLLED_REACT_SNAPSHOT_REF_PREFIX,
    bind_controlled_react_snapshot,
    canonical_json_bytes,
    model_payload,
    parse_bound_observation_reference,
    parse_snapshot_reference,
    require_bound_observation_truth,
    verify_controlled_react_snapshot_binding,
)
from proof_agent.errors import ProofAgentError


_PUBLISH_LOCK_FILENAME = ".proofagent.publish.lock"
_ROOT_THREAD_LOCKS_GUARD = threading.Lock()
_ROOT_THREAD_LOCKS: dict[tuple[int, int], LockType] = {}
_FORK_STATE_GUARD = threading.Lock()
_ACTIVE_FORK_FDS: set[int] = set()


def _prepare_local_store_fork() -> None:
    _FORK_STATE_GUARD.acquire()


def _finish_local_store_fork_in_parent() -> None:
    _FORK_STATE_GUARD.release()


def _reset_local_store_state_after_fork_in_child() -> None:
    global _ACTIVE_FORK_FDS
    global _FORK_STATE_GUARD
    global _ROOT_THREAD_LOCKS
    global _ROOT_THREAD_LOCKS_GUARD

    inherited_descriptors = tuple(_ACTIVE_FORK_FDS)
    try:
        for file_descriptor in inherited_descriptors:
            try:
                os.close(file_descriptor)
            except OSError:
                pass
    finally:
        _ACTIVE_FORK_FDS = set()
        _FORK_STATE_GUARD = threading.Lock()
        _ROOT_THREAD_LOCKS = {}
        _ROOT_THREAD_LOCKS_GUARD = threading.Lock()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(
        before=_prepare_local_store_fork,
        after_in_parent=_finish_local_store_fork_in_parent,
        after_in_child=_reset_local_store_state_after_fork_in_child,
    )


class FileControlledReActSnapshotStore:
    """Dev/test snapshot store for one private app-owned POSIX root.

    This adapter is not a sandbox boundary against another process running as
    the same effective user. Production uses an isolated artifact-store port.
    """

    def __init__(self, root_dir: Path) -> None:
        self._storage = _AnchoredLocalStorage(root_dir)

    def save(self, snapshot: ControlledReActRunStateSnapshot) -> str:
        binding = bind_controlled_react_snapshot(snapshot)
        self._storage.publish_json(
            (binding.run_id, "controlled_react"),
            f"{binding.snapshot_id}.json",
            binding.payload,
            artifact_name="controlled ReAct snapshot",
            reference=binding.reference,
        )
        return binding.reference

    def load(self, snapshot_ref: str) -> ControlledReActRunStateSnapshot:
        run_id, snapshot_id, _ = parse_snapshot_reference(snapshot_ref)
        path = self._storage.artifact_path(
            (run_id, "controlled_react"),
            f"{snapshot_id}.json",
        )
        payload = self._storage.read_json(
            (run_id, "controlled_react"),
            f"{snapshot_id}.json",
            artifact_name="controlled ReAct snapshot",
            reference=snapshot_ref,
            missing_fix="Restart the run so approval resume can persist a fresh snapshot.",
        )
        try:
            snapshot = ControlledReActRunStateSnapshot.model_validate(payload)
        except ValidationError as exc:
            raise _corrupt_artifact_error(
                artifact_name="controlled ReAct snapshot",
                reference=snapshot_ref,
                path=path,
            ) from exc
        try:
            verify_controlled_react_snapshot_binding(snapshot, snapshot_ref)
        except ProofAgentError as exc:
            raise _corrupt_artifact_error(
                artifact_name="controlled ReAct snapshot",
                reference=snapshot_ref,
                path=path,
            ) from exc
        return snapshot


class FileObservationTruthStore:
    """Dev/test truth store for one private app-owned POSIX root.

    This adapter is not a sandbox boundary against another process running as
    the same effective user. Production uses an isolated artifact-store port.
    """

    def __init__(self, root_dir: Path) -> None:
        self._storage = _AnchoredLocalStorage(root_dir)

    def save(self, truth: ObservationTruthArtifact) -> str:
        binding = require_bound_observation_truth(truth)
        self._storage.publish_json(
            (binding.run_id, "controlled_react", "observation_truth"),
            f"{binding.observation_id}.json",
            model_payload(binding.truth),
            artifact_name="controlled ReAct observation truth",
            reference=binding.reference,
        )
        return binding.reference

    def load(self, truth_ref: str) -> ObservationTruthArtifact:
        run_id, observation_id, _ = parse_bound_observation_reference(truth_ref)
        directories = (run_id, "controlled_react", "observation_truth")
        filename = f"{observation_id}.json"
        path = self._storage.artifact_path(directories, filename)
        payload = self._storage.read_json(
            directories,
            filename,
            artifact_name="controlled ReAct observation truth",
            reference=truth_ref,
            missing_fix=("Restart the run so approval resume can persist observation truth."),
        )
        try:
            truth = _observation_truth_from_payload(payload)
            binding = require_bound_observation_truth(truth)
        except (ProofAgentError, ValidationError) as exc:
            raise _corrupt_artifact_error(
                artifact_name="controlled ReAct observation truth",
                reference=truth_ref,
                path=path,
            ) from exc
        if binding.reference != truth_ref or binding.observation_id != observation_id:
            raise _corrupt_artifact_error(
                artifact_name="controlled ReAct observation truth",
                reference=truth_ref,
                path=path,
            )
        return binding.truth


class _AnchoredLocalStorage:
    """Filesystem boundary anchored to one private application-owned root."""

    def __init__(self, root_dir: Path) -> None:
        if not _supports_posix_dir_fd():
            raise ProofAgentError(
                "PA_RUNTIME_001",
                "controlled ReAct local stores require anchored POSIX filesystem capabilities",
                (
                    "Use a POSIX runtime with dir_fd, O_NOFOLLOW, at-fork hooks, "
                    "and flock support, or configure a production artifact-store adapter."
                ),
                artifact_path=root_dir,
            )
        root = Path(os.path.abspath(os.fspath(root_dir)))
        try:
            root_fd = _open_directory_path_nofollow(root, create=True)
            try:
                root_stat = os.fstat(root_fd)
                _require_private_directory(root_stat, label="local-store root")
                lock_fd, lock_stat, lock_created = _open_publish_lock_at(root_fd)
                try:
                    if lock_created:
                        _fsync_directory(root_fd)
                finally:
                    os.close(lock_fd)
            finally:
                os.close(root_fd)
        except OSError as exc:
            raise ProofAgentError(
                "PA_RUNTIME_001",
                "controlled ReAct local-store root is unavailable",
                "Use an accessible trusted local artifact directory.",
                artifact_path=root_dir,
            ) from exc
        self._root = root
        self._root_identity = (root_stat.st_dev, root_stat.st_ino)
        self._publish_lock_identity = (lock_stat.st_dev, lock_stat.st_ino)

    def artifact_path(self, directories: tuple[str, ...], filename: str) -> Path:
        return self._root.joinpath(*directories, filename)

    def read_json(
        self,
        directories: tuple[str, ...],
        filename: str,
        *,
        artifact_name: str,
        reference: str,
        missing_fix: str,
    ) -> dict[str, Any]:
        path = self.artifact_path(directories, filename)
        try:
            with self._locked_root_publication():
                content = self._read_bytes_posix(directories, filename)
        except FileNotFoundError as exc:
            raise ProofAgentError(
                "PA_RUNTIME_001",
                f"{artifact_name} not found: {reference}",
                missing_fix,
                artifact_path=path,
            ) from exc
        except ProofAgentError:
            raise
        except OSError as exc:
            raise _corrupt_artifact_error(
                artifact_name=artifact_name,
                reference=reference,
                path=path,
            ) from exc
        return _decode_json_object(
            content,
            artifact_name=artifact_name,
            reference=reference,
            path=path,
        )

    def publish_json(
        self,
        directories: tuple[str, ...],
        filename: str,
        payload: dict[str, Any],
        *,
        artifact_name: str,
        reference: str,
    ) -> None:
        path = self.artifact_path(directories, filename)
        content = canonical_json_bytes(payload)
        try:
            with self._locked_root_publication():
                self._publish_posix(
                    directories,
                    filename,
                    content,
                    payload,
                    artifact_name=artifact_name,
                    reference=reference,
                    path=path,
                )
        except ProofAgentError:
            raise
        except OSError as exc:
            raise _storage_write_error(
                artifact_name=artifact_name,
                reference=reference,
                path=path,
            ) from exc

    @contextmanager
    def _locked_root_publication(self) -> Iterator[None]:
        with _thread_lock_for_root(self._root_identity):
            with _FORK_STATE_GUARD:
                root_fd = self._open_root_fd_posix()
                _ACTIVE_FORK_FDS.add(root_fd)
            lock_fd: int | None = None
            primary_error: BaseException | None = None
            try:
                with _FORK_STATE_GUARD:
                    lock_fd, _, _ = _open_publish_lock_at(
                        root_fd,
                        expected_identity=self._publish_lock_identity,
                    )
                    _ACTIVE_FORK_FDS.add(lock_fd)
                _flock(lock_fd, exclusive=True)
                yield
            except BaseException as exc:
                primary_error = exc
                raise
            finally:
                cleanup_error: BaseException | None = None
                if lock_fd is not None:
                    try:
                        _close_registered_descriptor(lock_fd)
                    except BaseException as exc:
                        cleanup_error = exc
                try:
                    _close_registered_descriptor(root_fd)
                except BaseException as exc:
                    if cleanup_error is None:
                        cleanup_error = exc
                if primary_error is None and cleanup_error is not None:
                    raise cleanup_error

    def _read_bytes_posix(
        self,
        directories: tuple[str, ...],
        filename: str,
    ) -> bytes:
        with self._open_leaf_dir_posix(directories, create=False) as (
            _root_fd,
            leaf_fd,
            leaf_identity,
        ):
            content = _read_regular_file_at(leaf_fd, filename)
            self._verify_leaf_identity_posix(directories, leaf_identity)
            return content

    def _publish_posix(
        self,
        directories: tuple[str, ...],
        filename: str,
        content: bytes,
        payload: dict[str, Any],
        *,
        artifact_name: str,
        reference: str,
        path: Path,
    ) -> None:
        with self._open_leaf_dir_posix(directories, create=True) as (
            root_fd,
            leaf_fd,
            leaf_identity,
        ):
            self._verify_leaf_identity_posix(directories, leaf_identity)
            existing = _try_read_regular_file_at(leaf_fd, filename)
            if existing is not None:
                _require_identical_payload(
                    _decode_json_object(
                        existing,
                        artifact_name=artifact_name,
                        reference=reference,
                        path=path,
                    ),
                    payload,
                    artifact_name=artifact_name,
                    reference=reference,
                    path=path,
                )
                self._verify_leaf_identity_posix(directories, leaf_identity)
                return

            temporary_name = f".proofagent.{secrets.token_hex(16)}.tmp"
            temporary_fd: int | None = None
            temporary_identity: tuple[int, int] | None = None
            published = False
            try:
                self._verify_leaf_identity_posix(directories, leaf_identity)
                temporary_fd = os.open(
                    temporary_name,
                    _write_create_flags(),
                    0o600,
                    dir_fd=root_fd,
                )
                os.fchmod(temporary_fd, 0o600)
                temporary_stat = os.fstat(temporary_fd)
                _require_private_regular_file(
                    temporary_stat,
                    label="temporary artifact",
                )
                temporary_identity = (
                    temporary_stat.st_dev,
                    temporary_stat.st_ino,
                )
                self._verify_leaf_identity_posix(directories, leaf_identity)
                with os.fdopen(temporary_fd, "wb", closefd=False) as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                self._verify_leaf_identity_posix(directories, leaf_identity)
                try:
                    os.link(
                        temporary_name,
                        filename,
                        src_dir_fd=root_fd,
                        dst_dir_fd=leaf_fd,
                        follow_symlinks=False,
                    )
                    published = True
                    _require_regular_file_identity_at(
                        leaf_fd,
                        filename,
                        temporary_identity,
                    )
                    _fsync_directory(leaf_fd)
                    _require_regular_file_identity_at(
                        leaf_fd,
                        filename,
                        temporary_identity,
                    )
                except FileExistsError:
                    raced = _try_read_regular_file_at(leaf_fd, filename)
                    if raced is None:
                        raise
                    _require_identical_payload(
                        _decode_json_object(
                            raced,
                            artifact_name=artifact_name,
                            reference=reference,
                            path=path,
                        ),
                        payload,
                        artifact_name=artifact_name,
                        reference=reference,
                        path=path,
                    )
                self._verify_leaf_identity_posix(directories, leaf_identity)
                _unlink_name_if_identity_at(
                    root_fd,
                    temporary_name,
                    temporary_identity,
                )
                _fsync_directory(root_fd)
                if published:
                    _require_regular_file_identity_at(
                        leaf_fd,
                        filename,
                        temporary_identity,
                    )
                    self._verify_leaf_identity_posix(directories, leaf_identity)
            except BaseException:
                if published and temporary_identity is not None:
                    try:
                        _unlink_all_names_for_identity_at(
                            leaf_fd,
                            temporary_identity,
                        )
                        _fsync_directory(leaf_fd)
                    except OSError:
                        pass
                if temporary_identity is not None:
                    try:
                        _unlink_name_if_identity_at(
                            root_fd,
                            temporary_name,
                            temporary_identity,
                        )
                        _fsync_directory(root_fd)
                    except OSError:
                        pass
                raise
            finally:
                if temporary_fd is not None:
                    os.close(temporary_fd)
                if temporary_identity is not None:
                    try:
                        _unlink_name_if_identity_at(
                            root_fd,
                            temporary_name,
                            temporary_identity,
                        )
                    except OSError:
                        pass

    @contextmanager
    def _open_leaf_dir_posix(
        self,
        directories: tuple[str, ...],
        *,
        create: bool,
    ) -> Iterator[tuple[int, int, tuple[int, int]]]:
        root_fd = self._open_root_fd_posix()
        opened = [root_fd]
        current_fd = root_fd
        try:
            for segment in directories:
                created = False
                if create:
                    try:
                        os.mkdir(segment, mode=0o700, dir_fd=current_fd)
                        created = True
                    except FileExistsError:
                        pass
                child_fd = os.open(segment, _directory_open_flags(), dir_fd=current_fd)
                try:
                    if created:
                        os.fchmod(child_fd, 0o700)
                        _fsync_directory(current_fd)
                    child_stat = os.fstat(child_fd)
                    _require_private_directory(
                        child_stat,
                        label="artifact path component",
                    )
                except BaseException:
                    os.close(child_fd)
                    raise
                opened.append(child_fd)
                current_fd = child_fd
            leaf_stat = os.fstat(current_fd)
            yield root_fd, current_fd, (leaf_stat.st_dev, leaf_stat.st_ino)
        finally:
            for file_descriptor in reversed(opened):
                try:
                    os.close(file_descriptor)
                except OSError:
                    pass

    def _open_root_fd_posix(self) -> int:
        root_fd = _open_directory_path_nofollow(self._root, create=False)
        root_stat = os.fstat(root_fd)
        try:
            _require_private_directory(root_stat, label="local-store root")
        except OSError:
            os.close(root_fd)
            raise
        if (root_stat.st_dev, root_stat.st_ino) != self._root_identity:
            os.close(root_fd)
            raise OSError(errno.ESTALE, "trusted artifact root identity changed")
        return root_fd

    def _verify_leaf_identity_posix(
        self,
        directories: tuple[str, ...],
        expected_identity: tuple[int, int],
    ) -> None:
        with self._open_leaf_dir_posix(directories, create=False) as (
            _root_fd,
            _leaf_fd,
            actual_identity,
        ):
            if actual_identity != expected_identity:
                raise OSError(errno.ESTALE, "artifact directory identity changed")


def _observation_truth_from_payload(
    payload: dict[str, Any],
) -> ObservationTruthArtifact:
    kind = payload.get("kind")
    if kind == ObservationTruthKind.RETRIEVAL.value:
        return RetrievalObservationTruth.model_validate(payload)
    if kind == ObservationTruthKind.TOOL.value:
        return ToolObservationTruth.model_validate(payload)
    raise ProofAgentError(
        "PA_RUNTIME_001",
        f"unsupported controlled ReAct observation truth kind: {kind}",
        "Discard the stale approval checkpoint and restart the run.",
    )


def _supports_posix_dir_fd() -> bool:
    return (
        os.name == "posix"
        and hasattr(os, "register_at_fork")
        and hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "geteuid")
        and hasattr(os, "fchmod")
        and os.open in os.supports_dir_fd
        and os.mkdir in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.unlink in os.supports_dir_fd
        and os.link in os.supports_dir_fd
        and os.stat in os.supports_follow_symlinks
        and os.link in os.supports_follow_symlinks
        and os.listdir in os.supports_fd
        and _supports_flock()
    )


def _directory_open_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )


def _read_open_flags() -> int:
    return os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


def _write_create_flags() -> int:
    return (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )


def _lock_open_flags() -> int:
    return os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


def _thread_lock_for_root(root_identity: tuple[int, int]) -> LockType:
    with _ROOT_THREAD_LOCKS_GUARD:
        lock = _ROOT_THREAD_LOCKS.get(root_identity)
        if lock is None:
            lock = threading.Lock()
            _ROOT_THREAD_LOCKS[root_identity] = lock
        return lock


def _close_registered_descriptor(file_descriptor: int) -> None:
    with _FORK_STATE_GUARD:
        try:
            os.close(file_descriptor)
        finally:
            _ACTIVE_FORK_FDS.discard(file_descriptor)


def _open_publish_lock_at(
    root_fd: int,
    *,
    expected_identity: tuple[int, int] | None = None,
) -> tuple[int, os.stat_result, bool]:
    created = False
    try:
        lock_fd = os.open(
            _PUBLISH_LOCK_FILENAME,
            _lock_open_flags() | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=root_fd,
        )
        created = True
    except FileExistsError:
        lock_fd = os.open(
            _PUBLISH_LOCK_FILENAME,
            _lock_open_flags(),
            dir_fd=root_fd,
        )
    try:
        if created:
            os.fchmod(lock_fd, 0o600)
        lock_stat = os.fstat(lock_fd)
        _require_private_regular_file(lock_stat, label="publication lock")
        if stat.S_IMODE(lock_stat.st_mode) != 0o600:
            raise OSError(errno.EPERM, "publication lock mode is not 0600")
        identity = (lock_stat.st_dev, lock_stat.st_ino)
        if expected_identity is not None and identity != expected_identity:
            raise OSError(errno.ESTALE, "publication lock identity changed")
        return lock_fd, lock_stat, created
    except BaseException:
        os.close(lock_fd)
        raise


def _supports_flock() -> bool:
    try:
        import fcntl
    except ImportError:
        return False
    return hasattr(fcntl, "flock") and hasattr(fcntl, "LOCK_EX")


def _flock(file_descriptor: int, *, exclusive: bool) -> None:
    try:
        import fcntl
    except ImportError as exc:  # pragma: no cover - guarded by capability check
        raise OSError(errno.ENOSYS, "fcntl.flock is unavailable") from exc
    operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_UN
    fcntl.flock(file_descriptor, operation)


def _open_directory_path_nofollow(path: Path, *, create: bool) -> int:
    if not path.is_absolute():
        raise OSError(errno.EINVAL, "artifact root must be absolute")
    current_fd = os.open(os.sep, _directory_open_flags())
    try:
        _require_trusted_ancestor(os.fstat(current_fd), label="artifact root ancestor")
        for segment in path.parts[1:]:
            created = False
            if create:
                try:
                    os.mkdir(segment, mode=0o700, dir_fd=current_fd)
                    created = True
                except FileExistsError:
                    pass
            child_fd = os.open(segment, _directory_open_flags(), dir_fd=current_fd)
            try:
                child_stat = os.fstat(child_fd)
                if not stat.S_ISDIR(child_stat.st_mode):
                    raise OSError(
                        errno.ENOTDIR,
                        "artifact root path component is not a directory",
                    )
                if created:
                    os.fchmod(child_fd, 0o700)
                    _fsync_directory(current_fd)
                    child_stat = os.fstat(child_fd)
                _require_trusted_ancestor(
                    child_stat,
                    label="artifact root ancestor",
                )
            except BaseException:
                os.close(child_fd)
                raise
            os.close(current_fd)
            current_fd = child_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def _require_private_directory(
    directory_stat: os.stat_result,
    *,
    label: str,
) -> None:
    if not stat.S_ISDIR(directory_stat.st_mode):
        raise OSError(errno.ENOTDIR, f"{label} is not a directory")
    if directory_stat.st_uid != os.geteuid():
        raise OSError(errno.EPERM, f"{label} is not owned by the effective user")
    if directory_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise OSError(errno.EPERM, f"{label} is group/world writable")


def _require_trusted_ancestor(
    directory_stat: os.stat_result,
    *,
    label: str,
) -> None:
    if not stat.S_ISDIR(directory_stat.st_mode):
        raise OSError(errno.ENOTDIR, f"{label} is not a directory")
    trusted_owner = directory_stat.st_uid in {0, os.geteuid()}
    group_or_world_writable = bool(directory_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH))
    sticky = bool(directory_stat.st_mode & stat.S_ISVTX)
    if not trusted_owner:
        raise OSError(errno.EPERM, f"{label} has an untrusted owner")
    if group_or_world_writable and not sticky:
        raise OSError(errno.EPERM, f"{label} is renamable by untrusted users")


def _require_private_regular_file(
    file_stat: os.stat_result,
    *,
    label: str,
) -> None:
    if not stat.S_ISREG(file_stat.st_mode):
        raise OSError(errno.EINVAL, f"{label} is not a regular file")
    if file_stat.st_uid != os.geteuid():
        raise OSError(errno.EPERM, f"{label} is not owned by the effective user")
    if file_stat.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise OSError(errno.EPERM, f"{label} is accessible by group/other users")


def _read_regular_file_at(directory_fd: int, filename: str) -> bytes:
    file_descriptor = os.open(filename, _read_open_flags(), dir_fd=directory_fd)
    try:
        opened_stat = os.fstat(file_descriptor)
        _require_private_regular_file(opened_stat, label="artifact")
        with os.fdopen(file_descriptor, "rb", closefd=False) as handle:
            content = handle.read()
        named_stat = os.stat(filename, dir_fd=directory_fd, follow_symlinks=False)
        _require_private_regular_file(named_stat, label="artifact")
        if (named_stat.st_dev, named_stat.st_ino) != (
            opened_stat.st_dev,
            opened_stat.st_ino,
        ):
            raise OSError(errno.ESTALE, "artifact file identity changed")
        return content
    finally:
        os.close(file_descriptor)


def _try_read_regular_file_at(directory_fd: int, filename: str) -> bytes | None:
    try:
        return _read_regular_file_at(directory_fd, filename)
    except FileNotFoundError:
        return None


def _require_regular_file_identity_at(
    directory_fd: int,
    filename: str,
    expected_identity: tuple[int, int],
) -> None:
    named_stat = os.stat(filename, dir_fd=directory_fd, follow_symlinks=False)
    _require_private_regular_file(named_stat, label="published artifact")
    if (named_stat.st_dev, named_stat.st_ino) != expected_identity:
        raise OSError(errno.ESTALE, "published artifact identity changed")


def _unlink_name_if_identity_at(
    directory_fd: int,
    filename: str,
    expected_identity: tuple[int, int],
) -> None:
    try:
        named_stat = os.stat(filename, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if (named_stat.st_dev, named_stat.st_ino) == expected_identity:
        os.unlink(filename, dir_fd=directory_fd)


def _unlink_all_names_for_identity_at(
    directory_fd: int,
    expected_identity: tuple[int, int],
) -> None:
    for filename in os.listdir(directory_fd):
        try:
            named_stat = os.stat(
                filename,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            continue
        if (named_stat.st_dev, named_stat.st_ino) != expected_identity:
            continue
        try:
            os.unlink(filename, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


def _fsync_directory(directory_fd: int) -> None:
    os.fsync(directory_fd)


class _DuplicateJsonKeyError(ValueError):
    pass


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError(key)
        result[key] = value
    return result


def _decode_json_object(
    content: bytes,
    *,
    artifact_name: str,
    reference: str,
    path: Path,
) -> dict[str, Any]:
    try:
        payload = json.loads(content, object_pairs_hook=_reject_duplicate_json_keys)
    except (json.JSONDecodeError, UnicodeDecodeError, _DuplicateJsonKeyError) as exc:
        raise _corrupt_artifact_error(
            artifact_name=artifact_name,
            reference=reference,
            path=path,
        ) from exc
    if not isinstance(payload, dict):
        raise _corrupt_artifact_error(
            artifact_name=artifact_name,
            reference=reference,
            path=path,
        )
    return payload


def _require_identical_payload(
    existing: dict[str, Any],
    candidate: dict[str, Any],
    *,
    artifact_name: str,
    reference: str,
    path: Path,
) -> None:
    if canonical_json_bytes(existing) == canonical_json_bytes(candidate):
        return
    raise ProofAgentError(
        "PA_RUNTIME_001",
        f"conflicting {artifact_name} already exists: {reference}",
        "Use a new immutable artifact identity instead of replacing persisted state.",
        artifact_path=path,
    )


def _corrupt_artifact_error(
    *,
    artifact_name: str,
    reference: str,
    path: Path,
) -> ProofAgentError:
    return ProofAgentError(
        "PA_RUNTIME_001",
        f"invalid or corrupt {artifact_name}: {reference}",
        "Discard the stale artifact and restart the run.",
        artifact_path=path,
    )


def _storage_write_error(
    *,
    artifact_name: str,
    reference: str,
    path: Path,
) -> ProofAgentError:
    return ProofAgentError(
        "PA_RUNTIME_001",
        f"failed to persist {artifact_name}: {reference}",
        "Check local storage permissions and retry the run.",
        artifact_path=path,
    )
