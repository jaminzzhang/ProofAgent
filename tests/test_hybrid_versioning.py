from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

import pytest

from proof_agent.capabilities.knowledge.hybrid.versioning import (
    index_generation_fingerprint,
    manifest_root_fingerprint,
    manifest_shard_fingerprint,
    projection_attestation_fingerprint,
    retrieval_profile_revision_fingerprint,
    stable_digest,
    structured_build_fingerprint,
)
from proof_agent.contracts import (
    ExactArtifactRef,
    PrevalidatedRetrievalDegradation,
    RuleUnitManifestEntry,
    RuleUnitManifestShardRef,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64


def generation_fields() -> dict[str, object]:
    return {
        "canonical_schema_version": "structured-knowledge.v1",
        "search_projection_version": "rule-unit-search.v1",
        "mapping_sha256": SHA_A,
        "analyzer_sha256": SHA_B,
        "embedding_model_revision": "embedding@sha256:model-v1",
        "embedding_instruction_sha256": SHA_C,
        "embedding_dimension": 1024,
        "embedding_pooling": "mean",
        "normalized": True,
    }


def profile_fields() -> dict[str, object]:
    return {
        "lexical_budget": 100,
        "dense_budget": 100,
        "rrf_window": 50,
        "reranker_revision": "reranker@sha256:model-v1",
        "rerank_budget": 40,
        "final_budget": 16,
        "query_expansion_revision": "query-expansion.v1",
        "fusion_revision": "rrf.v1",
        "context_expansion_revision": "rule-context.v1",
        "enabled_degradations": (),
    }


GENERATION_CHANGES: dict[str, object] = {
    "canonical_schema_version": "structured-knowledge.v2",
    "search_projection_version": "rule-unit-search.v2",
    "mapping_sha256": SHA_D,
    "analyzer_sha256": SHA_D,
    "embedding_model_revision": "embedding@sha256:model-v2",
    "embedding_instruction_sha256": SHA_D,
    "embedding_dimension": 512,
    "embedding_pooling": "cls",
    "normalized": False,
}


PROFILE_CHANGES: dict[str, object] = {
    "lexical_budget": 120,
    "dense_budget": 120,
    "rrf_window": 60,
    "reranker_revision": "reranker@sha256:model-v2",
    "rerank_budget": 45,
    "final_budget": 12,
    "query_expansion_revision": "query-expansion.v2",
    "fusion_revision": "rrf.v2",
    "context_expansion_revision": "rule-context.v2",
    "enabled_degradations": (
        PrevalidatedRetrievalDegradation(
            degradation_id="degradation-1",
            mode="BM25_ONLY",
            source_id="source-1",
            query_type="clause_lookup",
            sealed_evaluation_ref=ExactArtifactRef(
                artifact_uri="s3://knowledge/evaluations/sealed.json",
                version_id="version-1",
                sha256=SHA_A,
                size_bytes=42,
                media_type="application/json",
            ),
        ),
    ),
}


@pytest.mark.parametrize("field", tuple(GENERATION_CHANGES))
def test_index_compatibility_field_changes_generation(field: str) -> None:
    baseline = generation_fields()
    changed = generation_fields()
    changed[field] = GENERATION_CHANGES[field]

    assert index_generation_fingerprint(**changed) != index_generation_fingerprint(**baseline)  # type: ignore[arg-type]


@pytest.mark.parametrize("field", tuple(PROFILE_CHANGES))
def test_query_time_field_changes_profile_but_not_generation(field: str) -> None:
    baseline_profile = profile_fields()
    changed_profile = profile_fields()
    changed_profile[field] = PROFILE_CHANGES[field]
    baseline_generation = generation_fields()

    assert retrieval_profile_revision_fingerprint(
        **changed_profile  # type: ignore[arg-type]
    ) != retrieval_profile_revision_fingerprint(**baseline_profile)  # type: ignore[arg-type]
    assert index_generation_fingerprint(
        **baseline_generation  # type: ignore[arg-type]
    ) == index_generation_fingerprint(**generation_fields())  # type: ignore[arg-type]


@pytest.mark.parametrize("field", tuple(PROFILE_CHANGES))
def test_generation_fingerprint_rejects_query_time_fields(field: str) -> None:
    values = generation_fields()
    values[field] = PROFILE_CHANGES[field]

    with pytest.raises(TypeError, match="unexpected keyword argument"):
        index_generation_fingerprint(**values)  # type: ignore[arg-type]


def test_stable_digest_uses_canonical_unicode_json() -> None:
    assert stable_digest({"产品": "意外险", "version": 1}) == stable_digest(
        {"version": 1, "产品": "意外险"}
    )


@pytest.mark.parametrize(
    "value",
    (
        {1: "same"},
        {"nested": {1: "same"}},
        {"value": Decimal("1")},
        {"value": (1, 2)},
        {"value": {1, 2}},
        {"value": float("nan")},
        {"value": float("inf")},
    ),
)
def test_stable_digest_rejects_noncanonical_json_values(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        stable_digest(value)  # type: ignore[arg-type]


def test_stable_digest_does_not_coerce_numeric_mapping_keys() -> None:
    canonical = stable_digest({"1": "same"})

    with pytest.raises(TypeError, match="keys must be exact strings"):
        stable_digest({1: "same"})  # type: ignore[dict-item]
    assert canonical == stable_digest({"1": "same"})


def test_stable_digest_rejects_nested_numeric_mapping_keys() -> None:
    with pytest.raises(TypeError, match="keys must be exact strings"):
        stable_digest({"nested": {1: "same"}})  # type: ignore[dict-item]


def test_stable_digest_keeps_boolean_and_integer_types_distinct() -> None:
    assert stable_digest({"value": True}) != stable_digest({"value": 1})


STRUCTURED_BUILD_CHANGES: dict[str, object] = {
    "source_sha256": SHA_D,
    "parser_adapter": "docling",
    "parser_revision": "docling-3+paddle-4",
    "model_digests": ("sha256:model-c",),
    "canonical_schema_version": "structured-knowledge.v2",
    "configuration_sha256": SHA_C,
}


def structured_build_fields() -> dict[str, object]:
    return {
        "source_sha256": SHA_A,
        "parser_adapter": "docling+paddle",
        "parser_revision": "docling-2+paddle-3",
        "model_digests": ("sha256:model-a", "sha256:model-b"),
        "canonical_schema_version": "structured-knowledge.v1",
        "configuration_sha256": SHA_B,
    }


@pytest.mark.parametrize("field", tuple(STRUCTURED_BUILD_CHANGES))
def test_structured_build_field_changes_build_fingerprint(field: str) -> None:
    baseline = structured_build_fields()
    changed = {**baseline, field: STRUCTURED_BUILD_CHANGES[field]}

    assert structured_build_fingerprint(
        **baseline  # type: ignore[arg-type]
    ) != structured_build_fingerprint(**changed)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "model_digests",
    (
        "ab",
        b"ab",
        ("sha256:model-a", "sha256:model-a"),
        ("",),
        (" model",),
        (1,),
        tuple(f"sha256:model-{index}" for index in range(65)),
    ),
)
def test_structured_build_rejects_malformed_model_digest_sequences(
    model_digests: object,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        structured_build_fingerprint(
            **{**structured_build_fields(), "model_digests": model_digests}  # type: ignore[arg-type]
        )


def test_structured_build_digest_sequence_is_canonical_and_not_scalar_coercion() -> None:
    fields = structured_build_fields()
    first = structured_build_fingerprint(**fields)  # type: ignore[arg-type]
    reversed_digest = structured_build_fingerprint(
        **{
            **fields,
            "model_digests": tuple(reversed(fields["model_digests"])),  # type: ignore[arg-type]
        }
    )

    with pytest.raises(TypeError, match="exact list or tuple"):
        structured_build_fingerprint(**{**fields, "model_digests": "ab"})  # type: ignore[arg-type]
    assert first == reversed_digest


def test_structured_build_rejects_scalar_that_json_would_split_like_a_sequence() -> None:
    fields = structured_build_fields()
    tuple_digest = structured_build_fingerprint(
        **{**fields, "model_digests": ("a", "b")}  # type: ignore[arg-type]
    )

    with pytest.raises(TypeError, match="exact list or tuple"):
        structured_build_fingerprint(**{**fields, "model_digests": "ab"})  # type: ignore[arg-type]
    assert tuple_digest == structured_build_fingerprint(
        **{**fields, "model_digests": ("b", "a")}  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    ("field", "invalid"),
    (
        ("mapping_sha256", "A" * 64),
        ("analyzer_sha256", "short"),
        ("embedding_instruction_sha256", "g" * 64),
        ("embedding_dimension", 0),
        ("embedding_dimension", True),
        ("normalized", 1),
        ("embedding_model_revision", " "),
        ("embedding_pooling", " mean "),
    ),
)
def test_generation_rejects_malformed_compatibility_fields(
    field: str,
    invalid: object,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        index_generation_fingerprint(
            **{**generation_fields(), field: invalid}  # type: ignore[arg-type]
        )


def degradation(degradation_id: str) -> PrevalidatedRetrievalDegradation:
    return PrevalidatedRetrievalDegradation(
        degradation_id=degradation_id,
        mode="BM25_ONLY",
        source_id="source-1",
        query_type="clause_lookup",
        sealed_evaluation_ref=ExactArtifactRef(
            artifact_uri="s3://knowledge/evaluations/sealed.json",
            version_id="version-1",
            sha256=SHA_A,
            size_bytes=42,
            media_type="application/json",
        ),
    )


@pytest.mark.parametrize(
    "updates",
    (
        {"lexical_budget": 0},
        {"dense_budget": True},
        {"rrf_window": 201},
        {"rerank_budget": 51},
        {"final_budget": 41},
        {"reranker_revision": " "},
        {"query_expansion_revision": " query-expansion.v1 "},
        {"enabled_degradations": "degradation-1"},
    ),
)
def test_profile_rejects_invalid_budgets_and_sequences(updates: dict[str, object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        retrieval_profile_revision_fingerprint(
            **{**profile_fields(), **updates}  # type: ignore[arg-type]
        )


def test_profile_rejects_duplicate_and_construct_bypassed_degradations() -> None:
    duplicate_semantics = (degradation("degradation-1"), degradation("degradation-2"))
    valid = degradation("degradation-3")
    bypassed = PrevalidatedRetrievalDegradation.model_construct(
        degradation_id=valid.degradation_id,
        mode=valid.mode,
        source_id=valid.source_id,
        query_type="not-a-query-type",
        sealed_evaluation_ref=valid.sealed_evaluation_ref,
    )

    with pytest.raises(ValueError, match="unique by mode, source, and query type"):
        retrieval_profile_revision_fingerprint(
            **{**profile_fields(), "enabled_degradations": duplicate_semantics}  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError):
        retrieval_profile_revision_fingerprint(
            **{**profile_fields(), "enabled_degradations": (bypassed,)}  # type: ignore[arg-type]
        )


def manifest_entry(
    rule_unit_revision_id: str = "rule-unit-1",
    *,
    document_id: str = "document-1",
) -> RuleUnitManifestEntry:
    return RuleUnitManifestEntry(
        rule_unit_revision_id=rule_unit_revision_id,
        document_id=document_id,
        revision_id="revision-1",
        structured_build_id="build-1",
        metadata_revision_id="metadata-1",
        visibility_revision_id="visibility-1",
        content_sha256=SHA_A,
        authority_sha256=SHA_B,
        citation_uri=(
            "knowledge://source/source-1/document/document-1/revision/revision-1#page=1"
        ),
        publication_seq_from=1,
    )


def shard_ref(
    document_id: str = "document-1",
    *,
    shard_id: str | None = None,
) -> RuleUnitManifestShardRef:
    return RuleUnitManifestShardRef(
        shard_id=shard_id or f"shard-{document_id}",
        document_id=document_id,
        artifact_ref=ExactArtifactRef(
            artifact_uri=f"s3://knowledge/manifests/{document_id}.json",
            version_id="version-1",
            sha256=SHA_C,
            size_bytes=42,
            media_type="application/json",
        ),
        rule_unit_count=1,
    )


def manifest_shard_fields() -> dict[str, object]:
    return {
        "schema_version": "rule-unit-manifest-shard.v1",
        "source_id": "source-1",
        "generation_id": "generation-1",
        "document_id": "document-1",
        "entries": (manifest_entry(),),
    }


def manifest_root_fields() -> dict[str, object]:
    return {
        "schema_version": "rule-unit-manifest-root.v1",
        "source_id": "source-1",
        "source_snapshot_id": "snapshot-1",
        "source_publication_seq": 1,
        "generation_id": "generation-1",
        "shards": (shard_ref(),),
        "document_count": 1,
        "rule_unit_count": 1,
    }


def attestation_fields() -> dict[str, object]:
    return {
        "source_id": "source-1",
        "generation_id": "generation-1",
        "publication_attempt_id": "attempt-1",
        "index_uuid": "index-uuid-1",
        "refresh_checkpoint": "refresh-1",
        "manifest_root_sha256": SHA_A,
        "mapping_sha256": SHA_B,
        "covered_publication_sequences": (1,),
        "parent_attestation_sha256": None,
        "projection_sha256": SHA_C,
        "validated_document_count": 1,
        "validated_rule_unit_count": 1,
    }


@pytest.mark.parametrize(
    ("fingerprint", "baseline", "changed"),
    (
        (
            manifest_shard_fingerprint,
            {
                "schema_version": "rule-unit-manifest-shard.v1",
                "source_id": "source-1",
                "generation_id": "generation-1",
                "document_id": "document-1",
                "entries": (manifest_entry(),),
            },
            {"entries": (manifest_entry("rule-unit-2"),)},
        ),
        (
            manifest_root_fingerprint,
            {
                "schema_version": "rule-unit-manifest-root.v1",
                "source_id": "source-1",
                "source_snapshot_id": "snapshot-1",
                "source_publication_seq": 1,
                "generation_id": "generation-1",
                "shards": (shard_ref(),),
                "document_count": 1,
                "rule_unit_count": 1,
            },
            {"source_publication_seq": 2},
        ),
        (
            projection_attestation_fingerprint,
            {
                "source_id": "source-1",
                "generation_id": "generation-1",
                "publication_attempt_id": "attempt-1",
                "index_uuid": "index-uuid-1",
                "refresh_checkpoint": "refresh-1",
                "manifest_root_sha256": SHA_A,
                "mapping_sha256": SHA_B,
                "covered_publication_sequences": (1,),
                "parent_attestation_sha256": None,
                "projection_sha256": SHA_C,
                "validated_document_count": 1,
                "validated_rule_unit_count": 1,
            },
            {"refresh_checkpoint": "refresh-2"},
        ),
    ),
)
def test_authority_artifact_fingerprints_cover_declared_fields(
    fingerprint: Callable[..., str],
    baseline: dict[str, object],
    changed: dict[str, object],
) -> None:
    assert fingerprint(**baseline) != fingerprint(**{**baseline, **changed})


def test_manifest_and_attestation_set_like_fields_are_order_stable() -> None:
    first_entry = manifest_entry("rule-unit-1")
    second_entry = manifest_entry("rule-unit-2")
    shard_fields = {
        "schema_version": "rule-unit-manifest-shard.v1",
        "source_id": "source-1",
        "generation_id": "generation-1",
        "document_id": "document-1",
    }
    attestation_fields = {
        "source_id": "source-1",
        "generation_id": "generation-1",
        "publication_attempt_id": "attempt-1",
        "index_uuid": "index-uuid-1",
        "refresh_checkpoint": "refresh-1",
        "manifest_root_sha256": SHA_A,
        "mapping_sha256": SHA_B,
        "parent_attestation_sha256": None,
        "projection_sha256": SHA_C,
        "validated_document_count": 2,
        "validated_rule_unit_count": 2,
    }

    assert manifest_shard_fingerprint(
        **shard_fields, entries=(first_entry, second_entry)  # type: ignore[arg-type]
    ) == manifest_shard_fingerprint(
        **shard_fields, entries=(second_entry, first_entry)  # type: ignore[arg-type]
    )
    assert projection_attestation_fingerprint(
        **attestation_fields, covered_publication_sequences=(1, 2)  # type: ignore[arg-type]
    ) == projection_attestation_fingerprint(
        **attestation_fields, covered_publication_sequences=(2, 1)  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    "updates",
    (
        {"entries": ()},
        {"entries": "rule-unit-1"},
        {"entries": (manifest_entry(), manifest_entry())},
        {"entries": (manifest_entry(document_id="document-2"),)},
        {"source_id": " "},
        {"schema_version": "rule-unit-manifest-shard.v2"},
    ),
)
def test_manifest_shard_rejects_invalid_membership(updates: dict[str, object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        manifest_shard_fingerprint(
            **{**manifest_shard_fields(), **updates}  # type: ignore[arg-type]
        )


def test_manifest_shard_rejects_construct_bypassed_entry() -> None:
    entry = manifest_entry()
    bypassed = RuleUnitManifestEntry.model_construct(
        **{**entry.model_dump(mode="python"), "content_sha256": "not-a-digest"}
    )

    with pytest.raises(ValueError):
        manifest_shard_fingerprint(
            **{**manifest_shard_fields(), "entries": (bypassed,)}  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "updates",
    (
        {"shards": ()},
        {"shards": "shard-1"},
        {"shards": (shard_ref(), shard_ref())},
        {
            "shards": (
                shard_ref(shard_id="shard-1"),
                shard_ref(shard_id="shard-2"),
            ),
            "document_count": 2,
            "rule_unit_count": 2,
        },
        {"document_count": 2},
        {"rule_unit_count": 2},
        {"source_publication_seq": 0},
        {"source_publication_seq": True},
        {"source_snapshot_id": " snapshot-1 "},
        {"schema_version": "rule-unit-manifest-root.v2"},
    ),
)
def test_manifest_root_rejects_invalid_shards_and_counts(updates: dict[str, object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        manifest_root_fingerprint(
            **{**manifest_root_fields(), **updates}  # type: ignore[arg-type]
        )


def test_manifest_root_rejects_construct_bypassed_shard_ref() -> None:
    ref = shard_ref()
    bypassed = RuleUnitManifestShardRef.model_construct(
        shard_id=ref.shard_id,
        document_id=ref.document_id,
        artifact_ref=ref.artifact_ref,
        rule_unit_count=0,
    )

    with pytest.raises(ValueError):
        manifest_root_fingerprint(
            **{**manifest_root_fields(), "shards": (bypassed,)}  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "updates",
    (
        {"covered_publication_sequences": "1"},
        {"covered_publication_sequences": ()},
        {"covered_publication_sequences": (1, 1)},
        {"covered_publication_sequences": (0,)},
        {"covered_publication_sequences": (True,)},
        {"validated_document_count": 0},
        {"validated_document_count": True},
        {"validated_rule_unit_count": 0},
        {"manifest_root_sha256": "A" * 64},
        {"mapping_sha256": "short"},
        {"projection_sha256": "g" * 64},
        {"parent_attestation_sha256": "bad"},
        {"index_uuid": " "},
        {"publication_attempt_id": " attempt-1 "},
    ),
)
def test_projection_attestation_rejects_invalid_authority_inputs(
    updates: dict[str, object],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        projection_attestation_fingerprint(
            **{**attestation_fields(), **updates}  # type: ignore[arg-type]
        )
