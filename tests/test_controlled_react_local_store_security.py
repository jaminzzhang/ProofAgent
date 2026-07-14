from __future__ import annotations

import errno
import json
import os
import signal
import stat
import subprocess
import sys
import threading
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import proof_agent.control.workflow.controlled_react.local_stores as local_stores
from proof_agent.contracts import (
    ApprovedToolProposalSnapshot,
    ControlledReActRunPhase,
    ControlledReActRunState,
    ControlledReActRunStateSnapshot,
    EvidenceChunk,
    EvidenceStatus,
    ObservationRecord,
    ReActActionProposal,
    ReActActionType,
    ReasoningSummary,
    RetrievalObservationTruth,
    ToolObservationTruth,
)
from proof_agent.control.workflow.controlled_react.local_stores import (
    FileControlledReActSnapshotStore,
    FileObservationTruthStore,
)
from proof_agent.control.workflow.controlled_react.artifact_binding import (
    OBSERVATION_TRUTH_BINDING_SCHEMA_VERSION,
    SNAPSHOT_BINDING_SCHEMA_VERSION,
    bind_observation_truth,
)
from proof_agent.control.workflow.controlled_react.observation_commit import (
    InMemoryObservationTruthStore,
    ObservationCommitter,
    ObservationEffect,
)
from proof_agent.errors import ProofAgentError


SNAPSHOT_GOLDEN_DIGEST = "8deca1c89c96b4730c749e8c85b1ed17054f660c13c9e4db81d6dc138b5cfec0"
OBSERVATION_GOLDEN_DIGEST = "5ae2f9c9e131b252bdd9d1460f487dc7573f565a10dd5c33629a2b8c37dc46e3"


@pytest.mark.parametrize(
    "store_type",
    (FileControlledReActSnapshotStore, FileObservationTruthStore),
)
def test_local_artifact_stores_fail_closed_without_anchored_posix_capabilities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    store_type: (type[FileControlledReActSnapshotStore] | type[FileObservationTruthStore]),
) -> None:
    monkeypatch.setattr(local_stores, "_supports_posix_dir_fd", lambda: False)
    unavailable_root = tmp_path / "must-not-be-created"

    with pytest.raises(ProofAgentError) as exc:
        store_type(unavailable_root)

    assert exc.value.code == "PA_RUNTIME_001"
    assert "POSIX" in str(exc.value)
    assert not unavailable_root.exists()


def test_snapshot_ref_uses_versioned_full_payload_digest(tmp_path: Path) -> None:
    snapshot = _snapshot()

    snapshot_ref = FileControlledReActSnapshotStore(tmp_path).save(snapshot)

    assert SNAPSHOT_BINDING_SCHEMA_VERSION == ("proofagent.controlled-react.snapshot-binding.v1")
    assert snapshot_ref == ("controlled-react://run_001/snap_001/sha256/" + SNAPSHOT_GOLDEN_DIGEST)


def test_observation_ref_uses_versioned_normalized_payload_digest(
    tmp_path: Path,
) -> None:
    truth = RetrievalObservationTruth(
        truth_ref="observation://run_001/obs_1/truth",
        observation_id="obs_1",
        action_id="act_original",
    )

    binding = bind_observation_truth(truth)
    truth_ref = FileObservationTruthStore(tmp_path).save(binding.truth)

    assert OBSERVATION_TRUTH_BINDING_SCHEMA_VERSION == (
        "proofagent.controlled-react.observation-truth-binding.v1"
    )
    assert truth_ref == ("observation://run_001/obs_1/truth/sha256/" + OBSERVATION_GOLDEN_DIGEST)
    assert FileObservationTruthStore(tmp_path).load(truth_ref).truth_ref == truth_ref


def test_snapshot_legacy_unbound_ref_fails_closed(tmp_path: Path) -> None:
    store = FileControlledReActSnapshotStore(tmp_path)
    bound_ref = store.save(_snapshot())
    assert "/sha256/" in bound_ref

    with pytest.raises(ProofAgentError) as exc:
        store.load("controlled-react://run_001/snap_001")

    assert exc.value.code == "PA_RUNTIME_001"


def test_snapshot_ref_rejects_modified_digest_segment(tmp_path: Path) -> None:
    store = FileControlledReActSnapshotStore(tmp_path)
    snapshot_ref = store.save(_snapshot())
    assert "/sha256/" in snapshot_ref
    replacement = "0" if snapshot_ref[-1] != "0" else "1"

    with pytest.raises(ProofAgentError) as exc:
        store.load(snapshot_ref[:-1] + replacement)

    assert exc.value.code == "PA_RUNTIME_001"


