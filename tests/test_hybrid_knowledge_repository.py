from datetime import datetime
from pathlib import Path

from pydantic import ValidationError
import pytest

from proof_agent.capabilities.knowledge.hybrid.ports import (
    HybridClock,
    HybridKnowledgeJobKind,
    HybridKnowledgeJobRequest,
    HybridKnowledgeWorkScheduler,
    KnowledgeArtifactStore,
)
from proof_agent.configuration.hybrid_knowledge_repository import (
    FileSystemKnowledgeArtifactStore,
    HybridKnowledgeIdempotencyConflict,
    HybridKnowledgeLeaseError,
    ImmutableArtifactError,
    InMemoryHybridKnowledgeRepository,
    ManualHybridClock,
)


def job(
    job_id: str,
    *,
    idempotency_key: str | None = None,
    request_sha256: str = "a" * 64,
    request_identity: str | None = None,
    kind: HybridKnowledgeJobKind = "parse",
    ready_at: datetime | None = None,
) -> HybridKnowledgeJobRequest:
    return HybridKnowledgeJobRequest(
        job_id=job_id,
        idempotency_key=idempotency_key or f"idempotency_{job_id}",
        request_identity=request_identity or f"request_{job_id}",
        request_sha256=request_sha256,
        kind=kind,
        ready_at=ready_at,
    )


def test_in_memory_repository_claims_one_job_with_fencing_token() -> None:
    repo = InMemoryHybridKnowledgeRepository()
    repo.enqueue(job("job_1"))
    first = repo.claim_next(worker_id="worker_a", lease_seconds=30)
    second = repo.claim_next(worker_id="worker_b", lease_seconds=30)
    assert first is not None
    assert first.fencing_token == 1
    assert second is None


def test_expired_lease_is_reclaimed_with_next_fencing_token() -> None:
    clock = ManualHybridClock()
    repo = InMemoryHybridKnowledgeRepository(clock=clock)
    repo.enqueue(job("job_1"))
    first = repo.claim_next(worker_id="worker_a", lease_seconds=30)
    assert first is not None

    clock.advance(seconds=30)
    reclaimed = repo.claim_next(worker_id="worker_b", lease_seconds=30)

    assert reclaimed is not None
    assert reclaimed.fencing_token == 2
    assert reclaimed.worker_id == "worker_b"
    with pytest.raises(HybridKnowledgeLeaseError):
        repo.complete(
            job_id="job_1",
            worker_id="worker_a",
            fencing_token=first.fencing_token,
        )


def test_renewal_extends_from_injected_clock_and_preserves_token() -> None:
    clock = ManualHybridClock()
    repo = InMemoryHybridKnowledgeRepository(clock=clock)
    repo.enqueue(job("job_1"))
    claim = repo.claim_next(worker_id="worker_a", lease_seconds=10)
    assert claim is not None
    clock.advance(seconds=5)

    renewed = repo.renew(
        job_id="job_1",
        worker_id="worker_a",
        fencing_token=claim.fencing_token,
        lease_seconds=20,
    )

    assert renewed.fencing_token == claim.fencing_token
    assert renewed.lease_expires_at == clock.now().replace(second=25)
    clock.advance(seconds=19)
    assert repo.claim_next(worker_id="worker_b", lease_seconds=1) is None


@pytest.mark.parametrize(
    ("worker_id", "token"),
    [("worker_b", 1), ("worker_a", 2)],
)
def test_wrong_worker_or_stale_token_cannot_mutate_claim(worker_id: str, token: int) -> None:
    repo = InMemoryHybridKnowledgeRepository()
    repo.enqueue(job("job_1"))
    assert repo.claim_next(worker_id="worker_a", lease_seconds=30) is not None

    with pytest.raises(HybridKnowledgeLeaseError):
        repo.renew(
            job_id="job_1",
            worker_id=worker_id,
            fencing_token=token,
            lease_seconds=30,
        )
    with pytest.raises(HybridKnowledgeLeaseError):
        repo.complete(job_id="job_1", worker_id=worker_id, fencing_token=token)
    with pytest.raises(HybridKnowledgeLeaseError):
        repo.fail(
            job_id="job_1",
            worker_id=worker_id,
            fencing_token=token,
            failure_code="FAILED",
        )


