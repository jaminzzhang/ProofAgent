"""Convert bounded vendor JSON into provider-neutral structured artifacts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, StrictStr, StringConstraints, model_validator

from proof_agent.capabilities.knowledge.hybrid.parser_clients import ParserServiceResponse
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
MAX_BLOCKS_PER_PAGE = 10_000
MAX_TABLES_PER_PAGE = 1_000
MAX_CELLS_PER_TABLE = 10_000
MAX_WARNINGS = 10_000
MAX_HEADING_DEPTH = 64
MAX_TEXT_CHARACTERS = 1_000_000
MAX_IDENTIFIER_CHARACTERS = 512
MAX_GRID_INDEX = 100_000
MAX_CELL_SPAN = 10_000
MAX_PAGE_DIMENSION = 1_000_000.0


class CanonicalParserPage(FrozenModel):
    """One provider-neutral page plus the exact vendor-build lineage that produced it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: NonBlankStr
    revision_id: NonBlankStr
    original_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    build_identity: StructuredArtifactBuildIdentity
    page: StructuredPage
    warnings: tuple[ParserWarning, ...] = ()

    @model_validator(mode="after")
    def validate_source_provenance(self) -> Self:
        if self.original_sha256 != self.build_identity.source_sha256:
            raise ValueError("original_sha256 must match build identity source_sha256")
        validate_page_geometry_and_bounds(self.page)
        return self


def canonicalize_docling(
    response: ParserServiceResponse,
    *,
    build: StructuredArtifactBuildIdentity,
) -> StructuredKnowledgeDocumentArtifact:
    """Map Docling service JSON without retaining vendor-specific objects."""

    response = ParserServiceResponse.model_validate(response.model_dump())
    _require_attested_build(response, build, "docling")
    payload = response.vendor_json
    document_id, revision_id, original_sha256 = _document_identity(payload, build)
    pages = tuple(
        _canonical_page(_mapping(page, "pages[]"), source_method="native")
        for page in _sequence(payload.get("pages"), "pages", max_items=500)
    )
    artifact = StructuredKnowledgeDocumentArtifact(
        schema_version="structured-knowledge.v1",
        document_id=document_id,
        revision_id=revision_id,
        original_sha256=original_sha256,
        build_identity=build,
        pages=pages,
        warnings=_warnings(payload),
    )
    for page in artifact.pages:
        validate_page_geometry_and_bounds(page)
    return artifact


def canonicalize_paddle_page(
    response: ParserServiceResponse,
    *,
    build: StructuredArtifactBuildIdentity,
) -> CanonicalParserPage:
    """Map one selected Paddle page and keep its exact build identity beside the page."""

    response = ParserServiceResponse.model_validate(response.model_dump())
    _require_attested_build(response, build, "paddle")
    payload = response.vendor_json
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
    width = _number(payload.get("width"), "width", maximum=MAX_PAGE_DIMENSION)
    height = _number(payload.get("height"), "height", maximum=MAX_PAGE_DIMENSION)
    blocks = tuple(
        _canonical_block(_mapping(block, "blocks[]"), source_method=source_method)
        for block in _sequence(payload.get("blocks", ()), "blocks", max_items=MAX_BLOCKS_PER_PAGE)
    )
    tables = tuple(
        _canonical_table(_mapping(table, "tables[]"), source_method=source_method)
        for table in _sequence(payload.get("tables", ()), "tables", max_items=MAX_TABLES_PER_PAGE)
    )
    page = StructuredPage(
        page_number=_integer(payload.get("page_number"), "page_number", maximum=500),
        width=width,
        height=height,
        native_text_ratio=(
            _number(payload.get("native_text_ratio"), "native_text_ratio")
            if "native_text_ratio" in payload
            else 0.0
        ),
        blocks=blocks,
        tables=tables,
    )
    validate_page_geometry_and_bounds(page)
    return page


