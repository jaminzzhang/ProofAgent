from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from ipaddress import ip_address
from typing import Annotated, Literal, Self
from urllib.parse import unquote_to_bytes, urlsplit

from pydantic import (
    AfterValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from proof_agent.contracts._base import FrozenModel


NonBlankStr = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1)]
UnmodifiedNonBlankStr = Annotated[StrictStr, StringConstraints(min_length=1)]
Sha256 = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]


def _raw_string_key(value: object, field_name: str) -> str:
    attribute = getattr(value, field_name, None)
    if isinstance(attribute, str):
        return attribute
    if isinstance(value, Mapping):
        raw = value.get(field_name)
        if isinstance(raw, str):
            return raw
    return ""


def _canonicalize_string_tuple(value: object) -> object:
    if not isinstance(value, list | tuple):
        return value
    if not all(isinstance(item, str) for item in value):
        return tuple(value)
    return tuple(sorted(value))


_PERCENT_ESCAPE = re.compile(r"%[0-9A-F]{2}")
_HOST_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_CITATION_FRAGMENT = re.compile(r"^[A-Za-z0-9._~!$&'()*+,;=:@/%-]+$")


def _validate_percent_encoding(value: str, *, field_name: str) -> None:
    index = 0
    while index < len(value):
        if value[index] != "%":
            index += 1
            continue
        if _PERCENT_ESCAPE.match(value, index) is None:
            raise ValueError(f"{field_name} contains a malformed or noncanonical percent escape")
        decoded_character = chr(int(value[index + 1 : index + 3], 16))
        if decoded_character in {"/", "\\", "%"}:
            raise ValueError(f"{field_name} must not percent-encode separators or percent signs")
        if decoded_character.isascii() and (
            decoded_character.isalnum() or decoded_character in "-._~"
        ):
            raise ValueError(f"{field_name} percent-encodes an unreserved character")
        index += 3


def _validate_uri_characters(value: str, *, field_name: str) -> None:
    if not value.isascii():
        raise ValueError(f"{field_name} source must contain ASCII characters only")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{field_name} must not contain ASCII controls")
    if any(character.isspace() for character in value):
        raise ValueError(f"{field_name} must not contain whitespace")
    if "\\" in value:
        raise ValueError(f"{field_name} must not contain backslashes")
    _validate_percent_encoding(value, field_name=field_name)
    decoded = unquote_to_bytes(value)
    try:
        decoded.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{field_name} contains invalid UTF-8 percent encoding") from exc
    if any(byte < 32 or byte == 127 for byte in decoded):
        raise ValueError(f"{field_name} must not contain percent-encoded ASCII controls")
    if b"\\" in decoded:
        raise ValueError(f"{field_name} must not contain percent-encoded backslashes")


def _canonicalize_hostname(hostname: str | None, *, field_name: str) -> str:
    if not hostname:
        raise ValueError(f"{field_name} requires a hostname")
    if hostname.endswith("."):
        raise ValueError(f"{field_name} must not contain a trailing-dot hostname")
    try:
        return ip_address(hostname).compressed.lower()
    except ValueError:
        pass
    if all(character.isdigit() or character == "." for character in hostname):
        raise ValueError(f"{field_name} contains an invalid IPv4 literal")
    if len(hostname) > 253 or any(
        _HOST_LABEL.fullmatch(label) is None for label in hostname.split(".")
    ):
        raise ValueError(f"{field_name} contains an invalid hostname")
    return hostname.lower()


def _validate_canonical_path(path: str, *, field_name: str) -> None:
    if not path.startswith("/") or path == "/":
        raise ValueError(f"{field_name} requires a nonempty absolute path")
    for segment in path.split("/"):
        decoded = unquote_to_bytes(segment)
        if decoded in {b".", b".."}:
            raise ValueError(f"{field_name} must not contain dot path segments")


