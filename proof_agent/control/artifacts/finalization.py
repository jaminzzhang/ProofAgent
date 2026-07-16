from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from io import BytesIO
import json

from proof_agent.contracts.artifacts import (
    ArtifactKind,
    ArtifactManifest,
    ArtifactManifestMember,
    ArtifactObjectVersion,
    ArtifactOwner,
    ArtifactOwnerBinding,
    ArtifactPutRequest,
)
from proof_agent.contracts.ports.artifact_references import ArtifactReferenceRepository
from proof_agent.contracts.ports.artifacts import ArtifactStore


@dataclass(frozen=True, slots=True)
class ArtifactMemberPayload:
    member_id: str
    kind: ArtifactKind
    content_type: str
    content: bytes
    display_filename: str | None = None
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.kind is ArtifactKind.ARTIFACT_MANIFEST:
            raise ValueError("artifact member cannot itself be the bundle manifest")
        if not self.member_id or not self.content_type or not self.content:
            raise ValueError("artifact member payload is incomplete")
        object.__setattr__(self, "content", bytes(self.content))


@dataclass(frozen=True, slots=True)
class ArtifactFinalizationResult:
    manifest: ArtifactManifest
    binding: ArtifactOwnerBinding


@dataclass(frozen=True, slots=True)
class PreparedArtifactBundle:
    """S3-verified manifest-last bundle that is not yet audience-visible."""

    manifest: ArtifactManifest
    manifest_ref: ArtifactObjectVersion


class ArtifactBundleFinalizer:
    """Manifest-last S3-first finalization with one PostgreSQL visibility commit."""

    def __init__(
        self,
        *,
        store: ArtifactStore,
        repository: ArtifactReferenceRepository,
        clock: Callable[[], datetime] | None = None,
        cancellation_check: Callable[[], None] | None = None,
    ) -> None:
        self._store = store
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(UTC))
        self._cancellation_check = cancellation_check or (lambda: None)

    def finalize(
        self,
        *,
        owner: ArtifactOwner,
        manifest_id: str,
        members: tuple[ArtifactMemberPayload, ...],
    ) -> ArtifactFinalizationResult:
        now = self._clock()
        existing = self._repository.get_visible_binding(owner, now=now)
        if existing is not None:
            manifest = self._repository.get_manifest(manifest_id)
            if manifest is None or existing.manifest.owner != owner:
                raise RuntimeError("visible artifact binding does not match finalization identity")
            self._verify_exact(existing.manifest)
            return ArtifactFinalizationResult(manifest=manifest, binding=existing)
        prepared = self.prepare(
            owner=owner,
            manifest_id=manifest_id,
            members=members,
        )
        return self.publish(prepared)

    def prepare(
        self,
        *,
        owner: ArtifactOwner,
        manifest_id: str,
        members: tuple[ArtifactMemberPayload, ...],
        cancellation_check: Callable[[], None] | None = None,
    ) -> PreparedArtifactBundle:
        """Upload and verify every exact version, leaving PostgreSQL invisible."""

        check = cancellation_check or self._cancellation_check
        now = self._clock()
        if not members:
            raise ValueError("artifact bundle requires at least one member")
        member_ids = [member.member_id for member in members]
        if len(member_ids) != len(set(member_ids)):
            raise ValueError("artifact bundle contains duplicate member ids")
        uploaded: list[ArtifactManifestMember] = []
        for member in sorted(members, key=lambda item: item.member_id):
            check()
            digest = hashlib.sha256(member.content).hexdigest()
            ref = self._store.put_immutable(
                ArtifactPutRequest(
                    kind=member.kind,
                    owner=owner,
                    content_type=member.content_type,
                    expected_sha256=digest,
                    expected_size_bytes=len(member.content),
                    display_filename=member.display_filename,
                    expires_at=member.expires_at,
                ),
                BytesIO(member.content),
            )
            self._verify_exact(ref)
            uploaded.append(ArtifactManifestMember(member_id=member.member_id, artifact=ref))
        manifest = ArtifactManifest(
            manifest_id=manifest_id,
            owner=owner,
            members=tuple(uploaded),
            created_at=now,
        )
        manifest_bytes = json.dumps(
            manifest.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        check()
        manifest_ref = self._store.put_immutable(
            ArtifactPutRequest(
                kind=ArtifactKind.ARTIFACT_MANIFEST,
                owner=owner,
                content_type="application/vnd.proofagent.artifact-manifest+json",
                expected_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
                expected_size_bytes=len(manifest_bytes),
                display_filename="artifact-manifest.json",
            ),
            BytesIO(manifest_bytes),
        )
        self._verify_exact(manifest_ref)
        return PreparedArtifactBundle(manifest=manifest, manifest_ref=manifest_ref)

    def publish(self, prepared: PreparedArtifactBundle) -> ArtifactFinalizationResult:
        """Publish a prepared bundle through the configured visibility authority."""

        self._cancellation_check()
        binding = self._repository.commit_visible_manifest(
            prepared.manifest,
            manifest_ref=prepared.manifest_ref,
        )
        return ArtifactFinalizationResult(manifest=prepared.manifest, binding=binding)

    def _verify_exact(self, ref: ArtifactObjectVersion) -> None:
        if self._store.head_exact(ref) != ref:
            raise RuntimeError("artifact exact head does not match returned reference")
        with self._store.open_exact(ref) as stream:
            digest = hashlib.sha256()
            length = 0
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                length += len(chunk)
                if length > ref.size_bytes:
                    raise RuntimeError("artifact exact read exceeds authority length")
                digest.update(chunk)
        if length != ref.size_bytes or digest.hexdigest() != ref.sha256:
            raise RuntimeError("artifact exact read failed length or digest verification")


__all__ = [
    "ArtifactBundleFinalizer",
    "ArtifactFinalizationResult",
    "ArtifactMemberPayload",
    "PreparedArtifactBundle",
]
