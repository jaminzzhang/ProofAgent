from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from proof_agent.contracts import (
    ExactArtifactRef,
    HybridKnowledgePublicationRecord,
    HybridKnowledgeRevisionReadinessRecord,
    HybridKnowledgeRevisionReviewRecord,
    HybridReadinessCheck,
    KnowledgeIndexGeneration,
    KnowledgeProjectionAttestation,
    KnowledgePublicationAttempt,
    KnowledgeRetrievalProfileRevision,
    KnowledgeSourcePublicationRecord,
    KnowledgeSourcePublicationValidation,
    PrevalidatedRetrievalDegradation,
    RuleUnitManifestEntry,
    RuleUnitManifestRoot,
    RuleUnitManifestShard,
    RuleUnitManifestShardRef,
)


NOW = datetime(2026, 7, 12, 8, 0, tzinfo=UTC)


def artifact_ref(
    sha256: str = "1" * 64,
    *,
    artifact_uri: str = "s3://knowledge/manifests/root.json",
    media_type: str = "application/json",
) -> ExactArtifactRef:
    return ExactArtifactRef(
        artifact_uri=artifact_uri,
        version_id="version-1",
        sha256=sha256,
        size_bytes=42,
        media_type=media_type,
    )


def manifest_entry(
    rule_unit_revision_id: str = "ru_1", document_id: str = "doc_1"
) -> RuleUnitManifestEntry:
    return RuleUnitManifestEntry(
        rule_unit_revision_id=rule_unit_revision_id,
        document_id=document_id,
        revision_id="rev_1",
        structured_build_id="build_1",
        metadata_revision_id="metadata_1",
        visibility_revision_id="visibility_1",
        content_sha256="2" * 64,
        authority_sha256="3" * 64,
        citation_uri="knowledge://source/ks_1/document/doc_1/revision/rev_1#page=1",
        publication_seq_from=1,
    )


def manifest_root() -> RuleUnitManifestRoot:
    return RuleUnitManifestRoot(
        schema_version="rule-unit-manifest-root.v1",
        manifest_id="manifest_1",
        source_id="ks_1",
        source_snapshot_id="snapshot_1",
        source_publication_seq=1,
        generation_id="kig_1",
        shards=(
            RuleUnitManifestShardRef(
                shard_id="shard_1",
                document_id="doc_1",
                artifact_ref=artifact_ref("4" * 64),
                rule_unit_count=1,
            ),
        ),
        document_count=1,
        rule_unit_count=1,
        root_sha256="5" * 64,
        created_at=NOW,
    )


def attestation(**updates: object) -> KnowledgeProjectionAttestation:
    values: dict[str, object] = {
        "attestation_id": "attestation_1",
        "attestation_sha256": "6" * 64,
        "source_id": "ks_1",
        "generation_id": "kig_1",
        "publication_attempt_id": "attempt_1",
        "index_uuid": "index-uuid-1",
        "refresh_checkpoint": "refresh-1",
        "manifest_root_sha256": "5" * 64,
        "mapping_sha256": "a" * 64,
        "covered_publication_sequences": (1,),
        "projection_sha256": "7" * 64,
        "validated_document_count": 1,
        "validated_rule_unit_count": 1,
    }
    values.update(updates)
    return KnowledgeProjectionAttestation(**values)  # type: ignore[arg-type]


def readiness_checks(*, failed: str | None = None) -> tuple[HybridReadinessCheck, ...]:
    names = (
        "structured_artifact",
        "rule_units_approved",
        "embeddings",
        "search_projection",
        "citations",
        "manifest_membership",
        "integrity",
        "review",
    )
    return tuple(
        HybridReadinessCheck(
            check=name,
            passed=name != failed,
            blocker_codes=("NOT_READY",) if name == failed else (),
        )
        for name in names
    )  # type: ignore[arg-type]