@pytest.mark.parametrize("terminal", ["complete", "fail"])
def test_terminal_jobs_cannot_transition_or_be_reclaimed(terminal: str) -> None:
    repo = InMemoryHybridKnowledgeRepository()
    repo.enqueue(job("job_1"))
    claim = repo.claim_next(worker_id="worker_a", lease_seconds=30)
    assert claim is not None
    if terminal == "complete":
        finished = repo.complete(
            job_id="job_1", worker_id="worker_a", fencing_token=claim.fencing_token
        )
    else:
        finished = repo.fail(
            job_id="job_1",
            worker_id="worker_a",
            fencing_token=claim.fencing_token,
            failure_code="CONTENT_INVALID",
        )
    assert finished.state in {"COMPLETED", "FAILED"}
    assert repo.claim_next(worker_id="worker_b", lease_seconds=30) is None
    with pytest.raises(HybridKnowledgeLeaseError):
        repo.complete(job_id="job_1", worker_id="worker_a", fencing_token=claim.fencing_token)


def test_queue_orders_oldest_ready_jobs_deterministically() -> None:
    clock = ManualHybridClock()
    repo = InMemoryHybridKnowledgeRepository(clock=clock)
    repo.enqueue(job("job_1", ready_at=clock.now()))
    repo.enqueue(job("job_2", ready_at=clock.now()))
    repo.enqueue(job("job_3", ready_at=clock.now().replace(second=10)))

    first = repo.claim_next(worker_id="worker_a", lease_seconds=30)
    assert first is not None and first.job_id == "job_1"
    repo.complete(job_id=first.job_id, worker_id=first.worker_id, fencing_token=first.fencing_token)
    second = repo.claim_next(worker_id="worker_a", lease_seconds=30)
    assert second is not None and second.job_id == "job_2"
    assert [item.request.job_id for item in repo.list()] == ["job_1", "job_2", "job_3"]


def test_enqueue_is_idempotent_and_conflicts_fail_closed() -> None:
    repo = InMemoryHybridKnowledgeRepository()
    request = job("job_1", idempotency_key="stable")
    assert repo.enqueue(request) is repo.enqueue(request)
    assert len(repo.list()) == 1

    with pytest.raises(HybridKnowledgeIdempotencyConflict):
        repo.enqueue(
            job(
                "job_2",
                idempotency_key="stable",
                request_sha256="b" * 64,
            )
        )
    with pytest.raises(HybridKnowledgeIdempotencyConflict):
        repo.enqueue(job("job_1", idempotency_key="different"))


def test_request_identity_rejects_cross_job_digest_and_kind_conflicts() -> None:
    repo = InMemoryHybridKnowledgeRepository()
    repo.enqueue(job("job_1", idempotency_key="key_1", request_identity="immutable_request"))

    with pytest.raises(HybridKnowledgeIdempotencyConflict):
        repo.enqueue(
            job(
                "job_2",
                idempotency_key="key_2",
                request_identity="immutable_request",
                request_sha256="b" * 64,
            )
        )
    with pytest.raises(HybridKnowledgeIdempotencyConflict):
        repo.enqueue(
            job(
                "job_3",
                idempotency_key="key_3",
                request_identity="immutable_request",
                kind="embed",
            )
        )


def test_request_identity_allows_same_digest_and_kind_with_distinct_keys() -> None:
    repo = InMemoryHybridKnowledgeRepository()
    first = repo.enqueue(
        job("job_1", idempotency_key="key_1", request_identity="immutable_request")
    )
    second = repo.enqueue(
        job("job_2", idempotency_key="key_2", request_identity="immutable_request")
    )

    assert first.request.job_id == "job_1"
    assert second.request.job_id == "job_2"
    assert len(repo.list()) == 2


def test_job_contract_is_frozen_round_trips_and_rejects_coercion() -> None:
    request = job("job_1")
    assert HybridKnowledgeJobRequest.model_validate_json(request.model_dump_json()) == request
    with pytest.raises(ValidationError):
        request.job_id = "changed"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        HybridKnowledgeJobRequest.model_validate({**request.model_dump(), "request_sha256": 1})
    with pytest.raises(ValidationError):
        HybridKnowledgeJobRequest.model_validate(
            {**request.model_dump(), "ready_at": "2026-01-01T00:00:00Z"}
        )
    with pytest.raises(ValidationError):
        HybridKnowledgeJobRequest.model_validate({**request.model_dump(), "unknown": "field"})


def test_runtime_checkable_reference_adapter_conformance(tmp_path: Path) -> None:
    clock = ManualHybridClock()
    assert isinstance(clock, HybridClock)
    assert isinstance(InMemoryHybridKnowledgeRepository(clock=clock), HybridKnowledgeWorkScheduler)
    assert isinstance(FileSystemKnowledgeArtifactStore(tmp_path), KnowledgeArtifactStore)


