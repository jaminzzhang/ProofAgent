"""Convert bounded vendor JSON into provider-neutral structured artifacts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated, Literal

from pydantic import ConfigDict, StrictStr, StringConstraints

from proof_agent.contracts._base import FrozenModel
from proof_agent.contracts.hybrid_documents import (
    BoundingBox,
    ParserWarning,
    StructuredArtifactBuildIdentity,
    StructuredBlock,
    StructuredKnowledgeDocumentArtifact,
    StructuredPage,
    StructuredTable,
    StructuredTableCell,
)


NonBlankStr = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1)]
SourceMethod = Literal["native", "ocr", "reconstructed"]
BlockType = Literal[
    "heading", "paragraph", "list_item", "caption", "footnote", "header", "footer", "other"
]


class CanonicalParserPage(FrozenModel):
    """One provider-neutral page plus the exact vendor-build lineage that produced it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: NonBlankStr
    revision_id: NonBlankStr
    original_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    build_identity: StructuredArtifactBuildIdentity
    page: StructuredPage
    warnings: tuple[ParserWarning, ...] = ()


def canonicalize_docling(
    payload: Mapping[str, object],
    *,
    build: StructuredArtifactBuildIdentity,
) -> StructuredKnowledgeDocumentArtifact:
    """Map Docling service JSON without retaining vendor-specific objects."""

    _require_adapter(build, "docling")
    document_id, revision_id, original_sha256 = _document_identity(payload, build)
    pages = tuple(
        _canonical_page(_mapping(page, "pages[]"), source_method="native")
        for page in _sequence(payload.get("pages"), "pages")
    )
    return StructuredKnowledgeDocumentArtifact(
        schema_version="structured-knowledge.v1",
        document_id=document_id,
        revision_id=revision_id,
        original_sha256=original_sha256,
        build_identity=build,
        pages=pages,
        warnings=_warnings(payload),
    )


def canonicalize_paddle_page(
    payload: Mapping[str, object],
    *,
    build: StructuredArtifactBuildIdentity,
) -> CanonicalParserPage:
    """Map one selected Paddle page and keep its exact build identity beside the page."""

    _require_adapter(build, "paddle")
    document_id, revision_id, original_sha256 = _document_identity(payload, build)
    page = _canonical_page(_mapping(payload.get("page"), "page"), source_method="ocr")
    return CanonicalParserPage(
        document_id=document_id,
        revision_id=revision_id,
        original_sha256=original_sha256,
        build_identity=build,
        page=page,
        warnings=_warnings(payload),
    )


def _document_identity(
    payload: Mapping[str, object], build: StructuredArtifactBuildIdentity
) -> tuple[str, str, str]:
    document_id = _string(payload.get("document_id"), "document_id")
    revision_id = _string(payload.get("revision_id"), "revision_id")
    original_sha256 = _string(payload.get("source_sha256"), "source_sha256")
    if original_sha256 != build.source_sha256:
        raise ValueError("vendor source_sha256 must match build source_sha256")
    return document_id, revision_id, original_sha256


def _canonical_page(
    payload: Mapping[str, object], *, source_method: SourceMethod
) -> StructuredPage:
    blocks = tuple(
        _canonical_block(_mapping(block, "blocks[]"), source_method=source_method)
        for block in _sequence(payload.get("blocks", ()), "blocks")
    )
    tables = tuple(
        _canonical_table(_mapping(table, "tables[]"), source_method=source_method)
        for table in _sequence(payload.get("tables", ()), "tables")
    )
    return StructuredPage(
        page_number=_integer(payload.get("page_number"), "page_number"),
        width=_number(payload.get("width"), "width"),
        height=_number(payload.get("height"), "height"),
        native_text_ratio=(
            _number(payload.get("native_text_ratio"), "native_text_ratio")
            if "native_text_ratio" in payload
            else 0.0
        ),
        blocks=blocks,
        tables=tables,
    )


