from datetime import UTC, datetime
from typing import Literal

import pytest
from pydantic import ValidationError

from proof_agent.contracts import (
    ExactArtifactRef,
    HybridKnowledgePublicationRecord,
    HybridKnowledgeRevisionReadinessRecord,
    HybridKnowledgeRevisionReviewRecord,
    HybridPublicationAuthorityChain,
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
            evidence_ref=(artifact_ref() if name != "review" and name != failed else None),
        )
        for name in names
    )  # type: ignore[arg-type]


def approved_review(
    *, state: Literal["APPROVED", "NOT_REQUIRED"] = "APPROVED", source_id: str = "ks_1"
) -> HybridKnowledgeRevisionReviewRecord:
    if state == "NOT_REQUIRED":
        return HybridKnowledgeRevisionReviewRecord(
            review_id="review_1",
            source_id=source_id,
            document_id="doc_1",
            revision_id="rev_1",
            structured_build_id="build_1",
            state="NOT_REQUIRED",
        )
    return HybridKnowledgeRevisionReviewRecord(
        review_id="review_1",
        source_id=source_id,
        document_id="doc_1",
        revision_id="rev_1",
        structured_build_id="build_1",
        state="APPROVED",
        reviewed_by="reviewer_1",
        reviewed_at=NOW,
    )


def generation(**updates: object) -> KnowledgeIndexGeneration:
    values: dict[str, object] = {
        "generation_id": "kig_1",
        "source_id": "ks_1",
        "canonical_schema_version": "structured-knowledge.v1",
        "search_projection_version": "rule-unit-search.v1",
        "mapping_sha256": "a" * 64,
        "analyzer_sha256": "b" * 64,
        "embedding_model_revision": "embedding@sha256:model",
        "embedding_instruction_sha256": "c" * 64,
        "embedding_dimension": 1024,
        "normalized": True,
    }
    values.update(updates)
    return KnowledgeIndexGeneration(**values)  # type: ignore[arg-type]


def published_attempt(**updates: object) -> KnowledgePublicationAttempt:
    values: dict[str, object] = {
        "attempt_id": "attempt_1",
        "source_id": "ks_1",
        "source_draft_version_id": "draft_1",
        "candidate_digest": "8" * 64,
        "reserved_publication_seq": 1,
        "fencing_token": 1,
        "generation_id": "kig_1",
        "validation_id": "validation_1",
        "state": "PUBLISHED",
        "started_at": NOW,
        "updated_at": NOW,
    }
    values.update(updates)
    return KnowledgePublicationAttempt(**values)  # type: ignore[arg-type]


def hybrid_publication(
    *,
    record_attestation: KnowledgeProjectionAttestation | None = None,
    **updates: object,
) -> HybridKnowledgePublicationRecord:
    bound_attestation = record_attestation or attestation()
    values: dict[str, object] = {
        "publication_id": "publication_1",
        "source_id": "ks_1",
        "source_draft_version_id": "draft_1",
        "source_snapshot_id": "snapshot_1",
        "source_publication_seq": 1,
        "candidate_digest": "8" * 64,
        "generation_id": "kig_1",
        "manifest_ref": artifact_ref("5" * 64),
        "attestation": bound_attestation,
        "validation_id": "validation_1",
        "published_at": NOW,
        "published_by": "publisher_1",
    }
    values.update(updates)
    return HybridKnowledgePublicationRecord(**values)  # type: ignore[arg-type]


