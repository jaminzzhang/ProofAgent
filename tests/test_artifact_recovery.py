from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine

from proof_agent.capabilities.artifacts.filesystem import FilesystemArtifactStore
from proof_agent.capabilities.persistence.postgres.artifact_repository import (
    PostgresArtifactReferenceRepository,
)
from proof_agent.control.artifacts.finalization import (
    ArtifactBundleFinalizer,
    ArtifactMemberPayload,
)
from proof_agent.contracts.artifacts import ArtifactKind, ArtifactOwner
from proof_agent.observability.recovery import ArtifactRecoveryVerifier


pytestmark = pytest.mark.postgres_integration
pytest_plugins = ("postgres_fixtures",)
NOW = datetime(2026, 7, 15, tzinfo=UTC)


def finalized(postgres_engine: Engine, tmp_path: Path):
    store = FilesystemArtifactStore(tmp_path, clock=lambda: NOW)
    repository = PostgresArtifactReferenceRepository(postgres_engine)
    result = ArtifactBundleFinalizer(
        store=store,
        repository=repository,
        clock=lambda: NOW,
    ).finalize(
        owner=ArtifactOwner(owner_type="run_attempt", owner_id="attempt-restore"),
        manifest_id="019ba001-1111-7000-8000-000000000831",
        members=(
            ArtifactMemberPayload(
                member_id="receipt",
                kind=ArtifactKind.GOVERNANCE_RECEIPT,
                content_type="text/markdown",
                content=b"# verified receipt",
            ),
        ),
    )
    return store, repository, result


def test_recovery_verifies_every_exact_postgres_s3_reference(
    postgres_engine: Engine,
    tmp_path: Path,
) -> None:
    store, repository, _result = finalized(postgres_engine, tmp_path)

    report = ArtifactRecoveryVerifier(store=store, repository=repository).verify(now=NOW)

    assert report.valid is True
    assert report.owner_count == 1
    assert report.reference_count == 2
    assert report.verified_reference_count == 2


def test_recovery_quarantines_corrupt_member_without_selecting_another_version(
    postgres_engine: Engine,
    tmp_path: Path,
) -> None:
    store, repository, result = finalized(postgres_engine, tmp_path)
    member = result.manifest.members[0].artifact
    path = tmp_path / member.object_key
    path.chmod(0o600)
    path.write_bytes(b"# corrupt receipt!")

    report = ArtifactRecoveryVerifier(store=store, repository=repository).verify(now=NOW)

    assert report.valid is False
    assert report.verified_reference_count == 1
    assert report.corrupt_owner_ids == ("run_attempt:attempt-restore",)
    assert repository.get_visible_binding(result.binding.owner, now=NOW) is None
