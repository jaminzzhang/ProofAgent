from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from proof_agent.contracts._base import FrozenModel


class BoundingBox(FrozenModel):
    x0: float = Field(allow_inf_nan=False)
    y0: float = Field(allow_inf_nan=False)
    x1: float = Field(allow_inf_nan=False)
    y1: float = Field(allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_coordinate_order(self) -> BoundingBox:
        if self.x1 < self.x0:
            raise ValueError("x1 must be greater than or equal to x0")
        if self.y1 < self.y0:
            raise ValueError("y1 must be greater than or equal to y0")
        return self


class StructuredArtifactBuildIdentity(FrozenModel):
    build_id: str
    source_sha256: str
    parser_adapter: str
    parser_revision: str
    model_digests: tuple[str, ...] = ()
    canonical_schema_version: Literal["structured-knowledge.v1"]
    configuration_sha256: str


class StructuredBlock(FrozenModel):
    block_id: str
    block_type: Literal[
        "heading",
        "paragraph",
        "list_item",
        "caption",
        "footnote",
        "header",
        "footer",
        "other",
    ]
    text: str
    bbox: BoundingBox
    reading_order: int = Field(ge=0)
    heading_level: int | None = Field(default=None, ge=1, le=6)
    source_method: Literal["native", "ocr", "reconstructed"] = "native"


class StructuredTableCell(FrozenModel):
    row: int = Field(ge=0)
    column: int = Field(ge=0)
    row_span: int = Field(default=1, ge=1)
    column_span: int = Field(default=1, ge=1)
    text: str
    bbox: BoundingBox
    source_method: Literal["native", "ocr", "reconstructed"] = "native"


class StructuredTable(FrozenModel):
    table_id: str
    title: str | None = None
    bbox: BoundingBox
    cells: tuple[StructuredTableCell, ...] = ()


class StructuredPage(FrozenModel):
    page_number: int = Field(ge=1)
    width: float = Field(gt=0, allow_inf_nan=False)
    height: float = Field(gt=0, allow_inf_nan=False)
    blocks: tuple[StructuredBlock, ...] = ()
    tables: tuple[StructuredTable, ...] = ()


class ParserWarning(FrozenModel):
    code: str
    message: str
    page_number: int | None = Field(default=None, ge=1)
    block_id: str | None = None
    table_id: str | None = None


class StructuredKnowledgeDocumentArtifact(FrozenModel):
    schema_version: Literal["structured-knowledge.v1"]
    document_id: str
    revision_id: str
    original_sha256: str
    build_identity: StructuredArtifactBuildIdentity
    pages: tuple[StructuredPage, ...]
    warnings: tuple[ParserWarning, ...] = ()