def test_retrieval_profile_is_not_part_of_index_generation() -> None:
    generation = KnowledgeIndexGeneration(
        generation_id="kig_1",
        source_id="ks_1",
        canonical_schema_version="structured-knowledge.v1",
        search_projection_version="rule-unit-search.v1",
        mapping_sha256="a" * 64,
        analyzer_sha256="b" * 64,
        embedding_model_revision="qwen3-embedding-0.6b@sha256:model",
        embedding_instruction_sha256="c" * 64,
        embedding_dimension=1024,
        normalized=True,
    )
    profile = KnowledgeRetrievalProfileRevision(
        profile_revision_id="krp_1",
        lexical_budget=100,
        dense_budget=100,
        rrf_window=50,
        reranker_revision="gte-reranker@sha256:model",
        rerank_budget=50,
        final_budget=16,
        enabled_degradations=(),
    )
    assert generation.generation_id != profile.profile_revision_id
    assert generation.embedding_pooling == "mean"
    assert "profile_revision_id" not in KnowledgeIndexGeneration.model_fields
    assert "generation_id" not in KnowledgeRetrievalProfileRevision.model_fields


def test_exact_artifact_ref_is_strict_immutable_and_round_trips() -> None:
    ref = artifact_ref(media_type="Application/Vnd.ProofAgent+JSON")
    restored = ExactArtifactRef.model_validate_json(ref.model_dump_json())
    assert restored == ref
    assert ref.media_type == "application/vnd.proofagent+json"
    with pytest.raises(ValidationError):
        ExactArtifactRef.model_validate({**ref.model_dump(), "size_bytes": "42"})
    with pytest.raises(ValidationError):
        ExactArtifactRef.model_validate({**ref.model_dump(), "sha256": "A" * 64})
    with pytest.raises(ValidationError):
        ExactArtifactRef.model_validate({**ref.model_dump(), "bucket": "private"})
    with pytest.raises(ValidationError):
        ref.version_id = "latest"


@pytest.mark.parametrize(
    "artifact_uri",
    [
        "s3://bucket/key",
        "https://host/path",
        "file:///absolute/path",
        "proofagent://artifact/id",
        "https://host/path%3Fpart%23anchor",
    ],
)
def test_exact_artifact_ref_accepts_absolute_provider_neutral_uris(
    artifact_uri: str,
) -> None:
    ref = artifact_ref(artifact_uri=artifact_uri)
    assert ExactArtifactRef.model_validate_json(ref.model_dump_json()) == ref


@pytest.mark.parametrize(
    "artifact_uri",
    [
        "relative/path",
        " s3://bucket/key",
        "s3://bucket/key with space",
        "s3://bucket/key%2",
        "https://user@host/path",
        "https://host/path?signature=secret",
        "https://host/path?",
        "https://host/path#fragment",
        "https://host/path#",
        "https://[broken/path",
    ],
)
def test_exact_artifact_ref_rejects_unsafe_or_malformed_uris(
    artifact_uri: str,
) -> None:
    with pytest.raises(ValidationError):
        artifact_ref(artifact_uri=artifact_uri)


@pytest.mark.parametrize(
    "media_type",
    [
        "application/json; charset=utf-8",
        " application/json",
        "application /json",
        "application",
        "/json",
    ],
)
def test_exact_artifact_ref_rejects_noncanonical_media_types(media_type: str) -> None:
    with pytest.raises(ValidationError):
        artifact_ref(media_type=media_type)


def test_manifest_contracts_canonicalize_and_validate_counts() -> None:
    first = manifest_entry("ru_1")
    second = manifest_entry("ru_2")
    shard = RuleUnitManifestShard(
        schema_version="rule-unit-manifest-shard.v1",
        shard_id="shard_1",
        source_id="ks_1",
        generation_id="kig_1",
        document_id="doc_1",
        entries=(second, first),
        sha256="4" * 64,
    )
    assert [entry.rule_unit_revision_id for entry in shard.entries] == ["ru_1", "ru_2"]
    assert RuleUnitManifestShard.model_validate_json(shard.model_dump_json()) == shard
    with pytest.raises(ValidationError):
        RuleUnitManifestShard.model_validate({**shard.model_dump(), "entries": (first, first)})
    with pytest.raises(ValidationError):
        RuleUnitManifestEntry.model_validate({**first.model_dump(), "publication_seq_to": 0})
    with pytest.raises(ValidationError):
        RuleUnitManifestRoot.model_validate({**manifest_root().model_dump(), "rule_unit_count": 2})