def test_observation_legacy_unbound_ref_fails_closed(tmp_path: Path) -> None:
    store = FileObservationTruthStore(tmp_path)
    truth = RetrievalObservationTruth(
        truth_ref="observation://run_001/obs_1/truth",
        observation_id="obs_1",
        action_id="act_original",
    )
    bound_ref = store.save(bind_observation_truth(truth).truth)
    assert "/sha256/" in bound_ref

    with pytest.raises(ProofAgentError) as exc:
        store.load(truth.truth_ref)

    assert exc.value.code == "PA_RUNTIME_001"


def test_snapshot_digest_rejects_question_tamper(tmp_path: Path) -> None:
    store = FileControlledReActSnapshotStore(tmp_path)
    snapshot_ref = store.save(_snapshot())
    artifact = _only_json_artifact(tmp_path)
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    payload["state"]["question"] = "Tampered question"
    artifact.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ProofAgentError) as exc:
        store.load(snapshot_ref)

    assert exc.value.code == "PA_RUNTIME_001"


def test_snapshot_canonical_json_preserves_utf8_and_rejects_nan(tmp_path: Path) -> None:
    store = FileControlledReActSnapshotStore(tmp_path)
    store.save(_snapshot())
    content = _only_json_artifact(tmp_path).read_text(encoding="utf-8")

    assert "原始问题" in content
    assert "\\u539f" not in content

    invalid = _snapshot().model_copy(
        update={
            "snapshot_id": "snap_nan",
            "state": _snapshot().state.model_copy(
                update={"intent_resolution": {"confidence": float("nan")}}
            ),
        }
    )
    with pytest.raises(ProofAgentError) as exc:
        store.save(invalid)

    assert exc.value.code == "PA_RUNTIME_001"


@pytest.mark.parametrize(
    ("original_value", "conflicting_value"),
    ((1, 1.0), (True, 1)),
)
def test_snapshot_store_rejects_json_distinct_python_equal_payloads(
    tmp_path: Path,
    original_value: object,
    conflicting_value: object,
) -> None:
    store = FileControlledReActSnapshotStore(tmp_path)
    baseline = _snapshot()
    original = baseline.model_copy(
        update={
            "state": baseline.state.model_copy(update={"memory_context": {"value": original_value}})
        }
    )
    conflicting = baseline.model_copy(
        update={
            "state": baseline.state.model_copy(
                update={"memory_context": {"value": conflicting_value}}
            )
        }
    )

    original_ref = store.save(original)
    assert store.load(original_ref) == original

    with pytest.raises(ProofAgentError, match="conflicting"):
        store.save(conflicting)


@pytest.mark.parametrize(
    ("original_value", "conflicting_value"),
    ((1, 1.0), (True, 1)),
)
def test_observation_store_rejects_json_distinct_python_equal_payloads(
    tmp_path: Path,
    original_value: object,
    conflicting_value: object,
) -> None:
    store = FileObservationTruthStore(tmp_path)
    original = ToolObservationTruth(
        truth_ref="observation://run_001/obs_tool/truth",
        observation_id="obs_tool",
        action_id="act_tool",
        tool_name="customer_lookup",
        authorized_result={"value": original_value},
    )
    conflicting = original.model_copy(update={"authorized_result": {"value": conflicting_value}})
    original_binding = bind_observation_truth(original)
    conflicting_binding = bind_observation_truth(conflicting)

    original_ref = store.save(original_binding.truth)
    assert store.load(original_ref) == original_binding.truth

    with pytest.raises(ProofAgentError, match="conflicting"):
        store.save(conflicting_binding.truth)


def test_snapshot_load_rejects_nested_duplicate_json_key(tmp_path: Path) -> None:
    store = FileControlledReActSnapshotStore(tmp_path)
    snapshot_ref = store.save(_snapshot())
    artifact = _only_json_artifact(tmp_path)
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    raw = raw.replace(
        '"question":"原始问题"',
        '"question":"原始问题","question":"重复字段"',
        1,
    )
    artifact.write_text(raw, encoding="utf-8")

    with pytest.raises(ProofAgentError) as exc:
        store.load(snapshot_ref)

    assert exc.value.code == "PA_RUNTIME_001"


def test_snapshot_digest_rejects_approved_proposal_tamper(tmp_path: Path) -> None:
    store = FileControlledReActSnapshotStore(tmp_path)
    snapshot_ref = store.save(_snapshot(with_approved_proposal=True))
    artifact = _only_json_artifact(tmp_path)
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    payload["state"]["approved_tool_proposal_snapshot"]["parameters"]["customer_id"] = (
        "CUST-TAMPERED"
    )
    artifact.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ProofAgentError) as exc:
        store.load(snapshot_ref)

    assert exc.value.code == "PA_RUNTIME_001"


