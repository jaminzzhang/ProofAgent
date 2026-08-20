"""Immutable source-version and release snapshots used by retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


StructuredValueType = Literal[
    "string",
    "integer",
    "decimal",
    "boolean",
    "date",
    "datetime",
    "null",
]
StructuredScalar = str | int | bool | None


@dataclass(frozen=True)
class TextLinesDocumentCitation:
    start_line: int
    end_line: int
    kind: Literal["text_lines"] = "text_lines"

    def __post_init__(self) -> None:
        if self.start_line < 1 or self.end_line < self.start_line:
            raise ValueError("text line citation is invalid")


@dataclass(frozen=True)
class PdfPageDocumentCitation:
    page_number: int
    kind: Literal["pdf_page"] = "pdf_page"

    def __post_init__(self) -> None:
        if self.page_number < 1:
            raise ValueError("PDF page citation is invalid")


@dataclass(frozen=True)
class DocxParagraphDocumentCitation:
    paragraph_number: int
    kind: Literal["docx_paragraph"] = "docx_paragraph"

    def __post_init__(self) -> None:
        if self.paragraph_number < 1:
            raise ValueError("DOCX paragraph citation is invalid")


@dataclass(frozen=True)
class DocxTableCellDocumentCitation:
    table_number: int
    row_number: int
    column_number: int
    kind: Literal["docx_table_cell"] = "docx_table_cell"

    def __post_init__(self) -> None:
        if min(self.table_number, self.row_number, self.column_number) < 1:
            raise ValueError("DOCX table cell citation is invalid")
        if self.row_number > 999 or self.column_number > 999:
            raise ValueError("DOCX table cell citation exceeds the admitted bound")


@dataclass(frozen=True)
class PptxShapeDocumentCitation:
    slide_number: int
    shape_id: int
    kind: Literal["pptx_shape"] = "pptx_shape"

    def __post_init__(self) -> None:
        if not 1 <= self.slide_number <= 1_000:
            raise ValueError("PPTX slide citation is invalid")
        if not 1 <= self.shape_id <= 999_999:
            raise ValueError("PPTX shape citation is invalid")


@dataclass(frozen=True)
class HtmlDomDocumentCitation:
    dom_path: str
    kind: Literal["html_dom"] = "html_dom"

    def __post_init__(self) -> None:
        if (
            not self.dom_path.startswith("/")
            or len(self.dom_path) > 1_024
            or any(character.isspace() for character in self.dom_path)
        ):
            raise ValueError("HTML DOM citation is invalid")


@dataclass(frozen=True)
class OcrRegionDocumentCitation:
    page_number: int
    x_min: int
    y_min: int
    x_max: int
    y_max: int
    kind: Literal["ocr_region"] = "ocr_region"

    def __post_init__(self) -> None:
        if not 1 <= self.page_number <= 1_000:
            raise ValueError("OCR citation page is invalid")
        if min(self.x_min, self.y_min) < 0 or self.x_max <= self.x_min or self.y_max <= self.y_min:
            raise ValueError("OCR citation bounding box is invalid")


DocumentCitation = (
    TextLinesDocumentCitation
    | PdfPageDocumentCitation
    | DocxParagraphDocumentCitation
    | DocxTableCellDocumentCitation
    | PptxShapeDocumentCitation
    | HtmlDomDocumentCitation
    | OcrRegionDocumentCitation
)


@dataclass(frozen=True)
class DocumentEvidenceUnit:
    evidence_unit_id: str
    text: str
    content_hash: str
    citation_locator: DocumentCitation


@dataclass(frozen=True)
class DocumentSourceVersion:
    knowledge_space_id: str
    knowledge_source_id: str
    knowledge_source_version_id: str
    media_type: str
    evidence_units: tuple[DocumentEvidenceUnit, ...]


@dataclass(frozen=True)
class StructuredField:
    field: str
    value_type: StructuredValueType
    value: StructuredScalar


@dataclass(frozen=True)
class StructuredRecord:
    record_id: str
    fields: tuple[StructuredField, ...]
    content_hash: str


@dataclass(frozen=True)
class DatasetSourceVersion:
    knowledge_space_id: str
    knowledge_source_id: str
    knowledge_source_version_id: str
    dataset_revision_id: str
    schema_revision_id: str
    field_order: tuple[str, ...]
    records: tuple[StructuredRecord, ...]

    @property
    def record_ids(self) -> tuple[str, ...]:
        return tuple(record.record_id for record in self.records)


KnowledgeSourceVersion = DocumentSourceVersion | DatasetSourceVersion


@dataclass(frozen=True)
class KnowledgeSourceVersionSummary:
    knowledge_space_id: str
    knowledge_source_id: str
    knowledge_source_version_id: str
    source_kind: Literal["document", "dataset"]
    media_type: str


@dataclass(frozen=True)
class KnowledgeBaseReleaseSummary:
    knowledge_space_id: str
    knowledge_base_id: str
    knowledge_base_version_id: str
    knowledge_base_release_id: str
    source_version_count: int
    state: Literal["queryable", "retired"]


@dataclass(frozen=True)
class RetrievalProjectionBinding:
    index_identity: str
    mapping_digest: str
    corpus_digest: str
    document_count: int
    dense_revision: str
    sparse_revision: str
    dense_dimension: int


@dataclass(frozen=True)
class KnowledgeBaseReleaseSnapshot:
    knowledge_space_id: str
    knowledge_base_id: str
    knowledge_base_version_id: str
    knowledge_base_release_id: str
    knowledge_source_version_ids: tuple[str, ...]
    release_manifest_digest: str
    retrieval_projection: RetrievalProjectionBinding | None = None