def _canonical_block(
    payload: Mapping[str, object], *, source_method: SourceMethod
) -> StructuredBlock:
    label = _string(payload.get("label"), "block.label")
    block_type, heading_level = _block_type(label, payload.get("heading_level"))
    return StructuredBlock(
        block_id=_string(payload.get("id"), "block.id", max_characters=MAX_IDENTIFIER_CHARACTERS),
        block_type=block_type,
        text=_string(
            payload.get("text"),
            "block.text",
            allow_empty=True,
            max_characters=MAX_TEXT_CHARACTERS,
        ),
        bbox=_bbox(payload.get("bbox"), "block.bbox"),
        reading_order=_integer(
            payload.get("reading_order"),
            "block.reading_order",
            minimum=0,
            maximum=MAX_BLOCKS_PER_PAGE - 1,
        ),
        heading_level=heading_level,
        heading_path=tuple(
            _string(
                value,
                "block.heading_path[]",
                max_characters=MAX_IDENTIFIER_CHARACTERS,
            )
            for value in _sequence(
                payload.get("heading_path", ()),
                "block.heading_path",
                max_items=MAX_HEADING_DEPTH,
            )
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
        return block_type, _integer(raw_level, "block.heading_level", minimum=1, maximum=6)
    if raw_level is not None:
        raise ValueError("only heading blocks may define heading_level")
    return block_type, None


def _canonical_table(
    payload: Mapping[str, object], *, source_method: SourceMethod
) -> StructuredTable:
    continuation = payload.get("continuation_of")
    return StructuredTable(
        table_id=_string(payload.get("id"), "table.id", max_characters=MAX_IDENTIFIER_CHARACTERS),
        title=(
            None
            if payload.get("title") is None
            else _string(payload["title"], "table.title", max_characters=MAX_TEXT_CHARACTERS)
        ),
        bbox=_bbox(payload.get("bbox"), "table.bbox"),
        continuation_of=(
            None
            if continuation is None
            else _string(
                continuation,
                "table.continuation_of",
                max_characters=MAX_IDENTIFIER_CHARACTERS,
            )
        ),
        cells=tuple(
            _canonical_cell(_mapping(cell, "table.cells[]"), source_method=source_method)
            for cell in _sequence(
                payload.get("cells", ()), "table.cells", max_items=MAX_CELLS_PER_TABLE
            )
        ),
    )


def _canonical_cell(
    payload: Mapping[str, object], *, source_method: SourceMethod
) -> StructuredTableCell:
    return StructuredTableCell(
        row=_integer(payload.get("row"), "cell.row", minimum=0, maximum=MAX_GRID_INDEX),
        column=_integer(payload.get("column"), "cell.column", minimum=0, maximum=MAX_GRID_INDEX),
        row_span=_integer(
            payload.get("row_span", 1), "cell.row_span", minimum=1, maximum=MAX_CELL_SPAN
        ),
        column_span=_integer(
            payload.get("column_span", 1),
            "cell.column_span",
            minimum=1,
            maximum=MAX_CELL_SPAN,
        ),
        text=_string(
            payload.get("text"),
            "cell.text",
            allow_empty=True,
            max_characters=MAX_TEXT_CHARACTERS,
        ),
        bbox=_bbox(payload.get("bbox"), "cell.bbox"),
        source_method=source_method,
    )


def _warnings(payload: Mapping[str, object]) -> tuple[ParserWarning, ...]:
    return tuple(
        ParserWarning.model_validate(_mapping(warning, "warnings[]"))
        for warning in _sequence(payload.get("warnings", ()), "warnings", max_items=MAX_WARNINGS)
    )


def _bbox(value: object, name: str) -> BoundingBox:
    values = _sequence(value, name, max_items=4)
    if len(values) != 4:
        raise ValueError(f"{name} must contain exactly four coordinates")
    return BoundingBox(
        x0=_number(values[0], f"{name}[0]", minimum=0, maximum=MAX_PAGE_DIMENSION),
        y0=_number(values[1], f"{name}[1]", minimum=0, maximum=MAX_PAGE_DIMENSION),
        x1=_number(values[2], f"{name}[2]", minimum=0, maximum=MAX_PAGE_DIMENSION),
        y1=_number(values[3], f"{name}[3]", minimum=0, maximum=MAX_PAGE_DIMENSION),
    )


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{name} must be a JSON object")
    return value


def _sequence(value: object, name: str, *, max_items: int) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{name} must be a JSON array")
    if len(value) > max_items:
        raise ValueError(f"{name} exceeds the {max_items}-item limit")
    return value


def _string(
    value: object,
    name: str,
    *,
    allow_empty: bool = False,
    max_characters: int = MAX_IDENTIFIER_CHARACTERS,
) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"{name} must be a string")
    if len(value) > max_characters:
        raise ValueError(f"{name} exceeds the {max_characters}-character limit")
    return value


def _integer(value: object, name: str, *, minimum: int = 1, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer between {minimum} and {maximum}")
    return value


def _number(
    value: object,
    name: str,
    *,
    minimum: float = 0.0,
    maximum: float = 1.0,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    result = float(value)
    if not minimum <= result <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return result


def validate_page_geometry_and_bounds(page: StructuredPage) -> None:
    """Defensively validate canonical page complexity and all nested coordinates."""

    if not 1 <= page.page_number <= 500:
        raise ValueError("canonical page_number is outside the supported range")
    if (
        not math.isfinite(page.width)
        or not math.isfinite(page.height)
        or not 0 < page.width <= MAX_PAGE_DIMENSION
        or not 0 < page.height <= MAX_PAGE_DIMENSION
    ):
        raise ValueError("canonical page dimensions are invalid")
    if len(page.blocks) > MAX_BLOCKS_PER_PAGE or len(page.tables) > MAX_TABLES_PER_PAGE:
        raise ValueError("canonical page exceeds structure limits")
    for block in page.blocks:
        if len(block.block_id) > MAX_IDENTIFIER_CHARACTERS:
            raise ValueError("canonical block identity exceeds the character limit")
        if len(block.text) > MAX_TEXT_CHARACTERS:
            raise ValueError("canonical block text exceeds the character limit")
        if not 0 <= block.reading_order < MAX_BLOCKS_PER_PAGE:
            raise ValueError("canonical block reading_order exceeds the supported range")
        if len(block.heading_path) > MAX_HEADING_DEPTH:
            raise ValueError("canonical heading path exceeds the depth limit")
        if any(len(item) > MAX_IDENTIFIER_CHARACTERS for item in block.heading_path):
            raise ValueError("canonical heading path item exceeds the character limit")
        _validate_bbox_within_page(block.bbox, page)
    for table in page.tables:
        if len(table.table_id) > MAX_IDENTIFIER_CHARACTERS:
            raise ValueError("canonical table identity exceeds the character limit")
        if table.title is not None and len(table.title) > MAX_TEXT_CHARACTERS:
            raise ValueError("canonical table title exceeds the character limit")
        if (
            table.continuation_of is not None
            and len(table.continuation_of) > MAX_IDENTIFIER_CHARACTERS
        ):
            raise ValueError("canonical table continuation identity exceeds the character limit")
        if len(table.cells) > MAX_CELLS_PER_TABLE:
            raise ValueError("canonical table exceeds the cell limit")
        _validate_bbox_within_page(table.bbox, page)
        for cell in table.cells:
            if (
                not 0 <= cell.row <= MAX_GRID_INDEX
                or not 0 <= cell.column <= MAX_GRID_INDEX
                or not 1 <= cell.row_span <= MAX_CELL_SPAN
                or not 1 <= cell.column_span <= MAX_CELL_SPAN
                or cell.row + cell.row_span > MAX_GRID_INDEX + 1
                or cell.column + cell.column_span > MAX_GRID_INDEX + 1
            ):
                raise ValueError("canonical table cell grid values exceed limits")
            if len(cell.text) > MAX_TEXT_CHARACTERS:
                raise ValueError("canonical table cell text exceeds the character limit")
            _validate_bbox_within_page(cell.bbox, page)
            if not _bbox_contains(table.bbox, cell.bbox):
                raise ValueError("canonical table cell bbox must be within its table bbox")


def _validate_bbox_within_page(bbox: BoundingBox, page: StructuredPage) -> None:
    coordinates = (bbox.x0, bbox.y0, bbox.x1, bbox.y1)
    if any(not math.isfinite(value) or value < 0 for value in coordinates):
        raise ValueError("canonical bbox coordinates must be finite and nonnegative")
    if bbox.x1 < bbox.x0 or bbox.y1 < bbox.y0:
        raise ValueError("canonical bbox coordinates must be ordered")
    if bbox.x1 > page.width or bbox.y1 > page.height:
        raise ValueError("canonical bbox must be within page geometry")


def _bbox_contains(outer: BoundingBox, inner: BoundingBox) -> bool:
    return (
        outer.x0 <= inner.x0 <= inner.x1 <= outer.x1
        and outer.y0 <= inner.y0 <= inner.y1 <= outer.y1
    )


def _require_attested_build(
    response: ParserServiceResponse,
    build: StructuredArtifactBuildIdentity,
    adapter: Literal["docling", "paddle"],
) -> None:
    if response.adapter != adapter or build.parser_adapter != adapter:
        raise ValueError(f"{adapter} canonicalization requires a {adapter} build identity")
    attestation = response.attestation
    if build.source_sha256 != attestation.original_ref.sha256:
        raise ValueError("build source_sha256 must match the service attestation")
    if build.parser_revision != attestation.parser_revision:
        raise ValueError("build parser_revision must match the service attestation")
    if build.model_digests != attestation.model_digests:
        raise ValueError("build model_digests must match the service attestation")
    if build.configuration_sha256 != attestation.configuration_sha256:
        raise ValueError("build configuration_sha256 must match the service attestation")