def authority_chain(**updates: object) -> HybridPublicationAuthorityChain:
    current_attestation = attestation()
    values: dict[str, object] = {
        "attempt": published_attempt(),
        "generation": generation(),
        "manifest_root": manifest_root(),
        "attestation": current_attestation,
        "publication": hybrid_publication(record_attestation=current_attestation),
    }
    values.update(updates)
    return HybridPublicationAuthorityChain(**values)  # type: ignore[arg-type]


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
        "https://host:8443/path",
        "file:///absolute/path",
        "file://localhost/absolute/path",
        "proofagent://artifact/id",
        "proofagent://[::1]:8443/id",
        "https://host/path%3Fpart%23anchor",
        "https://host/%E4%B8%AD",
    ],
)
def test_exact_artifact_ref_accepts_absolute_provider_neutral_uris(
    artifact_uri: str,
) -> None:
    ref = artifact_ref(artifact_uri=artifact_uri)
    assert ExactArtifactRef.model_validate_json(ref.model_dump_json()) == ref


def test_exact_artifact_ref_canonicalizes_supported_scheme_to_lowercase() -> None:
    equivalent_pairs = (
        ("S3://BUCKET/object", "s3://bucket/object"),
        ("HTTPS://EXAMPLE.COM:8443/path", "https://example.com:8443/path"),
        ("file://LOCALHOST/absolute/path", "file://localhost/absolute/path"),
        ("PROOFAGENT://ARTIFACT/id", "proofagent://artifact/id"),
    )
    for variant, canonical in equivalent_pairs:
        first = artifact_ref(artifact_uri=variant)
        second = artifact_ref(artifact_uri=canonical)
        assert first.artifact_uri == canonical
        assert first == second
        assert hash(first) == hash(second)
        assert ExactArtifactRef.model_validate_json(first.model_dump_json()) == second