def _canonical_block(
    payload: Mapping[str, object], *, source_method: SourceMethod
) -> StructuredBlock:
    label = _string(payload.get("label"), "block.label")
    block_type, heading_level = _block_type(label, payload.get("heading_level"))
    return StructuredBlock(
        block_id=_string(payload.get("id"), "block.id"),
        block_type=block_type,
        text=_string(payload.get("text"), "block.text", allow_empty=True),
        bbox=_bbox(payload.get("bbox"), "block.bbox"),
        reading_order=_integer(payload.get("reading_order"), "block.reading_order", minimum=0),
        heading_level=heading_level,
        heading_path=tuple(
            _string(value, "block.heading_path[]")
            for value in _sequence(payload.get("heading_path", ()), "block.heading_path")
        ),
        source_method=source_method,
    )


def _block_type(label: str, raw_level: object) -> tuple[BlockType, int | None]:
    labels: dict[str, BlockType] = {
        "section_header": "heading",
        "heading": "heading",
        "text": "paragraph",
        "paragraph": "paragraph",
        "list_item": "list_item",
        "caption": "caption",
        "footnote": "footnote",
        "header": "header",
        "footer": "footer",
    }
    block_type = labels.get(label, "other")
    if block_type == "heading":
        return block_type, _integer(raw_level, "block.heading_level", minimum=1)
    if raw_level is not None:
        raise ValueError("only heading blocks may define heading_level")
    return block_type, None


def _canonical_table(
    payload: Mapping[str, object], *, source_method: SourceMethod
) -> StructuredTable:
    continuation = payload.get("continuation_of")
    return StructuredTable(
        table_id=_string(payload.get("id"), "table.id"),
        title=(None if payload.get("title") is None else _string(payload["title"], "table.title")),
        bbox=_bbox(payload.get("bbox"), "table.bbox"),
        continuation_of=(
            None if continuation is None else _string(continuation, "table.continuation_of")
        ),
        cells=tuple(
            _canonical_cell(_mapping(cell, "table.cells[]"), source_method=source_method)
            for cell in _sequence(payload.get("cells", ()), "table.cells")
        ),
    )


def _canonical_cell(
    payload: Mapping[str, object], *, source_method: SourceMethod
) -> StructuredTableCell:
    return StructuredTableCell(
        row=_integer(payload.get("row"), "cell.row", minimum=0),
        column=_integer(payload.get("column"), "cell.column", minimum=0),
        row_span=_integer(payload.get("row_span", 1), "cell.row_span", minimum=1),
        column_span=_integer(payload.get("column_span", 1), "cell.column_span", minimum=1),
        text=_string(payload.get("text"), "cell.text", allow_empty=True),
        bbox=_bbox(payload.get("bbox"), "cell.bbox"),
        source_method=source_method,
    )


def _warnings(payload: Mapping[str, object]) -> tuple[ParserWarning, ...]:
    return tuple(
        ParserWarning.model_validate(_mapping(warning, "warnings[]"))
        for warning in _sequence(payload.get("warnings", ()), "warnings")
    )


def _bbox(value: object, name: str) -> BoundingBox:
    values = _sequence(value, name)
    if len(values) != 4:
        raise ValueError(f"{name} must contain exactly four coordinates")
    return BoundingBox(
        x0=_number(values[0], f"{name}[0]"),
        y0=_number(values[1], f"{name}[1]"),
        x1=_number(values[2], f"{name}[2]"),
        y1=_number(values[3], f"{name}[3]"),
    )


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{name} must be a JSON object")
    return value


def _sequence(value: object, name: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{name} must be a JSON array")
    return value


def _string(value: object, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"{name} must be a string")
    return value


def _integer(value: object, name: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer greater than or equal to {minimum}")
    return value


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    return float(value)


def _require_adapter(build: StructuredArtifactBuildIdentity, adapter: str) -> None:
    if build.parser_adapter != adapter:
        raise ValueError(f"{adapter} canonicalization requires a {adapter} build identity")
