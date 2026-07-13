"""Canonical compatibility fingerprints for Hybrid Knowledge artifacts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

from proof_agent.capabilities.knowledge.hybrid.rule_units import InsuranceRuleUnitDraft
from proof_agent.contracts.insurance_rules import (
    ApprovedInsuranceKnowledgeVisibilityScope,
    ApprovedInsuranceRuleMetadataRevision,
    InsuranceRuleUnitLineage,
    InsuranceRuleUnitRevision,
)
from proof_agent.contracts.knowledge_index import (
    PrevalidatedRetrievalDegradation,
    RuleUnitManifestEntry,
    RuleUnitManifestShardRef,
)


def stable_digest(value: Mapping[str, object]) -> str:
    """Hash a mapping with one stable UTF-8 canonical JSON representation."""

    payload = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def structured_build_fingerprint(
    *,
    source_sha256: str,
    parser_adapter: str,
    parser_revision: str,
    model_digests: Sequence[str],
    canonical_schema_version: str,
    configuration_sha256: str,
) -> str:
    """Fingerprint only fields that determine one structured derivative build."""

    return stable_digest(
        {
            "fingerprint_schema": "structured-build-fingerprint.v1",
            "source_sha256": source_sha256,
            "parser_adapter": parser_adapter,
            "parser_revision": parser_revision,
            "model_digests": list(model_digests),
            "canonical_schema_version": canonical_schema_version,
            "configuration_sha256": configuration_sha256,
        }
    )


def index_generation_fingerprint(
    *,
    canonical_schema_version: str,
    search_projection_version: str,
    mapping_sha256: str,
    analyzer_sha256: str,
    embedding_model_revision: str,
    embedding_instruction_sha256: str,
    embedding_dimension: int,
    embedding_pooling: str,
    normalized: bool,
) -> str:
    """Fingerprint stored index compatibility without query-time behavior."""

    return stable_digest(
        {
            "fingerprint_schema": "knowledge-index-generation-fingerprint.v1",
            "canonical_schema_version": canonical_schema_version,
            "search_projection_version": search_projection_version,
            "mapping_sha256": mapping_sha256,
            "analyzer_sha256": analyzer_sha256,
            "embedding_model_revision": embedding_model_revision,
            "embedding_instruction_sha256": embedding_instruction_sha256,
            "embedding_dimension": embedding_dimension,
            "embedding_pooling": embedding_pooling,
            "normalized": normalized,
        }
    )


def retrieval_profile_revision_fingerprint(
    *,
    lexical_budget: int,
    dense_budget: int,
    rrf_window: int,
    reranker_revision: str,
    rerank_budget: int,
    final_budget: int,
    query_expansion_revision: str | None,
    fusion_revision: str | None,
    context_expansion_revision: str | None,
    enabled_degradations: Sequence[PrevalidatedRetrievalDegradation],
) -> str:
    """Fingerprint immutable query-time retrieval behavior without index fields."""

    degradations = sorted(
        (
            degradation.model_dump(mode="json")
            for degradation in enabled_degradations
        ),
        key=lambda item: str(item["degradation_id"]),
    )
    return stable_digest(
        {
            "fingerprint_schema": "knowledge-retrieval-profile-fingerprint.v1",
            "lexical_budget": lexical_budget,
            "dense_budget": dense_budget,
            "rrf_window": rrf_window,
            "reranker_revision": reranker_revision,
            "rerank_budget": rerank_budget,
            "final_budget": final_budget,
            "query_expansion_revision": query_expansion_revision,
            "fusion_revision": fusion_revision,
            "context_expansion_revision": context_expansion_revision,
            "enabled_degradations": degradations,
        }
    )


def manifest_shard_fingerprint(
    *,
    schema_version: str,
    source_id: str,
    generation_id: str,
    document_id: str,
    entries: Sequence[RuleUnitManifestEntry],
) -> str:
    """Fingerprint one canonical, content-addressed Rule Unit manifest shard."""

    canonical_entries = sorted(
        (entry.model_dump(mode="json") for entry in entries),
        key=lambda item: str(item["rule_unit_revision_id"]),
    )
    return stable_digest(
        {
            "fingerprint_schema": "rule-unit-manifest-shard-fingerprint.v1",
            "schema_version": schema_version,
            "source_id": source_id,
            "generation_id": generation_id,
            "document_id": document_id,
            "entries": canonical_entries,
        }
    )


def manifest_root_fingerprint(
    *,
    schema_version: str,
    source_id: str,
    source_snapshot_id: str,
    source_publication_seq: int,
    generation_id: str,
    shards: Sequence[RuleUnitManifestShardRef],
    document_count: int,
    rule_unit_count: int,
) -> str:
    """Fingerprint one publication manifest root without creation metadata."""

    canonical_shards = sorted(
        (shard.model_dump(mode="json") for shard in shards),
        key=lambda item: str(item["document_id"]),
    )
    return stable_digest(
        {
            "fingerprint_schema": "rule-unit-manifest-root-fingerprint.v1",
            "schema_version": schema_version,
            "source_id": source_id,
            "source_snapshot_id": source_snapshot_id,
            "source_publication_seq": source_publication_seq,
            "generation_id": generation_id,
            "shards": canonical_shards,
            "document_count": document_count,
            "rule_unit_count": rule_unit_count,
        }
    )


def projection_attestation_fingerprint(
    *,
    source_id: str,
    generation_id: str,
    publication_attempt_id: str,
    index_uuid: str,
    refresh_checkpoint: str,
    manifest_root_sha256: str,
    mapping_sha256: str,
    covered_publication_sequences: Sequence[int],
    parent_attestation_sha256: str | None,
    projection_sha256: str,
    validated_document_count: int,
    validated_rule_unit_count: int,
) -> str:
    """Fingerprint one exact index-projection proof and its chain position."""

    return stable_digest(
        {
            "fingerprint_schema": "knowledge-projection-attestation-fingerprint.v1",
            "source_id": source_id,
            "generation_id": generation_id,
            "publication_attempt_id": publication_attempt_id,
            "index_uuid": index_uuid,
            "refresh_checkpoint": refresh_checkpoint,
            "manifest_root_sha256": manifest_root_sha256,
            "mapping_sha256": mapping_sha256,
            "covered_publication_sequences": sorted(covered_publication_sequences),
            "parent_attestation_sha256": parent_attestation_sha256,
            "projection_sha256": projection_sha256,
            "validated_document_count": validated_document_count,
            "validated_rule_unit_count": validated_rule_unit_count,
        }
    )


def materialize_rule_unit_revision(
    draft: InsuranceRuleUnitDraft,
    *,
    approved_metadata: ApprovedInsuranceRuleMetadataRevision,
    approved_visibility: ApprovedInsuranceKnowledgeVisibilityScope,
) -> InsuranceRuleUnitRevision:
    """Materialize one approved revision; the review-only logical key is not its identity."""

    # Revalidate inputs so model_copy/model_construct cannot bypass lineage validators at the
    # identity boundary.
    draft = InsuranceRuleUnitDraft.model_validate(draft.model_dump())
    approved_metadata = ApprovedInsuranceRuleMetadataRevision.model_validate(
        approved_metadata.model_dump()
    )
    approved_visibility = ApprovedInsuranceKnowledgeVisibilityScope.model_validate(
        approved_visibility.model_dump()
    )
    content_sha256 = _sha256_text(draft.content)
    authority_payload = {
        "approved_metadata": approved_metadata.model_dump(mode="json"),
        "approved_visibility": approved_visibility.model_dump(mode="json"),
    }
    authority_sha256 = _sha256_json(authority_payload)
    projection_payload = draft.model_dump(
        mode="json",
        exclude={"logical_rule_key", "inherited_metadata", "ordinal"},
    )
    identity_payload = {
        "schema_version": "insurance-rule-unit-revision.v1",
        "projection": projection_payload,
        "content_sha256": content_sha256,
        "structured_build_identity": draft.structured_build_identity.model_dump(mode="json"),
        "approved_metadata": approved_metadata.model_dump(mode="json"),
        "approved_visibility": approved_visibility.model_dump(mode="json"),
    }
    revision_id = f"rur-{_sha256_json(identity_payload)}"
    return InsuranceRuleUnitRevision(
        rule_unit_revision_id=revision_id,
        logical_rule_key=draft.logical_rule_key,
        unit_kind=draft.unit_kind,
        document_id=draft.document_id,
        revision_id=draft.revision_id,
        structured_build_id=draft.structured_build_id,
        content=draft.content,
        citation_uri=draft.citation_uri,
        metadata_revision_id=approved_metadata.metadata_revision_id,
        visibility_scope=approved_visibility,
        content_sha256=content_sha256,
        authority_sha256=authority_sha256,
        lineage=InsuranceRuleUnitLineage(
            source_id=draft.source_id,
            original_sha256=draft.original_sha256,
            heading_path=draft.heading_path,
            definitions=draft.definitions,
            page_numbers=draft.page_numbers,
            page_bboxes=draft.page_bboxes,
            block_ids=draft.block_ids,
            table_id=draft.table_id,
            table_continuation_id=draft.table_continuation_id,
            table_title=draft.table_title,
            table_headers=draft.table_headers,
            row_header=draft.row_header,
            row_numbers=draft.row_numbers,
            header_cell_coordinates=draft.header_cell_coordinates,
            cell_coordinates=draft.cell_coordinates,
        ),
    )


def rule_unit_revision_fingerprint(
    draft: InsuranceRuleUnitDraft,
    *,
    approved_metadata: ApprovedInsuranceRuleMetadataRevision,
    approved_visibility: ApprovedInsuranceKnowledgeVisibilityScope,
) -> str:
    """Return the immutable revision identity without exposing review-key semantics."""

    return materialize_rule_unit_revision(
        draft,
        approved_metadata=approved_metadata,
        approved_visibility=approved_visibility,
    ).rule_unit_revision_id


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: object) -> str:
    if not isinstance(value, Mapping):
        raise TypeError("canonical identity payload must be a mapping")
    return stable_digest(value)


__all__ = [
    "index_generation_fingerprint",
    "manifest_root_fingerprint",
    "manifest_shard_fingerprint",
    "materialize_rule_unit_revision",
    "projection_attestation_fingerprint",
    "retrieval_profile_revision_fingerprint",
    "rule_unit_revision_fingerprint",
    "stable_digest",
    "structured_build_fingerprint",
]
