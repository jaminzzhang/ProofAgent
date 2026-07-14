"""Deterministic structure-quality decisions for canonical parser pages."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import ConfigDict, Field, StrictStr, StringConstraints

from proof_agent.capabilities.knowledge.hybrid.canonicalizer import (
    validate_page_geometry_and_bounds,
)
from proof_agent.contracts._base import FrozenModel
from proof_agent.contracts.hybrid_documents import (
    ParserWarning,
    StructuredKnowledgeDocumentArtifact,
    StructuredPage,
    StructuredTableCell,
)


NonBlankStr = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1)]


class QualityOutcome(StrEnum):
    PASS = "PASS"
    ESCALATE_PAGE = "ESCALATE_PAGE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class PageQualityDecision(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    page_number: int = Field(ge=1)
    outcome: QualityOutcome
    reasons: tuple[NonBlankStr, ...] = ()


def assess_page_quality(
    page: StructuredPage,
    *,
    warnings: tuple[ParserWarning, ...],
) -> PageQualityDecision:
    """Choose pass, page escalation, or human review without probabilistic inference."""

    review_reasons: list[str] = []
    escalation_reasons: list[str] = []

    try:
        validate_page_geometry_and_bounds(page)
    except ValueError:
        return PageQualityDecision(
            page_number=page.page_number,
            outcome=QualityOutcome.REVIEW_REQUIRED,
            reasons=("invalid_page_geometry_or_bounds",),
        )

    page_warnings = tuple(
        warning for warning in warnings if warning.page_number in {None, page.page_number}
    )
    if page_warnings:
        review_reasons.append("parser_warning")

    orders = sorted(block.reading_order for block in page.blocks)
    if len(orders) != len(set(orders)) or any(
        actual != expected for expected, actual in enumerate(orders)
    ):
        review_reasons.append("reading_order_gap")

    block_ids = [block.block_id for block in page.blocks]
    table_ids = [table.table_id for table in page.tables]
    if len(block_ids) != len(set(block_ids)) or len(table_ids) != len(set(table_ids)):
        review_reasons.append("duplicate_boundary_identity")

    for table in page.tables:
        if not table.cells:
            review_reasons.append("table_without_cells")
        if _table_has_overlapping_cells(table.cells):
            review_reasons.append("table_cell_overlap")
        for cell in table.cells:
            if not (
                table.bbox.x0 <= cell.bbox.x0 <= cell.bbox.x1 <= table.bbox.x1
                and table.bbox.y0 <= cell.bbox.y0 <= cell.bbox.y1 <= table.bbox.y1
            ):
                review_reasons.append("table_cell_outside_table")
                break

    native_texts = tuple(
        block.text for block in page.blocks if block.source_method == "native"
    ) + tuple(
        cell.text for table in page.tables for cell in table.cells if cell.source_method == "native"
    )
    ocr_texts = tuple(block.text for block in page.blocks if block.source_method == "ocr") + tuple(
        cell.text for table in page.tables for cell in table.cells if cell.source_method == "ocr"
    )
    if not any(text.strip() for text in (*native_texts, *ocr_texts)):
        if ocr_texts:
            review_reasons.append("ocr_attempt_without_meaningful_text")
        else:
            escalation_reasons.append("missing_native_text")

    if review_reasons:
        return PageQualityDecision(
            page_number=page.page_number,
            outcome=QualityOutcome.REVIEW_REQUIRED,
            reasons=tuple(dict.fromkeys(review_reasons)),
        )
    if escalation_reasons:
        return PageQualityDecision(
            page_number=page.page_number,
            outcome=QualityOutcome.ESCALATE_PAGE,
            reasons=tuple(dict.fromkeys(escalation_reasons)),
        )
    return PageQualityDecision(page_number=page.page_number, outcome=QualityOutcome.PASS)


def _table_has_overlapping_cells(cells: tuple[StructuredTableCell, ...]) -> bool:
    """Detect rectangle overlap in O(n log n) without expanding grid coordinates."""

    if len(cells) < 2:
        return False
    column_coordinates = sorted(
        {
            coordinate
            for cell in cells
            for coordinate in (cell.column, cell.column + cell.column_span)
        }
    )
    column_index = {coordinate: index for index, coordinate in enumerate(column_coordinates)}
    events: list[tuple[int, int, int, int, int]] = []
    for cell in cells:
        left = column_index[cell.column]
        right = column_index[cell.column + cell.column_span] - 1
        events.append((cell.row, 1, left, right, 1))
        events.append((cell.row + cell.row_span, 0, left, right, -1))
    events.sort()

    coverage = _RangeAddMaximum(segment_count=len(column_coordinates) - 1)
    for _row, _event_kind, left, right, delta in events:
        coverage.add(left, right, delta)
        if delta > 0 and coverage.maximum > 1:
            return True
    return False


class _RangeAddMaximum:
    """Coordinate-compressed range-add tree exposing the global maximum."""

    def __init__(self, *, segment_count: int) -> None:
        self._segment_count = segment_count
        self._maximum = [0] * (segment_count * 4)
        self._lazy = [0] * (segment_count * 4)

    @property
    def maximum(self) -> int:
        return self._maximum[1] if self._segment_count else 0

    def add(self, left: int, right: int, delta: int) -> None:
        if left > right or not self._segment_count:
            return
        self._add(
            node=1,
            start=0,
            end=self._segment_count - 1,
            left=left,
            right=right,
            delta=delta,
        )

    def _add(
        self,
        *,
        node: int,
        start: int,
        end: int,
        left: int,
        right: int,
        delta: int,
    ) -> None:
        if left <= start and end <= right:
            self._maximum[node] += delta
            self._lazy[node] += delta
            return
        midpoint = (start + end) // 2
        if left <= midpoint:
            self._add(
                node=node * 2,
                start=start,
                end=midpoint,
                left=left,
                right=right,
                delta=delta,
            )
        if right > midpoint:
            self._add(
                node=node * 2 + 1,
                start=midpoint + 1,
                end=end,
                left=left,
                right=right,
                delta=delta,
            )
        self._maximum[node] = self._lazy[node] + max(
            self._maximum[node * 2], self._maximum[node * 2 + 1]
        )


def assess_cross_page_continuations(
    pages: tuple[StructuredPage, ...],
) -> tuple[PageQualityDecision, ...]:
    """Review table continuations that do not name a table on an earlier page."""

    prior_table_ids: set[str] = set()
    decisions: list[PageQualityDecision] = []
    for page in pages:
        missing = any(
            table.continuation_of is not None and table.continuation_of not in prior_table_ids
            for table in page.tables
        )
        decisions.append(
            PageQualityDecision(
                page_number=page.page_number,
                outcome=(QualityOutcome.REVIEW_REQUIRED if missing else QualityOutcome.PASS),
                reasons=(("unresolved_cross_page_continuation",) if missing else ()),
            )
        )
        prior_table_ids.update(table.table_id for table in page.tables)
    return tuple(decisions)


def assess_document_quality(
    artifact: StructuredKnowledgeDocumentArtifact,
) -> tuple[PageQualityDecision, ...]:
    """Apply page-local gates and cross-page table lineage as one deterministic pass."""

    local = {
        page.page_number: assess_page_quality(page, warnings=artifact.warnings)
        for page in artifact.pages
    }
    continuation = {
        decision.page_number: decision
        for decision in assess_cross_page_continuations(artifact.pages)
    }
    decisions: list[PageQualityDecision] = []
    for page in artifact.pages:
        page_local = local[page.page_number]
        page_continuation = continuation[page.page_number]
        if (
            page_local.outcome is QualityOutcome.REVIEW_REQUIRED
            or page_continuation.outcome is QualityOutcome.REVIEW_REQUIRED
        ):
            decisions.append(
                PageQualityDecision(
                    page_number=page.page_number,
                    outcome=QualityOutcome.REVIEW_REQUIRED,
                    reasons=tuple(dict.fromkeys(page_local.reasons + page_continuation.reasons)),
                )
            )
        else:
            decisions.append(page_local)
    return tuple(decisions)
