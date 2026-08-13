from __future__ import annotations

from datetime import UTC, datetime
import hashlib

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine, text

from proof_agent.capabilities.persistence.postgres.release_registry_repository import (
    PostgresReleaseRegistryRepository,
)
from proof_agent.contracts.artifacts import ArtifactKind, ArtifactObjectVersion, ArtifactOwner
from proof_agent.contracts.release_registry import (
    ReleaseBundleIndex,
    ReleaseBundleIndexMember,
    ReleaseBundleMemberRole,
    ReleaseFinalization,
    ReleaseLifecycleState,
    ReleaseRegistryRecord,
    ReleaseTrustIdentity,
    finalize_release_record,
)
from proof_agent.contracts.ports.release_registry import ReleaseRegistryConflictError


pytest_plugins = ("postgres_fixtures",)


NOW = datetime(2026, 7, 25, 8, 30, tzinfo=UTC)
RELEASE_ID = "proofagent-2026.07.25-rc1"
CANDIDATE_SHA256 = "a" * 64


def _ref(
    *,
    object_id: str,
    body: bytes,
    kind: ArtifactKind,
    name: str,
    owner_id: str = RELEASE_ID,
) -> ArtifactObjectVersion:
    return ArtifactObjectVersion(
        object_id=object_id,
        bucket="proof-agent-releases",
        object_key=f"objects/{object_id[:2]}/{object_id}",
        version_id=f"version-{object_id}",
        sha256=hashlib.sha256(body).hexdigest(),
        size_bytes=len(body),
        kind=kind,
        owner=ArtifactOwner(owner_type="release", owner_id=owner_id),
        content_type="application/json",
        created_at=NOW,
        display_filename=name,
    )


MANIFEST = _ref(
    object_id="019ba001-1111-7000-8000-000000000901",
    body=b"manifest",
    kind=ArtifactKind.RELEASE_MANIFEST,
    name="release-gate-manifest.json",
)
REPORT = _ref(
    object_id="019ba001-1111-7000-8000-000000000902",
    body=b"report",
    kind=ArtifactKind.HTML_REPORT,
    name="release-readiness-report.html",
)
ATTESTATION = _ref(
    object_id="019ba001-1111-7000-8000-000000000903",
    body=b"attestation",
    kind=ArtifactKind.RELEASE_ATTESTATION,
    name="release-bundle-index.json.attestation",
)
INDEX_REF = _ref(
    object_id="019ba001-1111-7000-8000-000000000904",
    body=b"index",
    kind=ArtifactKind.BUNDLE_INDEX,
    name="release-bundle-index.json",
)
TRUST = ReleaseTrustIdentity(
    protocol_id="dsse-v1",
    issuer="https://issuer.example.test",
    subject="proofagent-release-builder",
    key_id="release-key-2026-07",
)


def _preparing() -> ReleaseRegistryRecord:
    return ReleaseRegistryRecord(
        schema_version="proofagent.release-registry.v1",
        release_id=RELEASE_ID,
        state=ReleaseLifecycleState.PREPARING,
        candidate_binding_sha256=CANDIDATE_SHA256,
        release_manifest=MANIFEST,
        created_at=NOW,
        created_by="release-controller",
    )


def _finalization(**updates: object) -> ReleaseFinalization:
    values: dict[str, object] = {
        "candidate_binding_sha256": CANDIDATE_SHA256,
        "release_manifest": MANIFEST,
        "bundle_index": INDEX_REF,
        "detached_attestation": ATTESTATION,
        "trust_identity": TRUST,
        "finalized_at": NOW,
    }
    values.update(updates)
    return ReleaseFinalization(**values)


def test_release_registry_allows_only_one_exact_preparing_to_finalized_transition() -> None:
    finalized = finalize_release_record(_preparing(), _finalization())

    assert finalized.state is ReleaseLifecycleState.FINALIZED
    assert finalized.finalization == _finalization()

    with pytest.raises(ValueError, match="PREPARING"):
        finalize_release_record(finalized, _finalization())


@pytest.mark.parametrize(
    "finalization",
    [
        _finalization(candidate_binding_sha256="b" * 64),
        _finalization(
            release_manifest=MANIFEST.model_copy(update={"sha256": "c" * 64})
        ),
        _finalization(
            bundle_index=INDEX_REF.model_copy(
                update={"owner": ArtifactOwner(owner_type="release", owner_id="wrong-release")}
            )
        ),
        _finalization(
            detached_attestation=ATTESTATION.model_copy(
                update={"kind": ArtifactKind.HTML_REPORT}
            )
        ),
    ],
)
def test_release_finalization_rejects_wrong_candidate_index_or_attestation(
    finalization: ReleaseFinalization,
) -> None:
    with pytest.raises(ValueError):
        finalize_release_record(_preparing(), finalization)