def _validate_artifact_uri(value: str) -> str:
    _validate_uri_characters(value, field_name="artifact_uri")
    if "?" in value or "#" in value:
        raise ValueError("artifact_uri must not contain query or fragment delimiters")
    raw_scheme, separator, remainder = value.partition(":")
    if not separator:
        raise ValueError("artifact_uri requires a URI scheme")
    scheme = raw_scheme.lower()
    if scheme not in {"https", "s3", "file", "proofagent"}:
        raise ValueError("artifact_uri uses an unsupported scheme")
    if not remainder.startswith("//"):
        raise ValueError("artifact_uri requires an unambiguous authority form")
    canonical = f"{scheme}:{remainder}"
    try:
        parsed = urlsplit(canonical)
        username = parsed.username
        password = parsed.password
        port = parsed.port
    except ValueError as exc:
        raise ValueError("artifact_uri is malformed") from exc
    if username is not None or password is not None or "@" in parsed.netloc:
        raise ValueError("artifact_uri must not contain userinfo")
    _validate_canonical_path(parsed.path, field_name="artifact_uri")
    canonical_authority = parsed.netloc.lower()
    if scheme == "https":
        if parsed.netloc.endswith(":"):
            raise ValueError("artifact_uri contains an empty port")
        if port is not None and not 1 <= port <= 65535:
            raise ValueError("artifact_uri contains an invalid port")
        hostname = _canonicalize_hostname(parsed.hostname, field_name="artifact_uri")
        if ":" in hostname:
            hostname = f"[{hostname}]"
        canonical_authority = hostname + (f":{port}" if port is not None and port != 443 else "")
    elif scheme == "s3":
        if not parsed.netloc:
            raise ValueError("s3 artifact_uri requires a bucket authority")
        if parsed.hostname != parsed.netloc.lower():
            raise ValueError("s3 artifact_uri authority must be a bucket without a port")
        canonical_authority = _canonicalize_hostname(parsed.hostname, field_name="artifact_uri")
    elif scheme == "proofagent":
        if not parsed.netloc:
            raise ValueError("proofagent artifact_uri requires an authority")
        if parsed.netloc.endswith(":"):
            raise ValueError("artifact_uri contains an empty port")
        if port is not None and not 1 <= port <= 65535:
            raise ValueError("artifact_uri contains an invalid port")
        hostname = _canonicalize_hostname(parsed.hostname, field_name="artifact_uri")
        if ":" in hostname:
            hostname = f"[{hostname}]"
        canonical_authority = hostname + (f":{port}" if port is not None else "")
    else:
        if parsed.netloc.endswith(":"):
            raise ValueError("file artifact_uri does not accept a port delimiter")
        if parsed.netloc and (parsed.hostname != "localhost" or parsed.port is not None):
            raise ValueError("file artifact_uri authority must be empty or localhost")
        if parsed.netloc:
            canonical_authority = "localhost"
    return f"{scheme}://{canonical_authority}{parsed.path}"