def test_immutable_artifact_repeat_conflict_and_exact_read(tmp_path: Path) -> None:
    store = FileSystemKnowledgeArtifactStore(tmp_path)
    first = store.put_immutable(
        key="source/revision/original.pdf",
        content=b"pdf bytes",
        media_type="application/pdf",
    )
    repeated = store.put_immutable(
        key="source/revision/original.pdf",
        content=b"pdf bytes",
        media_type="application/pdf",
    )

    assert repeated == first
    assert first.artifact_uri.startswith("file:///")
    assert store.get_exact(first) == b"pdf bytes"
    with pytest.raises(ImmutableArtifactError):
        store.put_immutable(
            key="source/revision/original.pdf",
            content=b"other",
            media_type="application/pdf",
        )
    with pytest.raises(ImmutableArtifactError):
        store.put_immutable(
            key="source/revision/original.pdf",
            content=b"pdf bytes",
            media_type="text/plain",
        )


@pytest.mark.parametrize(
    "key",
    ["../escape", "/absolute", "a/../../escape", "a\\b", "a//b", "a/%2E%2E/b"],
)
def test_artifact_key_rejects_traversal(key: str, tmp_path: Path) -> None:
    store = FileSystemKnowledgeArtifactStore(tmp_path)
    with pytest.raises(ImmutableArtifactError):
        store.put_immutable(key=key, content=b"x", media_type="text/plain")


def test_artifact_store_rejects_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)
    store = FileSystemKnowledgeArtifactStore(root)

    with pytest.raises(ImmutableArtifactError):
        store.put_immutable(key="linked/escape.bin", content=b"x", media_type="text/plain")
    assert list(outside.iterdir()) == []


def test_artifact_put_rejects_parent_swapped_to_symlink_during_walk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "source").mkdir()
    store = FileSystemKnowledgeArtifactStore(root)
    swapped = False

    def swap_parent(*, key: str, component: str, parent_fd: int) -> None:
        nonlocal swapped
        del key, parent_fd
        if component == "source" and not swapped:
            (root / "source").rename(root / "detached")
            (root / "source").symlink_to(outside, target_is_directory=True)
            swapped = True

    monkeypatch.setattr(store, "_before_open_parent_component", swap_parent)

    with pytest.raises(ImmutableArtifactError):
        store.put_immutable(key="source/artifact.bin", content=b"inside", media_type="text/plain")
    assert list(outside.iterdir()) == []


def test_artifact_get_uses_verified_parent_fd_after_path_is_swapped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    store = FileSystemKnowledgeArtifactStore(root)
    ref = store.put_immutable(key="source/artifact.bin", content=b"inside", media_type="text/plain")
    (outside / "artifact.bin").write_bytes(b"outside")
    swapped = False

    def swap_after_open(*, key: str, parent_fd: int) -> None:
        nonlocal swapped
        del parent_fd
        if key == "source/artifact.bin" and not swapped:
            (root / "source").rename(root / "detached")
            (root / "source").symlink_to(outside, target_is_directory=True)
            swapped = True

    monkeypatch.setattr(store, "_after_open_parent", swap_after_open)

    assert store.get_exact(ref) == b"inside"
    assert (outside / "artifact.bin").read_bytes() == b"outside"


def test_artifact_put_rejects_final_symlink(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside.bin"
    root.mkdir()
    outside.write_bytes(b"outside")
    (root / "artifact.bin").symlink_to(outside)
    store = FileSystemKnowledgeArtifactStore(root)

    with pytest.raises(ImmutableArtifactError):
        store.put_immutable(key="artifact.bin", content=b"inside", media_type="text/plain")
    assert outside.read_bytes() == b"outside"


def test_artifact_read_rejects_tamper_digest_length_and_version(tmp_path: Path) -> None:
    store = FileSystemKnowledgeArtifactStore(tmp_path)
    ref = store.put_immutable(key="artifact.bin", content=b"original", media_type="text/plain")
    artifact_path = Path(ref.artifact_uri.removeprefix("file://"))
    artifact_path.write_bytes(b"tampered")
    with pytest.raises(ImmutableArtifactError):
        store.get_exact(ref)

    artifact_path.write_bytes(b"original")
    with pytest.raises(ImmutableArtifactError):
        store.get_exact(ref.model_copy(update={"version_id": "other"}))
    with pytest.raises(ImmutableArtifactError):
        store.get_exact(ref.model_copy(update={"size_bytes": ref.size_bytes + 1}))
    with pytest.raises(ImmutableArtifactError):
        store.get_exact(ref.model_copy(update={"sha256": "f" * 64}))
