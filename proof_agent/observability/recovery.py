from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json

from proof_agent.contracts.artifacts import ArtifactObjectVersion
from proof_agent.contracts.ports.artifact_references import ArtifactReferenceRepository
from proof_agent.contracts.ports.artifacts import ArtifactStore


@dataclass(frozen=True, slots=True)
class ArtifactRecoveryReport:
    checked_at: datetime
    owner_count: int
    reference_count: int
    verified_reference_count: int
    corrupt_owner_ids: tuple[str, ...]
    expired_owner_count: int
    valid: bool


class ArtifactRecoveryVerifier:
    """Reapply retention then verify every PostgreSQL-bound exact object version."""

    def __init__(
        self,
        *,
        store: ArtifactStore,
        repository: ArtifactReferenceRepository,
    ) -> None:
        self._store = store
        self._repository = repository

    def verify(self, *, now: datetime, apply: bool = True) -> ArtifactRecoveryReport:
        if now.utcoffset() is None:
            raise ValueError("artifact recovery timestamp must be timezone-aware")
        expired = self._repository.expire_due(now=now) if apply else 0
        bound = self._repository.list_bound_manifests()
        references = 0
        verified = 0
        corrupt_owners: list[str] = []
        for item in bound:
            owner_valid = True
            manifest_ref = item.binding.manifest
            references += 1
            if self._verify_ref(manifest_ref):
                expected_manifest_bytes = json.dumps(
                    item.manifest.model_dump(mode="json"),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                if (
                    len(expected_manifest_bytes) == manifest_ref.size_bytes
                    and hashlib.sha256(expected_manifest_bytes).hexdigest()
                    == manifest_ref.sha256
                ):
                    verified += 1
                else:
                    owner_valid = False
                    if apply:
                        self._repository.mark_corrupt(manifest_ref, now=now)
            else:
                owner_valid = False
                if apply:
                    self._repository.mark_corrupt(manifest_ref, now=now)
            for member in item.manifest.members:
                references += 1
                if self._verify_ref(member.artifact):
                    verified += 1
                else:
                    owner_valid = False
                    if apply:
                        self._repository.mark_corrupt(member.artifact, now=now)
            if not owner_valid:
                corrupt_owners.append(
                    f"{item.binding.owner.owner_type}:{item.binding.owner.owner_id}"
                )
        return ArtifactRecoveryReport(
            checked_at=now,
            owner_count=len(bound),
            reference_count=references,
            verified_reference_count=verified,
            corrupt_owner_ids=tuple(corrupt_owners),
            expired_owner_count=expired,
            valid=not corrupt_owners and verified == references,
        )

    def _verify_ref(self, ref: ArtifactObjectVersion) -> bool:
        try:
            if self._store.head_exact(ref) != ref:
                return False
            digest = hashlib.sha256()
            length = 0
            with self._store.open_exact(ref) as stream:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    length += len(chunk)
                    if length > ref.size_bytes:
                        return False
                    digest.update(chunk)
            return length == ref.size_bytes and digest.hexdigest() == ref.sha256
        except Exception:
            return False


__all__ = ["ArtifactRecoveryReport", "ArtifactRecoveryVerifier"]
