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
    """Sweep row intervals without expanding any row/column span into coordinates."""

    ordered = sorted(cells, key=lambda cell: (cell.row, cell.column))
    active: list[StructuredTableCell] = []
    for cell in ordered:
        active = [other for other in active if other.row + other.row_span > cell.row]
        cell_column_end = cell.column + cell.column_span
        for other in active:
            other_column_end = other.column + other.column_span
            if cell.column < other_column_end and other.column < cell_column_end:
                return True
        active.append(cell)
    return False


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
