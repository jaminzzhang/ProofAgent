from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_validator,
)

from proof_agent.contracts._base import FrozenModel


NonBlankStr = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1)]
UnmodifiedNonBlankStr = Annotated[StrictStr, StringConstraints(min_length=1)]
Sha256 = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]


def _validate_artifact_uri(value: str) -> str:
    if any(character.isspace() for character in value):
        raise ValueError("artifact_uri must not contain whitespace")
    if re.search(r"%(?![0-9A-Fa-f]{2})", value):
        raise ValueError("artifact_uri contains a malformed percent escape")
    try:
        parsed = urlsplit(value)
        username = parsed.username
        password = parsed.password
    except ValueError as exc:
        raise ValueError("artifact_uri is malformed") from exc
    if not parsed.scheme:
        raise ValueError("artifact_uri requires a URI scheme")
    if not parsed.netloc and not parsed.path.startswith("/"):
        raise ValueError("artifact_uri requires an authority or absolute path")
    if username is not None or password is not None or "@" in parsed.netloc:
        raise ValueError("artifact_uri must not contain userinfo")
    if parsed.query:
        raise ValueError("artifact_uri must not contain a query")
    if parsed.fragment:
        raise ValueError("artifact_uri must not contain a fragment")
    return value


_MEDIA_TYPE_PATTERN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+/[!#$%&'*+.^_`|~0-9A-Za-z-]+$")


def _normalize_media_type(value: str) -> str:
    if _MEDIA_TYPE_PATTERN.fullmatch(value) is None:
        raise ValueError("media_type must be a type/subtype token without parameters")
    return value.lower()


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone offset")
    return value


AwareTimestamp = Annotated[
    datetime,
    Field(strict=True),
    AfterValidator(_require_aware),
]


class _KnowledgeIndexModel(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ExactArtifactRef(_KnowledgeIndexModel):
    artifact_uri: Annotated[UnmodifiedNonBlankStr, AfterValidator(_validate_artifact_uri)]
    version_id: NonBlankStr
    sha256: Sha256
    size_bytes: NonNegativeInt
    media_type: Annotated[UnmodifiedNonBlankStr, AfterValidator(_normalize_media_type)]


class RuleUnitManifestEntry(_KnowledgeIndexModel):
    rule_unit_revision_id: NonBlankStr
    document_id: NonBlankStr
    revision_id: NonBlankStr
    structured_build_id: NonBlankStr
    metadata_revision_id: NonBlankStr
    visibility_revision_id: NonBlankStr
    content_sha256: Sha256
    authority_sha256: Sha256
    citation_uri: NonBlankStr
    publication_seq_from: PositiveInt
    publication_seq_to: PositiveInt | None = None

    @model_validator(mode="after")
    def validate_membership_interval(self) -> Self:
        if (
            self.publication_seq_to is not None
            and self.publication_seq_to < self.publication_seq_from
        ):
            raise ValueError("publication_seq_to must not precede publication_seq_from")
        return self


class RuleUnitManifestShard(_KnowledgeIndexModel):
    schema_version: Literal["rule-unit-manifest-shard.v1"]
    shard_id: NonBlankStr
    source_id: NonBlankStr
    generation_id: NonBlankStr
    document_id: NonBlankStr
    entries: tuple[RuleUnitManifestEntry, ...] = Field(min_length=1)
    sha256: Sha256

    @model_validator(mode="after")
    def canonicalize_entries(self) -> Self:
        entry_ids = [entry.rule_unit_revision_id for entry in self.entries]
        if len(entry_ids) != len(set(entry_ids)):
            raise ValueError("manifest entry identities must be unique")
        for entry in self.entries:
            if entry.document_id != self.document_id:
                raise ValueError("manifest entries must match the shard document_id")
        ordered = tuple(sorted(self.entries, key=lambda entry: entry.rule_unit_revision_id))
        if ordered != self.entries:
            object.__setattr__(self, "entries", ordered)
        return self


class RuleUnitManifestShardRef(_KnowledgeIndexModel):
    shard_id: NonBlankStr
    document_id: NonBlankStr
    artifact_ref: ExactArtifactRef
    rule_unit_count: PositiveInt


class RuleUnitManifestRoot(_KnowledgeIndexModel):
    schema_version: Literal["rule-unit-manifest-root.v1"]
    manifest_id: NonBlankStr
    source_id: NonBlankStr
    source_snapshot_id: NonBlankStr
    source_publication_seq: PositiveInt
    generation_id: NonBlankStr
    shards: tuple[RuleUnitManifestShardRef, ...] = Field(min_length=1)
    document_count: PositiveInt
    rule_unit_count: PositiveInt
    root_sha256: Sha256
    created_at: AwareTimestamp

    @model_validator(mode="after")
    def validate_and_canonicalize_shards(self) -> Self:
        shard_ids = [shard.shard_id for shard in self.shards]
        document_ids = [shard.document_id for shard in self.shards]
        if len(shard_ids) != len(set(shard_ids)):
            raise ValueError("manifest shard identities must be unique")
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("manifest shard document identities must be unique")
        if self.document_count != len(self.shards):
            raise ValueError("document_count must equal the number of manifest shards")
        if self.rule_unit_count != sum(shard.rule_unit_count for shard in self.shards):
            raise ValueError("rule_unit_count must equal the sum of shard counts")
        ordered = tuple(sorted(self.shards, key=lambda shard: shard.document_id))
        if ordered != self.shards:
            object.__setattr__(self, "shards", ordered)
        return self


class KnowledgePublicationAttempt(_KnowledgeIndexModel):
    attempt_id: NonBlankStr
    source_id: NonBlankStr
    source_draft_version_id: NonBlankStr
    candidate_digest: Sha256
    reserved_publication_seq: PositiveInt
    fencing_token: PositiveInt
    generation_id: NonBlankStr
    validation_id: NonBlankStr
    state: Literal["BUILDING", "VALIDATED", "PUBLISHED", "FAILED"]
    started_at: AwareTimestamp
    updated_at: AwareTimestamp
    failure_code: NonBlankStr | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        if self.updated_at < self.started_at:
            raise ValueError("updated_at must not precede started_at")
        if self.state == "FAILED" and self.failure_code is None:
            raise ValueError("FAILED attempts require failure_code")
        if self.state != "FAILED" and self.failure_code is not None:
            raise ValueError("only FAILED attempts accept failure_code")
        return self


class KnowledgeIndexGeneration(_KnowledgeIndexModel):
    generation_id: NonBlankStr
    source_id: NonBlankStr
    canonical_schema_version: NonBlankStr
    search_projection_version: NonBlankStr
    mapping_sha256: Sha256
    analyzer_sha256: Sha256
    embedding_model_revision: NonBlankStr
    embedding_instruction_sha256: Sha256
    embedding_dimension: PositiveInt
    embedding_pooling: NonBlankStr = "mean"
    normalized: StrictBool


class PrevalidatedRetrievalDegradation(_KnowledgeIndexModel):
    degradation_id: NonBlankStr
    mode: Literal["BM25_ONLY", "RRF_WITHOUT_RERANKER"]
    source_id: NonBlankStr
    query_type: Literal["clause_lookup", "conditional_guidance", "comparison"]
    sealed_evaluation_ref: ExactArtifactRef


class KnowledgeRetrievalProfileRevision(_KnowledgeIndexModel):
    profile_revision_id: NonBlankStr
    lexical_budget: PositiveInt
    dense_budget: PositiveInt
    rrf_window: PositiveInt
    reranker_revision: NonBlankStr
    rerank_budget: PositiveInt
    final_budget: PositiveInt
    query_expansion_revision: NonBlankStr | None = None
    fusion_revision: NonBlankStr | None = None
    context_expansion_revision: NonBlankStr | None = None
    enabled_degradations: tuple[PrevalidatedRetrievalDegradation, ...] = ()

    @model_validator(mode="after")
    def validate_budgets_and_degradations(self) -> Self:
        if self.final_budget > self.rerank_budget:
            raise ValueError("final_budget must not exceed rerank_budget")
        if self.rerank_budget > self.rrf_window:
            raise ValueError("rerank_budget must not exceed rrf_window")
        if self.rrf_window > self.lexical_budget + self.dense_budget:
            raise ValueError("rrf_window must not exceed total lane candidates")
        degradation_ids = [item.degradation_id for item in self.enabled_degradations]
        if len(degradation_ids) != len(set(degradation_ids)):
            raise ValueError("degradation identities must be unique")
        ordered = tuple(sorted(self.enabled_degradations, key=lambda item: item.degradation_id))
        if ordered != self.enabled_degradations:
            object.__setattr__(self, "enabled_degradations", ordered)
        return self


class KnowledgeProjectionAttestation(_KnowledgeIndexModel):
    attestation_id: NonBlankStr
    attestation_sha256: Sha256
    source_id: NonBlankStr
    generation_id: NonBlankStr
    publication_attempt_id: NonBlankStr
    index_uuid: NonBlankStr
    refresh_checkpoint: NonBlankStr
    manifest_root_sha256: Sha256
    mapping_sha256: Sha256
    covered_publication_sequences: tuple[PositiveInt, ...] = Field(min_length=1)
    parent_attestation_sha256: Sha256 | None = None
    projection_sha256: Sha256
    validated_document_count: NonNegativeInt
    validated_rule_unit_count: NonNegativeInt

    @model_validator(mode="after")
    def validate_chain_and_coverage(self) -> Self:
        sequences = self.covered_publication_sequences
        if len(sequences) != len(set(sequences)):
            raise ValueError("covered publication sequences must be unique")
        if self.parent_attestation_sha256 == self.attestation_sha256:
            raise ValueError("an attestation cannot refer to itself as parent")
        ordered = tuple(sorted(sequences))
        if ordered != sequences:
            object.__setattr__(self, "covered_publication_sequences", ordered)
        return self


class HybridKnowledgeRevisionReviewRecord(_KnowledgeIndexModel):
    review_id: NonBlankStr
    source_id: NonBlankStr
    document_id: NonBlankStr
    revision_id: NonBlankStr
    structured_build_id: NonBlankStr
    state: Literal["NOT_REQUIRED", "REVIEW_REQUIRED", "APPROVED", "REJECTED"]
    reason_codes: tuple[NonBlankStr, ...] = ()
    reviewed_by: NonBlankStr | None = None
    reviewed_at: AwareTimestamp | None = None

    @model_validator(mode="after")
    def validate_review_state(self) -> Self:
        if len(self.reason_codes) != len(set(self.reason_codes)):
            raise ValueError("review reason codes must be unique")
        ordered = tuple(sorted(self.reason_codes))
        if ordered != self.reason_codes:
            object.__setattr__(self, "reason_codes", ordered)
        has_reviewer = self.reviewed_by is not None and self.reviewed_at is not None
        has_partial_reviewer = (self.reviewed_by is None) != (self.reviewed_at is None)
        if has_partial_reviewer:
            raise ValueError("reviewed_by and reviewed_at must be supplied together")
        if self.state in {"APPROVED", "REJECTED"} and not has_reviewer:
            raise ValueError("completed reviews require reviewer identity and timestamp")
        if self.state == "REVIEW_REQUIRED" and not self.reason_codes:
            raise ValueError("REVIEW_REQUIRED requires at least one reason code")
        if self.state == "REVIEW_REQUIRED" and has_reviewer:
            raise ValueError("REVIEW_REQUIRED does not accept completed review details")
        if self.state == "REJECTED" and not self.reason_codes:
            raise ValueError("REJECTED requires at least one reason code")
        if self.state == "NOT_REQUIRED" and (
            self.reason_codes or self.reviewed_by is not None or self.reviewed_at is not None
        ):
            raise ValueError("NOT_REQUIRED does not accept review details")
        return self


ReadinessCheckName = Literal[
    "structured_artifact",
    "rule_units_approved",
    "embeddings",
    "search_projection",
    "citations",
    "manifest_membership",
    "integrity",
    "review",
]
_REQUIRED_READINESS_CHECKS = frozenset(
    {
        "structured_artifact",
        "rule_units_approved",
        "embeddings",
        "search_projection",
        "citations",
        "manifest_membership",
        "integrity",
        "review",
    }
)


class HybridReadinessCheck(_KnowledgeIndexModel):
    check: ReadinessCheckName
    passed: StrictBool
    blocker_codes: tuple[NonBlankStr, ...] = ()
    evidence_ref: ExactArtifactRef | None = None

    @model_validator(mode="after")
    def validate_blockers(self) -> Self:
        if len(self.blocker_codes) != len(set(self.blocker_codes)):
            raise ValueError("readiness blocker codes must be unique")
        ordered = tuple(sorted(self.blocker_codes))
        if ordered != self.blocker_codes:
            object.__setattr__(self, "blocker_codes", ordered)
        if self.passed and self.blocker_codes:
            raise ValueError("passing checks do not accept blockers")
        if not self.passed and not self.blocker_codes:
            raise ValueError("failing checks require at least one blocker")
        return self


class HybridKnowledgeRevisionReadinessRecord(_KnowledgeIndexModel):
    readiness_id: NonBlankStr
    source_id: NonBlankStr
    document_id: NonBlankStr
    revision_id: NonBlankStr
    structured_build_id: NonBlankStr
    status: Literal["READY", "BLOCKED"]
    checks: tuple[HybridReadinessCheck, ...]
    evaluated_at: AwareTimestamp

    @model_validator(mode="after")
    def validate_readiness(self) -> Self:
        check_names = [check.check for check in self.checks]
        if len(check_names) != len(set(check_names)):
            raise ValueError("readiness checks must be unique")
        if set(check_names) != _REQUIRED_READINESS_CHECKS:
            raise ValueError("readiness requires exactly one of every required check")
        ordered = tuple(sorted(self.checks, key=lambda check: check.check))
        if ordered != self.checks:
            object.__setattr__(self, "checks", ordered)
        all_passed = all(check.passed for check in self.checks)
        if (self.status == "READY") != all_passed:
            raise ValueError("READY requires every check to pass; BLOCKED requires a failure")
        return self


class HybridKnowledgePublicationRecord(_KnowledgeIndexModel):
    publication_id: NonBlankStr
    source_id: NonBlankStr
    source_draft_version_id: NonBlankStr
    source_snapshot_id: NonBlankStr
    source_publication_seq: PositiveInt
    candidate_digest: Sha256
    generation_id: NonBlankStr
    manifest_ref: ExactArtifactRef
    attestation: KnowledgeProjectionAttestation
    validation_id: NonBlankStr
    published_at: AwareTimestamp
    published_by: NonBlankStr

    @model_validator(mode="after")
    def validate_authority_bindings(self) -> Self:
        attestation = self.attestation
        if attestation.source_id != self.source_id:
            raise ValueError("attestation source_id must match publication")
        if attestation.generation_id != self.generation_id:
            raise ValueError("attestation generation_id must match publication")
        if attestation.manifest_root_sha256 != self.manifest_ref.sha256:
            raise ValueError("attestation must cover the exact manifest root")
        if self.source_publication_seq not in attestation.covered_publication_sequences:
            raise ValueError("attestation must cover the publication sequence")
        return self
