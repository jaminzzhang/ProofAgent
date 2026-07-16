from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest

from proof_agent.capabilities.artifacts import ArtifactStoreError
from proof_agent.capabilities.artifacts.filesystem import FilesystemArtifactStore
from proof_agent.contracts.artifacts import ArtifactKind, ArtifactOwner, ArtifactPutRequest


NOW = datetime(2026, 7, 15, tzinfo=UTC)


def request(content: bytes = b"trace") -> ArtifactPutRequest:
    import hashlib

    return ArtifactPutRequest(
        kind=ArtifactKind.RUN_TRACE,
        owner=ArtifactOwner(owner_type="run_attempt", owner_id="attempt-1"),
        content_type="application/json",
        expected_sha256=hashlib.sha256(content).hexdigest(),
        expected_size_bytes=len(content),
        display_filename="trace.json",
    )


def test_filesystem_store_puts_and_reads_one_verified_exact_version(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path, clock=lambda: NOW)

    ref = store.put_immutable(request(), BytesIO(b"trace"))

    assert ref.bucket == "local-artifacts"
    assert ref.object_key.startswith("objects/")
    assert store.head_exact(ref) == ref
    with store.open_exact(ref) as body:
        assert body.read() == b"trace"
    assert list(
        store.iter_versions_before(prefix="objects/", before=NOW + timedelta(seconds=1))
    ) == [ref]


@pytest.mark.parametrize("content", (b"trac", b"trace-longer", b"other"))
def test_filesystem_store_rejects_short_long_or_wrong_digest_content(
    tmp_path: Path,
    content: bytes,
) -> None:
    store = FilesystemArtifactStore(tmp_path, clock=lambda: NOW)

    with pytest.raises(ArtifactStoreError, match="length|digest"):
        store.put_immutable(request(), BytesIO(content))

    assert list(store.iter_versions_before(prefix="objects/", before=NOW)) == []


def test_filesystem_store_detects_corruption_and_deletes_only_exact_version(
    tmp_path: Path,
) -> None:
    store = FilesystemArtifactStore(tmp_path, clock=lambda: NOW)
    ref = store.put_immutable(request(), BytesIO(b"trace"))
    path = tmp_path / ref.object_key
    path.chmod(0o600)
    path.write_bytes(b"bad!!")

    with pytest.raises(ArtifactStoreError, match="digest"):
        store.open_exact(ref)

    store.delete_exact(ref)
    with pytest.raises(ArtifactStoreError, match="unavailable"):
        store.head_exact(ref)