def test_observation_digest_rejects_retrieval_content_tamper(
    tmp_path: Path,
) -> None:
    store = FileObservationTruthStore(tmp_path)
    truth = RetrievalObservationTruth(
        truth_ref="observation://run_001/obs_1/truth",
        observation_id="obs_1",
        action_id="act_retrieve",
        accepted_evidence=(
            EvidenceChunk(
                source="Claims Guide",
                content="Original governed evidence.",
                status=EvidenceStatus.ACCEPTED,
                citation="claims.md#L1",
            ),
        ),
    )
    truth_ref = store.save(bind_observation_truth(truth).truth)
    artifact = _only_json_artifact(tmp_path)
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    payload["accepted_evidence"][0]["content"] = "Tampered evidence."
    artifact.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ProofAgentError) as exc:
        store.load(truth_ref)

    assert exc.value.code == "PA_RUNTIME_001"


def test_observation_digest_rejects_tool_authorized_result_tamper(
    tmp_path: Path,
) -> None:
    store = FileObservationTruthStore(tmp_path)
    truth = ToolObservationTruth(
        truth_ref="observation://run_001/obs_tool/truth",
        observation_id="obs_tool",
        action_id="act_tool",
        tool_name="customer_lookup",
        authorized_result={"status": "active", "customer_id": "CUST-001"},
        result_schema_id="customer_lookup.v1",
    )
    truth_ref = store.save(bind_observation_truth(truth).truth)
    artifact = _only_json_artifact(tmp_path)
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    payload["authorized_result"]["status"] = "cancelled"
    artifact.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ProofAgentError) as exc:
        store.load(truth_ref)

    assert exc.value.code == "PA_RUNTIME_001"


def test_snapshot_store_rejects_symlink_root(tmp_path: Path) -> None:
    actual_root = tmp_path / "actual-store"
    actual_root.mkdir(mode=0o700)
    symlink_root = tmp_path / "store-link"
    symlink_root.symlink_to(actual_root, target_is_directory=True)

    with pytest.raises(ProofAgentError):
        FileControlledReActSnapshotStore(symlink_root)

    assert not tuple(actual_root.iterdir())


def test_snapshot_store_rejects_symlink_in_existing_root_path(tmp_path: Path) -> None:
    actual_parent = tmp_path / "actual-parent"
    actual_parent.mkdir(mode=0o700)
    symlink_parent = tmp_path / "parent-link"
    symlink_parent.symlink_to(actual_parent, target_is_directory=True)

    with pytest.raises(ProofAgentError):
        FileControlledReActSnapshotStore(symlink_parent / "store")


def test_snapshot_store_creates_private_root(tmp_path: Path) -> None:
    root = tmp_path / "new-store"

    FileControlledReActSnapshotStore(root)

    assert stat.S_IMODE(root.stat().st_mode) == 0o700


def test_snapshot_store_rejects_group_or_world_writable_root(tmp_path: Path) -> None:
    root = tmp_path / "writable-store"
    root.mkdir(mode=0o700)
    root.chmod(0o770)

    with pytest.raises(ProofAgentError):
        FileControlledReActSnapshotStore(root)


def test_snapshot_store_rejects_non_sticky_writable_ancestor(tmp_path: Path) -> None:
    writable_ancestor = tmp_path / "writable-ancestor"
    writable_ancestor.mkdir(mode=0o700)
    writable_ancestor.chmod(0o770)

    with pytest.raises(ProofAgentError):
        FileControlledReActSnapshotStore(writable_ancestor / "store")


def test_snapshot_store_allows_trusted_sticky_writable_ancestor(tmp_path: Path) -> None:
    sticky_ancestor = tmp_path / "sticky-ancestor"
    sticky_ancestor.mkdir(mode=0o700)
    sticky_ancestor.chmod(0o1777)

    FileControlledReActSnapshotStore(sticky_ancestor / "store")


def test_snapshot_store_rejects_owner_writable_ancestor_with_untrusted_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ancestor = tmp_path / "foreign-ancestor"
    ancestor.mkdir(mode=0o700)
    ancestor_identity = (ancestor.stat().st_dev, ancestor.stat().st_ino)
    real_fstat = os.fstat

    def foreign_owner_fstat(file_descriptor: int) -> os.stat_result:
        result = real_fstat(file_descriptor)
        if (result.st_dev, result.st_ino) != ancestor_identity:
            return result
        fields = list(result)
        fields[4] = os.geteuid() + 1
        return os.stat_result(fields)

    monkeypatch.setattr(os, "fstat", foreign_owner_fstat)

    with pytest.raises(ProofAgentError):
        FileControlledReActSnapshotStore(ancestor / "store")


