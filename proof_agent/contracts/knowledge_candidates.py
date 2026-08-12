"""Strict ProofAgent-side contract for remote Candidate Evidence queries."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from proof_agent.contracts._base import StrictFrozenModel


NonBlankText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
QueryFilterScalar = str | int | float | bool | None


class KnowledgeCandidateQueryFilter(StrictFrozenModel):
    field: NonBlankText
    operator: Literal["eq", "ne", "lt", "lte", "gt", "gte", "in", "between", "is_null"]
    value: QueryFilterScalar | tuple[QueryFilterScalar, ...] = None

    @model_validator(mode="after")
    def require_operator_specific_value_shape(self) -> Self:
        if self.operator == "is_null":
            if self.value is not None:
                raise ValueError("is_null does not accept a comparison value")
        elif self.operator == "in":
            if not isinstance(self.value, tuple) or not self.value:
                raise ValueError("in requires a nonempty tuple of values")
        elif self.operator == "between":
            if not isinstance(self.value, tuple) or len(self.value) != 2:
                raise ValueError("between requires exactly two values")
        elif isinstance(self.value, tuple) or self.value is None:
            raise ValueError("comparison operator requires one scalar value")
        return self


class KnowledgeStructuredQuerySort(StrictFrozenModel):
    field: NonBlankText
    direction: Literal["asc", "desc"] = "asc"
    nulls: Literal["first", "last"] = "last"


class KnowledgeStructuredQueryAggregation(StrictFrozenModel):
    function: Literal["count", "sum", "avg", "min", "max", "exact_distinct_count"]
    field: NonBlankText | None = None
    output_field: NonBlankText

    @model_validator(mode="after")
    def require_aggregation_field(self) -> Self:
        if self.function != "count" and self.field is None:
            raise ValueError("only count may omit its input field")
        return self


class KnowledgeBoundedStructuredQuery(StrictFrozenModel):
    schema_version: Literal["bounded-structured-query.v1"] = (
        "bounded-structured-query.v1"
    )
    dataset_revision_id: NonBlankText
    projections: tuple[NonBlankText, ...] = Field(default=(), max_length=64)
    filters: tuple[KnowledgeCandidateQueryFilter, ...] = Field(
        default=(),
        max_length=64,
    )
    group_by: tuple[NonBlankText, ...] = Field(default=(), max_length=8)
    aggregations: tuple[KnowledgeStructuredQueryAggregation, ...] = Field(
        default=(),
        max_length=16,
    )
    sort: tuple[KnowledgeStructuredQuerySort, ...] = Field(
        default=(),
        max_length=4,
    )
    limit: int = Field(default=100, ge=1, le=1000)

    @model_validator(mode="after")
    def reject_ambiguous_or_duplicate_output(self) -> Self:
        if any(len(set(values)) != len(values) for values in (self.projections, self.group_by)):
            raise ValueError("structured query fields must be unique")
        aliases = tuple(item.output_field for item in self.aggregations)
        if len(set(aliases)) != len(aliases):
            raise ValueError("structured aggregation output fields must be unique")
        if self.aggregations or self.group_by:
            if not self.aggregations:
                raise ValueError("group_by requires at least one aggregation")
            if self.projections:
                raise ValueError("aggregate query cannot declare record projections")
            if set(aliases) & set(self.group_by):
                raise ValueError("aggregate output cannot shadow a group field")
        return self


class KnowledgeCandidateQueryConstraints(StrictFrozenModel):
    as_of: AwareDatetime | None = None
    filters: tuple[KnowledgeCandidateQueryFilter, ...] = ()
    structured_queries: tuple[KnowledgeBoundedStructuredQuery, ...] = Field(
        default=(),
        max_length=16,
    )

    @model_validator(mode="after")
    def reject_ambiguous_global_and_explicit_filters(self) -> Self:
        if self.filters and self.structured_queries:
            raise ValueError(
                "global filters and explicit structured queries cannot be combined"
            )
        return self


class KnowledgeCandidateAccessContext(StrictFrozenModel):
    assertion_token: NonBlankText


class KnowledgeCandidateExecutionBudget(StrictFrozenModel):
    max_rounds: int = Field(gt=0)
    max_model_calls: int = Field(gt=0)
    max_candidates: int = Field(gt=0)
    max_model_tokens: int = Field(gt=0)
    max_duration_ms: int = Field(gt=0)


class KnowledgeCandidateQuery(StrictFrozenModel):
    """One exact-Release request plus the stable client idempotency identity."""

    idempotency_key: NonBlankText
    knowledge_base_release_id: NonBlankText
    question: NonBlankText
    strategy: Literal["single_pass", "agentic"] = "single_pass"
    query_constraints: KnowledgeCandidateQueryConstraints = Field(
        default_factory=KnowledgeCandidateQueryConstraints
    )
    access_narrowing_context: KnowledgeCandidateAccessContext | None = None
    execution_budget: KnowledgeCandidateExecutionBudget
    deadline_at: AwareDatetime


class KnowledgeCandidateContent(StrictFrozenModel):
    media_type: NonBlankText
    text: NonBlankText


class KnowledgeStructuredFieldValue(StrictFrozenModel):
    field: NonBlankText
    value_type: Literal["string", "integer", "decimal", "boolean", "date", "datetime", "null"]
    value: str | int | float | bool | None

    @model_validator(mode="after")
    def require_declared_value_type(self) -> Self:
        valid = False
        if self.value_type == "string":
            valid = type(self.value) is str
        elif self.value_type == "integer":
            valid = type(self.value) is int
        elif self.value_type == "decimal":
            valid = _is_finite_decimal_string(self.value)
        elif self.value_type == "boolean":
            valid = type(self.value) is bool
        elif self.value_type == "date":
            valid = _is_iso_date(self.value)
        elif self.value_type == "datetime":
            valid = _is_aware_iso_datetime(self.value)
        elif self.value_type == "null":
            valid = self.value is None
        if not valid:
            raise ValueError("structured value does not match value_type")
        return self


class KnowledgeStructuredEvidenceData(StrictFrozenModel):
    schema_revision_id: NonBlankText
    fields: tuple[KnowledgeStructuredFieldValue, ...] = Field(min_length=1)


class KnowledgeStructuredCandidateContent(KnowledgeCandidateContent):
    structured_data: KnowledgeStructuredEvidenceData


class KnowledgeTextLinesCitation(StrictFrozenModel):
    kind: Literal["text_lines"] = "text_lines"
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)


class KnowledgePdfPageCitation(StrictFrozenModel):
    kind: Literal["pdf_page"] = "pdf_page"
    page_number: int = Field(ge=1)


class KnowledgeDocxParagraphCitation(StrictFrozenModel):
    kind: Literal["docx_paragraph"] = "docx_paragraph"
    paragraph_number: int = Field(ge=1)


class KnowledgeDocxTableCellCitation(StrictFrozenModel):
    kind: Literal["docx_table_cell"] = "docx_table_cell"
    table_number: int = Field(ge=1)
    row_number: int = Field(ge=1, le=999)
    column_number: int = Field(ge=1, le=999)


class KnowledgePptxShapeCitation(StrictFrozenModel):
    kind: Literal["pptx_shape"] = "pptx_shape"
    slide_number: int = Field(ge=1, le=1000)
    shape_id: int = Field(ge=1, le=999_999)


class KnowledgeHtmlDomCitation(StrictFrozenModel):
    kind: Literal["html_dom"] = "html_dom"
    dom_path: NonBlankText = Field(max_length=1024)


class KnowledgePixelBoundingBox(StrictFrozenModel):
    x_min: int = Field(ge=0)
    y_min: int = Field(ge=0)
    x_max: int = Field(ge=1)
    y_max: int = Field(ge=1)

    @model_validator(mode="after")
    def require_positive_area(self) -> Self:
        if self.x_max <= self.x_min or self.y_max <= self.y_min:
            raise ValueError("bounding box must have positive area")
        return self


class KnowledgeOcrRegionCitation(StrictFrozenModel):
    kind: Literal["ocr_region"] = "ocr_region"
    page_number: int = Field(ge=1, le=1000)
    bounding_box: KnowledgePixelBoundingBox


class KnowledgeDatasetRecordsCitation(StrictFrozenModel):
    kind: Literal["dataset_records"] = "dataset_records"
    dataset_revision_id: NonBlankText
    record_ids: tuple[NonBlankText, ...] = Field(min_length=1)
    typed_query_digest: Sha256Digest
    input_set_digest: Sha256Digest


class KnowledgeDatasetAggregateCitation(StrictFrozenModel):
    kind: Literal["dataset_aggregate"] = "dataset_aggregate"
    dataset_revision_id: NonBlankText
    typed_query_digest: Sha256Digest
    input_predicate_digest: Sha256Digest
    input_record_count: int = Field(ge=1)
    input_set_digest: Sha256Digest


KnowledgeDatasetCitation = Annotated[
    KnowledgeDatasetRecordsCitation | KnowledgeDatasetAggregateCitation,
    Field(discriminator="kind"),
]


KnowledgeCandidateCitation = Annotated[
    KnowledgeTextLinesCitation
    | KnowledgePdfPageCitation
    | KnowledgeDocxParagraphCitation
    | KnowledgeDocxTableCellCitation
    | KnowledgePptxShapeCitation
    | KnowledgeHtmlDomCitation
    | KnowledgeOcrRegionCitation
    | KnowledgeDatasetRecordsCitation
    | KnowledgeDatasetAggregateCitation,
    Field(discriminator="kind"),
]
KnowledgeDocumentCitation = Annotated[
    KnowledgeTextLinesCitation
    | KnowledgePdfPageCitation
    | KnowledgeDocxParagraphCitation
    | KnowledgeDocxTableCellCitation
    | KnowledgePptxShapeCitation
    | KnowledgeHtmlDomCitation
    | KnowledgeOcrRegionCitation,
    Field(discriminator="kind"),
]


class KnowledgeRetrievalLaneContribution(StrictFrozenModel):
    lane: Literal["lexical", "sparse", "dense"]
    native_score: float
    lane_rank: int = Field(ge=1)
    weight: float = Field(gt=0)
    rrf_contribution: float = Field(ge=0)


class KnowledgeRelevanceRanking(StrictFrozenModel):
    kind: Literal["relevance"] = "relevance"
    lane_contributions: tuple[KnowledgeRetrievalLaneContribution, ...] = Field(min_length=1)
    fused_rank: int = Field(ge=1)
    reranked_rank: int | None = Field(default=None, ge=1)


class KnowledgeStructuredRanking(StrictFrozenModel):
    kind: Literal["structured"] = "structured"
    structured_order: int = Field(ge=1)


class KnowledgeCandidateLineage(StrictFrozenModel):
    retrieval_round: int = Field(ge=1)
    plan_revision: int = Field(ge=1)
    index_identity: NonBlankText
    query_digest: Sha256Digest
    access_scope_digest: Sha256Digest


class KnowledgeContextEvidenceUnit(StrictFrozenModel):
    relation: Literal[
        "heading_path",
        "table_header",
        "adjacent_sibling",
        "referenced_definition",
    ]
    knowledge_source_id: NonBlankText
    knowledge_source_version_id: NonBlankText
    evidence_unit_id: NonBlankText
    content: KnowledgeCandidateContent | KnowledgeStructuredCandidateContent
    content_hash: Sha256Digest
    citation_locator: KnowledgeCandidateCitation
    retrieval_lineage: KnowledgeCandidateLineage


class KnowledgeCandidateBase(StrictFrozenModel):
    candidate_evidence_id: NonBlankText
    knowledge_space_id: NonBlankText
    knowledge_base_id: NonBlankText
    knowledge_base_version_id: NonBlankText
    knowledge_base_release_id: NonBlankText
    knowledge_source_id: NonBlankText
    knowledge_source_version_id: NonBlankText
    evidence_unit_id: NonBlankText
    content_hash: Sha256Digest
    context_evidence_units: tuple[KnowledgeContextEvidenceUnit, ...] = ()


class KnowledgeRelevanceCandidate(KnowledgeCandidateBase):
    content: KnowledgeCandidateContent
    citation_locator: KnowledgeDocumentCitation
    ranking: KnowledgeRelevanceRanking
    retrieval_lineage: KnowledgeCandidateLineage


class KnowledgeStructuredCandidate(KnowledgeCandidateBase):
    content: KnowledgeStructuredCandidateContent
    citation_locator: KnowledgeDatasetCitation
    ranking: KnowledgeStructuredRanking
    retrieval_lineage: KnowledgeCandidateLineage


class KnowledgeRelevanceOrdering(StrictFrozenModel):
    kind: Literal["relevance"] = "relevance"
    final_rank_field: Literal["fused_rank", "reranked_rank"]


class KnowledgeStructuredOrdering(StrictFrozenModel):
    kind: Literal["typed"] = "typed"
    fields: tuple[NonBlankText, ...] = Field(min_length=1)


class KnowledgeRelevanceCandidateGroup(StrictFrozenModel):
    evidence_group_id: NonBlankText
    group_type: Literal["relevance_ranked"] = "relevance_ranked"
    ordering: KnowledgeRelevanceOrdering
    candidate_evidence: tuple[KnowledgeRelevanceCandidate, ...] = ()


class KnowledgeStructuredCandidateGroup(StrictFrozenModel):
    evidence_group_id: NonBlankText
    group_type: Literal["structured"] = "structured"
    ordering: KnowledgeStructuredOrdering
    candidate_evidence: tuple[KnowledgeStructuredCandidate, ...] = ()


KnowledgeCandidateGroup = Annotated[
    KnowledgeRelevanceCandidateGroup | KnowledgeStructuredCandidateGroup,
    Field(discriminator="group_type"),
]


class KnowledgeQueryPlanSummary(StrictFrozenModel):
    plan_revision: int = Field(ge=1)
    planned_lanes: tuple[Literal["lexical", "sparse", "dense", "structured"], ...] = Field(
        min_length=1
    )
    structured_query_count: int = Field(ge=0)
    plan_digest: Sha256Digest


class KnowledgeQueryBudgetUsage(StrictFrozenModel):
    rounds: int = Field(ge=0)
    model_calls: int = Field(ge=0)
    candidates: int = Field(ge=0)
    model_tokens: int = Field(ge=0)
    duration_ms: int = Field(ge=0)


class KnowledgeQueryExecutionSummary(StrictFrozenModel):
    strategy: Literal["single_pass", "agentic"]
    rounds: int = Field(ge=1)
    stop_reason: Literal[
        "single_pass_complete",
        "coverage_complete",
        "budget_exhausted",
        "no_candidates",
    ]
    degraded: bool
    budget_usage: KnowledgeQueryBudgetUsage


class KnowledgeQueryResultLineage(StrictFrozenModel):
    knowledge_base_release_id: NonBlankText
    release_manifest_digest: Sha256Digest
    access_scope_digest: Sha256Digest
    plan_revision_digests: tuple[Sha256Digest, ...] = Field(min_length=1)


class KnowledgeQueryResultPayload(StrictFrozenModel):
    schema_version: Literal["knowledge-query-result.v1"]
    evidence_groups: tuple[KnowledgeCandidateGroup, ...] = Field(min_length=1)
    query_plan_summary: KnowledgeQueryPlanSummary
    execution_summary: KnowledgeQueryExecutionSummary
    retrieval_lineage: KnowledgeQueryResultLineage

    @model_validator(mode="after")
    def require_exact_release_for_every_candidate(self) -> Self:
        release_id = self.retrieval_lineage.knowledge_base_release_id
        if any(
            candidate.knowledge_base_release_id != release_id
            for group in self.evidence_groups
            for candidate in group.candidate_evidence
        ):
            raise ValueError("candidate must match exact result Release")
        return self


class KnowledgeCandidateResult(KnowledgeQueryResultPayload):
    knowledge_query_id: NonBlankText


def _is_finite_decimal_string(value: object) -> bool:
    if type(value) is not str:
        return False
    try:
        return Decimal(value).is_finite()
    except InvalidOperation:
        return False


def _is_iso_date(value: object) -> bool:
    if type(value) is not str:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _is_aware_iso_datetime(value: object) -> bool:
    if type(value) is not str:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None
