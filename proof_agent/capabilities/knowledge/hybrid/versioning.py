"""Canonical compatibility fingerprints for Hybrid Knowledge artifacts."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import TypeVar, cast

from pydantic import BaseModel

from proof_agent.capabilities.knowledge.hybrid.rule_units import InsuranceRuleUnitDraft
from proof_agent.contracts.insurance_rules import (
    ApprovedInsuranceKnowledgeVisibilityScope,
    ApprovedInsuranceRuleMetadataRevision,
    InsuranceRuleUnitLineage,
    InsuranceRuleUnitRevision,
)
from proof_agent.contracts.knowledge_index import (
    KnowledgeIndexGeneration,
    KnowledgeProjectionAttestation,
    KnowledgeRetrievalProfileRevision,
    PrevalidatedRetrievalDegradation,
    RuleUnitManifestEntry,
    RuleUnitManifestRoot,
    RuleUnitManifestShard,
    RuleUnitManifestShardRef,
)


_MAX_CANONICAL_JSON_DEPTH = 64
_MAX_CANONICAL_JSON_NODES = 200_000
_MAX_MODEL_DIGESTS = 64
_MAX_DEGRADATIONS = 128
_MAX_MANIFEST_ENTRIES = 100_000
_MAX_MANIFEST_SHARDS = 10_000
_MAX_ATTESTED_SEQUENCES = 10_000
_MAX_IDENTIFIER_LENGTH = 512
_MAX_POSITIVE_INTEGER = (1 << 63) - 1
_MIN_CANONICAL_INTEGER = -(1 << 63)
_SHA256_LENGTH = 64
_VALIDATION_SHA256 = "0" * _SHA256_LENGTH
_VALIDATION_CREATED_AT = datetime(1970, 1, 1, tzinfo=UTC)
_ModelT = TypeVar("_ModelT", bound=BaseModel)


def stable_digest(value: Mapping[str, object]) -> str:
    """Hash an exact JSON-native mapping after recursive canonical validation."""

    if type(value) is not dict:
        raise TypeError("canonical JSON root must be an exact dict")
    _validate_canonical_json(value, depth=0, active_containers=set(), node_count=[0])

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

    raw_model_digests = _bounded_sequence(
        model_digests,
        field_name="model_digests",
        minimum=0,
        maximum=_MAX_MODEL_DIGESTS,
    )
    canonical_model_digests = tuple(
        sorted(
            _canonical_nonblank_string(item, field_name="model_digests item")
            for item in raw_model_digests
        )
    )
    if len(canonical_model_digests) != len(set(canonical_model_digests)):
        raise ValueError("model_digests must contain unique values")
    validated_source_sha256 = _sha256(source_sha256, field_name="source_sha256")
    validated_parser_adapter = _canonical_nonblank_string(
        parser_adapter, field_name="parser_adapter"
    )
    validated_parser_revision = _canonical_nonblank_string(
        parser_revision, field_name="parser_revision"
    )
    validated_schema_version = _canonical_nonblank_string(
        canonical_schema_version, field_name="canonical_schema_version"
    )
    validated_configuration_sha256 = _sha256(
        configuration_sha256, field_name="configuration_sha256"
    )

    return stable_digest(
        {
            "fingerprint_schema": "structured-build-fingerprint.v1",
            "source_sha256": validated_source_sha256,
            "parser_adapter": validated_parser_adapter,
            "parser_revision": validated_parser_revision,
            "model_digests": list(canonical_model_digests),
            "canonical_schema_version": validated_schema_version,
            "configuration_sha256": validated_configuration_sha256,
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

    validated = KnowledgeIndexGeneration.model_validate(
        {
            "generation_id": "fingerprint-validation",
            "source_id": "fingerprint-validation",
            "canonical_schema_version": _canonical_nonblank_string(
                canonical_schema_version, field_name="canonical_schema_version"
            ),
            "search_projection_version": _canonical_nonblank_string(
                search_projection_version, field_name="search_projection_version"
            ),
            "mapping_sha256": _sha256(mapping_sha256, field_name="mapping_sha256"),
            "analyzer_sha256": _sha256(analyzer_sha256, field_name="analyzer_sha256"),
            "embedding_model_revision": _canonical_nonblank_string(
                embedding_model_revision, field_name="embedding_model_revision"
            ),
            "embedding_instruction_sha256": _sha256(
                embedding_instruction_sha256,
                field_name="embedding_instruction_sha256",
            ),
            "embedding_dimension": _positive_integer(
                embedding_dimension, field_name="embedding_dimension"
            ),
            "embedding_pooling": _canonical_nonblank_string(
                embedding_pooling, field_name="embedding_pooling"
            ),
            "normalized": _exact_bool(normalized, field_name="normalized"),
        }
    )

    return stable_digest(
        {
            "fingerprint_schema": "knowledge-index-generation-fingerprint.v1",
            "canonical_schema_version": validated.canonical_schema_version,
            "search_projection_version": validated.search_projection_version,
            "mapping_sha256": validated.mapping_sha256,
            "analyzer_sha256": validated.analyzer_sha256,
            "embedding_model_revision": validated.embedding_model_revision,
            "embedding_instruction_sha256": validated.embedding_instruction_sha256,
            "embedding_dimension": validated.embedding_dimension,
            "embedding_pooling": validated.embedding_pooling,
            "normalized": validated.normalized,
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

    raw_degradations = _bounded_sequence(
        enabled_degradations,
        field_name="enabled_degradations",
        minimum=0,
        maximum=_MAX_DEGRADATIONS,
    )
    degradations = tuple(
        _strict_contract_instance(
            degradation,
            PrevalidatedRetrievalDegradation,
            field_name="enabled_degradations item",
        )
        for degradation in raw_degradations
    )
    validated = KnowledgeRetrievalProfileRevision.model_validate(
        {
            "profile_revision_id": "fingerprint-validation",
            "lexical_budget": _positive_integer(lexical_budget, field_name="lexical_budget"),
            "dense_budget": _positive_integer(dense_budget, field_name="dense_budget"),
            "rrf_window": _positive_integer(rrf_window, field_name="rrf_window"),
            "reranker_revision": _canonical_nonblank_string(
                reranker_revision, field_name="reranker_revision"
            ),
            "rerank_budget": _positive_integer(rerank_budget, field_name="rerank_budget"),
            "final_budget": _positive_integer(final_budget, field_name="final_budget"),
            "query_expansion_revision": _optional_canonical_nonblank_string(
                query_expansion_revision, field_name="query_expansion_revision"
            ),
            "fusion_revision": _optional_canonical_nonblank_string(
                fusion_revision, field_name="fusion_revision"
            ),
            "context_expansion_revision": _optional_canonical_nonblank_string(
                context_expansion_revision, field_name="context_expansion_revision"
            ),
            "enabled_degradations": degradations,
        }
    )
    return stable_digest(
        {
            "fingerprint_schema": "knowledge-retrieval-profile-fingerprint.v1",
            "lexical_budget": validated.lexical_budget,
            "dense_budget": validated.dense_budget,
            "rrf_window": validated.rrf_window,
            "reranker_revision": validated.reranker_revision,
            "rerank_budget": validated.rerank_budget,
            "final_budget": validated.final_budget,
            "query_expansion_revision": validated.query_expansion_revision,
            "fusion_revision": validated.fusion_revision,
            "context_expansion_revision": validated.context_expansion_revision,
            "enabled_degradations": [
                degradation.model_dump(mode="json")
                for degradation in validated.enabled_degradations
            ],
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

    raw_entries = _bounded_sequence(
        entries,
        field_name="entries",
        minimum=1,
        maximum=_MAX_MANIFEST_ENTRIES,
    )
    validated_entries = tuple(
        _strict_contract_instance(
            entry,
            RuleUnitManifestEntry,
            field_name="entries item",
        )
        for entry in raw_entries
    )
    validated = RuleUnitManifestShard.model_validate(
        {
            "schema_version": _canonical_nonblank_string(
                schema_version, field_name="schema_version"
            ),
            "shard_id": "fingerprint-validation",
            "source_id": _canonical_nonblank_string(source_id, field_name="source_id"),
            "generation_id": _canonical_nonblank_string(
                generation_id, field_name="generation_id"
            ),
            "document_id": _canonical_nonblank_string(document_id, field_name="document_id"),
            "entries": validated_entries,
            "sha256": _VALIDATION_SHA256,
        }
    )
    return stable_digest(
        {
            "fingerprint_schema": "rule-unit-manifest-shard-fingerprint.v1",
            "schema_version": validated.schema_version,
            "source_id": validated.source_id,
            "generation_id": validated.generation_id,
            "document_id": validated.document_id,
            "entries": [entry.model_dump(mode="json") for entry in validated.entries],
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

    raw_shards = _bounded_sequence(
        shards,
        field_name="shards",
        minimum=1,
        maximum=_MAX_MANIFEST_SHARDS,
    )
    validated_shards = tuple(
        _strict_contract_instance(
            shard,
            RuleUnitManifestShardRef,
            field_name="shards item",
        )
        for shard in raw_shards
    )
    validated = RuleUnitManifestRoot.model_validate(
        {
            "schema_version": _canonical_nonblank_string(
                schema_version, field_name="schema_version"
            ),
            "manifest_id": "fingerprint-validation",
            "source_id": _canonical_nonblank_string(source_id, field_name="source_id"),
            "source_snapshot_id": _canonical_nonblank_string(
                source_snapshot_id, field_name="source_snapshot_id"
            ),
            "source_publication_seq": _positive_integer(
                source_publication_seq, field_name="source_publication_seq"
            ),
            "generation_id": _canonical_nonblank_string(
                generation_id, field_name="generation_id"
            ),
            "shards": validated_shards,
            "document_count": _positive_integer(document_count, field_name="document_count"),
            "rule_unit_count": _positive_integer(rule_unit_count, field_name="rule_unit_count"),
            "root_sha256": _VALIDATION_SHA256,
            "created_at": _VALIDATION_CREATED_AT,
        }
    )
    return stable_digest(
        {
            "fingerprint_schema": "rule-unit-manifest-root-fingerprint.v1",
            "schema_version": validated.schema_version,
            "source_id": validated.source_id,
            "source_snapshot_id": validated.source_snapshot_id,
            "source_publication_seq": validated.source_publication_seq,
            "generation_id": validated.generation_id,
            "shards": [shard.model_dump(mode="json") for shard in validated.shards],
            "document_count": validated.document_count,
            "rule_unit_count": validated.rule_unit_count,
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

    raw_sequences = _bounded_sequence(
        covered_publication_sequences,
        field_name="covered_publication_sequences",
        minimum=1,
        maximum=_MAX_ATTESTED_SEQUENCES,
    )
    sequences = tuple(
        sorted(
            _positive_integer(sequence, field_name="covered_publication_sequences item")
            for sequence in raw_sequences
        )
    )
    if len(sequences) != len(set(sequences)):
        raise ValueError("covered_publication_sequences must contain unique values")
    payload: dict[str, object] = {
        "fingerprint_schema": "knowledge-projection-attestation-fingerprint.v1",
        "source_id": _canonical_nonblank_string(source_id, field_name="source_id"),
        "generation_id": _canonical_nonblank_string(
            generation_id, field_name="generation_id"
        ),
        "publication_attempt_id": _canonical_nonblank_string(
            publication_attempt_id, field_name="publication_attempt_id"
        ),
        "index_uuid": _canonical_nonblank_string(index_uuid, field_name="index_uuid"),
        "refresh_checkpoint": _canonical_nonblank_string(
            refresh_checkpoint, field_name="refresh_checkpoint"
        ),
        "manifest_root_sha256": _sha256(
            manifest_root_sha256, field_name="manifest_root_sha256"
        ),
        "mapping_sha256": _sha256(mapping_sha256, field_name="mapping_sha256"),
        "covered_publication_sequences": list(sequences),
        "parent_attestation_sha256": _optional_sha256(
            parent_attestation_sha256, field_name="parent_attestation_sha256"
        ),
        "projection_sha256": _sha256(projection_sha256, field_name="projection_sha256"),
        "validated_document_count": _positive_integer(
            validated_document_count, field_name="validated_document_count"
        ),
        "validated_rule_unit_count": _positive_integer(
            validated_rule_unit_count, field_name="validated_rule_unit_count"
        ),
    }
    digest = stable_digest(payload)
    KnowledgeProjectionAttestation.model_validate(
        {
            "attestation_id": f"attestation-{digest}",
            "attestation_sha256": digest,
            **{key: value for key, value in payload.items() if key != "fingerprint_schema"},
        }
    )
    return digest


def _validate_canonical_json(
    value: object,
    *,
    depth: int,
    active_containers: set[int],
    node_count: list[int],
) -> None:
    node_count[0] += 1
    if node_count[0] > _MAX_CANONICAL_JSON_NODES:
        raise ValueError("canonical JSON exceeds the node limit")
    if depth > _MAX_CANONICAL_JSON_DEPTH:
        raise ValueError("canonical JSON exceeds the nesting limit")

    value_type = type(value)
    if value is None or value_type in {str, bool}:
        return
    if value_type is int:
        integer = cast(int, value)
        if not _MIN_CANONICAL_INTEGER <= integer <= _MAX_POSITIVE_INTEGER:
            raise ValueError("canonical JSON integer exceeds the signed 64-bit limit")
        return
    if value_type is float:
        floating = cast(float, value)
        if not math.isfinite(floating):
            raise ValueError("canonical JSON floats must be finite")
        return
    if value_type not in {dict, list}:
        raise TypeError("canonical JSON accepts only exact JSON-native value types")

    identity = id(value)
    if identity in active_containers:
        raise ValueError("canonical JSON must not contain cycles")
    active_containers.add(identity)
    try:
        if value_type is dict:
            mapping = cast(dict[object, object], value)
            for key, item in mapping.items():
                if type(key) is not str:
                    raise TypeError("canonical JSON object keys must be exact strings")
                _validate_canonical_json(
                    item,
                    depth=depth + 1,
                    active_containers=active_containers,
                    node_count=node_count,
                )
        else:
            array = cast(list[object], value)
            for item in array:
                _validate_canonical_json(
                    item,
                    depth=depth + 1,
                    active_containers=active_containers,
                    node_count=node_count,
                )
    finally:
        active_containers.remove(identity)


def _bounded_sequence(
    value: object,
    *,
    field_name: str,
    minimum: int,
    maximum: int,
) -> tuple[object, ...]:
    if type(value) not in {list, tuple}:
        raise TypeError(f"{field_name} must be an exact list or tuple")
    sequence = cast(list[object] | tuple[object, ...], value)
    result: tuple[object, ...] = tuple(sequence)
    if not minimum <= len(result) <= maximum:
        raise ValueError(f"{field_name} length is outside the allowed bounds")
    return result


def _canonical_nonblank_string(value: object, *, field_name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be an exact string")
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be nonblank and canonically trimmed")
    if len(value) > _MAX_IDENTIFIER_LENGTH:
        raise ValueError(f"{field_name} exceeds the length limit")
    return value


def _optional_canonical_nonblank_string(
    value: object,
    *,
    field_name: str,
) -> str | None:
    if value is None:
        return None
    return _canonical_nonblank_string(value, field_name=field_name)


def _sha256(value: object, *, field_name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be an exact string")
    if len(value) != _SHA256_LENGTH or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _optional_sha256(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _sha256(value, field_name=field_name)


def _positive_integer(value: object, *, field_name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{field_name} must be an exact integer")
    if not 1 <= value <= _MAX_POSITIVE_INTEGER:
        raise ValueError(f"{field_name} must be a bounded positive integer")
    return value


def _exact_bool(value: object, *, field_name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{field_name} must be an exact boolean")
    return value


def _strict_contract_instance(
    value: object,
    model_type: type[_ModelT],
    *,
    field_name: str,
) -> _ModelT:
    if type(value) is not model_type:
        raise TypeError(f"{field_name} must be an exact {model_type.__name__} instance")
    raw = value.model_dump(mode="python")
    validated = model_type.model_validate(raw)
    if validated.model_dump(mode="python") != raw:
        raise ValueError(f"{field_name} must already use its canonical contract form")
    return validated


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
