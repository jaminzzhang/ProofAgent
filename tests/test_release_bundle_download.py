from __future__ import annotations

from datetime import UTC, datetime, timedelta
import base64
import hashlib
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from proof_agent.contracts import Permission
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
from proof_agent.delivery.release_bundle_api import (
    Ed25519ReleaseBundleAttestationVerifier,
    release_bundle_signature_payload,
    router,
)
from proof_agent.observability.api.dependencies import get_operator_identity
from proof_agent.observability.api.operator_identity import OperatorIdentityContext


NOW = datetime(2026, 7, 25, 8, 30, tzinfo=UTC)
RELEASE_ID = "proofagent-2026.07.25-rc1"
CANDIDATE_SHA256 = "a" * 64


def _ref(
    *,
    object_id: str,
    body: bytes,
    kind: ArtifactKind,
    name: str,
    expires_at: datetime | None = None,
) -> ArtifactObjectVersion:
    return ArtifactObjectVersion(
        object_id=object_id,
        bucket="proof-agent-releases",
        object_key=f"objects/{object_id[:2]}/{object_id}",
        version_id=f"version-{object_id}",
        sha256=hashlib.sha256(body).hexdigest(),
        size_bytes=len(body),
        kind=kind,
        owner=ArtifactOwner(owner_type="release", owner_id=RELEASE_ID),
        content_type="application/json" if name.endswith("json") else "text/html",
        created_at=NOW,
        expires_at=expires_at,
        display_filename=name,
    )


class Registry:
    def __init__(self, record: ReleaseRegistryRecord, *, invisible: set[str] | None = None):
        self.record = record
        self.invisible = invisible or set()

    def get(self, release_id: str) -> ReleaseRegistryRecord | None:
        return self.record if release_id == self.record.release_id else None

    def list(self) -> tuple[ReleaseRegistryRecord, ...]:
        return (self.record,)

    def resolve_exact_visible(
        self,
        ref: ArtifactObjectVersion,
        *,
        now: datetime,
    ) -> ArtifactObjectVersion | None:
        if ref.object_id in self.invisible:
            return None
        if ref.expires_at is not None and ref.expires_at <= now:
            return None
        return ref


class Materializer:
    def __init__(self, paths: dict[str, Path]):
        self.paths = paths
        self.calls: list[str] = []

    def materialize(self, ref: ArtifactObjectVersion) -> Path:
        self.calls.append(ref.object_id)
        return self.paths[ref.object_id]


class Verifier:
    def __init__(self, accepted: bool = True):
        self.accepted = accepted
        self.calls: list[tuple[bytes, bytes, ReleaseTrustIdentity]] = []

    def verify(
        self,
        *,
        index: bytes,
        attestation: bytes,
        trust_identity: ReleaseTrustIdentity,
    ) -> bool:
        self.calls.append((index, attestation, trust_identity))
        return self.accepted


class Audit:
    def __init__(self) -> None:
        self.events: list[object] = []

    def append(self, event: object) -> None:
        self.events.append(event)


