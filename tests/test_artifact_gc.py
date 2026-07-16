from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

from proof_agent.capabilities.artifacts.filesystem import FilesystemArtifactStore
from proof_agent.contracts.artifacts import ArtifactKind, ArtifactOwner, ArtifactPutRequest
from proof_agent.observability.artifact_gc import ArtifactGarbageCollector


NOW = datetime(2026, 7, 15, tzinfo=UTC)


class References:
    def __init__(self) -> None:
        self.referenced: set[tuple[str, str, str]] = set()
        self.race_to_reference: set[tuple[str, str, str]] = set()

    @staticmethod
    def identity(ref):
        return ref.bucket, ref.object_key, ref.version_id

    def contains_exact(self, ref):
        return self.identity(ref) in self.referenced

    def delete_if_unreferenced(self, ref, *, deleter):
        identity = self.identity(ref)
        if identity in self.race_to_reference:
            self.referenced.add(identity)
        if identity in self.referenced:
            return False
        deleter()
        return True


def put(store: FilesystemArtifactStore, content: bytes):
    import hashlib

    return store.put_immutable(
        ArtifactPutRequest(
            kind=ArtifactKind.HTML_REPORT,
            owner=ArtifactOwner(owner_type="evaluation", owner_id=content.decode()),
            content_type="text/html",
            expected_sha256=hashlib.sha256(content).hexdigest(),
            expected_size_bytes=len(content),
        ),
        BytesIO(content),
    )


def test_gc_preserves_grace_references_and_reference_races(tmp_path: Path) -> None:
    clock_value = NOW - timedelta(days=2)
    store = FilesystemArtifactStore(tmp_path, clock=lambda: clock_value)
    orphan = put(store, b"orphan")
    referenced = put(store, b"referenced")
    raced = put(store, b"raced")
    refs = References()
    refs.referenced.add(refs.identity(referenced))
    refs.race_to_reference.add(refs.identity(raced))
    collector = ArtifactGarbageCollector(store=store, repository=refs)  # type: ignore[arg-type]

    report = collector.collect(now=NOW, dry_run=False)

    assert report.deleted == 1
    assert report.referenced == 2
    assert report.failed == 0
    assert report.release_healthy is True
    store.head_exact(referenced)
    store.head_exact(raced)
    remaining = {
        item.object_key
        for item in store.iter_versions_before(prefix="objects/", before=NOW)
    }
    assert orphan.object_key not in remaining


def test_gc_does_not_scan_younger_than_24_hours_and_flags_seven_day_backlog(
    tmp_path: Path,
) -> None:
    recent_store = FilesystemArtifactStore(tmp_path / "recent", clock=lambda: NOW - timedelta(hours=23))
    put(recent_store, b"recent")
    recent_report = ArtifactGarbageCollector(
        store=recent_store,
        repository=References(),  # type: ignore[arg-type]
    ).collect(now=NOW, dry_run=True)
    assert recent_report.scanned == 0

    old_store = FilesystemArtifactStore(tmp_path / "old", clock=lambda: NOW - timedelta(days=8))
    put(old_store, b"old")
    old_report = ArtifactGarbageCollector(
        store=old_store,
        repository=References(),  # type: ignore[arg-type]
    ).collect(now=NOW, dry_run=True)
    assert old_report.release_healthy is False
    assert old_report.oldest_orphan_age_seconds == 8 * 24 * 60 * 60