def test_release_registry_record_rejects_finalized_state_without_finalization() -> None:
    with pytest.raises(ValidationError, match="finalization"):
        _preparing().model_copy(
            update={"state": ReleaseLifecycleState.FINALIZED},
        ).__class__.model_validate(
            {
                **_preparing().model_dump(mode="json"),
                "state": "FINALIZED",
            }
        )


def test_bundle_index_authorizes_only_named_non_bootstrap_members() -> None:
    index = ReleaseBundleIndex(
        schema_version="proofagent.release-bundle-index.v1",
        release_id=RELEASE_ID,
        candidate_binding_sha256=CANDIDATE_SHA256,
        release_manifest_sha256=MANIFEST.sha256,
        members=(
            ReleaseBundleIndexMember(
                artifact_name="release-gate-manifest.json",
                role=ReleaseBundleMemberRole.RELEASE_MANIFEST,
                artifact=MANIFEST,
            ),
            ReleaseBundleIndexMember(
                artifact_name="release-readiness-report.html",
                role=ReleaseBundleMemberRole.READINESS_REPORT,
                artifact=REPORT,
            ),
        ),
        created_at=NOW,
    )

    assert index.member("release-readiness-report.html").artifact == REPORT
    assert index.member("not-indexed.json") is None

    with pytest.raises(ValidationError):
        ReleaseBundleIndex(
            **{
                **index.model_dump(),
                "members": (*index.members, index.members[1]),
            }
        )
    with pytest.raises(ValidationError):
        ReleaseBundleIndex(
            **{
                **index.model_dump(),
                "members": (
                    *index.members,
                    ReleaseBundleIndexMember(
                        artifact_name="release-bundle-index.json",
                        role=ReleaseBundleMemberRole.EVIDENCE,
                        artifact=INDEX_REF,
                    ),
                ),
            }
        )


def test_bundle_index_accepts_exact_product_release_evidence() -> None:
    evidence = _ref(
        object_id="019ba001-1111-7000-8000-000000000905",
        body=b"release evidence",
        kind=ArtifactKind.RELEASE_EVIDENCE,
        name="candidate-integrity-quality.json",
    )

    member = ReleaseBundleIndexMember(
        artifact_name="candidate-integrity-quality.json",
        role=ReleaseBundleMemberRole.EVIDENCE,
        artifact=evidence,
    )

    assert member.artifact == evidence


def test_bundle_index_accepts_detached_product_evidence_attestation() -> None:
    attestation = _ref(
        object_id="019ba001-1111-7000-8000-000000000906",
        body=b"release evidence attestation",
        kind=ArtifactKind.RELEASE_ATTESTATION,
        name="candidate-integrity-quality.attestation.json",
    )

    member = ReleaseBundleIndexMember(
        artifact_name="candidate-integrity-quality.attestation.json",
        role=ReleaseBundleMemberRole.EVIDENCE,
        artifact=attestation,
    )

    assert member.artifact == attestation


def test_release_registry_contract_rejects_path_like_artifact_names() -> None:
    with pytest.raises(ValidationError):
        ReleaseBundleIndexMember(
            artifact_name="../release-gate-manifest.json",
            role=ReleaseBundleMemberRole.RELEASE_MANIFEST,
            artifact=MANIFEST,
        )


@pytest.mark.postgres_integration
def test_postgres_release_registry_finalization_is_conditional_and_exact(
    postgres_engine: Engine,
) -> None:
    repository = PostgresReleaseRegistryRepository(postgres_engine)

    assert repository.create_preparing(_preparing()) == _preparing()
    finalized = repository.finalize(RELEASE_ID, _finalization())

    assert repository.get(RELEASE_ID) == finalized
    assert repository.list() == (finalized,)
    assert repository.resolve_exact_visible(INDEX_REF, now=NOW) == INDEX_REF
    with pytest.raises(ReleaseRegistryConflictError):
        repository.finalize(RELEASE_ID, _finalization())
    with postgres_engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT state, candidate_binding_sha256, bundle_index_object_id, "
                "detached_attestation_object_id FROM release_registry WHERE release_id=:id"
            ),
            {"id": RELEASE_ID},
        ).mappings().one()
    assert row["state"] == "FINALIZED"
    assert row["candidate_binding_sha256"] == CANDIDATE_SHA256
    assert row["bundle_index_object_id"] is not None
    assert row["detached_attestation_object_id"] is not None