def test_publication_attempt_state_and_timestamp_validation() -> None:
    attempt = KnowledgePublicationAttempt(
        attempt_id="attempt_1",
        source_id="ks_1",
        source_draft_version_id="draft_1",
        candidate_digest="8" * 64,
        reserved_publication_seq=1,
        fencing_token=1,
        generation_id="kig_1",
        validation_id="validation_1",
        state="BUILDING",
        started_at=NOW,
        updated_at=NOW,
    )
    assert KnowledgePublicationAttempt.model_validate_json(attempt.model_dump_json()) == attempt
    with pytest.raises(ValidationError):
        KnowledgePublicationAttempt.model_validate({**attempt.model_dump(), "failure_code": "ERR"})
    with pytest.raises(ValidationError):
        KnowledgePublicationAttempt.model_validate(
            {**attempt.model_dump(), "started_at": datetime(2026, 7, 12, 8, 0)}
        )


def test_retrieval_profile_validates_budgets_and_degradation_identity() -> None:
    degradation = PrevalidatedRetrievalDegradation(
        degradation_id="degradation_1",
        mode="BM25_ONLY",
        source_id="ks_1",
        query_type="clause_lookup",
        sealed_evaluation_ref=artifact_ref("9" * 64),
    )
    profile = KnowledgeRetrievalProfileRevision(
        profile_revision_id="krp_1",
        lexical_budget=100,
        dense_budget=100,
        rrf_window=50,
        reranker_revision="reranker@sha256:model",
        rerank_budget=40,
        final_budget=16,
        query_expansion_revision="query-expansion.v1",
        enabled_degradations=(degradation,),
    )
    assert (
        KnowledgeRetrievalProfileRevision.model_validate_json(profile.model_dump_json()) == profile
    )
    with pytest.raises(ValidationError):
        KnowledgeRetrievalProfileRevision.model_validate(
            {**profile.model_dump(), "final_budget": 41}
        )
    with pytest.raises(ValidationError):
        KnowledgeRetrievalProfileRevision.model_validate(
            {**profile.model_dump(), "enabled_degradations": (degradation, degradation)}
        )


@pytest.mark.parametrize("sequences", [(1, 1), (0,), (-1,)])
def test_attestation_rejects_duplicate_or_non_positive_coverage(
    sequences: tuple[int, ...],
) -> None:
    with pytest.raises(ValidationError):
        attestation(covered_publication_sequences=sequences)


def test_attestation_canonicalizes_coverage_and_rejects_self_reference() -> None:
    record = attestation(covered_publication_sequences=(2, 1))
    assert record.covered_publication_sequences == (1, 2)
    with pytest.raises(ValidationError):
        attestation(parent_attestation_sha256="6" * 64)