def _fixture(
    tmp_path: Path,
    *,
    finalized: bool = True,
    accepted: bool = True,
    invisible: set[str] | None = None,
    permissions: frozenset[Permission] = frozenset({Permission.AUDIT_EXPORT}),
) -> tuple[TestClient, dict[str, ArtifactObjectVersion], Materializer, Verifier, Audit]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    bodies = {
        "manifest": b'{"decision":"GO"}',
        "report": b"<html>verified release</html>",
        "attestation": b"detached-attestation",
    }
    refs = {
        "manifest": _ref(
            object_id="019ba001-1111-7000-8000-000000000921",
            body=bodies["manifest"],
            kind=ArtifactKind.RELEASE_MANIFEST,
            name="release-gate-manifest.json",
        ),
        "report": _ref(
            object_id="019ba001-1111-7000-8000-000000000922",
            body=bodies["report"],
            kind=ArtifactKind.HTML_REPORT,
            name="release-readiness-report.html",
        ),
        "attestation": _ref(
            object_id="019ba001-1111-7000-8000-000000000923",
            body=bodies["attestation"],
            kind=ArtifactKind.RELEASE_ATTESTATION,
            name="release-bundle-index.json.attestation",
        ),
    }
    index = ReleaseBundleIndex(
        schema_version="proofagent.release-bundle-index.v1",
        release_id=RELEASE_ID,
        candidate_binding_sha256=CANDIDATE_SHA256,
        release_manifest_sha256=refs["manifest"].sha256,
        members=(
            ReleaseBundleIndexMember(
                artifact_name="release-gate-manifest.json",
                role=ReleaseBundleMemberRole.RELEASE_MANIFEST,
                artifact=refs["manifest"],
            ),
            ReleaseBundleIndexMember(
                artifact_name="release-readiness-report.html",
                role=ReleaseBundleMemberRole.READINESS_REPORT,
                artifact=refs["report"],
            ),
        ),
        created_at=NOW,
    )
    bodies["index"] = index.model_dump_json().encode()
    refs["index"] = _ref(
        object_id="019ba001-1111-7000-8000-000000000924",
        body=bodies["index"],
        kind=ArtifactKind.BUNDLE_INDEX,
        name="release-bundle-index.json",
    )
    preparation = ReleaseRegistryRecord(
        schema_version="proofagent.release-registry.v1",
        release_id=RELEASE_ID,
        state=ReleaseLifecycleState.PREPARING,
        candidate_binding_sha256=CANDIDATE_SHA256,
        release_manifest=refs["manifest"],
        created_at=NOW,
        created_by="release-controller",
    )
    record = preparation
    if finalized:
        record = finalize_release_record(
            preparation,
            ReleaseFinalization(
                candidate_binding_sha256=CANDIDATE_SHA256,
                release_manifest=refs["manifest"],
                bundle_index=refs["index"],
                detached_attestation=refs["attestation"],
                trust_identity=ReleaseTrustIdentity(
                    protocol_id="dsse-v1",
                    issuer="https://issuer.example.test",
                    subject="proofagent-release-builder",
                    key_id="release-key-2026-07",
                ),
                finalized_at=NOW,
            ),
        )
    paths: dict[str, Path] = {}
    for name, body in bodies.items():
        path = tmp_path / name
        path.write_bytes(body)
        paths[refs[name].object_id] = path
    materializer = Materializer(paths)
    verifier = Verifier(accepted)
    audit = Audit()
    app = FastAPI()
    app.state.proof_agent_mode = "production"
    app.state.release_registry_repository = Registry(record, invisible=invisible)
    app.state.release_bundle_materializer = materializer
    app.state.release_bundle_attestation_verifier = verifier
    app.state.release_bundle_audit_repository = audit
    app.state.release_bundle_clock = lambda: NOW
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_operator_identity] = lambda: OperatorIdentityContext(
        operator_id="operator-1",
        display_name="Operator One",
        permissions=permissions,
        permission_mapping_version_id="mapping-1",
        permission_epoch=1,
    )
    return TestClient(app), refs, materializer, verifier, audit


def test_bundle_download_requires_authentication(tmp_path: Path) -> None:
    client, _, _, _, _ = _fixture(tmp_path)
    client.app.dependency_overrides.clear()

    assert client.get(
        f"/api/releases/{RELEASE_ID}/bundle/release-bundle-index.json"
    ).status_code == 401


def test_bundle_download_requires_audit_export_permission_and_audits_denial(
    tmp_path: Path,
) -> None:
    client, _, materializer, _, audit = _fixture(tmp_path, permissions=frozenset())

    response = client.get(
        f"/api/releases/{RELEASE_ID}/bundle/release-bundle-index.json"
    )

    assert response.status_code == 403
    assert materializer.calls == []
    assert getattr(audit.events[-1], "outcome").value == "denied"