def _validate_citation_uri(value: str) -> str:
    _validate_uri_characters(value, field_name="citation_uri")
    raw_scheme, separator, remainder = value.partition(":")
    if not separator or raw_scheme.lower() not in {"knowledge", "proofagent"}:
        raise ValueError("citation_uri requires the knowledge or proofagent scheme")
    canonical = f"{raw_scheme.lower()}:{remainder}"
    try:
        parsed = urlsplit(canonical)
        username = parsed.username
        password = parsed.password
        port = parsed.port
    except ValueError as exc:
        raise ValueError("citation_uri is malformed") from exc
    if username is not None or password is not None or "@" in parsed.netloc:
        raise ValueError("citation_uri must not contain userinfo")
    if not parsed.netloc:
        raise ValueError("citation_uri requires an authority")
    if parsed.hostname is not None and parsed.hostname.endswith("."):
        raise ValueError("citation_uri must not contain a trailing-dot authority")
    if parsed.netloc.endswith(":"):
        raise ValueError("citation_uri must not contain an empty port")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("citation_uri contains an invalid port")
    if "?" in canonical:
        raise ValueError("citation_uri must not contain a query")
    _validate_canonical_path(parsed.path, field_name="citation_uri")
    if canonical.count("#") > 1:
        raise ValueError("citation_uri must contain at most one fragment delimiter")
    if "#" in canonical and _CITATION_FRAGMENT.fullmatch(parsed.fragment) is None:
        raise ValueError("citation_uri fragment is not a canonical page or anchor identity")
    fragment = f"#{parsed.fragment}" if parsed.fragment else ""
    hostname = parsed.hostname
    if hostname is None:
        raise ValueError("citation_uri requires a hostname or authority identity")
    try:
        hostname = ip_address(hostname).compressed.lower()
    except ValueError:
        hostname = hostname.lower()
    if ":" in hostname:
        hostname = f"[{hostname}]"
    canonical_authority = hostname + (f":{port}" if port is not None else "")
    return f"{raw_scheme.lower()}://{canonical_authority}{parsed.path}{fragment}"


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
    citation_uri: Annotated[UnmodifiedNonBlankStr, AfterValidator(_validate_citation_uri)]
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

    @field_validator("entries", mode="before")
    @classmethod
    def canonicalize_entries(cls, value: object) -> object:
        if not isinstance(value, list | tuple):
            return value
        return tuple(
            sorted(
                value,
                key=lambda entry: _raw_string_key(entry, "rule_unit_revision_id"),
            )
        )

    @model_validator(mode="after")
    def validate_entries(self) -> Self:
        entry_ids = [entry.rule_unit_revision_id for entry in self.entries]
        if len(entry_ids) != len(set(entry_ids)):
            raise ValueError("manifest entry identities must be unique")
        for entry in self.entries:
            if entry.document_id != self.document_id:
                raise ValueError("manifest entries must match the shard document_id")
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

    @field_validator("shards", mode="before")
    @classmethod
    def canonicalize_shards(cls, value: object) -> object:
        if not isinstance(value, list | tuple):
            return value
        return tuple(
            sorted(
                value,
                key=lambda shard: _raw_string_key(shard, "document_id"),
            )
        )

    @model_validator(mode="after")
    def validate_shards(self) -> Self:
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

    @field_validator("enabled_degradations", mode="before")
    @classmethod
    def canonicalize_degradations(cls, value: object) -> object:
        if not isinstance(value, list | tuple):
            return value

        return tuple(sorted(value, key=lambda item: _raw_string_key(item, "degradation_id")))

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
        semantic_keys = [
            (item.mode, item.source_id, item.query_type) for item in self.enabled_degradations
        ]
        if len(semantic_keys) != len(set(semantic_keys)):
            raise ValueError("degradations must be unique by mode, source, and query type")
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
    validated_document_count: PositiveInt
    validated_rule_unit_count: PositiveInt

    @field_validator("covered_publication_sequences", mode="before")
    @classmethod
    def canonicalize_coverage(cls, value: object) -> object:
        if isinstance(value, list | tuple):
            if not all(type(item) is int for item in value):
                return tuple(value)
            return tuple(sorted(value))
        return value

    @model_validator(mode="after")
    def validate_chain_and_coverage(self) -> Self:
        sequences = self.covered_publication_sequences
        if len(sequences) != len(set(sequences)):
            raise ValueError("covered publication sequences must be unique")
        if self.parent_attestation_sha256 == self.attestation_sha256:
            raise ValueError("an attestation cannot refer to itself as parent")
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

    @field_validator("reason_codes", mode="before")
    @classmethod
    def canonicalize_reasons(cls, value: object) -> object:
        return _canonicalize_string_tuple(value)

    @model_validator(mode="after")
    def validate_review_state(self) -> Self:
        if len(self.reason_codes) != len(set(self.reason_codes)):
            raise ValueError("review reason codes must be unique")
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

    @field_validator("blocker_codes", mode="before")
    @classmethod
    def canonicalize_blockers(cls, value: object) -> object:
        return _canonicalize_string_tuple(value)

    @model_validator(mode="after")
    def validate_blockers(self) -> Self:
        if len(self.blocker_codes) != len(set(self.blocker_codes)):
            raise ValueError("readiness blocker codes must be unique")
        if self.passed and self.blocker_codes:
            raise ValueError("passing checks do not accept blockers")
        if not self.passed and not self.blocker_codes:
            raise ValueError("failing checks require at least one blocker")
        if self.passed and self.check != "review" and self.evidence_ref is None:
            raise ValueError("passing proof-bearing checks require evidence_ref")
        return self