@pytest.mark.parametrize(
    "artifact_uri",
    [
        "relative/path",
        "http://host/path",
        "ftp://host/path",
        " s3://bucket/key",
        "s3:/bucket/key",
        "s3:///key",
        "s3://bucket/",
        "s3://bucket:443/key",
        "proofagent:///artifact",
        "proofagent://artifact/",
        "file://remote/absolute/path",
        "file:/absolute/path",
        "https://host/",
        "https:///path",
        "https://bad_host/path",
        "https://host:not-a-port/path",
        "https://host:/path",
        "s3://bucket/key with space",
        "s3://bucket/key%2",
        "s3://bucket/key%3f",
        "s3://bucket/key%41",
        "s3://bucket/key%7E",
        "s3://bucket/a%2Fb",
        "s3://bucket/a%2fb",
        "s3://bucket/a%252Fb",
        "s3://bucket/a%252E%252E/b",
        "s3://bucket/a/../b",
        "s3://bucket/a/%2E%2E/b",
        "s3://bucket/a\\b",
        "s3://bucket/a%5Cb",
        "s3://bucket/a%0Ab",
        "https://user@host/path",
        "https://host/path?signature=secret",
        "https://host/path?",
        "https://host/path#fragment",
        "https://host/path#",
        "https://[broken/path",
        "https://host/a%2Fb",
        "https://host/a/../b",
        "https://host/a%252Fb",
        "file:///a%5Cb",
        "file:///a/../b",
        "file:///a%2Fb",
        "file:///a%252Fb",
        "proofagent://artifact/a%25b",
        "proofagent://artifact/a/../b",
        "proofagent://artifact/a%2Fb",
        "proofagent://artifact/a%252Fb",
        "https://host./path",
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


def test_manifest_entry_accepts_canonical_internal_citations() -> None:
    entry = manifest_entry()
    assert RuleUnitManifestEntry.model_validate_json(entry.model_dump_json()) == entry
    proofagent = RuleUnitManifestEntry.model_validate(
        {
            **entry.model_dump(),
            "citation_uri": "PROOFAGENT://SOURCE/%E4%B8%AD%3Fpart#page=1",
        }
    )
    canonical = RuleUnitManifestEntry.model_validate(
        {
            **entry.model_dump(),
            "citation_uri": "proofagent://source/%E4%B8%AD%3Fpart#page=1",
        }
    )
    assert proofagent == canonical
    assert hash(proofagent) == hash(canonical)


@pytest.mark.parametrize(
    "citation_uri",
    [
        "https://source/path#page=1",
        "knowledge:/source/path#page=1",
        "knowledge:///path#page=1",
        "knowledge://user@source/path#page=1",
        "knowledge://source/path?latest=true",
        "knowledge://source/path#",
        "knowledge://source/path#page=1#duplicate",
        "knowledge://source/a/../b#page=1",
        "knowledge://source/a%2fb#page=1",
        "knowledge://source/a%2Fb#page=1",
        "knowledge://source/a%5Cb#page=1",
        "knowledge://source/a%25b#page=1",
        "knowledge://source/a%252Fb#page=1",
        "knowledge://source/a%252E%252E/b#page=1",
        "knowledge://source/a%0Ab#page=1",
        "knowledge://source/a\\b#page=1",
        "knowledge://source./path#page=1",
        "proofagent://source/a%2Fb#page=1",
        "proofagent://source/a%252Fb#page=1",
    ],
)
def test_manifest_entry_rejects_noncanonical_internal_citations(
    citation_uri: str,
) -> None:
    with pytest.raises(ValidationError):
        RuleUnitManifestEntry.model_validate(
            {**manifest_entry().model_dump(), "citation_uri": citation_uri}
        )


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
    semantically_duplicate = degradation.model_copy(update={"degradation_id": "degradation_2"})
    with pytest.raises(ValidationError):
        KnowledgeRetrievalProfileRevision.model_validate(
            {
                **profile.model_dump(),
                "enabled_degradations": (degradation, semantically_duplicate),
            }
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
    with pytest.raises(ValidationError):
        attestation(validated_document_count=0)
    with pytest.raises(ValidationError):
        attestation(validated_rule_unit_count=0)


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
        review_record=approved_review(),
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
    without_evidence = ready.checks[0].model_copy(update={"evidence_ref": None})
    with pytest.raises(ValidationError):
        HybridReadinessCheck.model_validate(without_evidence.model_dump())
    with pytest.raises(ValidationError):
        HybridKnowledgeRevisionReadinessRecord.model_validate(
            {**ready.model_dump(), "review_record": approved_review(source_id="ks_other")}
        )
    for state in ("REVIEW_REQUIRED", "REJECTED"):
        pending_or_rejected = HybridKnowledgeRevisionReviewRecord(
            review_id="review_bad",
            source_id="ks_1",
            document_id="doc_1",
            revision_id="rev_1",
            structured_build_id="build_1",
            state=state,
            reason_codes=("BLOCKED",),
            reviewed_by="reviewer_1" if state == "REJECTED" else None,
            reviewed_at=NOW if state == "REJECTED" else None,
        )
        blocked = HybridKnowledgeRevisionReadinessRecord.model_validate(
            {
                **ready.model_dump(),
                "status": "BLOCKED",
                "checks": readiness_checks(failed="review"),
                "review_record": pending_or_rejected,
            }
        )
        assert blocked.status == "BLOCKED"
        with pytest.raises(ValidationError):
            HybridKnowledgeRevisionReadinessRecord.model_validate(
                {**ready.model_dump(), "review_record": pending_or_rejected}
            )
    approved_but_blocked_elsewhere = HybridKnowledgeRevisionReadinessRecord.model_validate(
        {
            **ready.model_dump(),
            "status": "BLOCKED",
            "checks": readiness_checks(failed="integrity"),
        }
    )
    assert approved_but_blocked_elsewhere.status == "BLOCKED"
    not_required = HybridKnowledgeRevisionReadinessRecord.model_validate(
        {**ready.model_dump(), "review_record": approved_review(state="NOT_REQUIRED")}
    )
    assert not_required.status == "READY"


def test_canonical_frozen_models_have_stable_hashes_and_permutation_identity() -> None:
    entry_1 = manifest_entry("ru_1")
    entry_2 = manifest_entry("ru_2")
    shard_values = {
        "schema_version": "rule-unit-manifest-shard.v1",
        "shard_id": "shard_1",
        "source_id": "ks_1",
        "generation_id": "kig_1",
        "document_id": "doc_1",
        "sha256": "4" * 64,
    }
    shard_a = RuleUnitManifestShard(**shard_values, entries=(entry_2, entry_1))
    shard_b = RuleUnitManifestShard(**shard_values, entries=(entry_1, entry_2))

    shard_ref_1 = RuleUnitManifestShardRef(
        shard_id="shard_1",
        document_id="doc_1",
        artifact_ref=artifact_ref("4" * 64),
        rule_unit_count=1,
    )
    shard_ref_2 = RuleUnitManifestShardRef(
        shard_id="shard_2",
        document_id="doc_2",
        artifact_ref=artifact_ref("9" * 64, artifact_uri="s3://knowledge/manifests/shard-2.json"),
        rule_unit_count=1,
    )
    root_values = {
        "schema_version": "rule-unit-manifest-root.v1",
        "manifest_id": "manifest_2",
        "source_id": "ks_1",
        "source_snapshot_id": "snapshot_1",
        "source_publication_seq": 1,
        "generation_id": "kig_1",
        "document_count": 2,
        "rule_unit_count": 2,
        "root_sha256": "5" * 64,
        "created_at": NOW,
    }
    root_a = RuleUnitManifestRoot(**root_values, shards=(shard_ref_2, shard_ref_1))
    root_b = RuleUnitManifestRoot(**root_values, shards=(shard_ref_1, shard_ref_2))

    degradation_1 = PrevalidatedRetrievalDegradation(
        degradation_id="d_1",
        mode="BM25_ONLY",
        source_id="ks_1",
        query_type="clause_lookup",
        sealed_evaluation_ref=artifact_ref(),
    )
    degradation_2 = PrevalidatedRetrievalDegradation(
        degradation_id="d_2",
        mode="RRF_WITHOUT_RERANKER",
        source_id="ks_1",
        query_type="comparison",
        sealed_evaluation_ref=artifact_ref(),
    )
    profile_values = {
        "profile_revision_id": "profile_1",
        "lexical_budget": 100,
        "dense_budget": 100,
        "rrf_window": 50,
        "reranker_revision": "reranker_1",
        "rerank_budget": 40,
        "final_budget": 16,
    }
    profile_a = KnowledgeRetrievalProfileRevision(
        **profile_values, enabled_degradations=(degradation_2, degradation_1)
    )
    profile_b = KnowledgeRetrievalProfileRevision(
        **profile_values, enabled_degradations=(degradation_1, degradation_2)
    )
    coverage_a = attestation(covered_publication_sequences=(2, 1))
    coverage_b = attestation(covered_publication_sequences=(1, 2))
    review_a = HybridKnowledgeRevisionReviewRecord(
        review_id="review_2",
        source_id="ks_1",
        document_id="doc_1",
        revision_id="rev_1",
        structured_build_id="build_1",
        state="REJECTED",
        reason_codes=("Z_REASON", "A_REASON"),
        reviewed_by="reviewer_1",
        reviewed_at=NOW,
    )
    review_b = review_a.model_copy(update={"reason_codes": ("A_REASON", "Z_REASON")})
    review_b = HybridKnowledgeRevisionReviewRecord.model_validate(review_b.model_dump())
    blocker_a = HybridReadinessCheck(
        check="integrity", passed=False, blocker_codes=("Z_BLOCK", "A_BLOCK")
    )
    blocker_b = HybridReadinessCheck(
        check="integrity", passed=False, blocker_codes=("A_BLOCK", "Z_BLOCK")
    )
    ready_a = HybridKnowledgeRevisionReadinessRecord(
        readiness_id="ready_1",
        source_id="ks_1",
        document_id="doc_1",
        revision_id="rev_1",
        structured_build_id="build_1",
        status="READY",
        checks=tuple(reversed(readiness_checks())),
        review_record=approved_review(),
        evaluated_at=NOW,
    )
    ready_b = HybridKnowledgeRevisionReadinessRecord(
        **{**ready_a.model_dump(), "checks": readiness_checks()}
    )

    for first, second in (
        (shard_a, shard_b),
        (root_a, root_b),
        (profile_a, profile_b),
        (coverage_a, coverage_b),
        (review_a, review_b),
        (blocker_a, blocker_b),
        (ready_a, ready_b),
    ):
        original_hash = hash(first)
        assert type(first).model_validate(first) is first
        assert hash(first) == original_hash
        assert first == second
        assert hash(first) == hash(second)


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


def test_hybrid_publication_authority_chain_round_trips() -> None:
    chain = authority_chain()
    assert HybridPublicationAuthorityChain.model_validate_json(chain.model_dump_json()) == chain


def test_hybrid_publication_authority_chain_rejects_one_field_mismatches() -> None:
    wrong_attempt_attestation = attestation(publication_attempt_id="attempt_other")
    wrong_document_count = attestation(validated_document_count=2)
    wrong_rule_count = attestation(validated_rule_unit_count=2)
    alternate_publication_attestation = attestation(attestation_id="attestation_other")
    lost_coverage = attestation(covered_publication_sequences=(2,))
    mismatches: tuple[tuple[str, dict[str, object]], ...] = (
        ("attempt state", {"attempt": published_attempt(state="BUILDING")}),
        ("attempt source", {"attempt": published_attempt(source_id="ks_other")}),
        (
            "manifest source",
            {"manifest_root": manifest_root().model_copy(update={"source_id": "ks_other"})},
        ),
        (
            "attempt id",
            {
                "attestation": wrong_attempt_attestation,
                "publication": hybrid_publication(record_attestation=wrong_attempt_attestation),
            },
        ),
        (
            "source draft",
            {"publication": hybrid_publication(source_draft_version_id="draft_other")},
        ),
        ("validation id", {"publication": hybrid_publication(validation_id="other")}),
        ("candidate digest", {"publication": hybrid_publication(candidate_digest="9" * 64)}),
        (
            "reserved sequence",
            {"attempt": published_attempt(reserved_publication_seq=2)},
        ),
        (
            "root sequence",
            {"manifest_root": manifest_root().model_copy(update={"source_publication_seq": 2})},
        ),
        (
            "publication sequence",
            {"publication": hybrid_publication().model_copy(update={"source_publication_seq": 2})},
        ),
        ("source snapshot", {"publication": hybrid_publication(source_snapshot_id="other")}),
        (
            "generation id",
            {"attempt": published_attempt(generation_id="generation_other")},
        ),
        ("current mapping", {"generation": generation(mapping_sha256="b" * 64)}),
        (
            "manifest root digest",
            {"manifest_root": manifest_root().model_copy(update={"root_sha256": "9" * 64})},
        ),
        (
            "publication manifest reference",
            {
                "publication": hybrid_publication().model_copy(
                    update={"manifest_ref": artifact_ref("9" * 64)}
                )
            },
        ),
        (
            "document count",
            {
                "attestation": wrong_document_count,
                "publication": hybrid_publication(record_attestation=wrong_document_count),
            },
        ),
        (
            "rule-unit count",
            {
                "attestation": wrong_rule_count,
                "publication": hybrid_publication(record_attestation=wrong_rule_count),
            },
        ),
        (
            "embedded attestation",
            {
                "publication": hybrid_publication(
                    record_attestation=alternate_publication_attestation
                )
            },
        ),
        (
            "current coverage",
            {
                "attestation": lost_coverage,
                "publication": hybrid_publication().model_copy(
                    update={"attestation": lost_coverage}
                ),
            },
        ),
    )
    for name, mismatch in mismatches:
        with pytest.raises(ValidationError) as error:
            authority_chain(**mismatch)
        assert error.value.errors(), name


def test_hybrid_publication_authority_chain_validates_parent_closure() -> None:
    parent = attestation()
    current = attestation(
        attestation_id="attestation_2",
        attestation_sha256="d" * 64,
        parent_attestation_sha256=parent.attestation_sha256,
        covered_publication_sequences=(1, 2),
    )
    root = manifest_root().model_copy(update={"source_publication_seq": 2})
    publication = hybrid_publication(
        record_attestation=current,
        source_publication_seq=2,
    )
    chain = authority_chain(
        attempt=published_attempt(reserved_publication_seq=2),
        manifest_root=root,
        parent_attestation=parent,
        attestation=current,
        publication=publication,
    )
    assert chain.parent_attestation == parent
    parent_mismatches = (
        (
            "parent digest",
            {
                "attestation": current.model_copy(update={"parent_attestation_sha256": "9" * 64}),
                "publication": publication.model_copy(
                    update={
                        "attestation": current.model_copy(
                            update={"parent_attestation_sha256": "9" * 64}
                        )
                    }
                ),
            },
        ),
        ("parent source", {"parent_attestation": parent.model_copy(update={"source_id": "other"})}),
        (
            "parent generation",
            {"parent_attestation": parent.model_copy(update={"generation_id": "other"})},
        ),
        (
            "parent mapping",
            {"parent_attestation": parent.model_copy(update={"mapping_sha256": "b" * 64})},
        ),
        (
            "lost retained coverage",
            {
                "parent_attestation": parent.model_copy(
                    update={"covered_publication_sequences": (1, 3)}
                )
            },
        ),
    )
    for name, updates in parent_mismatches:
        with pytest.raises(ValidationError) as error:
            HybridPublicationAuthorityChain.model_validate({**chain.model_dump(), **updates})
        assert error.value.errors(), name
    with pytest.raises(ValidationError):
        authority_chain(attestation=current, publication=publication)


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
            **validation_fields,
            resource_kind="hybrid_publication",
            resource_id="publication_1",
        ).resource_kind
        == "hybrid_publication"
    )
    assert "hybrid_publication" in str(
        KnowledgeSourcePublicationRecord.model_fields["resource_kind"].annotation
    )
    with pytest.raises(ValidationError):
        KnowledgeSourcePublicationValidation(
            **validation_fields, resource_kind="hybrid_publication"
        )
    with pytest.raises(ValidationError):
        KnowledgeSourcePublicationValidation(
            **validation_fields,
            resource_kind="hybrid_publication",
            resource_id="publication_1",
            snapshot_id="snapshot_1",
        )

    record_fields = {
        "publication_id": "source_publication_1",
        "source_id": "ks_1",
        "source_draft_version_id": "draft_1",
        "validation_id": "validation_1",
        "change_note": "publish",
        "published_at": "2026-07-12T08:00:00Z",
        "published_by": "operator_1",
        "document_count": 1,
        "smoke_query": "query",
    }
    assert KnowledgeSourcePublicationRecord(**record_fields).resource_kind == "local_index_snapshot"
    assert (
        KnowledgeSourcePublicationRecord(
            **record_fields,
            resource_kind="remote_config",
            resource_id=None,
            snapshot_id="legacy-remote-shape",
        ).resource_kind
        == "remote_config"
    )
    assert (
        KnowledgeSourcePublicationRecord(
            **record_fields,
            resource_kind="hybrid_publication",
            resource_id="publication_1",
        ).resource_id
        == "publication_1"
    )
    with pytest.raises(ValidationError):
        KnowledgeSourcePublicationRecord(**record_fields, resource_kind="hybrid_publication")
    with pytest.raises(ValidationError):
        KnowledgeSourcePublicationRecord(
            **record_fields,
            resource_kind="hybrid_publication",
            resource_id="publication_1",
            snapshot_id="snapshot_1",
        )