def test_preparing_release_is_not_downloadable(tmp_path: Path) -> None:
    client, _, materializer, _, _ = _fixture(tmp_path, finalized=False)

    response = client.get(
        f"/api/releases/{RELEASE_ID}/bundle/release-bundle-index.json"
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "release_not_finalized"
    assert materializer.calls == []


def test_download_verifies_index_and_attestation_before_exact_member(tmp_path: Path) -> None:
    client, refs, materializer, verifier, audit = _fixture(tmp_path)

    response = client.get(
        f"/api/releases/{RELEASE_ID}/bundle/release-readiness-report.html"
    )

    assert response.status_code == 200
    assert response.content == b"<html>verified release</html>"
    assert materializer.calls == [
        refs["index"].object_id,
        refs["attestation"].object_id,
        refs["report"].object_id,
    ]
    assert len(verifier.calls) == 1
    assert response.headers["content-disposition"].endswith(
        'filename="release-readiness-report.html"'
    )
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert getattr(audit.events[-1], "outcome").value == "succeeded"


def test_unverified_index_and_non_index_member_fail_closed(tmp_path: Path) -> None:
    rejected, _, _, _, _ = _fixture(tmp_path / "rejected", accepted=False)
    absent, _, _, _, _ = _fixture(tmp_path / "absent")

    rejected_response = rejected.get(
        f"/api/releases/{RELEASE_ID}/bundle/release-readiness-report.html"
    )
    absent_response = absent.get(
        f"/api/releases/{RELEASE_ID}/bundle/not-indexed.json"
    )

    assert rejected_response.status_code == 409
    assert rejected_response.json()["detail"] == "release_bundle_attestation_invalid"
    assert absent_response.status_code == 404


def test_wrong_release_path_injection_and_invisible_object_are_rejected(tmp_path: Path) -> None:
    visible, refs, _, _, _ = _fixture(tmp_path / "visible")
    invisible, _, _, _, _ = _fixture(
        tmp_path / "invisible",
        invisible={"019ba001-1111-7000-8000-000000000922"},
    )

    assert visible.get(
        "/api/releases/wrong-release/bundle/release-bundle-index.json"
    ).status_code == 404
    assert visible.get(f"/api/releases/{RELEASE_ID}/bundle/%2e%2e").status_code == 404
    assert visible.get(
        f"/api/releases/{RELEASE_ID}/bundle/..%2Frelease-gate-manifest.json"
    ).status_code == 404
    assert invisible.get(
        f"/api/releases/{RELEASE_ID}/bundle/release-readiness-report.html"
    ).status_code == 404
    assert refs["report"].object_id


def test_expired_exact_object_is_not_downloadable(tmp_path: Path) -> None:
    client, refs, _, _, _ = _fixture(tmp_path)
    expired = refs["report"].model_copy(update={"expires_at": NOW - timedelta(seconds=1)})
    registry = client.app.state.release_registry_repository
    registry.invisible.add(expired.object_id)

    response = client.get(
        f"/api/releases/{RELEASE_ID}/bundle/release-readiness-report.html"
    )

    assert response.status_code == 404


def test_verified_cache_supports_single_byte_range(tmp_path: Path) -> None:
    client, _, _, _, _ = _fixture(tmp_path)

    response = client.get(
        f"/api/releases/{RELEASE_ID}/bundle/release-readiness-report.html",
        headers={"Range": "bytes=2-7"},
    )

    assert response.status_code == 206
    assert response.content == b"tml>ve"
    assert response.headers["content-range"].startswith("bytes 2-7/")
    assert response.headers["accept-ranges"] == "bytes"


def test_digest_mismatch_is_rejected_before_response_bytes(tmp_path: Path) -> None:
    client, refs, materializer, _, audit = _fixture(tmp_path)
    materializer.paths[refs["report"].object_id].write_bytes(
        b"<html>tampered release</html>"
    )

    response = client.get(
        f"/api/releases/{RELEASE_ID}/bundle/release-readiness-report.html"
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "release_artifact_verification_failed"
    assert getattr(audit.events[-1], "outcome").value == "failed"


def test_release_list_exposes_no_s3_location_and_only_verified_artifact_names(
    tmp_path: Path,
) -> None:
    client, _, _, _, _ = _fixture(tmp_path)

    response = client.get("/api/releases")

    assert response.status_code == 200
    payload = response.json()
    assert payload["releases"][0]["artifact_names"] == [
        "release-bundle-index.json",
        "release-bundle-index.json.attestation",
        "release-gate-manifest.json",
        "release-readiness-report.html",
    ]
    rendered = response.text
    assert "proof-agent-releases" not in rendered
    assert "objects/" not in rendered


def test_ed25519_verifier_binds_index_digest_and_exact_registry_trust_identity() -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes_raw()
    index = b'{"schema_version":"proofagent.release-bundle-index.v1"}'
    trust = ReleaseTrustIdentity(
        protocol_id="ed25519-sha256-v1",
        issuer="proofagent-build-service",
        subject="production-release-bundle",
        key_id="release-key-1",
    )
    signature = private_key.sign(release_bundle_signature_payload(index))
    attestation = json.dumps(
        {
            "schema_version": "proofagent.release-bundle-attestation.v1",
            "protocol_id": trust.protocol_id,
            "issuer": trust.issuer,
            "subject": trust.subject,
            "key_id": trust.key_id,
            "artifact_sha256": hashlib.sha256(index).hexdigest(),
            "signature_base64": base64.b64encode(signature).decode("ascii"),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    verifier = Ed25519ReleaseBundleAttestationVerifier({trust.key_id: public_key})

    assert verifier.verify(index=index, attestation=attestation, trust_identity=trust) is True
    assert verifier.verify(
        index=index + b" ",
        attestation=attestation,
        trust_identity=trust,
    ) is False
    assert verifier.verify(
        index=index,
        attestation=attestation,
        trust_identity=trust.model_copy(update={"subject": "another-subject"}),
    ) is False