def test_snapshot_store_rejects_read_only_ancestor_with_untrusted_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ancestor = tmp_path / "foreign-read-only-ancestor"
    ancestor.mkdir(mode=0o700)
    store_root = ancestor / "store"
    store_root.mkdir(mode=0o700)
    ancestor.chmod(0o555)
    ancestor_identity = (ancestor.stat().st_dev, ancestor.stat().st_ino)
    real_fstat = os.fstat

    def foreign_owner_fstat(file_descriptor: int) -> os.stat_result:
        result = real_fstat(file_descriptor)
        if (result.st_dev, result.st_ino) != ancestor_identity:
            return result
        fields = list(result)
        fields[4] = os.geteuid() + 1
        return os.stat_result(fields)

    monkeypatch.setattr(os, "fstat", foreign_owner_fstat)

    with pytest.raises(ProofAgentError):
        FileControlledReActSnapshotStore(store_root)


def test_snapshot_store_rejects_root_not_owned_by_effective_user(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "foreign-store"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(os, "geteuid", lambda: root.stat().st_uid + 1)

    with pytest.raises(ProofAgentError):
        FileControlledReActSnapshotStore(root)


def test_snapshot_store_revalidates_root_permissions_on_every_operation(
    tmp_path: Path,
) -> None:
    root = tmp_path / "store"
    store = FileControlledReActSnapshotStore(root)
    root.chmod(0o770)

    with pytest.raises(ProofAgentError):
        store.save(_snapshot())


def test_snapshot_store_rejects_parent_directory_symlink(tmp_path: Path) -> None:
    root = tmp_path / "store"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "run_001").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ProofAgentError) as exc:
        FileControlledReActSnapshotStore(root).save(_snapshot())

    assert exc.value.code == "PA_RUNTIME_001"
    assert not tuple(outside.rglob("*.json"))


def test_snapshot_store_rejects_final_file_symlink(tmp_path: Path) -> None:
    root = tmp_path / "store"
    outside = tmp_path / "outside.json"
    store = FileControlledReActSnapshotStore(root)
    snapshot_ref = store.save(_snapshot())
    artifact = _only_json_artifact(root)
    original = artifact.read_bytes()
    outside.write_bytes(original)
    artifact.unlink()
    artifact.symlink_to(outside)

    with pytest.raises(ProofAgentError) as exc:
        store.load(snapshot_ref)

    assert exc.value.code == "PA_RUNTIME_001"
    assert outside.read_bytes() == original


def test_snapshot_store_detects_directory_replacement_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "store"
    outside = tmp_path / "outside"
    detached = tmp_path / "detached-run"
    root.mkdir()
    outside.mkdir()
    store = FileControlledReActSnapshotStore(root)
    real_open = os.open
    swapped = False

    def race_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        file_descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
        if path == "controlled_react" and dir_fd is not None and not swapped:
            run_dir = root / "run_001"
            run_dir.rename(detached)
            run_dir.symlink_to(outside, target_is_directory=True)
            swapped = True
        return file_descriptor

    monkeypatch.setattr(os, "open", race_open)

    with pytest.raises(ProofAgentError) as exc:
        store.save(_snapshot())

    assert exc.value.code == "PA_RUNTIME_001"
    assert swapped is True
    assert not tuple(outside.rglob("*.json"))
    assert not tuple(detached.rglob("*.json"))


def test_snapshot_store_never_exposes_sensitive_temp_when_run_dir_moves_on_fsync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "store"
    outside = tmp_path / "outside-run"
    store = FileControlledReActSnapshotStore(root)
    baseline = _snapshot()
    snapshot = baseline.model_copy(
        update={
            "state": baseline.state.model_copy(
                update={"question": "SENSITIVE-CONTROLLED-REACT-PAYLOAD"}
            )
        }
    )
    real_fsync = os.fsync
    moved = False
    sensitive_visible_during_fsync = False

    def race_fsync(file_descriptor: int) -> None:
        nonlocal moved, sensitive_visible_during_fsync
        real_fsync(file_descriptor)
        if moved or not stat.S_ISREG(os.fstat(file_descriptor).st_mode):
            return
        run_dir = root / "run_001"
        run_dir.rename(outside)
        moved = True
        sensitive_visible_during_fsync = any(
            path.is_file() and b"SENSITIVE-CONTROLLED-REACT-PAYLOAD" in path.read_bytes()
            for path in outside.rglob("*")
        )

    monkeypatch.setattr(os, "fsync", race_fsync)

    with pytest.raises(ProofAgentError):
        store.save(snapshot)

    assert moved is True
    assert sensitive_visible_during_fsync is False
    assert not any(
        path.is_file() and b"SENSITIVE-CONTROLLED-REACT-PAYLOAD" in path.read_bytes()
        for path in outside.rglob("*")
    )


