"""Provider-neutral ports for hybrid knowledge ingestion and retrieval."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Annotated, Literal, Protocol, Self, runtime_checkable

from pydantic import (
    AfterValidator,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_validator,
)

from proof_agent.contracts._base import FrozenModel
from proof_agent.contracts.hybrid_documents import StructuredKnowledgeDocumentArtifact
from proof_agent.contracts.insurance_authorization import InstitutionAuthorizationContext
from proof_agent.contracts.insurance_rules import (
    ApprovedInsuranceRuleMetadataRevision,
    InsuranceRuleUnitRevision,
    TaxonomyCondition,
)
from proof_agent.contracts.knowledge_index import (
    ExactArtifactRef,
    HybridKnowledgePublicationRecord,
    KnowledgeIndexGeneration,
    RuleUnitManifestEntry,
)

if TYPE_CHECKING:
    from proof_agent.capabilities.knowledge.ingestion.hybrid_worker import (
        HybridArtifactBuildRequest,
        HybridArtifactBuildResult,
    )


NonBlankStr = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256 = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
FiniteStrictFloat = Annotated[float, Field(strict=True, allow_inf_nan=False)]
BoundedStr = Annotated[
    StrictStr,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
]
BoundedContent = Annotated[
    StrictStr,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=50_000),
]
BoundedQuery = Annotated[
    StrictStr,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=10_000),
]
BoundedBudget = Annotated[StrictInt, Field(gt=0, le=1_000)]


def _require_aware_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone offset")
    return value


AwareTimestamp = Annotated[
    datetime,
    Field(strict=True),
    AfterValidator(_require_aware_timestamp),
]


class _PortModel(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SearchIndexIdentity(_PortModel):
    generation: KnowledgeIndexGeneration
    index_uuid: NonBlankStr


class ProjectionDocument(_PortModel):
    projection_id: NonBlankStr
    rule_unit: InsuranceRuleUnitRevision
    manifest_entry: RuleUnitManifestEntry
    approved_metadata: ApprovedInsuranceRuleMetadataRevision
    projection_revision: NonBlankStr
    embedding: tuple[FiniteStrictFloat, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_approved_projection(self) -> Self:
        rule = self.rule_unit
        entry = self.manifest_entry
        expected = (
            entry.rule_unit_revision_id == rule.rule_unit_revision_id
            and entry.document_id == rule.document_id
            and entry.revision_id == rule.revision_id
            and entry.structured_build_id == rule.structured_build_id
            and entry.metadata_revision_id == rule.metadata_revision_id
            and entry.visibility_revision_id == rule.visibility_scope.revision_id
            and entry.content_sha256 == rule.content_sha256
            and entry.authority_sha256 == rule.authority_sha256
            and entry.citation_uri == rule.citation_uri
            and self.approved_metadata.metadata_revision_id == rule.metadata_revision_id
        )
        if not expected:
            raise ValueError("projection must bind one exact approved Rule Unit manifest entry")
        return self


class ProjectionBulkRequest(_PortModel):
    identity: SearchIndexIdentity
    publication_attempt_id: NonBlankStr
    manifest_root_sha256: Sha256
    documents: tuple[ProjectionDocument, ...] = Field(min_length=1, max_length=1_000)

    @model_validator(mode="after")
    def validate_documents(self) -> Self:
        projection_ids = [document.projection_id for document in self.documents]
        rule_unit_ids = [document.rule_unit.rule_unit_revision_id for document in self.documents]
        if len(projection_ids) != len(set(projection_ids)):
            raise ValueError("projection document identities must be unique")
        if len(rule_unit_ids) != len(set(rule_unit_ids)):
            raise ValueError("projected Rule Unit identities must be unique")
        dimension = self.identity.generation.embedding_dimension
        if any(len(document.embedding) != dimension for document in self.documents):
            raise ValueError("every projection embedding must match generation dimension")
        return self


class ProjectionBulkResult(_PortModel):
    """Request-bound result; partial acceptance remains explicit for later validation."""

    request: ProjectionBulkRequest
    accepted_count: NonNegativeInt
    refresh_checkpoint: NonBlankStr

    @model_validator(mode="after")
    def validate_accepted_count(self) -> Self:
        if self.accepted_count > len(self.request.documents):
            raise ValueError("accepted_count must not exceed submitted document count")
        return self


class HybridSearchRequest(_PortModel):
    identity: SearchIndexIdentity
    manifest_root_sha256: Sha256
    query_text: BoundedQuery
    query_embedding: tuple[FiniteStrictFloat, ...] = Field(min_length=1)
    source_publication_seq: PositiveInt
    authorization: InstitutionAuthorizationContext
    applicability_filters: tuple[TaxonomyCondition, ...] = Field(
        default=(), max_length=128
    )
    as_of_date: Annotated[date, Field(strict=True)]
    lexical_budget: BoundedBudget
    dense_budget: BoundedBudget
    rrf_window: BoundedBudget
    rrf_pipeline: NonBlankStr
    limit: Annotated[StrictInt, Field(gt=0, le=200)]

    @model_validator(mode="after")
    def validate_query_dimension(self) -> Self:
        if len(self.query_embedding) != self.identity.generation.embedding_dimension:
            raise ValueError("query embedding must match generation dimension")
        if self.rrf_window > self.lexical_budget + self.dense_budget:
            raise ValueError("rrf_window must not exceed total lane candidates")
        if self.limit > self.rrf_window:
            raise ValueError("limit must not exceed rrf_window")
        keys = [condition.key for condition in self.applicability_filters]
        if len(keys) != len(set(keys)):
            raise ValueError("applicability filter keys must be unique")
        return self


class HybridSearchHit(_PortModel):
    rank: PositiveInt
    source_id: BoundedStr
    index_generation_id: BoundedStr
    index_uuid: BoundedStr
    projection_id: BoundedStr
    rule_unit_revision_id: BoundedStr
    document_id: BoundedStr
    revision_id: BoundedStr
    authority_manifest_digest: Sha256
    metadata_revision_digest: Sha256
    visibility_revision_digest: Sha256
    content_sha256: Sha256
    authority_sha256: Sha256
    citation_uri: BoundedStr
    content: BoundedContent
    lexical_score: FiniteStrictFloat | None = None
    vector_score: FiniteStrictFloat | None = None
    fused_score: FiniteStrictFloat


class StructuredParseRequest(_PortModel):
    source: ExactArtifactRef
    document_id: NonBlankStr
    revision_id: NonBlankStr


class StructuredParseResult(_PortModel):
    artifact: StructuredKnowledgeDocumentArtifact
    canonical_artifact_ref: ExactArtifactRef


class EmbeddingRequest(_PortModel):
    request_id: NonBlankStr
    model_revision: NonBlankStr
    dimension: PositiveInt
    texts: tuple[NonBlankStr, ...] = Field(min_length=1)


class EmbeddingResult(_PortModel):
    request: EmbeddingRequest
    vectors: tuple[tuple[FiniteStrictFloat, ...], ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_vectors(self) -> Self:
        if len(self.vectors) != len(self.request.texts):
            raise ValueError("embedding result requires exactly one vector per input")
        if any(len(vector) != self.request.dimension for vector in self.vectors):
            raise ValueError("embedding vectors must match the requested dimension")
        return self


class RerankCandidate(_PortModel):
    candidate_id: NonBlankStr
    text: NonBlankStr


class RerankRequest(_PortModel):
    request_id: NonBlankStr
    model_revision: NonBlankStr
    query_text: NonBlankStr
    candidates: tuple[RerankCandidate, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_candidate_identities(self) -> Self:
        candidate_ids = [candidate.candidate_id for candidate in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("rerank candidate identities must be unique")
        return self


class RerankScore(_PortModel):
    candidate_id: NonBlankStr
    score: FiniteStrictFloat


class RerankResult(_PortModel):
    request: RerankRequest
    scores: tuple[RerankScore, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_score_coverage(self) -> Self:
        expected = {candidate.candidate_id for candidate in self.request.candidates}
        actual = [score.candidate_id for score in self.scores]
        if len(actual) != len(set(actual)):
            raise ValueError("rerank score identities must be unique")
        if set(actual) != expected:
            raise ValueError("rerank scores must cover exactly the requested candidates")
        return self


HybridKnowledgeJobKind = Literal["parse", "embed", "project", "publish", "reconcile", "rebuild"]
HybridKnowledgeJobState = Literal[
    "READY",
    "LEASED",
    "RETRY_SCHEDULED",
    "REVIEW_REQUIRED",
    "COMPLETED",
    "FAILED",
]


class HybridKnowledgeJobRequest(_PortModel):
    job_id: NonBlankStr
    idempotency_key: NonBlankStr
    request_identity: NonBlankStr
    request_sha256: Sha256
    kind: HybridKnowledgeJobKind
    ready_at: AwareTimestamp | None = None


class HybridKnowledgeJob(_PortModel):
    request: HybridKnowledgeJobRequest
    state: HybridKnowledgeJobState
    created_at: AwareTimestamp
    updated_at: AwareTimestamp
    fencing_token: NonNegativeInt = 0
    auto_retry_count: NonNegativeInt = 0
    max_auto_retries: NonNegativeInt = 2
    next_attempt_at: AwareTimestamp | None = None
    safe_reason: NonBlankStr | None = None
    completed_at: AwareTimestamp | None = None
    failure_code: NonBlankStr | None = None
    failure_classification: Literal["non_recoverable", "recoverable_exhausted"] | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        if self.state == "READY" and self.fencing_token != 0:
            raise ValueError("READY jobs require fencing_token zero")
        if self.state != "READY" and self.fencing_token <= 0:
            raise ValueError("claimed and terminal jobs require a positive fencing_token")
        if self.auto_retry_count > self.max_auto_retries:
            raise ValueError("auto_retry_count cannot exceed max_auto_retries")
        if self.state == "RETRY_SCHEDULED" and self.next_attempt_at is None:
            raise ValueError("RETRY_SCHEDULED jobs require next_attempt_at")
        if self.state != "RETRY_SCHEDULED" and self.next_attempt_at is not None:
            raise ValueError("only RETRY_SCHEDULED jobs accept next_attempt_at")
        if self.state in {"RETRY_SCHEDULED", "REVIEW_REQUIRED", "FAILED"}:
            if self.safe_reason is None:
                raise ValueError(f"{self.state} jobs require safe_reason")
        elif self.safe_reason is not None:
            raise ValueError("successful and active jobs cannot contain safe_reason")
        if self.state in {"COMPLETED", "FAILED"} and self.completed_at is None:
            raise ValueError("terminal jobs require completed_at")
        if self.state not in {"COMPLETED", "FAILED"} and self.completed_at is not None:
            raise ValueError("nonterminal jobs do not accept completed_at")
        if self.state == "FAILED" and self.failure_code is None:
            raise ValueError("FAILED jobs require failure_code")
        if self.state != "FAILED" and self.failure_code is not None:
            raise ValueError("only FAILED jobs accept failure_code")
        if self.state == "FAILED" and self.failure_classification is None:
            raise ValueError("FAILED jobs require a failure classification")
        if self.state != "FAILED" and self.failure_classification is not None:
            raise ValueError("only FAILED jobs accept a failure classification")
        if self.completed_at is not None:
            if self.completed_at < self.created_at:
                raise ValueError("completed_at must not precede created_at")
            if self.updated_at != self.completed_at:
                raise ValueError("terminal updated_at must equal completed_at")
        return self


class HybridKnowledgeJobClaim(_PortModel):
    job_id: NonBlankStr
    request: HybridKnowledgeJobRequest
    worker_id: NonBlankStr
    fencing_token: PositiveInt
    claimed_at: AwareTimestamp
    lease_expires_at: AwareTimestamp

    @model_validator(mode="after")
    def validate_lease(self) -> Self:
        if self.job_id != self.request.job_id:
            raise ValueError("claim job_id must match request job_id")
        if self.request.ready_at is not None and self.claimed_at < self.request.ready_at:
            raise ValueError("claim cannot precede request ready_at")
        if self.lease_expires_at <= self.claimed_at:
            raise ValueError("lease_expires_at must follow claimed_at")
        return self


@runtime_checkable
class KnowledgeArtifactStore(Protocol):
    def put_immutable(self, *, key: str, content: bytes, media_type: str) -> ExactArtifactRef: ...

    def get_exact(self, ref: ExactArtifactRef) -> bytes: ...


@runtime_checkable
class HybridSearchIndex(Protocol):
    def bulk_upsert(self, request: ProjectionBulkRequest) -> ProjectionBulkResult: ...

    def verify_identity(self, expected: SearchIndexIdentity) -> SearchIndexIdentity: ...

    def search(self, request: HybridSearchRequest) -> tuple[HybridSearchHit, ...]: ...


@runtime_checkable
class StructuredKnowledgeParser(Protocol):
    def parse(self, request: StructuredParseRequest) -> StructuredParseResult: ...


@runtime_checkable
class KnowledgeEmbeddingModel(Protocol):
    def embed(self, request: EmbeddingRequest) -> EmbeddingResult: ...


@runtime_checkable
class KnowledgeReranker(Protocol):
    def rerank(self, request: RerankRequest) -> RerankResult: ...


@runtime_checkable
class HybridClock(Protocol):
    def now(self) -> datetime: ...


@runtime_checkable
class HybridKnowledgeWorkScheduler(Protocol):
    def enqueue(self, request: HybridKnowledgeJobRequest) -> HybridKnowledgeJob: ...

    def claim_next(
        self, *, worker_id: str, lease_seconds: int
    ) -> HybridKnowledgeJobClaim | None: ...

    def renew(
        self,
        *,
        job_id: str,
        worker_id: str,
        fencing_token: int,
        lease_seconds: int,
    ) -> HybridKnowledgeJobClaim: ...

    def complete(
        self, *, job_id: str, worker_id: str, fencing_token: int
    ) -> HybridKnowledgeJob: ...

    def fail(
        self,
        *,
        job_id: str,
        worker_id: str,
        fencing_token: int,
        failure_code: str,
    ) -> HybridKnowledgeJob: ...


@runtime_checkable
class HybridKnowledgeArtifactLifecycle(Protocol):
    """Exact structured-build state machine under the scheduler's active fence."""

    def claim_next(
        self, *, worker_id: str, lease_seconds: int
    ) -> HybridKnowledgeJobClaim | None: ...

    def load_build_request(self, claim: HybridKnowledgeJobClaim) -> HybridArtifactBuildRequest: ...

    def renew_claim(
        self, claim: HybridKnowledgeJobClaim, *, lease_seconds: int
    ) -> HybridKnowledgeJobClaim: ...

    def commit_artifact_build(
        self,
        claim: HybridKnowledgeJobClaim,
        result: HybridArtifactBuildResult,
    ) -> object: ...

    def schedule_retry(
        self,
        claim: HybridKnowledgeJobClaim,
        *,
        auto_retry_count: int,
        safe_error: str,
    ) -> object: ...

    def require_review(self, claim: HybridKnowledgeJobClaim, *, safe_reason: str) -> object: ...

    def fail_integrity(
        self,
        claim: HybridKnowledgeJobClaim,
        *,
        failure_code: str,
        safe_reason: str,
    ) -> object: ...

    def fail_retries_exhausted(
        self,
        claim: HybridKnowledgeJobClaim,
        *,
        failure_code: str,
        safe_reason: str,
    ) -> object: ...


@runtime_checkable
class HybridKnowledgeAuthorityRepository(Protocol):
    def get_rule_unit_revision(
        self, rule_unit_revision_id: str
    ) -> InsuranceRuleUnitRevision | None: ...

    def get_index_generation(
        self, *, source_id: str, generation_id: str
    ) -> KnowledgeIndexGeneration | None: ...

    def get_publication(
        self, *, source_id: str, source_publication_seq: int
    ) -> HybridKnowledgePublicationRecord | None: ...
