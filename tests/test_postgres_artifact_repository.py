from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, inspect, text

from proof_agent.capabilities.persistence.postgres.artifact_repository import (
    PostgresArtifactReferenceRepository,
)
from proof_agent.contracts import PersistenceConflictError
from proof_agent.contracts.artifacts import (
    ArtifactKind,
    ArtifactManifest,
    ArtifactManifestMember,
    ArtifactObjectVersion,
    ArtifactOwner,
    ArtifactVisibility,
)


pytestmark = pytest.mark.postgres_integration
pytest_plugins = ("postgres_fixtures",)
NOW = datetime(2026, 7, 15, tzinfo=UTC)


def owner(owner_id: str = "attempt-1") -> ArtifactOwner:
    return ArtifactOwner(owner_type="run_attempt", owner_id=owner_id)


def ref(
    *,
    object_id: str,
    suffix: str,
    kind: ArtifactKind,
    owner_value: ArtifactOwner | None = None,
    expires_at: datetime | None = None,
) -> ArtifactObjectVersion:
    return ArtifactObjectVersion(
        object_id=object_id,
        bucket="proof-agent",
        object_key=f"objects/{suffix}0/{object_id}",
        version_id=f"version-{suffix}",
        sha256=suffix * 64,
        size_bytes=10,
        kind=kind,
        owner=owner_value or owner(),
        content_type="application/json",
        created_at=NOW,
        expires_at=expires_at,
    )


MEMBER = ref(
    object_id="019ba001-1111-7000-8000-000000000811",
    suffix="a",
    kind=ArtifactKind.RUN_TRACE,
)
MANIFEST_REF = ref(
    object_id="019ba001-1111-7000-8000-000000000812",
    suffix="b",
    kind=ArtifactKind.ARTIFACT_MANIFEST,
)
MANIFEST = ArtifactManifest(
    manifest_id="019ba001-1111-7000-8000-000000000813",
    owner=owner(),
    members=(ArtifactManifestMember(member_id="trace", artifact=MEMBER),),
    created_at=NOW,
)


def test_postgres_artifact_visibility_commit_is_atomic_and_idempotent(
    postgres_engine: Engine,
) -> None:
    repository = PostgresArtifactReferenceRepository(postgres_engine)

    first = repository.commit_visible_manifest(MANIFEST, manifest_ref=MANIFEST_REF)
    second = repository.commit_visible_manifest(MANIFEST, manifest_ref=MANIFEST_REF)

    assert first == second
    assert first.visibility is ArtifactVisibility.VISIBLE
    assert first.result_available is True
    assert repository.get_visible_binding(owner(), now=NOW) == first
    assert repository.get_manifest(MANIFEST.manifest_id) == MANIFEST
    with postgres_engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM artifact_objects")).scalar_one() == 2
        assert (
            connection.execute(text("SELECT count(*) FROM artifact_owner_bindings")).scalar_one()
            == 1
        )


def test_postgres_artifact_owner_cannot_be_rebound_to_another_manifest(
    postgres_engine: Engine,
) -> None:
    repository = PostgresArtifactReferenceRepository(postgres_engine)
    repository.commit_visible_manifest(MANIFEST, manifest_ref=MANIFEST_REF)
    different_ref = ref(
        object_id="019ba001-1111-7000-8000-000000000814",
        suffix="c",
        kind=ArtifactKind.ARTIFACT_MANIFEST,
    )
    different = MANIFEST.model_copy(
        update={"manifest_id": "019ba001-1111-7000-8000-000000000815"}
    )

    with pytest.raises(PersistenceConflictError):
        repository.commit_visible_manifest(different, manifest_ref=different_ref)

    assert repository.get_visible_binding(owner(), now=NOW) is not None


def test_corruption_or_logical_expiry_removes_ordinary_visibility(
    postgres_engine: Engine,
) -> None:
    repository = PostgresArtifactReferenceRepository(postgres_engine)
    repository.commit_visible_manifest(MANIFEST, manifest_ref=MANIFEST_REF)

    assert repository.mark_corrupt(MEMBER) == 1
    assert repository.get_visible_binding(owner(), now=NOW) is None

    expiring_owner = owner("attempt-expiring")
    expiring_member = ref(
        object_id="019ba001-1111-7000-8000-000000000816",
        suffix="d",
        kind=ArtifactKind.VALIDATION_CAPTURE,
        owner_value=expiring_owner,
        expires_at=NOW + timedelta(days=7),
    )
    expiring_manifest_ref = ref(
        object_id="019ba001-1111-7000-8000-000000000817",
        suffix="e",
        kind=ArtifactKind.ARTIFACT_MANIFEST,
        owner_value=expiring_owner,
    )
    expiring_manifest = ArtifactManifest(
        manifest_id="019ba001-1111-7000-8000-000000000818",
        owner=expiring_owner,
        members=(ArtifactManifestMember(member_id="capture", artifact=expiring_member),),
        created_at=NOW,
    )
    repository.commit_visible_manifest(
        expiring_manifest,
        manifest_ref=expiring_manifest_ref,
    )

    assert repository.expire_due(now=NOW + timedelta(days=8)) == 1
    assert repository.get_visible_binding(expiring_owner, now=NOW + timedelta(days=8)) is None


def test_artifact_schema_stores_references_but_no_payload_blob(postgres_engine: Engine) -> None:
    columns = {
        column["name"] for column in inspect(postgres_engine).get_columns("artifact_objects")
    }

    assert {"bucket", "object_key", "version_id", "sha256", "size_bytes"} <= columns
    assert not {"body", "payload", "content", "bytes"}.intersection(columns)