def test_snapshot_store_fails_if_published_name_moves_during_directory_fsync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "store"
    store = FileControlledReActSnapshotStore(root)
    real_fsync = os.fsync
    moved = False

    def race_fsync(file_descriptor: int) -> None:
        nonlocal moved
        descriptor_stat = os.fstat(file_descriptor)
        if stat.S_ISDIR(descriptor_stat.st_mode) and not moved:
            try:
                os.stat(
                    "snap_001.json",
                    dir_fd=file_descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                pass
            else:
                os.rename(
                    "snap_001.json",
                    "leaked.json",
                    src_dir_fd=file_descriptor,
                    dst_dir_fd=file_descriptor,
                )
                moved = True
        real_fsync(file_descriptor)

    monkeypatch.setattr(os, "fsync", race_fsync)

    with pytest.raises(ProofAgentError):
        store.save(_snapshot())

    assert moved is True
    assert not tuple(root.rglob("leaked.json"))


def test_concurrent_successful_save_remains_loadable_after_publisher_fault(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "store"
    publisher_store = FileControlledReActSnapshotStore(root)
    contender_store = FileControlledReActSnapshotStore(root)
    snapshot = _snapshot()
    root_identity = (root.stat().st_dev, root.stat().st_ino)
    real_fsync = os.fsync
    fault_reached = threading.Event()
    second_returned = threading.Event()
    fault_injected = False
    successful_refs: list[str] = []

    def fault_after_root_temp_cleanup(file_descriptor: int) -> None:
        nonlocal fault_injected
        descriptor_stat = os.fstat(file_descriptor)
        is_root = (descriptor_stat.st_dev, descriptor_stat.st_ino) == root_identity
        final_exists = (root / "run_001" / "controlled_react" / "snap_001.json").exists()
        root_temp_exists = any(
            name.startswith(".proofagent.") and name.endswith(".tmp") for name in os.listdir(root)
        )
        if is_root and final_exists and not root_temp_exists and not fault_injected:
            fault_injected = True
            fault_reached.set()
            second_returned.wait(timeout=1.0)
            raise OSError(errno.EIO, "injected root directory fsync failure")
        real_fsync(file_descriptor)

    def save_outcome(
        store: FileControlledReActSnapshotStore,
        *,
        signal_return: bool = False,
    ) -> str:
        try:
            snapshot_ref = store.save(snapshot)
        except ProofAgentError:
            return "failed"
        finally:
            if signal_return:
                second_returned.set()
        successful_refs.append(snapshot_ref)
        return "saved"

    monkeypatch.setattr(os, "fsync", fault_after_root_temp_cleanup)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(save_outcome, publisher_store)
        assert fault_reached.wait(timeout=2.0)
        second = executor.submit(save_outcome, contender_store, signal_return=True)
        outcomes = (first.result(timeout=3.0), second.result(timeout=3.0))

    assert "saved" in outcomes
    for snapshot_ref in successful_refs:
        assert contender_store.load(snapshot_ref) == snapshot


def test_publication_lock_is_persistent_private_and_shared_by_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "store"
    first_store = FileControlledReActSnapshotStore(root)
    lock_path = root / ".proofagent.publish.lock"
    first_stat = lock_path.stat(follow_symlinks=False)

    second_store = FileControlledReActSnapshotStore(root)
    snapshot_ref = second_store.save(_snapshot())
    second_stat = lock_path.stat(follow_symlinks=False)

    assert stat.S_ISREG(first_stat.st_mode)
    assert stat.S_IMODE(first_stat.st_mode) == 0o600
    assert (second_stat.st_dev, second_stat.st_ino) == (
        first_stat.st_dev,
        first_stat.st_ino,
    )
    assert first_store.load(snapshot_ref) == _snapshot()


def test_publication_waits_for_lock_held_by_another_process(tmp_path: Path) -> None:
    root = tmp_path / "store"
    store = FileControlledReActSnapshotStore(root)
    lock_path = root / ".proofagent.publish.lock"
    ready_read, ready_write = os.pipe()
    release_read, release_write = os.pipe()
    child = subprocess.Popen(
        (
            sys.executable,
            "-c",
            (
                "import fcntl, os, sys; "
                "fd=os.open(sys.argv[1], os.O_RDWR); "
                "fcntl.flock(fd, fcntl.LOCK_EX); "
                "os.write(int(sys.argv[2]), b'1'); "
                "os.read(int(sys.argv[3]), 1); "
                "os.close(fd)"
            ),
            str(lock_path),
            str(ready_write),
            str(release_read),
        ),
        pass_fds=(ready_write, release_read),
    )
    os.close(ready_write)
    os.close(release_read)
    assert os.read(ready_read, 1) == b"1"
    os.close(ready_read)
    started = threading.Event()
    returned = threading.Event()

    def save_snapshot() -> str:
        started.set()
        snapshot_ref = store.save(_snapshot())
        returned.set()
        return snapshot_ref

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(save_snapshot)
            try:
                assert started.wait(timeout=1.0)
                blocked_by_child = not returned.wait(timeout=0.25)
            finally:
                os.write(release_write, b"1")
                os.close(release_write)
            snapshot_ref = future.result(timeout=3.0)
    finally:
        if child.poll() is None:
            try:
                os.write(release_write, b"1")
            except OSError:
                pass
        try:
            os.close(release_write)
        except OSError:
            pass
        child.wait(timeout=3.0)

    assert blocked_by_child is True
    assert store.load(snapshot_ref) == _snapshot()


def test_child_store_after_active_multithreaded_fork_does_not_inherit_deadlock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FileControlledReActSnapshotStore(tmp_path / "store")
    publisher_snapshot = _snapshot()
    child_snapshot = _snapshot().model_copy(update={"snapshot_id": "snap_child"})
    real_fsync = os.fsync
    publisher_holds_lock = threading.Event()
    release_publisher = threading.Event()
    blocked_once = False

    def hold_first_file_fsync(file_descriptor: int) -> None:
        nonlocal blocked_once
        real_fsync(file_descriptor)
        if blocked_once or not stat.S_ISREG(os.fstat(file_descriptor).st_mode):
            return
        blocked_once = True
        publisher_holds_lock.set()
        release_publisher.wait(timeout=5.0)

    monkeypatch.setattr(os, "fsync", hold_first_file_fsync)

    with ThreadPoolExecutor(max_workers=1) as executor:
        publisher = executor.submit(store.save, publisher_snapshot)
        assert publisher_holds_lock.wait(timeout=2.0)
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="This process .* is multi-threaded.*",
                category=DeprecationWarning,
            )
            child_pid = os.fork()
        if child_pid == 0:  # pragma: no branch - child exits directly
            signal.signal(signal.SIGALRM, lambda *_args: os._exit(91))
            signal.alarm(2)
            try:
                child_ref = store.save(child_snapshot)
                store.load(child_ref)
            except BaseException:
                os._exit(92)
            os._exit(0)
        release_publisher.set()
        publisher.result(timeout=3.0)

    _, child_status = os.waitpid(child_pid, 0)
    assert os.WIFEXITED(child_status)
    assert os.WEXITSTATUS(child_status) == 0


def test_publication_lock_acquire_failure_is_not_masked_by_unlock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FileControlledReActSnapshotStore(tmp_path / "store")
    operations: list[bool] = []

    def fail_flock(_file_descriptor: int, *, exclusive: bool) -> None:
        operations.append(exclusive)
        message = "acquire failure" if exclusive else "unlock masked acquire failure"
        raise OSError(errno.EIO, message)

    monkeypatch.setattr(local_stores, "_flock", fail_flock)

    with pytest.raises(ProofAgentError) as exc:
        store.save(_snapshot())

    assert operations == [True]
    assert exc.value.__cause__ is not None
    assert "acquire failure" in str(exc.value.__cause__)


def test_body_failure_is_not_masked_by_unlock_and_closes_descriptors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FileControlledReActSnapshotStore(tmp_path / "store")
    real_flock = local_stores._flock

    def fail_link(
        _source: os.PathLike[str] | str,
        _target: os.PathLike[str] | str,
        **_kwargs: object,
    ) -> None:
        raise OSError(errno.ENOSPC, "BODY_LINK_FAILURE")

    def fail_unlock(file_descriptor: int, *, exclusive: bool) -> None:
        if exclusive:
            real_flock(file_descriptor, exclusive=True)
            return
        raise OSError(errno.EIO, "UNLOCK_MASK")

    monkeypatch.setattr(os, "link", fail_link)
    monkeypatch.setattr(local_stores, "_flock", fail_unlock)
    descriptor_count_before = len(os.listdir("/dev/fd"))

    with pytest.raises(ProofAgentError) as exc:
        store.save(_snapshot())

    descriptor_count_after = len(os.listdir("/dev/fd"))
    assert exc.value.__cause__ is not None
    assert "BODY_LINK_FAILURE" in str(exc.value.__cause__)
    assert "UNLOCK_MASK" not in str(exc.value.__cause__)
    assert descriptor_count_after == descriptor_count_before


def test_observation_committer_records_file_store_authoritative_ref(
    tmp_path: Path,
) -> None:
    action = _proposal()
    state = ControlledReActRunState(
        run_id="run_001",
        template_name="react_enterprise_qa_v3",
        template_descriptor_version="react_enterprise_qa.v3",
        question="What is the policy status?",
        phase=ControlledReActRunPhase.OBSERVING,
        plan_round=1,
        action_history=(action,),
    )
    base_ref = "observation://run_001/obs_1/truth"
    truth = ToolObservationTruth(
        truth_ref=base_ref,
        observation_id="obs_1",
        action_id=action.action_id,
        tool_name="customer_lookup",
        authorized_result={"status": "active"},
    )
    record = ObservationRecord(
        observation_id="obs_1",
        action_id=action.action_id,
        action_type=action.action_type,
        round=1,
        truth_ref=base_ref,
    )
    store = FileObservationTruthStore(tmp_path)

    result = ObservationCommitter(truth_store=store).commit(
        state,
        action,
        ObservationEffect(observation_record=record, truth_artifact=truth),
    )

    authoritative_ref = result.state.observation_records[0].truth_ref
    assert authoritative_ref.startswith(base_ref + "/sha256/")
    assert result.trace_projection["truth_ref"] == authoritative_ref
    assert store.load(authoritative_ref).truth_ref == authoritative_ref


def test_in_memory_store_uses_the_same_domain_bound_observation_ref() -> None:
    store = InMemoryObservationTruthStore()
    truth = RetrievalObservationTruth(
        truth_ref="observation://run_001/obs_1/truth",
        observation_id="obs_1",
        action_id="act_original",
    )

    bound_truth = bind_observation_truth(truth).truth
    truth_ref = store.save(bound_truth)

    assert truth_ref.startswith(truth.truth_ref + "/sha256/")
    assert store.load(truth_ref).truth_ref == truth_ref


def test_observation_commit_rejects_duplicate_identity_with_different_digest() -> None:
    action = _proposal()
    state = ControlledReActRunState(
        run_id="run_001",
        template_name="react_enterprise_qa_v3",
        template_descriptor_version="react_enterprise_qa.v3",
        question="What is the policy status?",
        phase=ControlledReActRunPhase.OBSERVING,
        plan_round=1,
        action_history=(action,),
    )
    base_ref = "observation://run_001/obs_1/truth"
    original = ToolObservationTruth(
        truth_ref=base_ref,
        observation_id="obs_1",
        action_id=action.action_id,
        tool_name="customer_lookup",
        authorized_result={"status": "active"},
    )
    record = ObservationRecord(
        observation_id="obs_1",
        action_id=action.action_id,
        action_type=action.action_type,
        round=1,
        truth_ref=base_ref,
    )
    store = InMemoryObservationTruthStore()
    committer = ObservationCommitter(truth_store=store)
    committed = committer.commit(
        state,
        action,
        ObservationEffect(observation_record=record, truth_artifact=original),
    )
    replacement = original.model_copy(update={"authorized_result": {"status": "cancelled"}})

    with pytest.raises(ValueError, match="conflicting observation"):
        committer.commit(
            committed.state,
            action,
            ObservationEffect(observation_record=record, truth_artifact=replacement),
        )


def test_observation_commit_retry_with_same_identity_and_payload_is_idempotent() -> None:
    action = _proposal()
    state = ControlledReActRunState(
        run_id="run_001",
        template_name="react_enterprise_qa_v3",
        template_descriptor_version="react_enterprise_qa.v3",
        question="What is the policy status?",
        phase=ControlledReActRunPhase.OBSERVING,
        plan_round=1,
        action_history=(action,),
    )
    base_ref = "observation://run_001/obs_1/truth"
    truth = ToolObservationTruth(
        truth_ref=base_ref,
        observation_id="obs_1",
        action_id=action.action_id,
        tool_name="customer_lookup",
        authorized_result={"status": "active"},
    )
    record = ObservationRecord(
        observation_id="obs_1",
        action_id=action.action_id,
        action_type=action.action_type,
        round=1,
        truth_ref=base_ref,
    )
    effect = ObservationEffect(observation_record=record, truth_artifact=truth)
    committer = ObservationCommitter(truth_store=InMemoryObservationTruthStore())

    committed = committer.commit(state, action, effect)
    retried = committer.commit(committed.state, action, effect)

    authoritative_ref = committed.state.observation_records[0].truth_ref
    assert retried.state == committed.state
    assert retried.state.observation_records[0].truth_ref == authoritative_ref
    assert retried.trace_projection["truth_ref"] == authoritative_ref


def test_concurrent_same_observation_payload_is_idempotent(tmp_path: Path) -> None:
    store = FileObservationTruthStore(tmp_path)
    truth = RetrievalObservationTruth(
        truth_ref="observation://run_001/obs_1/truth",
        observation_id="obs_1",
        action_id="act_original",
    )

    bound_truth = bind_observation_truth(truth).truth
    with ThreadPoolExecutor(max_workers=2) as executor:
        refs = tuple(executor.map(store.save, (bound_truth, bound_truth)))

    assert refs[0] == refs[1]
    assert "/sha256/" in refs[0]


def test_concurrent_python_equal_snapshot_payloads_have_one_loadable_winner(
    tmp_path: Path,
) -> None:
    store = FileControlledReActSnapshotStore(tmp_path)
    baseline = _snapshot()
    integer_snapshot = baseline.model_copy(
        update={"state": baseline.state.model_copy(update={"memory_context": {"value": 1}})}
    )
    float_snapshot = baseline.model_copy(
        update={"state": baseline.state.model_copy(update={"memory_context": {"value": 1.0}})}
    )

    def save_outcome(snapshot: ControlledReActRunStateSnapshot) -> str:
        try:
            snapshot_ref = store.save(snapshot)
        except ProofAgentError:
            return "conflict"
        store.load(snapshot_ref)
        return "saved"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(save_outcome, (integer_snapshot, float_snapshot)))

    assert sorted(outcomes) == ["conflict", "saved"]


