from __future__ import annotations

import errno
import json
import os
import secrets
import stat
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


class FileControlledReActSnapshotStore:
    """Immutable, content-bound local snapshot store."""

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
    """Immutable, content-bound local Observation Truth Store."""

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
    """Filesystem boundary anchored to one canonical trusted root."""

    def __init__(self, root_dir: Path) -> None:
        if not _supports_posix_dir_fd():
            raise ProofAgentError(
                "PA_RUNTIME_001",
                "controlled ReAct local stores require anchored POSIX filesystem capabilities",
                (
                    "Use a POSIX runtime with dir_fd and O_NOFOLLOW support, or "
                    "configure a production artifact-store adapter."
                ),
                artifact_path=root_dir,
            )
        try:
            root_dir.mkdir(parents=True, exist_ok=True)
            canonical_root = root_dir.resolve(strict=True)
            root_stat = canonical_root.stat(follow_symlinks=False)
        except OSError as exc:
            raise ProofAgentError(
                "PA_RUNTIME_001",
                "controlled ReAct local-store root is unavailable",
                "Use an accessible trusted local artifact directory.",
                artifact_path=root_dir,
            ) from exc
        if not stat.S_ISDIR(root_stat.st_mode):
            raise ProofAgentError(
                "PA_RUNTIME_001",
                "controlled ReAct local-store root is not a directory",
                "Use a trusted local artifact directory.",
                artifact_path=canonical_root,
            )
        self._root = canonical_root
        self._root_identity = (root_stat.st_dev, root_stat.st_ino)

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

    def _read_bytes_posix(
        self,
        directories: tuple[str, ...],
        filename: str,
    ) -> bytes:
        with self._open_leaf_dir_posix(directories, create=False) as (
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

            temporary_name = f".{filename}.{secrets.token_hex(16)}.tmp"
            temporary_fd: int | None = None
            published = False
            try:
                self._verify_leaf_identity_posix(directories, leaf_identity)
                temporary_fd = os.open(
                    temporary_name,
                    _write_create_flags(),
                    0o600,
                    dir_fd=leaf_fd,
                )
                self._verify_leaf_identity_posix(directories, leaf_identity)
                with os.fdopen(temporary_fd, "wb") as handle:
                    temporary_fd = None
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                self._verify_leaf_identity_posix(directories, leaf_identity)
                try:
                    os.link(
                        temporary_name,
                        filename,
                        src_dir_fd=leaf_fd,
                        dst_dir_fd=leaf_fd,
                        follow_symlinks=False,
                    )
                    published = True
                    _fsync_directory(leaf_fd)
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
            except BaseException:
                if published:
                    try:
                        os.unlink(filename, dir_fd=leaf_fd)
                        _fsync_directory(leaf_fd)
                    except FileNotFoundError:
                        pass
                raise
            finally:
                if temporary_fd is not None:
                    os.close(temporary_fd)
                try:
                    os.unlink(temporary_name, dir_fd=leaf_fd)
                except FileNotFoundError:
                    pass

    @contextmanager
    def _open_leaf_dir_posix(
        self,
        directories: tuple[str, ...],
        *,
        create: bool,
    ) -> Iterator[tuple[int, tuple[int, int]]]:
        root_fd = self._open_root_fd_posix()
        opened = [root_fd]
        current_fd = root_fd
        try:
            for segment in directories:
                if create:
                    try:
                        os.mkdir(segment, mode=0o700, dir_fd=current_fd)
                    except FileExistsError:
                        pass
                child_fd = os.open(segment, _directory_open_flags(), dir_fd=current_fd)
                child_stat = os.fstat(child_fd)
                if not stat.S_ISDIR(child_stat.st_mode):
                    os.close(child_fd)
                    raise OSError(errno.ENOTDIR, "artifact path component is not a directory")
                opened.append(child_fd)
                current_fd = child_fd
            leaf_stat = os.fstat(current_fd)
            yield current_fd, (leaf_stat.st_dev, leaf_stat.st_ino)
        finally:
            for file_descriptor in reversed(opened):
                try:
                    os.close(file_descriptor)
                except OSError:
                    pass

    def _open_root_fd_posix(self) -> int:
        root_fd = os.open(self._root, _directory_open_flags())
        root_stat = os.fstat(root_fd)
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
        and hasattr(os, "O_NOFOLLOW")
        and os.open in os.supports_dir_fd
        and os.mkdir in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.unlink in os.supports_dir_fd
        and os.link in os.supports_dir_fd
        and os.stat in os.supports_follow_symlinks
        and os.link in os.supports_follow_symlinks
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


def _read_regular_file_at(directory_fd: int, filename: str) -> bytes:
    file_descriptor = os.open(filename, _read_open_flags(), dir_fd=directory_fd)
    try:
        opened_stat = os.fstat(file_descriptor)
        if not stat.S_ISREG(opened_stat.st_mode):
            raise OSError(errno.EINVAL, "artifact is not a regular file")
        with os.fdopen(file_descriptor, "rb", closefd=False) as handle:
            content = handle.read()
        named_stat = os.stat(filename, dir_fd=directory_fd, follow_symlinks=False)
        if not stat.S_ISREG(named_stat.st_mode) or (named_stat.st_dev, named_stat.st_ino) != (
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


def _fsync_directory(directory_fd: int) -> None:
    try:
        os.fsync(directory_fd)
    except OSError:
        pass


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
    if existing == candidate:
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
