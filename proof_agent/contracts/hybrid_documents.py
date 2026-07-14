from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AliasChoices, ConfigDict, Field, StringConstraints, model_validator

from proof_agent.contracts._base import FrozenModel


NonBlankStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class _StructuredDocumentModel(FrozenModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        serialize_by_alias=True,
    )


class BoundingBox(_StructuredDocumentModel):
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


class StructuredArtifactBuildIdentity(_StructuredDocumentModel):
    build_id: NonBlankStr
    source_sha256: Sha256
    parser_adapter: NonBlankStr
    parser_revision: NonBlankStr
    model_digests: tuple[NonBlankStr, ...] = ()
    canonical_schema_version: Literal["structured-knowledge.v1"]
    configuration_sha256: Sha256


class StructuredBlock(_StructuredDocumentModel):
    block_id: NonBlankStr
    block_type: Literal[
        "heading",
        "paragraph",
        "list_item",
        "caption",
        "footnote",
        "header",
        "footer",
        "other",
    ] = Field(
        validation_alias=AliasChoices("kind", "block_type"),
        serialization_alias="kind",
    )
    text: str
    bbox: BoundingBox
    reading_order: int = Field(ge=0)
    heading_level: int | None = Field(default=None, ge=1, le=6)
    heading_path: tuple[NonBlankStr, ...] = ()
    source_method: Literal["native", "ocr", "reconstructed"] = "native"

    @model_validator(mode="after")
    def validate_heading_level(self) -> StructuredBlock:
        if self.block_type == "heading" and self.heading_level is None:
            raise ValueError("heading blocks require heading_level")
        if self.block_type != "heading" and self.heading_level is not None:
            raise ValueError("only heading blocks may define heading_level")
        return self


class StructuredTableCell(_StructuredDocumentModel):
    row: int = Field(ge=0)
    column: int = Field(ge=0)
    row_span: int = Field(default=1, ge=1)
    column_span: int = Field(default=1, ge=1)
    text: str
    bbox: BoundingBox
    source_method: Literal["native", "ocr", "reconstructed"] = "native"


class StructuredTable(_StructuredDocumentModel):
    table_id: NonBlankStr
    title: str | None = None
    bbox: BoundingBox
    continuation_of: NonBlankStr | None = None
    cells: tuple[StructuredTableCell, ...] = ()

    @model_validator(mode="after")
    def validate_continuation_identity(self) -> StructuredTable:
        if self.continuation_of == self.table_id:
            raise ValueError("a table cannot continue itself")
        return self


class StructuredPage(_StructuredDocumentModel):
    page_number: int = Field(ge=1)
    width: float = Field(gt=0, allow_inf_nan=False)
    height: float = Field(gt=0, allow_inf_nan=False)
    native_text_ratio: float = Field(ge=0, le=1, allow_inf_nan=False)
    blocks: tuple[StructuredBlock, ...] = ()
    tables: tuple[StructuredTable, ...] = ()


class ParserWarning(_StructuredDocumentModel):
    code: NonBlankStr
    message: NonBlankStr
    page_number: int | None = Field(default=None, ge=1)
    block_id: NonBlankStr | None = None
    table_id: NonBlankStr | None = None


class StructuredQualitySignal(_StructuredDocumentModel):
    code: NonBlankStr
    score: float = Field(ge=0, le=1, allow_inf_nan=False)
    page_number: int | None = Field(default=None, ge=1)
    block_id: NonBlankStr | None = None
    table_id: NonBlankStr | None = None
    requires_review: bool = False


class StructuredKnowledgeDocumentArtifact(_StructuredDocumentModel):
    schema_version: Literal["structured-knowledge.v1"]
    document_id: NonBlankStr
    revision_id: NonBlankStr
    original_sha256: Sha256
    build_identity: StructuredArtifactBuildIdentity
    pages: tuple[StructuredPage, ...] = Field(min_length=1)
    warnings: tuple[ParserWarning, ...] = ()
    quality_signals: tuple[StructuredQualitySignal, ...] = ()

    @model_validator(mode="after")
    def validate_source_provenance(self) -> StructuredKnowledgeDocumentArtifact:
        if self.original_sha256 != self.build_identity.source_sha256:
            raise ValueError("original_sha256 must match build identity source_sha256")
        return self