def test_concurrent_different_observation_payload_has_one_winner(
    tmp_path: Path,
) -> None:
    store = FileObservationTruthStore(tmp_path)
    original = RetrievalObservationTruth(
        truth_ref="observation://run_001/obs_1/truth",
        observation_id="obs_1",
        action_id="act_original",
    )
    conflicting = original.model_copy(update={"action_id": "act_conflicting"})

    def save_outcome(truth: RetrievalObservationTruth) -> str:
        try:
            store.save(truth)
        except ProofAgentError:
            return "conflict"
        return "saved"

    bound_original = bind_observation_truth(original).truth
    bound_conflicting = bind_observation_truth(conflicting).truth
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(save_outcome, (bound_original, bound_conflicting)))

    assert sorted(outcomes) == ["conflict", "saved"]


def _snapshot(*, with_approved_proposal: bool = False) -> ControlledReActRunStateSnapshot:
    approved_proposal = (
        ApprovedToolProposalSnapshot(
            snapshot_id="approved_act_tool",
            action_id="act_tool",
            tool_contract_id="customer_lookup",
            parameters={"customer_id": "CUST-001"},
            parameter_digest="a" * 64,
            policy_decision="require_approval",
            risk_level="high",
            approval_reason="Operator approval required.",
        )
        if with_approved_proposal
        else None
    )
    return ControlledReActRunStateSnapshot(
        snapshot_id="snap_001",
        run_id="run_001",
        state=ControlledReActRunState(
            run_id="run_001",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="原始问题",
            approved_tool_proposal_snapshot=approved_proposal,
        ),
    )


def _proposal() -> ReActActionProposal:
    return ReActActionProposal(
        action_id="act_tool",
        action_type=ReActActionType.PROPOSE_TOOL_CALL,
        reasoning_summary=ReasoningSummary(
            goal="Use one governed tool observation.",
            observations=(),
            candidate_actions=(ReActActionType.PROPOSE_TOOL_CALL,),
            selected_action=ReActActionType.PROPOSE_TOOL_CALL,
            rationale_summary="The governed tool can provide the required status.",
            risk_flags=(),
            required_evidence=(),
        ),
        target_tool_name="customer_lookup",
        risk_level="high",
    )


def _only_json_artifact(root: Path) -> Path:
    artifacts = tuple(root.rglob("*.json"))
    assert len(artifacts) == 1
    return artifacts[0]