def test_review_state_is_separate_from_ingestion_and_strict() -> None:
    review = HybridKnowledgeRevisionReviewRecord(
        review_id="review_1",
        source_id="ks_1",
        document_id="doc_1",
        revision_id="rev_1",
        structured_build_id="build_1",
        state="REVIEW_REQUIRED",
        reason_codes=("TABLE_AMBIGUITY",),
    )
    assert "ingestion_state" not in type(review).model_fields
    with pytest.raises(ValidationError):
        HybridKnowledgeRevisionReviewRecord.model_validate(
            {**review.model_dump(), "reason_codes": ()}
        )
    with pytest.raises(ValidationError):
        HybridKnowledgeRevisionReviewRecord.model_validate(
            {**review.model_dump(), "reviewed_by": "reviewer_1", "reviewed_at": NOW}
        )
    approved = HybridKnowledgeRevisionReviewRecord(
        **{
            **review.model_dump(),
            "state": "APPROVED",
            "reason_codes": (),
            "reviewed_by": "reviewer_1",
            "reviewed_at": NOW,
        }
    )
    assert (
        HybridKnowledgeRevisionReviewRecord.model_validate_json(approved.model_dump_json())
        == approved
    )
    rejected = HybridKnowledgeRevisionReviewRecord(
        **{
            **review.model_dump(),
            "state": "REJECTED",
            "reviewed_by": "reviewer_1",
            "reviewed_at": NOW,
        }
    )
    assert rejected.reason_codes == ("TABLE_AMBIGUITY",)
    with pytest.raises(ValidationError):
        HybridKnowledgeRevisionReviewRecord.model_validate(
            {**rejected.model_dump(), "reason_codes": ()}
        )
    not_required = HybridKnowledgeRevisionReviewRecord(
        **{
            **review.model_dump(),
            "state": "NOT_REQUIRED",
            "reason_codes": (),
        }
    )
    assert not_required.reviewed_by is None


def test_readiness_requires_every_check_and_status_consistency() -> None:
    ready = HybridKnowledgeRevisionReadinessRecord(
        readiness_id="readiness_1",
        source_id="ks_1",
        document_id="doc_1",
        revision_id="rev_1",
        structured_build_id="build_1",
        status="READY",
        checks=readiness_checks(),
        evaluated_at=NOW,
    )
    assert (
        HybridKnowledgeRevisionReadinessRecord.model_validate_json(ready.model_dump_json()) == ready
    )
    with pytest.raises(ValidationError):
        HybridKnowledgeRevisionReadinessRecord.model_validate(
            {**ready.model_dump(), "checks": ready.checks[:-1]}
        )
    with pytest.raises(ValidationError):
        HybridKnowledgeRevisionReadinessRecord.model_validate(
            {**ready.model_dump(), "checks": readiness_checks(failed="review")}
        )


def test_hybrid_publication_binds_exact_manifest_and_attestation() -> None:
    root = manifest_root()
    publication = HybridKnowledgePublicationRecord(
        publication_id="publication_1",
        source_id="ks_1",
        source_draft_version_id="draft_1",
        source_snapshot_id="snapshot_1",
        source_publication_seq=1,
        candidate_digest="8" * 64,
        generation_id="kig_1",
        manifest_ref=artifact_ref(root.root_sha256),
        attestation=attestation(),
        validation_id="validation_1",
        published_at=NOW,
        published_by="publisher_1",
    )
    assert (
        HybridKnowledgePublicationRecord.model_validate_json(publication.model_dump_json())
        == publication
    )
    with pytest.raises(ValidationError):
        HybridKnowledgePublicationRecord.model_validate(
            {**publication.model_dump(), "source_publication_seq": 2}
        )


def test_hybrid_resource_kind_preserves_existing_defaults_and_remote_behavior() -> None:
    validation_fields = {
        "validation_id": "validation_1",
        "source_id": "ks_1",
        "source_draft_version_id": "draft_1",
        "candidate_digest": "digest",
        "status": "passed",
        "smoke_query": "query",
        "candidate_count": 1,
        "citation_count": 1,
        "created_at": "2026-07-12T08:00:00Z",
        "created_by": "operator_1",
    }
    assert (
        KnowledgeSourcePublicationValidation(**validation_fields).resource_kind
        == "local_index_snapshot"
    )
    assert (
        KnowledgeSourcePublicationValidation(
            **validation_fields, resource_kind="remote_config"
        ).resource_kind
        == "remote_config"
    )
    assert (
        KnowledgeSourcePublicationValidation(
            **validation_fields, resource_kind="hybrid_publication"
        ).resource_kind
        == "hybrid_publication"
    )
    assert "hybrid_publication" in str(
        KnowledgeSourcePublicationRecord.model_fields["resource_kind"].annotation
    )
