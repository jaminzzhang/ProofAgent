"""Public Knowledge Query Result V1 contracts."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from knowledge_source_service.contracts.base import NonBlankText, StrictContract


Sha256Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
RetrievalLane = Literal["lexical", "sparse", "dense", "structured"]


class CandidateEvidenceContent(StrictContract):
    media_type: NonBlankText
    text: NonBlankText


class StructuredFieldValue(StrictContract):
    field: NonBlankText
    value_type: Literal["string", "integer", "decimal", "boolean", "date", "datetime", "null"]
    value: str | int | float | bool | None

    @model_validator(mode="after")
    def require_value_to_match_declared_type(self) -> Self:
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


class StructuredEvidenceData(StrictContract):
    schema_revision_id: NonBlankText
    fields: tuple[StructuredFieldValue, ...] = Field(min_length=1)


class StructuredCandidateEvidenceContent(CandidateEvidenceContent):
    structured_data: StructuredEvidenceData


class TextLinesCitationLocator(StrictContract):
    kind: Literal["text_lines"] = "text_lines"
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)


class PdfPageCitationLocator(StrictContract):
    kind: Literal["pdf_page"] = "pdf_page"
    page_number: int = Field(ge=1)


class DocxParagraphCitationLocator(StrictContract):
    kind: Literal["docx_paragraph"] = "docx_paragraph"
    paragraph_number: int = Field(ge=1)


class DocxTableCellCitationLocator(StrictContract):
    kind: Literal["docx_table_cell"] = "docx_table_cell"
    table_number: int = Field(ge=1)
    row_number: int = Field(ge=1, le=999)
    column_number: int = Field(ge=1, le=999)


class PptxShapeCitationLocator(StrictContract):
    kind: Literal["pptx_shape"] = "pptx_shape"
    slide_number: int = Field(ge=1, le=1000)
    shape_id: int = Field(ge=1, le=999_999)


class HtmlDomCitationLocator(StrictContract):
    kind: Literal["html_dom"] = "html_dom"
    dom_path: NonBlankText = Field(max_length=1024)


class PixelBoundingBox(StrictContract):
    x_min: int = Field(ge=0)
    y_min: int = Field(ge=0)
    x_max: int = Field(ge=1)
    y_max: int = Field(ge=1)

    @model_validator(mode="after")
    def require_positive_area(self) -> Self:
        if self.x_max <= self.x_min or self.y_max <= self.y_min:
            raise ValueError("bounding box must have positive area")
        return self


class OcrRegionCitationLocator(StrictContract):
    kind: Literal["ocr_region"] = "ocr_region"
    page_number: int = Field(ge=1, le=1000)
    bounding_box: PixelBoundingBox


class DatasetRecordsCitationLocator(StrictContract):
    kind: Literal["dataset_records"] = "dataset_records"
    dataset_revision_id: NonBlankText
    record_ids: tuple[NonBlankText, ...] = Field(min_length=1)
    typed_query_digest: Sha256Digest
    input_set_digest: Sha256Digest


class DatasetAggregateCitationLocator(StrictContract):
    kind: Literal["dataset_aggregate"] = "dataset_aggregate"
    dataset_revision_id: NonBlankText
    typed_query_digest: Sha256Digest
    input_predicate_digest: Sha256Digest
    input_record_count: int = Field(ge=1)
    input_set_digest: Sha256Digest


DatasetCitationLocator = Annotated[
    DatasetRecordsCitationLocator | DatasetAggregateCitationLocator,
    Field(discriminator="kind"),
]


CitationLocator = Annotated[
    TextLinesCitationLocator
    | PdfPageCitationLocator
    | DocxParagraphCitationLocator
    | DocxTableCellCitationLocator
    | PptxShapeCitationLocator
    | HtmlDomCitationLocator
    | OcrRegionCitationLocator
    | DatasetRecordsCitationLocator
    | DatasetAggregateCitationLocator,
    Field(discriminator="kind"),
]
DocumentCitationLocator = Annotated[
    TextLinesCitationLocator
    | PdfPageCitationLocator
    | DocxParagraphCitationLocator
    | DocxTableCellCitationLocator
    | PptxShapeCitationLocator
    | HtmlDomCitationLocator
    | OcrRegionCitationLocator,
    Field(discriminator="kind"),
]


class RetrievalLaneContribution(StrictContract):
    lane: Literal["lexical", "sparse", "dense"]
    native_score: float
    lane_rank: int = Field(ge=1)
    weight: float = Field(gt=0)
    rrf_contribution: float = Field(ge=0)


class RelevanceRanking(StrictContract):
    kind: Literal["relevance"] = "relevance"
    lane_contributions: tuple[RetrievalLaneContribution, ...] = Field(min_length=1)
    fused_rank: int = Field(ge=1)
    reranked_rank: int | None = Field(default=None, ge=1)


class StructuredRanking(StrictContract):
    kind: Literal["structured"] = "structured"
    structured_order: int = Field(ge=1)


class CandidateRetrievalLineage(StrictContract):
    retrieval_round: int = Field(ge=1)
    plan_revision: int = Field(ge=1)
    index_identity: NonBlankText
    query_digest: Sha256Digest
    access_scope_digest: Sha256Digest


class ContextEvidenceUnit(StrictContract):
    """Independently authorized and cited context attached after ranking."""

    relation: Literal[
        "heading_path",
        "table_header",
        "adjacent_sibling",
        "referenced_definition",
    ]
    knowledge_source_id: NonBlankText
    knowledge_source_version_id: NonBlankText
    evidence_unit_id: NonBlankText
    content: CandidateEvidenceContent | StructuredCandidateEvidenceContent
    content_hash: Sha256Digest
    citation_locator: CitationLocator
    retrieval_lineage: CandidateRetrievalLineage


class CandidateEvidenceBase(StrictContract):
    """Shared source identity without Evidence Admission semantics."""

    candidate_evidence_id: NonBlankText
    knowledge_space_id: NonBlankText
    knowledge_base_id: NonBlankText
    knowledge_base_version_id: NonBlankText
    knowledge_base_release_id: NonBlankText
    knowledge_source_id: NonBlankText
    knowledge_source_version_id: NonBlankText
    evidence_unit_id: NonBlankText
    content_hash: Sha256Digest
    context_evidence_units: tuple[ContextEvidenceUnit, ...] = ()


class RelevanceCandidateEvidence(CandidateEvidenceBase):
    content: CandidateEvidenceContent
    citation_locator: DocumentCitationLocator
    ranking: RelevanceRanking
    retrieval_lineage: CandidateRetrievalLineage


class StructuredCandidateEvidence(CandidateEvidenceBase):
    content: StructuredCandidateEvidenceContent
    citation_locator: DatasetCitationLocator
    ranking: StructuredRanking
    retrieval_lineage: CandidateRetrievalLineage


class RelevanceOrdering(StrictContract):
    kind: Literal["relevance"] = "relevance"
    final_rank_field: Literal["fused_rank", "reranked_rank"]


class StructuredOrdering(StrictContract):
    kind: Literal["typed"] = "typed"
    fields: tuple[NonBlankText, ...] = Field(min_length=1)


class RelevanceRankedEvidenceGroup(StrictContract):
    evidence_group_id: NonBlankText
    group_type: Literal["relevance_ranked"] = "relevance_ranked"
    ordering: RelevanceOrdering
    candidate_evidence: tuple[RelevanceCandidateEvidence, ...] = ()


class StructuredEvidenceGroup(StrictContract):
    evidence_group_id: NonBlankText
    group_type: Literal["structured"] = "structured"
    ordering: StructuredOrdering
    candidate_evidence: tuple[StructuredCandidateEvidence, ...] = ()


EvidenceGroup = Annotated[
    RelevanceRankedEvidenceGroup | StructuredEvidenceGroup,
    Field(discriminator="group_type"),
]


class QueryPlanSummary(StrictContract):
    plan_revision: int = Field(ge=1)
    planned_lanes: tuple[RetrievalLane, ...] = Field(min_length=1)
    structured_query_count: int = Field(ge=0)
    plan_digest: Sha256Digest


class KnowledgeQueryBudgetUsage(StrictContract):
    rounds: int = Field(ge=0)
    model_calls: int = Field(ge=0)
    candidates: int = Field(ge=0)
    model_tokens: int = Field(ge=0)
    duration_ms: int = Field(ge=0)


class KnowledgeQueryExecutionSummary(StrictContract):
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


class KnowledgeQueryResultLineage(StrictContract):
    knowledge_base_release_id: NonBlankText
    release_manifest_digest: Sha256Digest
    access_scope_digest: Sha256Digest
    plan_revision_digests: tuple[Sha256Digest, ...] = Field(min_length=1)


class KnowledgeQueryResult(StrictContract):
    """Immutable Candidate Evidence result for one exact Knowledge Query."""

    schema_version: Literal["knowledge-query-result.v1"] = "knowledge-query-result.v1"
    evidence_groups: tuple[EvidenceGroup, ...] = Field(min_length=1)
    query_plan_summary: QueryPlanSummary
    execution_summary: KnowledgeQueryExecutionSummary
    retrieval_lineage: KnowledgeQueryResultLineage

    @model_validator(mode="after")
    def require_every_candidate_to_match_exact_result_release(self) -> Self:
        release_id = self.retrieval_lineage.knowledge_base_release_id
        for group in self.evidence_groups:
            for candidate in group.candidate_evidence:
                if candidate.knowledge_base_release_id != release_id:
                    raise ValueError("candidate must match the exact result release")
        return self


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
