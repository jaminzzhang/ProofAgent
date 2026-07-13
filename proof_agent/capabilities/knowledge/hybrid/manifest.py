"""Content-addressed Rule Unit manifests and projection attestation chains.

Manifest artifacts store a canonical, domain-separated fingerprint body rather than a
self-hashing contract model.  The body omits only fields derived from its digest and,
for roots, non-authoritative creation metadata.  Its exact UTF-8 bytes therefore hash
to the existing versioning fingerprint and can be strictly decoded, revalidated, and
reconstructed without an impossible digest-containing-itself representation.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Literal, Self, TypeVar

from pydantic import (
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from proof_agent.capabilities.knowledge.hybrid.ports import (
    KnowledgeArtifactStore,
    SearchIndexIdentity,
)
from proof_agent.capabilities.knowledge.hybrid.versioning import (
    manifest_root_fingerprint,
    manifest_shard_fingerprint,
    projection_attestation_fingerprint,
)
from proof_agent.contracts._base import FrozenModel
from proof_agent.contracts.insurance_rules import InsuranceRuleUnitRevision
from proof_agent.contracts.knowledge_index import (
    ExactArtifactRef,
    KnowledgePublicationAttempt,
    KnowledgeProjectionAttestation,
    RuleUnitManifestEntry,
    RuleUnitManifestRoot,
    RuleUnitManifestShard,
    RuleUnitManifestShardRef,
)


_SHARD_SCHEMA: Literal["rule-unit-manifest-shard.v1"] = "rule-unit-manifest-shard.v1"
_ROOT_SCHEMA: Literal["rule-unit-manifest-root.v1"] = "rule-unit-manifest-root.v1"
_SHARD_FINGERPRINT_SCHEMA: Literal["rule-unit-manifest-shard-fingerprint.v1"] = (
    "rule-unit-manifest-shard-fingerprint.v1"
)
_ROOT_FINGERPRINT_SCHEMA: Literal["rule-unit-manifest-root-fingerprint.v1"] = (
    "rule-unit-manifest-root-fingerprint.v1"
)
_SHARD_MEDIA_TYPE = "application/vnd.proofagent.rule-unit-manifest-shard+json"
_ROOT_MEDIA_TYPE = "application/vnd.proofagent.rule-unit-manifest-root+json"
_MAX_RULE_UNITS = 100_000
_MAX_DOCUMENTS = 10_000
_MAX_COVERED_SEQUENCES = 10_000
_MAX_ARTIFACT_BYTES = 64 * 1024 * 1024

NonBlankStr = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256 = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
PositiveInt = Annotated[StrictInt, Field(gt=0)]


class _ManifestModel(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


_ManifestModelT = TypeVar("_ManifestModelT", bound=_ManifestModel)


class ManifestRuleUnitMembership(_ManifestModel):
    """One exact Rule Unit revision and its inclusive publication interval."""

    rule_unit: InsuranceRuleUnitRevision
    publication_seq_from: PositiveInt
    publication_seq_to: PositiveInt | None = None

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        if (
            self.publication_seq_to is not None
            and self.publication_seq_to < self.publication_seq_from
        ):
            raise ValueError("publication_seq_to must not precede publication_seq_from")
        return self


class PersistedRuleUnitManifestShard(_ManifestModel):
    shard: RuleUnitManifestShard
    artifact_ref: ExactArtifactRef

    @model_validator(mode="after")
    def validate_content_address(self) -> Self:
        if self.artifact_ref.sha256 != self.shard.sha256:
            raise ValueError("shard artifact digest must match the shard fingerprint")
        if self.artifact_ref.media_type != _SHARD_MEDIA_TYPE:
            raise ValueError("shard artifact media type is incompatible")
        return self


class RuleUnitManifestMaterialization(_ManifestModel):
    root: RuleUnitManifestRoot
    root_ref: ExactArtifactRef
    shards: tuple[PersistedRuleUnitManifestShard, ...] = Field(
        min_length=1,
        max_length=_MAX_DOCUMENTS,
    )

    @model_validator(mode="after")
    def validate_root_and_shards(self) -> Self:
        if self.root_ref.sha256 != self.root.root_sha256:
            raise ValueError("root artifact digest must match the root fingerprint")
        if self.root_ref.media_type != _ROOT_MEDIA_TYPE:
            raise ValueError("root artifact media type is incompatible")
        by_document = {item.shard.document_id: item for item in self.shards}
        if len(by_document) != len(self.shards):
            raise ValueError("persisted manifest document identities must be unique")
        if set(by_document) != {item.document_id for item in self.root.shards}:
            raise ValueError("persisted shards must cover exactly the root shard references")
        for root_ref in self.root.shards:
            persisted = by_document[root_ref.document_id]
            if (
                root_ref.shard_id != persisted.shard.shard_id
                or root_ref.artifact_ref != persisted.artifact_ref
                or root_ref.rule_unit_count != len(persisted.shard.entries)
            ):
                raise ValueError("persisted shard must match its exact root reference")
        return self

    def shard_for(self, document_id: str) -> PersistedRuleUnitManifestShard:
        matches = tuple(item for item in self.shards if item.shard.document_id == document_id)
        if len(matches) != 1:
            raise KeyError(document_id)
        return matches[0]


class ProjectionValidationEvidence(_ManifestModel):
    """Exact projection facts produced before an attestation can be appended."""

    publication_attempt_id: NonBlankStr
    candidate_digest: Sha256
    identity: SearchIndexIdentity
    refresh_checkpoint: NonBlankStr
    manifest_root_sha256: Sha256
    covered_publication_sequences: tuple[PositiveInt, ...] = Field(
        min_length=1,
        max_length=_MAX_COVERED_SEQUENCES,
    )
    projection_sha256: Sha256
    validated_document_count: PositiveInt
    validated_rule_unit_count: PositiveInt

    @field_validator("covered_publication_sequences", mode="before")
    @classmethod
    def canonicalize_coverage(cls, value: object) -> object:
        if not isinstance(value, list | tuple):
            return value
        if not all(type(item) is int for item in value):
            return tuple(value)
        return tuple(sorted(value))

    @model_validator(mode="after")
    def validate_coverage(self) -> Self:
        if len(self.covered_publication_sequences) != len(set(self.covered_publication_sequences)):
            raise ValueError("covered publication sequences must be unique")
        return self


class _ManifestShardArtifactBody(_ManifestModel):
    fingerprint_schema: Literal["rule-unit-manifest-shard-fingerprint.v1"]
    schema_version: Literal["rule-unit-manifest-shard.v1"]
    source_id: NonBlankStr
    generation_id: NonBlankStr
    document_id: NonBlankStr
    entries: tuple[RuleUnitManifestEntry, ...] = Field(
        min_length=1,
        max_length=_MAX_RULE_UNITS,
    )


class _ManifestRootArtifactBody(_ManifestModel):
    fingerprint_schema: Literal["rule-unit-manifest-root-fingerprint.v1"]
    schema_version: Literal["rule-unit-manifest-root.v1"]
    source_id: NonBlankStr
    source_snapshot_id: NonBlankStr
    source_publication_seq: PositiveInt
    generation_id: NonBlankStr
    shards: tuple[RuleUnitManifestShardRef, ...] = Field(
        min_length=1,
        max_length=_MAX_DOCUMENTS,
    )
    document_count: PositiveInt
    rule_unit_count: PositiveInt


def build_rule_unit_manifest(
    *,
    source_id: str,
    source_snapshot_id: str,
    source_publication_seq: int,
    generation_id: str,
    memberships: tuple[ManifestRuleUnitMembership, ...],
    created_at: datetime,
    artifact_store: KnowledgeArtifactStore,
    previous: RuleUnitManifestMaterialization | None = None,
) -> RuleUnitManifestMaterialization:
    """Build and persist one immutable manifest with document-shard reuse."""

    if type(memberships) is not tuple:
        raise TypeError("memberships must be an exact tuple")
    if not 1 <= len(memberships) <= _MAX_RULE_UNITS:
        raise ValueError("memberships must contain between 1 and 100000 Rule Units")
    canonical_memberships = tuple(
        ManifestRuleUnitMembership.model_validate(item.model_dump(mode="python"))
        if isinstance(item, ManifestRuleUnitMembership)
        else ManifestRuleUnitMembership.model_validate(item)
        for item in memberships
    )
    rule_ids = [item.rule_unit.rule_unit_revision_id for item in canonical_memberships]
    if len(rule_ids) != len(set(rule_ids)):
        raise ValueError("manifest Rule Unit revision identities must be unique")
    if any(item.rule_unit.lineage.source_id != source_id for item in canonical_memberships):
        raise ValueError("every manifest Rule Unit must match the source")
    if any(
        item.publication_seq_from > source_publication_seq
        or (
            item.publication_seq_to is not None and item.publication_seq_to < source_publication_seq
        )
        for item in canonical_memberships
    ):
        raise ValueError("every manifest membership must be active at the publication sequence")

    grouped: dict[str, list[RuleUnitManifestEntry]] = {}
    for item in canonical_memberships:
        entry = _manifest_entry(item)
        grouped.setdefault(entry.document_id, []).append(entry)
    if len(grouped) > _MAX_DOCUMENTS:
        raise ValueError("manifest exceeds the document shard limit")
    for document_entries in grouped.values():
        revision_builds = {
            (entry.revision_id, entry.structured_build_id) for entry in document_entries
        }
        if len(revision_builds) != 1:
            raise ValueError(
                "one manifest document shard must bind one exact revision and structured build"
            )

    validated_previous = _validate_previous(previous, artifact_store)
    if validated_previous is not None and (
        validated_previous.root.source_id != source_id
        or validated_previous.root.generation_id != generation_id
    ):
        raise ValueError("previous manifest must match the source and generation")
    if (
        validated_previous is not None
        and validated_previous.root.source_publication_seq > source_publication_seq
    ):
        raise ValueError("previous manifest publication sequence cannot be in the future")
    previous_by_document = (
        {item.shard.document_id: item for item in validated_previous.shards}
        if validated_previous is not None
        else {}
    )
    persisted_shards: list[PersistedRuleUnitManifestShard] = []
    for document_id in sorted(grouped):
        canonical_entries = tuple(
            sorted(grouped[document_id], key=lambda entry: entry.rule_unit_revision_id)
        )
        shard_sha256 = manifest_shard_fingerprint(
            schema_version=_SHARD_SCHEMA,
            source_id=source_id,
            generation_id=generation_id,
            document_id=document_id,
            entries=canonical_entries,
        )
        shard = RuleUnitManifestShard(
            schema_version=_SHARD_SCHEMA,
            shard_id=f"manifest-shard-{shard_sha256}",
            source_id=source_id,
            generation_id=generation_id,
            document_id=document_id,
            entries=canonical_entries,
            sha256=shard_sha256,
        )
        content = _shard_artifact_bytes(shard)
        reusable = previous_by_document.get(document_id)
        if reusable is not None and reusable.shard.sha256 == shard.sha256:
            _verify_exact_artifact(
                artifact_store,
                reusable.artifact_ref,
                content,
                expected_digest=shard.sha256,
                media_type=_SHARD_MEDIA_TYPE,
                label="exact shard artifact",
            )
            artifact_ref = reusable.artifact_ref
        else:
            artifact_ref = _persist_exact_artifact(
                artifact_store,
                key=f"hybrid-manifests/shards/{shard_sha256}.json",
                content=content,
                expected_digest=shard_sha256,
                media_type=_SHARD_MEDIA_TYPE,
                label="shard artifact",
            )
        persisted_shards.append(
            PersistedRuleUnitManifestShard(shard=shard, artifact_ref=artifact_ref)
        )

    shard_refs = tuple(
        RuleUnitManifestShardRef(
            shard_id=item.shard.shard_id,
            document_id=item.shard.document_id,
            artifact_ref=item.artifact_ref,
            rule_unit_count=len(item.shard.entries),
        )
        for item in persisted_shards
    )
    root_sha256 = manifest_root_fingerprint(
        schema_version=_ROOT_SCHEMA,
        source_id=source_id,
        source_snapshot_id=source_snapshot_id,
        source_publication_seq=source_publication_seq,
        generation_id=generation_id,
        shards=shard_refs,
        document_count=len(shard_refs),
        rule_unit_count=len(canonical_memberships),
    )
    root = RuleUnitManifestRoot(
        schema_version=_ROOT_SCHEMA,
        manifest_id=f"manifest-{root_sha256}",
        source_id=source_id,
        source_snapshot_id=source_snapshot_id,
        source_publication_seq=source_publication_seq,
        generation_id=generation_id,
        shards=shard_refs,
        document_count=len(shard_refs),
        rule_unit_count=len(canonical_memberships),
        root_sha256=root_sha256,
        created_at=created_at,
    )
    root_content = _root_artifact_bytes(root)
    if validated_previous is not None and validated_previous.root.root_sha256 == root_sha256:
        _verify_exact_artifact(
            artifact_store,
            validated_previous.root_ref,
            root_content,
            expected_digest=root_sha256,
            media_type=_ROOT_MEDIA_TYPE,
            label="exact root artifact",
        )
        root_ref = validated_previous.root_ref
    else:
        root_ref = _persist_exact_artifact(
            artifact_store,
            key=f"hybrid-manifests/roots/{root_sha256}.json",
            content=root_content,
            expected_digest=root_sha256,
            media_type=_ROOT_MEDIA_TYPE,
            label="root artifact",
        )
    return RuleUnitManifestMaterialization(
        root=root,
        root_ref=root_ref,
        shards=tuple(persisted_shards),
    )


def decode_manifest_shard_artifact(content: bytes) -> RuleUnitManifestShard:
    """Strictly decode one canonical shard body and reconstruct derived identity fields."""

    body = _decode_canonical_body(content, _ManifestShardArtifactBody)
    digest = manifest_shard_fingerprint(
        schema_version=body.schema_version,
        source_id=body.source_id,
        generation_id=body.generation_id,
        document_id=body.document_id,
        entries=body.entries,
    )
    if hashlib.sha256(content).hexdigest() != digest:
        raise ValueError("shard artifact bytes do not match the versioned fingerprint")
    return RuleUnitManifestShard(
        schema_version=body.schema_version,
        shard_id=f"manifest-shard-{digest}",
        source_id=body.source_id,
        generation_id=body.generation_id,
        document_id=body.document_id,
        entries=body.entries,
        sha256=digest,
    )


def decode_manifest_root_artifact(
    content: bytes,
    *,
    created_at: datetime,
) -> RuleUnitManifestRoot:
    """Strictly decode a canonical root body and attach non-addressed creation metadata."""

    body = _decode_canonical_body(content, _ManifestRootArtifactBody)
    digest = manifest_root_fingerprint(
        schema_version=body.schema_version,
        source_id=body.source_id,
        source_snapshot_id=body.source_snapshot_id,
        source_publication_seq=body.source_publication_seq,
        generation_id=body.generation_id,
        shards=body.shards,
        document_count=body.document_count,
        rule_unit_count=body.rule_unit_count,
    )
    if hashlib.sha256(content).hexdigest() != digest:
        raise ValueError("root artifact bytes do not match the versioned fingerprint")
    return RuleUnitManifestRoot(
        schema_version=body.schema_version,
        manifest_id=f"manifest-{digest}",
        source_id=body.source_id,
        source_snapshot_id=body.source_snapshot_id,
        source_publication_seq=body.source_publication_seq,
        generation_id=body.generation_id,
        shards=body.shards,
        document_count=body.document_count,
        rule_unit_count=body.rule_unit_count,
        root_sha256=digest,
        created_at=created_at,
    )


def append_projection_attestation(
    *,
    attempt: KnowledgePublicationAttempt,
    manifest_root: RuleUnitManifestRoot,
    identity: SearchIndexIdentity,
    evidence: ProjectionValidationEvidence,
    parent: KnowledgeProjectionAttestation | None = None,
) -> KnowledgeProjectionAttestation:
    """Validate exact publication/projection bindings and append one chain record."""

    validated_attempt = KnowledgePublicationAttempt.model_validate(
        attempt.model_dump(mode="python")
    )
    if validated_attempt.state != "VALIDATED":
        raise ValueError("attestation append requires a VALIDATED publication attempt")
    root = _validate_manifest_root(manifest_root)
    expected_identity = SearchIndexIdentity.model_validate(identity.model_dump(mode="python"))
    validation = ProjectionValidationEvidence.model_validate(evidence.model_dump(mode="python"))
    generation = expected_identity.generation

    if validation.identity != expected_identity:
        raise ValueError("projection index identity or mapping binding does not match")

    if validated_attempt.source_id != root.source_id or generation.source_id != root.source_id:
        raise ValueError("attestation source binding does not match")
    if (
        validated_attempt.generation_id != root.generation_id
        or generation.generation_id != root.generation_id
    ):
        raise ValueError("attestation generation binding does not match")
    if validated_attempt.reserved_publication_seq != root.source_publication_seq:
        raise ValueError("attestation publication sequence does not match")
    if validation.publication_attempt_id != validated_attempt.attempt_id:
        raise ValueError("attestation publication attempt binding does not match")
    if validation.candidate_digest != validated_attempt.candidate_digest:
        raise ValueError("attestation candidate digest binding does not match")
    if validation.manifest_root_sha256 != root.root_sha256:
        raise ValueError("attestation manifest root binding does not match")
    if validation.validated_document_count != root.document_count:
        raise ValueError("attestation document count does not match the manifest root")
    if validation.validated_rule_unit_count != root.rule_unit_count:
        raise ValueError("attestation Rule Unit count does not match the manifest root")
    if root.source_publication_seq not in validation.covered_publication_sequences:
        raise ValueError("attestation must cover the current publication sequence")
    if any(
        sequence > root.source_publication_seq
        for sequence in validation.covered_publication_sequences
    ):
        raise ValueError("attestation cannot claim a future publication sequence")

    parent_sha256: str | None = None
    if parent is not None:
        validated_parent = _validate_attestation(parent)
        parent_sha256 = validated_parent.attestation_sha256
        if validated_parent.source_id != root.source_id:
            raise ValueError("parent attestation source does not match")
        if validated_parent.generation_id != root.generation_id:
            raise ValueError("parent attestation generation does not match")
        if validated_parent.mapping_sha256 != generation.mapping_sha256:
            raise ValueError("parent attestation mapping does not match")
        if validated_parent.index_uuid != validation.identity.index_uuid:
            raise ValueError("parent attestation index identity does not match")
        retained = set(validated_parent.covered_publication_sequences)
        if not retained.issubset(validation.covered_publication_sequences):
            raise ValueError("descendant attestation lost a retained sequence")

    digest = projection_attestation_fingerprint(
        source_id=root.source_id,
        generation_id=root.generation_id,
        publication_attempt_id=validated_attempt.attempt_id,
        index_uuid=expected_identity.index_uuid,
        refresh_checkpoint=validation.refresh_checkpoint,
        manifest_root_sha256=root.root_sha256,
        mapping_sha256=generation.mapping_sha256,
        covered_publication_sequences=validation.covered_publication_sequences,
        parent_attestation_sha256=parent_sha256,
        projection_sha256=validation.projection_sha256,
        validated_document_count=root.document_count,
        validated_rule_unit_count=root.rule_unit_count,
    )
    attestation = KnowledgeProjectionAttestation(
        attestation_id=f"attestation-{digest}",
        attestation_sha256=digest,
        source_id=root.source_id,
        generation_id=root.generation_id,
        publication_attempt_id=validated_attempt.attempt_id,
        index_uuid=expected_identity.index_uuid,
        refresh_checkpoint=validation.refresh_checkpoint,
        manifest_root_sha256=root.root_sha256,
        mapping_sha256=generation.mapping_sha256,
        covered_publication_sequences=validation.covered_publication_sequences,
        parent_attestation_sha256=parent_sha256,
        projection_sha256=validation.projection_sha256,
        validated_document_count=root.document_count,
        validated_rule_unit_count=root.rule_unit_count,
    )
    return _validate_attestation(attestation)


def _manifest_entry(item: ManifestRuleUnitMembership) -> RuleUnitManifestEntry:
    unit = item.rule_unit
    return RuleUnitManifestEntry(
        rule_unit_revision_id=unit.rule_unit_revision_id,
        document_id=unit.document_id,
        revision_id=unit.revision_id,
        structured_build_id=unit.structured_build_id,
        metadata_revision_id=unit.metadata_revision_id,
        visibility_revision_id=unit.visibility_scope.revision_id,
        content_sha256=unit.content_sha256,
        authority_sha256=unit.authority_sha256,
        citation_uri=unit.citation_uri,
        publication_seq_from=item.publication_seq_from,
        publication_seq_to=item.publication_seq_to,
    )


def _shard_artifact_bytes(shard: RuleUnitManifestShard) -> bytes:
    body = _ManifestShardArtifactBody(
        fingerprint_schema=_SHARD_FINGERPRINT_SCHEMA,
        schema_version=shard.schema_version,
        source_id=shard.source_id,
        generation_id=shard.generation_id,
        document_id=shard.document_id,
        entries=shard.entries,
    )
    content = _canonical_bytes(body.model_dump(mode="json"))
    if hashlib.sha256(content).hexdigest() != shard.sha256:
        raise RuntimeError("shard canonical bytes diverged from the versioned fingerprint")
    if decode_manifest_shard_artifact(content) != shard:
        raise RuntimeError("shard canonical artifact failed reconstruction")
    return content


def _root_artifact_bytes(root: RuleUnitManifestRoot) -> bytes:
    body = _ManifestRootArtifactBody(
        fingerprint_schema=_ROOT_FINGERPRINT_SCHEMA,
        schema_version=root.schema_version,
        source_id=root.source_id,
        source_snapshot_id=root.source_snapshot_id,
        source_publication_seq=root.source_publication_seq,
        generation_id=root.generation_id,
        shards=root.shards,
        document_count=root.document_count,
        rule_unit_count=root.rule_unit_count,
    )
    content = _canonical_bytes(body.model_dump(mode="json"))
    if hashlib.sha256(content).hexdigest() != root.root_sha256:
        raise RuntimeError("root canonical bytes diverged from the versioned fingerprint")
    if decode_manifest_root_artifact(content, created_at=root.created_at) != root:
        raise RuntimeError("root canonical artifact failed reconstruction")
    return content


def _canonical_bytes(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _decode_canonical_body(
    content: bytes,
    model_type: type[_ManifestModelT],
) -> _ManifestModelT:
    if type(content) is not bytes:
        raise TypeError("manifest artifact content must be exact bytes")
    if not 1 <= len(content) <= _MAX_ARTIFACT_BYTES:
        raise ValueError("manifest artifact byte length is outside the allowed bound")
    try:
        text = content.decode("utf-8", errors="strict")
        payload = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_nonfinite_json,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("manifest artifact is not strict UTF-8 JSON") from exc
    if type(payload) is not dict:
        raise ValueError("manifest artifact root must be an object")
    validated = model_type.model_validate(payload)
    if _canonical_bytes(validated.model_dump(mode="json")) != content:
        raise ValueError("manifest artifact is not canonical JSON")
    return validated


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("manifest artifact contains duplicate JSON keys")
        result[key] = value
    return result


def _reject_nonfinite_json(value: str) -> None:
    raise ValueError(f"manifest artifact contains non-finite JSON constant {value}")


def _persist_exact_artifact(
    store: KnowledgeArtifactStore,
    *,
    key: str,
    content: bytes,
    expected_digest: str,
    media_type: str,
    label: str,
) -> ExactArtifactRef:
    raw_ref = store.put_immutable(key=key, content=content, media_type=media_type)
    ref = ExactArtifactRef.model_validate(raw_ref.model_dump(mode="python"))
    _verify_exact_artifact(
        store,
        ref,
        content,
        expected_digest=expected_digest,
        media_type=media_type,
        label=label,
    )
    return ref


def _verify_exact_artifact(
    store: KnowledgeArtifactStore,
    ref: ExactArtifactRef,
    expected_content: bytes,
    *,
    expected_digest: str,
    media_type: str,
    label: str,
) -> None:
    if (
        ref.sha256 != expected_digest
        or ref.size_bytes != len(expected_content)
        or ref.media_type != media_type
    ):
        raise ValueError(f"{label} reference does not match canonical bytes")
    try:
        stored = store.get_exact(ref)
    except Exception as exc:
        raise ValueError(f"{label} could not be read exactly") from exc
    if type(stored) is not bytes or stored != expected_content:
        raise ValueError(f"{label} bytes do not match canonical bytes")
    if hashlib.sha256(stored).hexdigest() != expected_digest:
        raise ValueError(f"{label} digest does not match canonical bytes")


def _validate_previous(
    previous: RuleUnitManifestMaterialization | None,
    store: KnowledgeArtifactStore,
) -> RuleUnitManifestMaterialization | None:
    if previous is None:
        return None
    validated = RuleUnitManifestMaterialization.model_validate(previous.model_dump(mode="python"))
    root = _validate_manifest_root(validated.root)
    for item in validated.shards:
        shard = _validate_manifest_shard(item.shard)
        _verify_exact_artifact(
            store,
            item.artifact_ref,
            _shard_artifact_bytes(shard),
            expected_digest=shard.sha256,
            media_type=_SHARD_MEDIA_TYPE,
            label="exact shard artifact",
        )
    _verify_exact_artifact(
        store,
        validated.root_ref,
        _root_artifact_bytes(root),
        expected_digest=root.root_sha256,
        media_type=_ROOT_MEDIA_TYPE,
        label="exact root artifact",
    )
    return validated


def _validate_manifest_shard(shard: RuleUnitManifestShard) -> RuleUnitManifestShard:
    validated = RuleUnitManifestShard.model_validate(shard.model_dump(mode="python"))
    digest = manifest_shard_fingerprint(
        schema_version=validated.schema_version,
        source_id=validated.source_id,
        generation_id=validated.generation_id,
        document_id=validated.document_id,
        entries=validated.entries,
    )
    if validated.sha256 != digest or validated.shard_id != f"manifest-shard-{digest}":
        raise ValueError("manifest shard identity does not match its versioned fingerprint")
    return validated


def _validate_manifest_root(root: RuleUnitManifestRoot) -> RuleUnitManifestRoot:
    validated = RuleUnitManifestRoot.model_validate(root.model_dump(mode="python"))
    digest = manifest_root_fingerprint(
        schema_version=validated.schema_version,
        source_id=validated.source_id,
        source_snapshot_id=validated.source_snapshot_id,
        source_publication_seq=validated.source_publication_seq,
        generation_id=validated.generation_id,
        shards=validated.shards,
        document_count=validated.document_count,
        rule_unit_count=validated.rule_unit_count,
    )
    if validated.root_sha256 != digest or validated.manifest_id != f"manifest-{digest}":
        raise ValueError("manifest root identity does not match its versioned fingerprint")
    return validated


def _validate_attestation(
    attestation: KnowledgeProjectionAttestation,
) -> KnowledgeProjectionAttestation:
    validated = KnowledgeProjectionAttestation.model_validate(attestation.model_dump(mode="python"))
    digest = projection_attestation_fingerprint(
        source_id=validated.source_id,
        generation_id=validated.generation_id,
        publication_attempt_id=validated.publication_attempt_id,
        index_uuid=validated.index_uuid,
        refresh_checkpoint=validated.refresh_checkpoint,
        manifest_root_sha256=validated.manifest_root_sha256,
        mapping_sha256=validated.mapping_sha256,
        covered_publication_sequences=validated.covered_publication_sequences,
        parent_attestation_sha256=validated.parent_attestation_sha256,
        projection_sha256=validated.projection_sha256,
        validated_document_count=validated.validated_document_count,
        validated_rule_unit_count=validated.validated_rule_unit_count,
    )
    if (
        validated.attestation_sha256 != digest
        or validated.attestation_id != f"attestation-{digest}"
    ):
        raise ValueError("parent attestation digest or identity does not match its record")
    return validated


__all__ = [
    "ManifestRuleUnitMembership",
    "PersistedRuleUnitManifestShard",
    "ProjectionValidationEvidence",
    "RuleUnitManifestMaterialization",
    "append_projection_attestation",
    "build_rule_unit_manifest",
    "decode_manifest_root_artifact",
    "decode_manifest_shard_artifact",
]
