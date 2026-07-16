from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from proof_agent.contracts.artifacts import (
    ArtifactKind,
    ArtifactManifest,
    ArtifactManifestMember,
    ArtifactObjectVersion,
    ArtifactOwner,
    ArtifactPutRequest,
)


def owner() -> ArtifactOwner:
    return ArtifactOwner(owner_type="run_attempt", owner_id="attempt-1")


def object_ref(**updates: object) -> ArtifactObjectVersion:
    values: dict[str, object] = {
        "object_id": "019ba001-1111-7000-8000-000000000801",
        "bucket": "proof-agent",
        "object_key": "objects/ab/019ba001-1111-7000-8000-000000000802",
        "version_id": "opaque-version-1",
        "sha256": "a" * 64,
        "size_bytes": 5,
        "kind": ArtifactKind.RUN_TRACE,
        "owner": owner(),
        "content_type": "application/json",
        "created_at": datetime(2026, 7, 15, tzinfo=UTC),
    }
    values.update(updates)
    return ArtifactObjectVersion.model_validate(values)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sha256", "not-a-digest"),
        ("size_bytes", -1),
        ("version_id", ""),
        ("object_key", "objects/../../secret"),
        ("created_at", datetime(2026, 7, 15)),
    ],
)
def test_exact_artifact_reference_rejects_invalid_authority_fields(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        object_ref(**{field: value})


@pytest.mark.parametrize("filename", ("../policy.pdf", "a/b.pdf", "a\\b.pdf", "\n.pdf"))
def test_artifact_put_request_rejects_path_bearing_display_filename(filename: str) -> None:
    with pytest.raises(ValidationError):
        ArtifactPutRequest(
            kind=ArtifactKind.KNOWLEDGE_SOURCE,
            owner=owner(),
            content_type="application/pdf",
            expected_sha256="a" * 64,
            expected_size_bytes=5,
            display_filename=filename,
        )

def test_manifest_rejects_duplicate_exact_members() -> None:
    ref = object_ref()
    member = ArtifactManifestMember(member_id="trace", artifact=ref)

    with pytest.raises(ValidationError, match="duplicate"):
        ArtifactManifest(
            manifest_id="019ba001-1111-7000-8000-000000000803",
            owner=owner(),
            members=(member, member.model_copy(update={"member_id": "trace-copy"})),
            created_at=datetime(2026, 7, 15, tzinfo=UTC),
        )


def test_manifest_rejects_cross_owner_member() -> None:
    with pytest.raises(ValidationError, match="owner"):
        ArtifactManifest(
            manifest_id="019ba001-1111-7000-8000-000000000803",
            owner=owner(),
            members=(
                ArtifactManifestMember(
                    member_id="trace",
                    artifact=object_ref(
                        owner=ArtifactOwner(owner_type="run_attempt", owner_id="attempt-2")
                    ),
                ),
            ),
            created_at=datetime(2026, 7, 15, tzinfo=UTC),
        )
