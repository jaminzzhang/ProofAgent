"""Deterministic projection of canonical insurance documents into reviewable rule units."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from typing import Annotated, Literal, Self
from urllib.parse import quote

from pydantic import ConfigDict, Field, StrictInt, StrictStr, StringConstraints, model_validator

from proof_agent.capabilities.knowledge.hybrid.canonicalizer import (
    validate_page_geometry_and_bounds,
)
from proof_agent.contracts._base import FrozenModel
from proof_agent.contracts.hybrid_documents import (
    BoundingBox,
    StructuredArtifactBuildIdentity,
    StructuredBlock,
    StructuredKnowledgeDocumentArtifact,
    StructuredPage,
    StructuredTable,
    StructuredTableCell,
)
from proof_agent.contracts.insurance_rules import InsuranceRuleMetadataDraft


NonBlankStr = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
Sha256 = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
RuleUnitKind = Literal["document", "clause", "section", "table_row", "row_group"]

_DEFINITION_PATTERN = re.compile(
    r"(?:\bmeans\b|\bdefinition\b|\bis defined as\b|是指|定义为|释义)", re.IGNORECASE
)


class _RuleProjectionModel(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class PageBoundingBox(_RuleProjectionModel):
    """One source-page geometry region contributing to a projected rule unit."""

    page_number: PositiveInt
    bbox: BoundingBox


class RuleCellCoordinate(_RuleProjectionModel):
    """Exact canonical grid and geometry lineage for one table cell."""

    page_number: PositiveInt
    row: NonNegativeInt
    column: NonNegativeInt
    row_span: PositiveInt
    column_span: PositiveInt
    bbox: BoundingBox


class InsuranceRuleUnitDraft(_RuleProjectionModel):
    """Non-authoritative, structurally coherent rule unit awaiting business approval."""

    ordinal: NonNegativeInt
    source_id: NonBlankStr | None = None
    document_id: NonBlankStr
    revision_id: NonBlankStr
    original_sha256: Sha256
    structured_build_id: NonBlankStr
    structured_build_identity: StructuredArtifactBuildIdentity
    logical_rule_key: NonBlankStr
    unit_kind: RuleUnitKind
    content: NonBlankStr
    citation_uri: NonBlankStr
    heading_path: tuple[NonBlankStr, ...] = ()
    definitions: tuple[NonBlankStr, ...] = ()
    page_numbers: tuple[PositiveInt, ...] = Field(min_length=1)
    page_bboxes: tuple[PageBoundingBox, ...] = Field(min_length=1)
    block_ids: tuple[NonBlankStr, ...] = ()
    table_id: NonBlankStr | None = None
    table_continuation_id: NonBlankStr | None = None
    table_context: StrictStr = ""
    row_header: StrictStr | None = None
    row_numbers: tuple[NonNegativeInt, ...] = ()
    header_cell_coordinates: tuple[RuleCellCoordinate, ...] = ()
    cell_coordinates: tuple[RuleCellCoordinate, ...] = ()
    inherited_metadata: InsuranceRuleMetadataDraft

    @model_validator(mode="after")
    def validate_lineage_and_shape(self) -> Self:
        if self.structured_build_id != self.structured_build_identity.build_id:
            raise ValueError("structured build id must match its exact build identity")
        if self.original_sha256 != self.structured_build_identity.source_sha256:
            raise ValueError("original SHA must match the structured build identity")
        if (
            self.inherited_metadata.document_id != self.document_id
            or self.inherited_metadata.revision_id != self.revision_id
        ):
            raise ValueError("inherited metadata draft lineage must match the rule unit")
        if tuple(sorted(set(self.page_numbers))) != self.page_numbers:
            raise ValueError("page_numbers must be strictly increasing and unique")
        if tuple(sorted(set(self.row_numbers))) != self.row_numbers:
            raise ValueError("row_numbers must be strictly increasing and unique")
        if len(set(self.block_ids)) != len(self.block_ids):
            raise ValueError("block_ids must be unique")
        bbox_pages = tuple(item.page_number for item in self.page_bboxes)
        if tuple(sorted(set(bbox_pages))) != bbox_pages:
            raise ValueError("page_bboxes must contain one region per page in page order")
        if set(bbox_pages) != set(self.page_numbers):
            raise ValueError("page_bboxes must cover exactly the projected page_numbers")
        if len(self.definitions) != len(set(self.definitions)):
            raise ValueError("definition context must be unique and deterministic")
        table_kind = self.unit_kind in {"table_row", "row_group"}
        table_fields_present = any(
            (
                self.table_id is not None,
                self.table_continuation_id is not None,
                bool(self.table_context),
                self.row_header is not None,
                bool(self.row_numbers),
                bool(self.header_cell_coordinates),
                bool(self.cell_coordinates),
            )
        )
        if table_kind:
            if self.table_id is None or not self.table_context or not self.row_numbers:
                raise ValueError("table rule units require table context and row lineage")
            if not self.cell_coordinates:
                raise ValueError("table rule units require complete cell coordinates")
            if self.block_ids:
                raise ValueError("table rule units cannot claim block lineage")
            if self.unit_kind == "table_row" and len(self.row_numbers) != 1:
                raise ValueError("table_row requires exactly one row number")
            if self.unit_kind == "row_group" and len(self.row_numbers) < 2:
                raise ValueError("row_group requires at least two row numbers")
            if self.table_continuation_id == self.table_id:
                raise ValueError("a table rule unit cannot continue itself")
            page_regions = {item.page_number: item.bbox for item in self.page_bboxes}
            all_coordinates = (*self.header_cell_coordinates, *self.cell_coordinates)
            coordinate_keys = [
                (item.page_number, item.row, item.column) for item in all_coordinates
            ]
            if len(coordinate_keys) != len(set(coordinate_keys)):
                raise ValueError("table cell coordinate anchors must be unique")
            for coordinate in all_coordinates:
                region = page_regions.get(coordinate.page_number)
                if region is None or not _bbox_contains(region, coordinate.bbox):
                    raise ValueError("table cell coordinates must stay within rule-unit geometry")
            covered_intervals = _merge_integer_intervals(
                (
                    (coordinate.row, coordinate.row + coordinate.row_span - 1)
                    for coordinate in self.cell_coordinates
                ),
                merge_adjacent=True,
            )
            if covered_intervals != _integer_intervals(self.row_numbers):
                raise ValueError("data cell coordinates must cover exactly the projected rows")
        elif table_fields_present:
            raise ValueError("non-table rule units cannot contain table lineage")
        return self


def project_rule_units(
    artifact: StructuredKnowledgeDocumentArtifact,
    *,
    document_defaults: InsuranceRuleMetadataDraft,
    source_id: str | None = None,
) -> tuple[InsuranceRuleUnitDraft, ...]:
    """Project business-reviewable structural units; never split by token count or cell."""

    _validate_projection_inputs(artifact, document_defaults=document_defaults, source_id=source_id)
    if source_id is not None:
        source_id = source_id.strip()
    definitions = _collect_definitions(artifact.pages)
    block_candidates = _project_blocks(artifact.pages, definitions=definitions)
    table_candidates = _project_tables(artifact.pages, definitions=definitions)
    candidates = sorted(
        (*block_candidates, *table_candidates),
        key=lambda item: item.sort_key,
    )
    if not candidates:
        raise ValueError("canonical artifact contains no coherent rule units")
    units = tuple(
        _draft_from_candidate(
            artifact,
            candidate,
            ordinal=ordinal,
            document_defaults=document_defaults,
            source_id=source_id,
        )
        for ordinal, candidate in enumerate(candidates)
    )
    logical_keys = [unit.logical_rule_key for unit in units]
    if len(logical_keys) != len(set(logical_keys)):
        raise ValueError("projected logical rule keys must be unique")
    return units


class _ProjectionCandidate(_RuleProjectionModel):
    sort_key: tuple[PositiveInt, NonNegativeInt, NonNegativeInt, NonBlankStr]
    unit_kind: RuleUnitKind
    content: NonBlankStr
    heading_path: tuple[NonBlankStr, ...]
    definitions: tuple[NonBlankStr, ...]
    page_numbers: tuple[PositiveInt, ...]
    page_bboxes: tuple[PageBoundingBox, ...]
    block_ids: tuple[NonBlankStr, ...] = ()
    anchor_parts: tuple[NonBlankStr, ...]
    table_id: NonBlankStr | None = None
    table_continuation_id: NonBlankStr | None = None
    table_context: StrictStr = ""
    row_header: StrictStr | None = None
    row_numbers: tuple[NonNegativeInt, ...] = ()
    header_cell_coordinates: tuple[RuleCellCoordinate, ...] = ()
    cell_coordinates: tuple[RuleCellCoordinate, ...] = ()


def _validate_projection_inputs(
    artifact: StructuredKnowledgeDocumentArtifact,
    *,
    document_defaults: InsuranceRuleMetadataDraft,
    source_id: str | None,
) -> None:
    # Revalidation closes model_copy/construct bypasses before identity material is produced.
    artifact = StructuredKnowledgeDocumentArtifact.model_validate(artifact.model_dump())
    document_defaults = InsuranceRuleMetadataDraft.model_validate(document_defaults.model_dump())
    if (
        document_defaults.document_id != artifact.document_id
        or document_defaults.revision_id != artifact.revision_id
    ):
        raise ValueError("metadata draft lineage must match the canonical artifact")
    if source_id is not None and not source_id.strip():
        raise ValueError("source_id must be non-empty when supplied")
    page_numbers = tuple(page.page_number for page in artifact.pages)
    if tuple(sorted(set(page_numbers))) != page_numbers:
        raise ValueError("canonical page numbers must be strictly increasing and unique")
    prior_table_ids: set[str] = set()
    seen_block_ids: set[str] = set()
    seen_table_ids: set[str] = set()
    for page in artifact.pages:
        validate_page_geometry_and_bounds(page)
        block_ids = {block.block_id for block in page.blocks}
        table_ids = {table.table_id for table in page.tables}
        if len(block_ids) != len(page.blocks) or block_ids & seen_block_ids:
            raise ValueError("canonical block identities must be document-unique")
        if len(table_ids) != len(page.tables) or table_ids & seen_table_ids:
            raise ValueError("canonical table identities must be document-unique")
        orders = tuple(block.reading_order for block in page.blocks)
        if len(orders) != len(set(orders)) or tuple(sorted(orders)) != orders:
            raise ValueError("canonical block reading order must be strictly increasing and unique")
        for table in page.tables:
            if table.continuation_of is not None and table.continuation_of not in prior_table_ids:
                raise ValueError("table continuation must reference an earlier canonical table")
            grid_anchors = [(cell.row, cell.column) for cell in table.cells]
            if len(grid_anchors) != len(set(grid_anchors)):
                raise ValueError("canonical table cell anchors must be unique")
        seen_block_ids.update(block_ids)
        seen_table_ids.update(table_ids)
        prior_table_ids.update(table_ids)


def _collect_definitions(pages: tuple[StructuredPage, ...]) -> tuple[StructuredBlock, ...]:
    return tuple(
        block
        for page in pages
        for block in page.blocks
        if block.text.strip() and _DEFINITION_PATTERN.search(block.text) is not None
    )


def _project_blocks(
    pages: tuple[StructuredPage, ...],
    *,
    definitions: tuple[StructuredBlock, ...],
) -> tuple[_ProjectionCandidate, ...]:
    ordered = tuple((page, block) for page in pages for block in page.blocks)
    candidates: list[_ProjectionCandidate] = []
    index = 0
    while index < len(ordered):
        page, block = ordered[index]
        if block.block_type != "heading":
            if block.block_type in {"paragraph", "list_item"} and block.text.strip():
                candidates.append(
                    _block_candidate(page, block, definitions=definitions, unit_kind="clause")
                )
            index += 1
            continue

        section_blocks = [block]
        cursor = index + 1
        while cursor < len(ordered) and ordered[cursor][1].block_type != "heading":
            _, candidate = ordered[cursor]
            if candidate.block_type not in {"header", "footer"} and candidate.text.strip():
                section_blocks.append(candidate)
            cursor += 1
        candidates.append(_section_candidate(ordered[index:cursor], section_blocks, definitions))
        index += 1
    return tuple(candidates)


def _block_candidate(
    page: StructuredPage,
    block: StructuredBlock,
    *,
    definitions: tuple[StructuredBlock, ...],
    unit_kind: Literal["clause"],
) -> _ProjectionCandidate:
    return _ProjectionCandidate(
        sort_key=(page.page_number, block.reading_order, 1, block.block_id),
        unit_kind=unit_kind,
        content=block.text.strip(),
        heading_path=block.heading_path,
        definitions=_definition_texts(definitions, block.heading_path),
        page_numbers=(page.page_number,),
        page_bboxes=(PageBoundingBox(page_number=page.page_number, bbox=block.bbox),),
        block_ids=(block.block_id,),
        anchor_parts=(block.block_id,),
    )


def _section_candidate(
    ordered_slice: tuple[tuple[StructuredPage, StructuredBlock], ...],
    blocks: list[StructuredBlock],
    definitions: tuple[StructuredBlock, ...],
) -> _ProjectionCandidate:
    heading = blocks[0]
    included_block_ids = {block.block_id for block in blocks}
    included = [
        (page, block) for page, block in ordered_slice if block.block_id in included_block_ids
    ]
    page_numbers = tuple(dict.fromkeys(page.page_number for page, _ in included))
    page_bboxes = tuple(
        PageBoundingBox(
            page_number=page_number,
            bbox=_union_bbox(
                block.bbox for page, block in included if page.page_number == page_number
            ),
        )
        for page_number in page_numbers
    )
    return _ProjectionCandidate(
        sort_key=(ordered_slice[0][0].page_number, heading.reading_order, 0, heading.block_id),
        unit_kind="section",
        content="\n".join(block.text.strip() for block in blocks),
        heading_path=heading.heading_path or (heading.text.strip(),),
        definitions=_definition_texts(definitions, heading.heading_path),
        page_numbers=page_numbers,
        page_bboxes=page_bboxes,
        block_ids=tuple(block.block_id for block in blocks),
        anchor_parts=(heading.block_id,),
    )


def _project_tables(
    pages: tuple[StructuredPage, ...],
    *,
    definitions: tuple[StructuredBlock, ...],
) -> tuple[_ProjectionCandidate, ...]:
    candidates: list[_ProjectionCandidate] = []
    active_heading: tuple[str, ...] = ()
    for page in pages:
        page_headings = [block for block in page.blocks if block.block_type == "heading"]
        if page_headings:
            final_heading = page_headings[-1]
            active_heading = final_heading.heading_path or (final_heading.text.strip(),)
        for table_index, table in enumerate(page.tables):
            candidates.extend(
                _table_candidates(
                    page,
                    table,
                    table_index=table_index,
                    heading_path=active_heading,
                    definitions=definitions,
                )
            )
    return tuple(candidates)


def _table_candidates(
    page: StructuredPage,
    table: StructuredTable,
    *,
    table_index: int,
    heading_path: tuple[str, ...],
    definitions: tuple[StructuredBlock, ...],
) -> tuple[_ProjectionCandidate, ...]:
    nonempty = tuple(cell for cell in table.cells if cell.text.strip())
    if not nonempty:
        return ()
    rows = _covered_grid_rows(nonempty)
    if len(rows) == 1:
        header_rows: tuple[int, ...] = ()
        data_rows = tuple(rows)
    else:
        header_rows = (rows[0],)
        data_rows = tuple(rows[1:])
    header_cells = tuple(cell for cell in nonempty if cell.row in header_rows)
    table_context = _table_context(table, header_cells)
    row_groups = _connected_row_groups(data_rows, nonempty)
    candidates: list[_ProjectionCandidate] = []
    for group_index, row_numbers in enumerate(row_groups):
        data_cells = tuple(
            cell
            for cell in nonempty
            if cell.row not in header_rows
            and cell.row <= row_numbers[-1]
            and cell.row + cell.row_span - 1 >= row_numbers[0]
        )
        data_cells = tuple(sorted(data_cells, key=lambda cell: (cell.row, cell.column)))
        if not data_cells:
            continue
        row_header_cell = min(data_cells, key=lambda cell: (cell.column, cell.row))
        row_header = row_header_cell.text.strip() or None
        unit_kind: Literal["table_row", "row_group"] = (
            "row_group" if len(row_numbers) > 1 else "table_row"
        )
        candidates.append(
            _ProjectionCandidate(
                sort_key=(page.page_number, 1_000_000 + table_index, group_index, table.table_id),
                unit_kind=unit_kind,
                content=" | ".join(cell.text.strip() for cell in data_cells),
                heading_path=heading_path,
                definitions=_definition_texts(definitions, heading_path),
                page_numbers=(page.page_number,),
                page_bboxes=(
                    PageBoundingBox(
                        page_number=page.page_number,
                        bbox=table.bbox,
                    ),
                ),
                anchor_parts=(
                    table.table_id,
                    "rows-" + "-".join(str(row) for row in row_numbers),
                ),
                table_id=table.table_id,
                table_continuation_id=table.continuation_of,
                table_context=table_context,
                row_header=row_header,
                row_numbers=row_numbers,
                header_cell_coordinates=tuple(
                    _cell_coordinate(page.page_number, cell) for cell in header_cells
                ),
                cell_coordinates=tuple(
                    _cell_coordinate(page.page_number, cell) for cell in data_cells
                ),
            )
        )
    return tuple(candidates)


def _connected_row_groups(
    data_rows: tuple[int, ...], cells: tuple[StructuredTableCell, ...]
) -> tuple[tuple[int, ...], ...]:
    if not data_rows:
        return ()
    intervals = [(row, row) for row in data_rows]
    intervals.extend(
        (cell.row, cell.row + cell.row_span - 1)
        for cell in cells
        if cell.row <= data_rows[-1] and cell.row + cell.row_span - 1 >= data_rows[0]
    )
    return tuple(
        tuple(row for row in data_rows if start <= row <= end)
        for start, end in _merge_integer_intervals(intervals)
    )


def _covered_grid_rows(cells: tuple[StructuredTableCell, ...]) -> tuple[int, ...]:
    intervals = _merge_integer_intervals(
        ((cell.row, cell.row + cell.row_span - 1) for cell in cells),
        merge_adjacent=True,
    )
    return tuple(row for start, end in intervals for row in range(start, end + 1))


def _integer_intervals(values: tuple[int, ...]) -> tuple[tuple[int, int], ...]:
    return _merge_integer_intervals(
        ((value, value) for value in values),
        merge_adjacent=True,
    )


def _merge_integer_intervals(
    intervals: Iterable[tuple[int, int]],
    *,
    merge_adjacent: bool = False,
) -> tuple[tuple[int, int], ...]:
    ordered = sorted(intervals)
    if not ordered:
        return ()
    merged: list[tuple[int, int]] = []
    current_start, current_end = ordered[0]
    for start, end in ordered[1:]:
        threshold = current_end + 1 if merge_adjacent else current_end
        if start <= threshold:
            current_end = max(current_end, end)
        else:
            merged.append((current_start, current_end))
            current_start, current_end = start, end
    merged.append((current_start, current_end))
    return tuple(merged)


def _table_context(table: StructuredTable, header_cells: tuple[StructuredTableCell, ...]) -> str:
    parts: list[str] = []
    if table.title and table.title.strip():
        parts.append(table.title.strip())
    if header_cells:
        parts.append(
            "Headers: "
            + " | ".join(cell.text.strip() for cell in sorted(header_cells, key=lambda c: c.column))
        )
    if table.continuation_of is not None:
        parts.append(f"Continuation of: {table.continuation_of}")
    return "\n".join(parts) or f"Table: {table.table_id}"


def _cell_coordinate(page_number: int, cell: StructuredTableCell) -> RuleCellCoordinate:
    return RuleCellCoordinate(
        page_number=page_number,
        row=cell.row,
        column=cell.column,
        row_span=cell.row_span,
        column_span=cell.column_span,
        bbox=cell.bbox,
    )


def _definition_texts(
    definitions: tuple[StructuredBlock, ...], heading_path: tuple[str, ...]
) -> tuple[str, ...]:
    related = tuple(
        block.text.strip()
        for block in definitions
        if _paths_related(block.heading_path, heading_path)
    )
    return tuple(dict.fromkeys(related))


def _paths_related(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    if not left or not right:
        return True
    shared = min(len(left), len(right))
    return left[:shared] == right[:shared]


def _draft_from_candidate(
    artifact: StructuredKnowledgeDocumentArtifact,
    candidate: _ProjectionCandidate,
    *,
    ordinal: int,
    document_defaults: InsuranceRuleMetadataDraft,
    source_id: str | None,
) -> InsuranceRuleUnitDraft:
    logical_key_payload = {
        "source_id": source_id,
        "document_id": artifact.document_id,
        "unit_kind": candidate.unit_kind,
        "anchor_parts": candidate.anchor_parts,
    }
    logical_key = f"lrk-{_sha256_json(logical_key_payload)}"
    citation_uri = _citation_uri(
        source_id=source_id,
        document_id=artifact.document_id,
        revision_id=artifact.revision_id,
        page_numbers=candidate.page_numbers,
        anchor=candidate.anchor_parts[0],
    )
    return InsuranceRuleUnitDraft(
        ordinal=ordinal,
        source_id=source_id,
        document_id=artifact.document_id,
        revision_id=artifact.revision_id,
        original_sha256=artifact.original_sha256,
        structured_build_id=artifact.build_identity.build_id,
        structured_build_identity=artifact.build_identity,
        logical_rule_key=logical_key,
        unit_kind=candidate.unit_kind,
        content=candidate.content,
        citation_uri=citation_uri,
        heading_path=candidate.heading_path,
        definitions=candidate.definitions,
        page_numbers=candidate.page_numbers,
        page_bboxes=candidate.page_bboxes,
        block_ids=candidate.block_ids,
        table_id=candidate.table_id,
        table_continuation_id=candidate.table_continuation_id,
        table_context=candidate.table_context,
        row_header=candidate.row_header,
        row_numbers=candidate.row_numbers,
        header_cell_coordinates=candidate.header_cell_coordinates,
        cell_coordinates=candidate.cell_coordinates,
        inherited_metadata=document_defaults,
    )


def _citation_uri(
    *,
    source_id: str | None,
    document_id: str,
    revision_id: str,
    page_numbers: tuple[int, ...],
    anchor: str,
) -> str:
    source_segment = quote(source_id or "unbound", safe="")
    document_segment = quote(document_id, safe="")
    revision_segment = quote(revision_id, safe="")
    pages = ",".join(str(page) for page in page_numbers)
    fragment = quote(f"pages={pages};anchor={anchor}", safe="=;,._~!$&'()*+:@/%-")
    return (
        f"knowledge://source/{source_segment}/document/{document_segment}/revision/"
        f"{revision_segment}#{fragment}"
    )


def _union_bbox(boxes: Iterable[BoundingBox]) -> BoundingBox:
    materialized = tuple(boxes)
    if not materialized:
        raise ValueError("cannot derive a rule-unit bbox from no source geometry")
    return BoundingBox(
        x0=min(box.x0 for box in materialized),
        y0=min(box.y0 for box in materialized),
        x1=max(box.x1 for box in materialized),
        y1=max(box.y1 for box in materialized),
    )


def _bbox_contains(outer: BoundingBox, inner: BoundingBox) -> bool:
    return (
        outer.x0 <= inner.x0 <= inner.x1 <= outer.x1
        and outer.y0 <= inner.y0 <= inner.y1 <= outer.y1
    )


def _sha256_json(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "InsuranceRuleUnitDraft",
    "PageBoundingBox",
    "RuleCellCoordinate",
    "project_rule_units",
]
