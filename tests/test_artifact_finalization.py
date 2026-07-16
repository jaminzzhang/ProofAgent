from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from proof_agent.capabilities.artifacts.filesystem import FilesystemArtifactStore
from proof_agent.control.artifacts.finalization import (
    ArtifactBundleFinalizer,
    ArtifactMemberPayload,
)
from proof_agent.contracts.artifacts import ArtifactKind, ArtifactOwner


NOW = datetime(2026, 7, 15, tzinfo=UTC)


class Repository:
    def __init__(self) -> None:
        self.binding = None
        self.manifest = None
        self.commits = 0
        self.fail = False

    def commit_visible_manifest(self, manifest, *, manifest_ref):
        self.commits += 1
        if self.fail:
            raise RuntimeError("postgres unavailable")
        from proof_agent.contracts.artifacts import ArtifactOwnerBinding, ArtifactVisibility

        self.manifest = manifest
        self.binding = ArtifactOwnerBinding(
            owner=manifest.owner,
            manifest=manifest_ref,
            visibility=ArtifactVisibility.VISIBLE,
            visible_at=manifest.created_at,
            result_available=True,
        )
        return self.binding

    def get_visible_binding(self, owner, *, now):
        del now
        return self.binding if self.binding is not None and self.binding.owner == owner else None

    def get_manifest(self, manifest_id):
        if self.manifest is not None and self.manifest.manifest_id == manifest_id:
            return self.manifest
        return None


def payloads() -> tuple[ArtifactMemberPayload, ...]:
    return (
        ArtifactMemberPayload(
            member_id="trace",
            kind=ArtifactKind.RUN_TRACE,
            content_type="application/json",
            content=b'{"event":"complete"}',
            display_filename="trace.json",
        ),
        ArtifactMemberPayload(
            member_id="receipt",
            kind=ArtifactKind.GOVERNANCE_RECEIPT,
            content_type="text/markdown",
            content=b"# Receipt",
            display_filename="receipt.md",
        ),
    )


def test_finalization_uploads_verified_members_then_manifest_then_visibility(
    tmp_path: Path,
) -> None:
    store = FilesystemArtifactStore(tmp_path, clock=lambda: NOW)
    repository = Repository()
    finalizer = ArtifactBundleFinalizer(store=store, repository=repository, clock=lambda: NOW)

    result = finalizer.finalize(
        owner=ArtifactOwner(owner_type="run_attempt", owner_id="attempt-1"),
        manifest_id="019ba001-1111-7000-8000-000000000821",
        members=payloads(),
    )

    assert repository.commits == 1
    assert result.binding.result_available is True
    assert result.binding.manifest.kind is ArtifactKind.ARTIFACT_MANIFEST
    assert [member.member_id for member in result.manifest.members] == ["receipt", "trace"]
    assert store.head_exact(result.binding.manifest) == result.binding.manifest
    for member in result.manifest.members:
        assert store.head_exact(member.artifact) == member.artifact


def test_postgres_failure_leaves_only_invisible_verified_orphans(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path, clock=lambda: NOW)
    repository = Repository()
    repository.fail = True
    finalizer = ArtifactBundleFinalizer(store=store, repository=repository, clock=lambda: NOW)

    with pytest.raises(RuntimeError, match="postgres"):
        finalizer.finalize(
            owner=ArtifactOwner(owner_type="run_attempt", owner_id="attempt-1"),
            manifest_id="019ba001-1111-7000-8000-000000000821",
            members=payloads(),
        )

    refs = list(store.iter_versions_before(prefix="objects/", before=NOW.replace(year=2027)))
    assert len(refs) == 3
    assert repository.binding is None


def test_completed_finalization_is_idempotent_without_new_uploads(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path, clock=lambda: NOW)
    repository = Repository()
    finalizer = ArtifactBundleFinalizer(store=store, repository=repository, clock=lambda: NOW)
    owner = ArtifactOwner(owner_type="run_attempt", owner_id="attempt-1")
    first = finalizer.finalize(
        owner=owner,
        manifest_id="019ba001-1111-7000-8000-000000000821",
        members=payloads(),
    )

    second = finalizer.finalize(
        owner=owner,
        manifest_id="019ba001-1111-7000-8000-000000000821",
        members=payloads(),
    )

    assert first == second
    assert repository.commits == 1
    assert len(list(store.iter_versions_before(prefix="objects/", before=NOW.replace(year=2027)))) == 3


def test_cancellation_before_visibility_never_commits(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path, clock=lambda: NOW)
    repository = Repository()
    calls = 0

    def cancellation() -> None:
        nonlocal calls
        calls += 1
        if calls == 4:
            raise RuntimeError("cancelled")

    finalizer = ArtifactBundleFinalizer(
        store=store,
        repository=repository,
        clock=lambda: NOW,
        cancellation_check=cancellation,
    )

    with pytest.raises(RuntimeError, match="cancelled"):
        finalizer.finalize(
            owner=ArtifactOwner(owner_type="run_attempt", owner_id="attempt-1"),
            manifest_id="019ba001-1111-7000-8000-000000000821",
            members=payloads(),
        )

    assert repository.commits == 0


def test_prepare_verifies_manifest_last_without_making_it_visible(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path, clock=lambda: NOW)
    repository = Repository()
    finalizer = ArtifactBundleFinalizer(store=store, repository=repository, clock=lambda: NOW)

    prepared = finalizer.prepare(
        owner=ArtifactOwner(owner_type="run_attempt", owner_id="attempt-1"),
        manifest_id="019ba001-1111-7000-8000-000000000821",
        members=payloads(),
    )

    assert repository.commits == 0
    assert prepared.manifest_ref.kind is ArtifactKind.ARTIFACT_MANIFEST
    assert store.head_exact(prepared.manifest_ref) == prepared.manifest_ref
    published = finalizer.publish(prepared)
    assert published.binding.result_available is True
    assert repository.commits == 1
