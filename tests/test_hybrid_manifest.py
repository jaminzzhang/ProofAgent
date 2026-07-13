from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from urllib.parse import quote

import pytest

from proof_agent.capabilities.knowledge.hybrid.manifest import (
    ManifestRuleUnitMembership,
    PersistedRuleUnitManifestShard,
    ProjectionValidationEvidence,
    RuleUnitManifestMaterialization,
    append_projection_attestation,
    build_rule_unit_manifest,
    decode_manifest_root_artifact,
    decode_manifest_shard_artifact,
)
from proof_agent.capabilities.knowledge.hybrid.versioning import manifest_root_fingerprint
from proof_agent.capabilities.knowledge.hybrid.ports import SearchIndexIdentity
from proof_agent.contracts.hybrid_documents import BoundingBox
from proof_agent.contracts.insurance_rules import (
    ApprovedInsuranceKnowledgeVisibilityScope,
    InsuranceRulePageBoundingBox,
    InsuranceRuleUnitLineage,
    InsuranceRuleUnitRevision,
)
from proof_agent.contracts.knowledge_index import (
    ExactArtifactRef,
    KnowledgeIndexGeneration,
    KnowledgePublicationAttempt,
    KnowledgeProjectionAttestation,
    RuleUnitManifestRoot,
    RuleUnitManifestShardRef,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
NOW = datetime(2026, 7, 14, tzinfo=UTC)


class RecordingArtifactStore:
    def __init__(self) -> None:
        self.contents: dict[str, tuple[bytes, ExactArtifactRef]] = {}
        self.put_keys: list[str] = []

    def put_immutable(self, *, key: str, content: bytes, media_type: str) -> ExactArtifactRef:
        self.put_keys.append(key)
        existing = self.contents.get(key)
        if existing is not None:
            if existing[0] != content or existing[1].media_type != media_type:
                raise ValueError("immutable conflict")
            return existing[1]
        digest = hashlib.sha256(content).hexdigest()
        ref = ExactArtifactRef(
            artifact_uri=f"s3://knowledge/{key}",
            version_id=f"opaque-provider-version-{len(self.contents) + 1}",
            sha256=digest,
            size_bytes=len(content),
            media_type=media_type,
        )
        self.contents[key] = (content, ref)
        return ref

    def get_exact(self, ref: ExactArtifactRef) -> bytes:
        for content, stored_ref in self.contents.values():
            if stored_ref == ref:
                return content
        raise ValueError("missing exact artifact")


def rule_unit(
    rule_id: str,
    document_id: str,
    *,
    content_sha256: str | None = None,
    source_id: str = "source-1",
    content: str | None = None,
    citation_uri: str | None = None,
    revision_id: str | None = None,
    structured_build_id: str | None = None,
) -> InsuranceRuleUnitRevision:
    rule_content = content or f"Rule content for {rule_id}."
    bound_revision_id = revision_id or f"revision-{document_id}"
    return InsuranceRuleUnitRevision(
        rule_unit_revision_id=rule_id,
        logical_rule_key=f"logical-{rule_id}",
        unit_kind="clause",
        document_id=document_id,
        revision_id=bound_revision_id,
        structured_build_id=structured_build_id or f"build-{document_id}",
        content=rule_content,
        citation_uri=citation_uri
        or (
            f"knowledge://source/{quote(source_id, safe='')}/document/"
            f"{quote(document_id, safe='')}/revision/"
            f"{quote(bound_revision_id, safe='')}#page=1"
        ),
        metadata_revision_id=f"metadata-{rule_id}",
        visibility_scope=ApprovedInsuranceKnowledgeVisibilityScope(
            visibility="PUBLIC",
            revision_id=f"visibility-{rule_id}",
        ),
        content_sha256=content_sha256 or hashlib.sha256(rule_content.encode("utf-8")).hexdigest(),
        authority_sha256=SHA_B,
        lineage=InsuranceRuleUnitLineage(
            source_id=source_id,
            original_sha256=SHA_C,
            heading_path=("Rules",),
            page_numbers=(1,),
            page_bboxes=(
                InsuranceRulePageBoundingBox(
                    page_number=1,
                    bbox=BoundingBox(x0=0, y0=0, x1=100, y1=100),
                ),
            ),
            block_ids=(f"block-{rule_id}",),
        ),
    )


def membership(
    rule_id: str,
    document_id: str,
    *,
    content_sha256: str | None = None,
    source_id: str = "source-1",
    publication_seq_from: int = 1,
    publication_seq_to: int | None = None,
    content: str | None = None,
    citation_uri: str | None = None,
    revision_id: str | None = None,
    structured_build_id: str | None = None,
) -> ManifestRuleUnitMembership:
    return ManifestRuleUnitMembership(
        rule_unit=rule_unit(
            rule_id,
            document_id,
            content_sha256=content_sha256,
            source_id=source_id,
            content=content,
            citation_uri=citation_uri,
            revision_id=revision_id,
            structured_build_id=structured_build_id,
        ),
        publication_seq_from=publication_seq_from,
        publication_seq_to=publication_seq_to,
    )


def generation(
    *,
    source_id: str = "source-1",
    generation_id: str = "generation-1",
    mapping_sha256: str = SHA_A,
) -> KnowledgeIndexGeneration:
    return KnowledgeIndexGeneration(
        generation_id=generation_id,
        source_id=source_id,
        canonical_schema_version="structured-knowledge.v1",
        search_projection_version="rule-unit-search.v1",
        mapping_sha256=mapping_sha256,
        analyzer_sha256=SHA_B,
        embedding_model_revision="embedding@revision-1",
        embedding_instruction_sha256=SHA_C,
        embedding_dimension=1024,
        normalized=True,
    )


def attempt(
    *,
    sequence: int = 2,
    source_id: str = "source-1",
    generation_id: str = "generation-1",
    candidate_digest: str = SHA_B,
) -> KnowledgePublicationAttempt:
    return KnowledgePublicationAttempt(
        attempt_id=f"attempt-{sequence}",
        source_id=source_id,
        source_draft_version_id=f"draft-{sequence}",
        candidate_digest=candidate_digest,
        reserved_publication_seq=sequence,
        fencing_token=sequence,
        generation_id=generation_id,
        validation_id=f"validation-{sequence}",
        state="VALIDATED",
        started_at=NOW,
        updated_at=NOW,
    )


def evidence(
    root_sha256: str,
    *,
    sequence: int = 2,
    covered: tuple[int, ...] = (1, 2),
    source_id: str = "source-1",
    generation_id: str = "generation-1",
    mapping_sha256: str = SHA_A,
    candidate_digest: str = SHA_B,
    index_uuid: str = "index-uuid-1",
    document_count: int = 2,
    rule_unit_count: int = 2,
    publication_attempt_id: str | None = None,
    manifest_root_sha256: str | None = None,
) -> ProjectionValidationEvidence:
    return ProjectionValidationEvidence(
        publication_attempt_id=publication_attempt_id or f"attempt-{sequence}",
        candidate_digest=candidate_digest,
        identity=SearchIndexIdentity(
            generation=generation(
                source_id=source_id,
                generation_id=generation_id,
                mapping_sha256=mapping_sha256,
            ),
            index_uuid=index_uuid,
        ),
        refresh_checkpoint=f"refresh-{sequence}",
        manifest_root_sha256=manifest_root_sha256 or root_sha256,
        covered_publication_sequences=covered,
        projection_sha256=SHA_C,
        validated_document_count=document_count,
        validated_rule_unit_count=rule_unit_count,
    )


def build_manifest(
    store: RecordingArtifactStore,
    *,
    sequence: int,
    memberships: tuple[ManifestRuleUnitMembership, ...],
    previous=None,
):
    return build_rule_unit_manifest(
        source_id="source-1",
        source_snapshot_id=f"snapshot-{sequence}",
        source_publication_seq=sequence,
        generation_id="generation-1",
        memberships=memberships,
        created_at=NOW,
        artifact_store=store,
        previous=previous,
    )


def test_manifest_reuses_unchanged_document_shards() -> None:
    store = RecordingArtifactStore()
    first = build_manifest(
        store,
        sequence=1,
        memberships=(membership("rule-a", "a"), membership("rule-b", "b")),
    )
    first_put_count = len(store.put_keys)

    second = build_manifest(
        store,
        sequence=2,
        memberships=(
            membership("rule-a", "a"),
            membership("rule-b2", "b", content="Changed Rule content."),
        ),
        previous=first,
    )

    assert first.shard_for("a").artifact_ref == second.shard_for("a").artifact_ref
    assert first.shard_for("b").artifact_ref != second.shard_for("b").artifact_ref
    assert first.root.root_sha256 != second.root.root_sha256
    assert len(store.put_keys) == first_put_count + 2  # changed shard plus new root


def test_manifest_is_permutation_stable_and_created_at_is_not_addressed() -> None:
    store = RecordingArtifactStore()
    first = build_rule_unit_manifest(
        source_id="source-1",
        source_snapshot_id="snapshot-1",
        source_publication_seq=1,
        generation_id="generation-1",
        memberships=(membership("rule-b", "b"), membership("rule-a", "a")),
        created_at=NOW,
        artifact_store=store,
    )
    second = build_rule_unit_manifest(
        source_id="source-1",
        source_snapshot_id="snapshot-1",
        source_publication_seq=1,
        generation_id="generation-1",
        memberships=(membership("rule-a", "a"), membership("rule-b", "b")),
        created_at=datetime(2027, 1, 1, tzinfo=UTC),
        artifact_store=store,
        previous=first,
    )
    independently_built = build_rule_unit_manifest(
        source_id="source-1",
        source_snapshot_id="snapshot-1",
        source_publication_seq=1,
        generation_id="generation-1",
        memberships=(membership("rule-a", "a"), membership("rule-b", "b")),
        created_at=datetime(2027, 1, 1, tzinfo=UTC),
        artifact_store=RecordingArtifactStore(),
    )

    assert first.root.root_sha256 == second.root.root_sha256
    assert first.root_ref == second.root_ref
    assert tuple(item.shard.document_id for item in first.shards) == ("a", "b")
    assert first == second
    assert first.root.root_sha256 == independently_built.root.root_sha256
    assert first.root.created_at != independently_built.root.created_at


def test_manifest_artifacts_are_exact_canonical_content_addresses() -> None:
    store = RecordingArtifactStore()
    result = build_manifest(
        store,
        sequence=1,
        memberships=(membership("rule-b", "a"), membership("rule-a", "a")),
    )

    for persisted in result.shards:
        content = store.get_exact(persisted.artifact_ref)
        assert hashlib.sha256(content).hexdigest() == persisted.shard.sha256
        assert persisted.artifact_ref.version_id.startswith("opaque-provider-version-")
        assert persisted.artifact_ref.size_bytes == len(content)
        assert content.endswith(b"}") and not content.endswith(b"\n")
        assert decode_manifest_shard_artifact(content) == persisted.shard
        assert tuple(entry.rule_unit_revision_id for entry in persisted.shard.entries) == (
            "rule-a",
            "rule-b",
        )
    root_content = store.get_exact(result.root_ref)
    assert hashlib.sha256(root_content).hexdigest() == result.root.root_sha256
    assert decode_manifest_root_artifact(root_content, created_at=NOW) == result.root


def test_manifest_decoder_rejects_noncanonical_and_duplicate_json() -> None:
    store = RecordingArtifactStore()
    result = build_manifest(
        store,
        sequence=1,
        memberships=(membership("rule-a", "a"),),
    )
    content = store.get_exact(result.shards[0].artifact_ref)

    with pytest.raises(ValueError, match="canonical JSON"):
        decode_manifest_shard_artifact(content + b"\n")
    with pytest.raises(ValueError, match="duplicate JSON keys"):
        decode_manifest_shard_artifact(b'{"fingerprint_schema":"x","fingerprint_schema":"x"}')


def test_manifest_rejects_inactive_and_mixed_document_revision_memberships() -> None:
    inactive = membership("rule-a", "a", publication_seq_from=3)
    closed = membership("rule-b", "b", publication_seq_to=1)
    mixed = membership("rule-c", "a")
    mixed_rule = mixed.rule_unit.model_copy(update={"revision_id": "another-revision"})

    for memberships in (
        (inactive,),
        (closed,),
        (membership("rule-a", "a"), mixed.model_copy(update={"rule_unit": mixed_rule})),
    ):
        with pytest.raises(ValueError):
            build_manifest(RecordingArtifactStore(), sequence=2, memberships=memberships)


def test_manifest_membership_interval_has_inclusive_upper_bound() -> None:
    result = build_manifest(
        RecordingArtifactStore(),
        sequence=2,
        memberships=(membership("rule-a", "a", publication_seq_to=2),),
    )

    assert result.shards[0].shard.entries[0].publication_seq_to == 2


def test_manifest_citation_binding_accepts_canonical_percent_encoded_unicode_ids() -> None:
    source_id = "来源一"
    result = build_rule_unit_manifest(
        source_id=source_id,
        source_snapshot_id="snapshot-1",
        source_publication_seq=1,
        generation_id="generation-1",
        memberships=(membership("规则一", "文档一", source_id=source_id),),
        created_at=NOW,
        artifact_store=RecordingArtifactStore(),
    )

    assert result.shards[0].shard.document_id == "文档一"


@pytest.mark.parametrize(
    "invalid_membership",
    (
        membership("rule-a", "a", content_sha256=SHA_A),
        membership(
            "rule-a",
            "a",
            citation_uri=("knowledge://source/source-2/document/a/revision/revision-a#page=1"),
        ),
        membership(
            "rule-a",
            "a",
            citation_uri=("knowledge://source/source-1/document/b/revision/revision-a#page=1"),
        ),
        membership(
            "rule-a",
            "a",
            citation_uri=("knowledge://source/source-1/document/a/revision/revision-b#page=1"),
        ),
        membership(
            "rule-a",
            "a",
            citation_uri=("proofagent://source/source-1/document/a/revision/revision-a#page=1"),
        ),
    ),
)
def test_manifest_rejects_stale_content_and_cross_bound_citations_before_writes(
    invalid_membership: ManifestRuleUnitMembership,
) -> None:
    store = RecordingArtifactStore()

    with pytest.raises(ValueError):
        build_manifest(store, sequence=1, memberships=(invalid_membership,))

    assert store.put_keys == []


def test_equal_sequence_is_zero_write_exact_replay_only() -> None:
    store = RecordingArtifactStore()
    memberships = (membership("rule-a", "a"),)
    first = build_manifest(store, sequence=1, memberships=memberships)
    puts_after_first = tuple(store.put_keys)

    replay = build_manifest(
        store,
        sequence=1,
        memberships=memberships,
        previous=first,
    )

    assert replay == first
    assert tuple(store.put_keys) == puts_after_first

    competing_calls = (
        {
            "source_snapshot_id": "different-snapshot",
            "memberships": memberships,
        },
        {
            "source_snapshot_id": "snapshot-1",
            "memberships": (membership("different-rule", "a"),),
        },
    )
    for call in competing_calls:
        with pytest.raises(ValueError, match="equal publication sequence"):
            build_rule_unit_manifest(
                source_id="source-1",
                source_snapshot_id=call["source_snapshot_id"],  # type: ignore[arg-type]
                source_publication_seq=1,
                generation_id="generation-1",
                memberships=call["memberships"],  # type: ignore[arg-type]
                created_at=datetime(2027, 1, 1, tzinfo=UTC),
                artifact_store=store,
                previous=first,
            )
        assert tuple(store.put_keys) == puts_after_first


def _cross_bound_materialization_parts(
    store: RecordingArtifactStore,
    *,
    foreign_source_id: str = "source-1",
    foreign_generation_id: str = "generation-1",
) -> tuple[RuleUnitManifestRoot, ExactArtifactRef, PersistedRuleUnitManifestShard]:
    foreign = build_rule_unit_manifest(
        source_id=foreign_source_id,
        source_snapshot_id="foreign-snapshot",
        source_publication_seq=1,
        generation_id=foreign_generation_id,
        memberships=(membership("foreign-rule", "a", source_id=foreign_source_id),),
        created_at=NOW,
        artifact_store=store,
    )
    persisted = foreign.shards[0]
    shard_ref = RuleUnitManifestShardRef(
        shard_id=persisted.shard.shard_id,
        document_id=persisted.shard.document_id,
        artifact_ref=persisted.artifact_ref,
        rule_unit_count=len(persisted.shard.entries),
    )
    root_fields = {
        "schema_version": "rule-unit-manifest-root.v1",
        "source_id": "source-1",
        "source_snapshot_id": "snapshot-1",
        "source_publication_seq": 1,
        "generation_id": "generation-1",
        "shards": (shard_ref,),
        "document_count": 1,
        "rule_unit_count": 1,
    }
    digest = manifest_root_fingerprint(**root_fields)  # type: ignore[arg-type]
    root = RuleUnitManifestRoot(
        manifest_id=f"manifest-{digest}",
        root_sha256=digest,
        created_at=NOW,
        **root_fields,  # type: ignore[arg-type]
    )
    root_body = {
        "fingerprint_schema": "rule-unit-manifest-root-fingerprint.v1",
        **{
            key: value
            for key, value in root.model_dump(mode="json").items()
            if key not in {"manifest_id", "root_sha256", "created_at"}
        },
    }
    root_content = json.dumps(
        root_body,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    root_ref = store.put_immutable(
        key=f"adversarial/{digest}.json",
        content=root_content,
        media_type="application/vnd.proofagent.rule-unit-manifest-root+json",
    )
    assert root_ref.sha256 == digest
    return root, root_ref, persisted


@pytest.mark.parametrize(
    ("foreign_source_id", "foreign_generation_id"),
    (("source-2", "generation-1"), ("source-1", "generation-2")),
)
def test_materialization_and_previous_reject_cross_bound_valid_shards(
    foreign_source_id: str,
    foreign_generation_id: str,
) -> None:
    store = RecordingArtifactStore()
    root, root_ref, persisted = _cross_bound_materialization_parts(
        store,
        foreign_source_id=foreign_source_id,
        foreign_generation_id=foreign_generation_id,
    )

    with pytest.raises(ValueError, match="source and generation"):
        RuleUnitManifestMaterialization(
            root=root,
            root_ref=root_ref,
            shards=(persisted,),
        )
    bypassed = RuleUnitManifestMaterialization.model_construct(
        root=root,
        root_ref=root_ref,
        shards=(persisted,),
    )
    writes_before_reuse = tuple(store.put_keys)
    with pytest.raises(ValueError, match="source and generation"):
        build_manifest(
            store,
            sequence=2,
            memberships=(membership("rule-a", "a"),),
            previous=bypassed,
        )
    assert tuple(store.put_keys) == writes_before_reuse


@pytest.mark.parametrize(
    "memberships",
    (
        (),
        (membership("duplicate", "a"), membership("duplicate", "a")),
        (membership("rule-a", "a"), membership("rule-b", "a", source_id="source-2")),
    ),
)
def test_manifest_rejects_empty_duplicate_and_cross_source_inputs(
    memberships: tuple[ManifestRuleUnitMembership, ...],
) -> None:
    with pytest.raises(ValueError):
        build_manifest(RecordingArtifactStore(), sequence=1, memberships=memberships)


def test_manifest_rejects_corrupt_reused_exact_artifact() -> None:
    store = RecordingArtifactStore()
    first = build_manifest(
        store,
        sequence=1,
        memberships=(membership("rule-a", "a"),),
    )
    key = next(key for key in store.contents if "/shards/" in key)
    _, ref = store.contents[key]
    store.contents[key] = (b"{}", ref)

    with pytest.raises(ValueError, match="exact shard artifact"):
        build_manifest(
            store,
            sequence=2,
            memberships=(membership("rule-a", "a"),),
            previous=first,
        )


def test_manifest_rejects_previous_from_another_source_or_generation() -> None:
    store = RecordingArtifactStore()
    foreign_manifests = (
        build_rule_unit_manifest(
            source_id="source-2",
            source_snapshot_id="snapshot-1",
            source_publication_seq=1,
            generation_id="generation-1",
            memberships=(membership("rule-a", "a", source_id="source-2"),),
            created_at=NOW,
            artifact_store=store,
        ),
        build_rule_unit_manifest(
            source_id="source-1",
            source_snapshot_id="snapshot-1",
            source_publication_seq=1,
            generation_id="generation-2",
            memberships=(membership("rule-a", "a"),),
            created_at=NOW,
            artifact_store=store,
        ),
    )

    for foreign in foreign_manifests:
        with pytest.raises(ValueError):
            build_manifest(
                store,
                sequence=2,
                memberships=(membership("rule-a", "a"),),
                previous=foreign,
            )


def test_attestation_rejects_manifest_root_identity_mutation() -> None:
    store = RecordingArtifactStore()
    root = materialized_root(store)
    forged = root.model_copy(update={"source_snapshot_id": "other-snapshot"})

    with pytest.raises(ValueError, match="manifest root identity"):
        append_projection_attestation(
            attempt=attempt(),
            manifest_root=forged,
            identity=SearchIndexIdentity(generation=generation(), index_uuid="index-uuid-1"),
            evidence=evidence(root.root_sha256),
        )


def materialized_root(store: RecordingArtifactStore, *, sequence: int = 2):
    return build_manifest(
        store,
        sequence=sequence,
        memberships=(membership("rule-a", "a"), membership("rule-b", "b")),
    ).root


def test_descendant_attestation_must_cover_retained_sequences() -> None:
    store = RecordingArtifactStore()
    first_root = materialized_root(store, sequence=1)
    first = append_projection_attestation(
        attempt=attempt(sequence=1),
        manifest_root=first_root,
        identity=SearchIndexIdentity(generation=generation(), index_uuid="index-uuid-1"),
        evidence=evidence(
            first_root.root_sha256,
            sequence=1,
            covered=(1,),
        ),
    )
    second_root = materialized_root(store, sequence=2)

    with pytest.raises(ValueError, match="retained sequence"):
        append_projection_attestation(
            attempt=attempt(sequence=2),
            manifest_root=second_root,
            identity=SearchIndexIdentity(generation=generation(), index_uuid="index-uuid-1"),
            evidence=evidence(second_root.root_sha256, covered=(2,)),
            parent=first,
        )


@pytest.mark.parametrize("child_sequence", (1, 2))
def test_descendant_attestation_must_strictly_advance_publication_sequence(
    child_sequence: int,
) -> None:
    store = RecordingArtifactStore()
    parent_root = materialized_root(store, sequence=2)
    parent = append_projection_attestation(
        attempt=attempt(sequence=2),
        manifest_root=parent_root,
        identity=SearchIndexIdentity(generation=generation(), index_uuid="index-uuid-1"),
        evidence=evidence(parent_root.root_sha256, sequence=2, covered=(1, 2)),
    )
    child_root = materialized_root(store, sequence=child_sequence)

    with pytest.raises(ValueError, match="strictly advance"):
        append_projection_attestation(
            attempt=attempt(sequence=child_sequence),
            manifest_root=child_root,
            identity=SearchIndexIdentity(generation=generation(), index_uuid="index-uuid-1"),
            evidence=evidence(
                child_root.root_sha256,
                sequence=child_sequence,
                covered=tuple(range(1, child_sequence + 1)),
            ),
            parent=parent,
        )


def test_attestation_is_canonical_and_binds_every_authority_input() -> None:
    store = RecordingArtifactStore()
    root = materialized_root(store)
    proof = append_projection_attestation(
        attempt=attempt(),
        manifest_root=root,
        identity=SearchIndexIdentity(generation=generation(), index_uuid="index-uuid-1"),
        evidence=evidence(root.root_sha256, covered=(2, 1)),
    )
    replay = append_projection_attestation(
        attempt=attempt(),
        manifest_root=root,
        identity=SearchIndexIdentity(generation=generation(), index_uuid="index-uuid-1"),
        evidence=evidence(root.root_sha256, covered=(1, 2)),
    )

    assert proof == replay
    assert proof.attestation_id == f"attestation-{proof.attestation_sha256}"
    assert proof.covered_publication_sequences == (1, 2)


def test_attestation_rejects_future_coverage() -> None:
    store = RecordingArtifactStore()
    root = materialized_root(store)

    with pytest.raises(ValueError, match="future publication sequence"):
        append_projection_attestation(
            attempt=attempt(),
            manifest_root=root,
            identity=SearchIndexIdentity(generation=generation(), index_uuid="index-uuid-1"),
            evidence=evidence(root.root_sha256, covered=(1, 2, 3)),
        )


@pytest.mark.parametrize(
    ("attempt_updates", "evidence_updates", "message"),
    (
        ({"candidate_digest": "d" * 64}, {}, "candidate digest"),
        ({"source_id": "source-2"}, {}, "source"),
        ({"generation_id": "generation-2"}, {}, "generation"),
        ({}, {"publication_attempt_id": "other-attempt"}, "attempt"),
        ({}, {"manifest_root_sha256": "d" * 64}, "manifest root"),
        ({}, {"mapping_sha256": "d" * 64}, "mapping"),
        ({}, {"document_count": 1}, "document count"),
        ({}, {"rule_unit_count": 1}, "Rule Unit count"),
    ),
)
def test_attestation_rejects_cross_bound_authority(
    attempt_updates: dict[str, object],
    evidence_updates: dict[str, object],
    message: str,
) -> None:
    store = RecordingArtifactStore()
    root = materialized_root(store)
    publication_attempt = attempt(**attempt_updates)  # type: ignore[arg-type]
    validation = evidence(root.root_sha256, **evidence_updates)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match=message):
        append_projection_attestation(
            attempt=publication_attempt,
            manifest_root=root,
            identity=SearchIndexIdentity(generation=generation(), index_uuid="index-uuid-1"),
            evidence=validation,
        )


def test_attestation_rejects_parent_digest_and_index_identity_drift() -> None:
    store = RecordingArtifactStore()
    first_root = materialized_root(store, sequence=1)
    parent = append_projection_attestation(
        attempt=attempt(sequence=1),
        manifest_root=first_root,
        identity=SearchIndexIdentity(generation=generation(), index_uuid="index-uuid-1"),
        evidence=evidence(first_root.root_sha256, sequence=1, covered=(1,)),
    )
    forged_parent = KnowledgeProjectionAttestation.model_construct(
        **{
            **parent.model_dump(mode="python"),
            "attestation_sha256": "d" * 64,
        }
    )
    second_root = materialized_root(store)

    with pytest.raises(ValueError, match="parent attestation digest"):
        append_projection_attestation(
            attempt=attempt(),
            manifest_root=second_root,
            identity=SearchIndexIdentity(generation=generation(), index_uuid="index-uuid-1"),
            evidence=evidence(second_root.root_sha256),
            parent=forged_parent,
        )
    with pytest.raises(ValueError, match="index identity"):
        append_projection_attestation(
            attempt=attempt(),
            manifest_root=second_root,
            identity=SearchIndexIdentity(generation=generation(), index_uuid="index-uuid-1"),
            evidence=evidence(second_root.root_sha256, index_uuid="index-uuid-2"),
            parent=parent,
        )
