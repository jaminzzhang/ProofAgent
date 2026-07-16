from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest

from proof_agent.capabilities.artifacts.filesystem import FilesystemArtifactStore
from proof_agent.capabilities.artifacts.materialization import (
    MaterializationError,
    VerifiedArtifactMaterializer,
)
from proof_agent.contracts.artifacts import ArtifactKind, ArtifactOwner, ArtifactPutRequest


NOW = datetime(2026, 7, 15, tzinfo=UTC)


class CountingStore:
    def __init__(self, delegate: FilesystemArtifactStore) -> None:
        self.delegate = delegate
        self.opens = 0

    def open_exact(self, ref):
        self.opens += 1
        return self.delegate.open_exact(ref)

    def head_exact(self, ref):
        return self.delegate.head_exact(ref)


def artifact(tmp_path: Path, content: bytes = b"verified artifact"):
    import hashlib

    store = FilesystemArtifactStore(tmp_path / "authority", clock=lambda: NOW)
    ref = store.put_immutable(
        ArtifactPutRequest(
            kind=ArtifactKind.KNOWLEDGE_INDEX_MEMBER,
            owner=ArtifactOwner(owner_type="knowledge_snapshot", owner_id="snapshot-1"),
            content_type="application/octet-stream",
            expected_sha256=hashlib.sha256(content).hexdigest(),
            expected_size_bytes=len(content),
        ),
        BytesIO(content),
    )
    return store, ref


def test_materializer_cold_read_cache_hit_and_cache_loss(tmp_path: Path) -> None:
    store, ref = artifact(tmp_path)
    counting = CountingStore(store)
    materializer = VerifiedArtifactMaterializer(counting, cache_root=tmp_path / "cache")

    first = materializer.materialize(ref)
    second = materializer.materialize(ref)
    first.unlink()
    third = materializer.materialize(ref)

    assert second == first == third
    assert third.read_bytes() == b"verified artifact"
    assert counting.opens == 2
    assert third.stat().st_mode & 0o222 == 0


def test_materializer_serializes_concurrent_same_digest_downloads(tmp_path: Path) -> None:
    store, ref = artifact(tmp_path)
    counting = CountingStore(store)
    materializer = VerifiedArtifactMaterializer(counting, cache_root=tmp_path / "cache")

    with ThreadPoolExecutor(max_workers=8) as executor:
        paths = tuple(executor.map(lambda _item: materializer.materialize(ref), range(32)))

    assert len(set(paths)) == 1
    assert counting.opens == 1


def test_corrupt_cache_is_replaced_only_from_verified_authority(tmp_path: Path) -> None:
    store, ref = artifact(tmp_path)
    materializer = VerifiedArtifactMaterializer(store, cache_root=tmp_path / "cache")
    path = materializer.materialize(ref)
    path.chmod(0o600)
    path.write_bytes(b"corrupt local")

    repaired = materializer.materialize(ref)

    assert repaired.read_bytes() == b"verified artifact"


def test_interrupted_or_corrupt_download_never_becomes_visible(tmp_path: Path) -> None:
    _store, ref = artifact(tmp_path)

    class BrokenStore:
        def open_exact(self, _ref):
            class BrokenBody(BytesIO):
                def read(self, size: int = -1) -> bytes:
                    value = super().read(size)
                    if self.tell() > 4:
                        raise OSError("connection interrupted")
                    return value

            return BrokenBody(b"verified artifact")

        def head_exact(self, exact_ref):
            return exact_ref

    cache = tmp_path / "cache"
    materializer = VerifiedArtifactMaterializer(BrokenStore(), cache_root=cache)

    with pytest.raises(MaterializationError, match="download"):
        materializer.materialize(ref)

    assert not (cache / "sha256" / ref.sha256).exists()
    assert list((cache / ".tmp").glob("*")) == []