class HybridKnowledgeRevisionReadinessRecord(_KnowledgeIndexModel):
    readiness_id: NonBlankStr
    source_id: NonBlankStr
    document_id: NonBlankStr
    revision_id: NonBlankStr
    structured_build_id: NonBlankStr
    status: Literal["READY", "BLOCKED"]
    checks: tuple[HybridReadinessCheck, ...]
    review_record: HybridKnowledgeRevisionReviewRecord
    evaluated_at: AwareTimestamp

    @field_validator("checks", mode="before")
    @classmethod
    def canonicalize_checks(cls, value: object) -> object:
        if not isinstance(value, list | tuple):
            return value
        return tuple(
            sorted(
                value,
                key=lambda check: _raw_string_key(check, "check"),
            )
        )

    @model_validator(mode="after")
    def validate_readiness(self) -> Self:
        check_names = [check.check for check in self.checks]
        if len(check_names) != len(set(check_names)):
            raise ValueError("readiness checks must be unique")
        if set(check_names) != _REQUIRED_READINESS_CHECKS:
            raise ValueError("readiness requires exactly one of every required check")
        review = self.review_record
        identity = (self.source_id, self.document_id, self.revision_id, self.structured_build_id)
        review_identity = (
            review.source_id,
            review.document_id,
            review.revision_id,
            review.structured_build_id,
        )
        if review_identity != identity:
            raise ValueError("review_record identity must match readiness identity")
        review_check = next(check for check in self.checks if check.check == "review")
        review_is_acceptable = review.state in {"APPROVED", "NOT_REQUIRED"}
        if review_is_acceptable != review_check.passed:
            raise ValueError("review check outcome must match the exact review record state")
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


class HybridPublicationAuthorityChain(_KnowledgeIndexModel):
    attempt: KnowledgePublicationAttempt
    generation: KnowledgeIndexGeneration
    manifest_root: RuleUnitManifestRoot
    parent_attestation: KnowledgeProjectionAttestation | None = None
    attestation: KnowledgeProjectionAttestation
    publication: HybridKnowledgePublicationRecord

    @model_validator(mode="after")
    def validate_authority_chain(self) -> Self:
        attempt = self.attempt
        generation = self.generation
        root = self.manifest_root
        attestation = self.attestation
        publication = self.publication
        if attempt.state != "PUBLISHED":
            raise ValueError("authority chain requires a PUBLISHED attempt")
        if (
            len(
                {
                    attempt.source_id,
                    generation.source_id,
                    root.source_id,
                    attestation.source_id,
                    publication.source_id,
                }
            )
            != 1
        ):
            raise ValueError("authority chain source identities must match")
        if attestation.publication_attempt_id != attempt.attempt_id:
            raise ValueError("attestation publication attempt must match attempt")
        if publication.source_draft_version_id != attempt.source_draft_version_id:
            raise ValueError("publication source draft must match attempt")
        if publication.validation_id != attempt.validation_id:
            raise ValueError("publication validation must match attempt")
        if publication.candidate_digest != attempt.candidate_digest:
            raise ValueError("publication candidate digest must match attempt")
        if not (
            attempt.reserved_publication_seq
            == root.source_publication_seq
            == publication.source_publication_seq
        ):
            raise ValueError("reserved, manifest, and publication sequences must match")
        if root.source_snapshot_id != publication.source_snapshot_id:
            raise ValueError("manifest and publication source snapshots must match")
        if (
            len(
                {
                    attempt.generation_id,
                    generation.generation_id,
                    root.generation_id,
                    attestation.generation_id,
                    publication.generation_id,
                }
            )
            != 1
        ):
            raise ValueError("authority chain generation identities must match")
        if generation.mapping_sha256 != attestation.mapping_sha256:
            raise ValueError("generation mapping digest must match attestation")
        if not (
            root.root_sha256 == attestation.manifest_root_sha256 == publication.manifest_ref.sha256
        ):
            raise ValueError("manifest root digests must match")
        if attestation.validated_document_count != root.document_count:
            raise ValueError("attested document count must match manifest root")
        if attestation.validated_rule_unit_count != root.rule_unit_count:
            raise ValueError("attested Rule Unit count must match manifest root")
        if publication.attestation != attestation:
            raise ValueError("publication must contain the exact attestation")
        if publication.source_publication_seq not in attestation.covered_publication_sequences:
            raise ValueError("attestation must cover the current publication sequence")
        parent = self.parent_attestation
        if parent is None:
            if attestation.parent_attestation_sha256 is not None:
                raise ValueError("parent attestation record is required for a parent digest")
        else:
            if attestation.parent_attestation_sha256 != parent.attestation_sha256:
                raise ValueError("parent attestation digest must match the parent record")
            if parent.source_id != attestation.source_id:
                raise ValueError("parent attestation source must match")
            if parent.generation_id != attestation.generation_id:
                raise ValueError("parent attestation generation must match")
            if parent.mapping_sha256 != generation.mapping_sha256:
                raise ValueError("parent attestation mapping digest must match generation")
            if not set(parent.covered_publication_sequences).issubset(
                attestation.covered_publication_sequences
            ):
                raise ValueError("attestation coverage must retain parent coverage")
        return self
