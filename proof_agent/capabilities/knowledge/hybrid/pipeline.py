"""Explicit boundary-level selection of Docling and Paddle canonical results."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, StrictStr, StringConstraints, model_validator

from proof_agent.capabilities.knowledge.hybrid.canonicalizer import CanonicalParserPage
from proof_agent.contracts._base import FrozenModel
from proof_agent.contracts.hybrid_documents import (
    StructuredArtifactBuildIdentity,
    StructuredBlock,
    StructuredKnowledgeDocumentArtifact,
    StructuredPage,
    StructuredQualitySignal,
    StructuredTable,
)


NonBlankStr = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1)]


class MergeSelection(FrozenModel):
    """Auditable selection of exactly one whole parser block or table."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    page_number: int = Field(ge=1)
    boundary_kind: Literal["block", "table"]
    docling_id: NonBlankStr
    paddle_id: NonBlankStr
    reason: NonBlankStr

    @model_validator(mode="after")
    def validate_distinct_ids(self) -> Self:
        if self.docling_id == self.paddle_id:
            raise ValueError("Docling and Paddle boundary identities must be distinct")
        return self


def merge_selected_results(
    docling: StructuredKnowledgeDocumentArtifact,
    paddle_pages: tuple[CanonicalParserPage, ...],
    *,
    decisions: tuple[MergeSelection, ...],
) -> StructuredKnowledgeDocumentArtifact:
    """Apply complete-boundary replacements; text is never concatenated across parsers."""

    _validate_paddle_identity(docling, paddle_pages)
    page_lookup = {candidate.page.page_number: candidate for candidate in paddle_pages}
    if len(page_lookup) != len(paddle_pages):
        raise ValueError("Paddle page numbers must be unique")
    decision_keys = [(item.page_number, item.boundary_kind, item.docling_id) for item in decisions]
    if len(decision_keys) != len(set(decision_keys)):
        raise ValueError("a canonical boundary may be selected only once")

    by_page: dict[int, list[MergeSelection]] = {}
    for decision in decisions:
        by_page.setdefault(decision.page_number, []).append(decision)
    unknown_pages = set(by_page) - {page.page_number for page in docling.pages}
    if unknown_pages:
        raise ValueError("merge decisions must target existing Docling pages")

    merged_pages = tuple(
        _merge_page(page, page_lookup, tuple(by_page.get(page.page_number, ())))
        for page in docling.pages
    )
    signals = tuple(
        StructuredQualitySignal(
            code=f"paddle_{decision.boundary_kind}_replacement",
            score=1.0,
            page_number=decision.page_number,
            block_id=(decision.docling_id if decision.boundary_kind == "block" else None),
            table_id=(decision.docling_id if decision.boundary_kind == "table" else None),
        )
        for decision in decisions
    )
    used_pages = tuple(page_lookup[number] for number in sorted(by_page))
    return StructuredKnowledgeDocumentArtifact(
        schema_version=docling.schema_version,
        document_id=docling.document_id,
        revision_id=docling.revision_id,
        original_sha256=docling.original_sha256,
        build_identity=_combined_build(docling.build_identity, used_pages),
        pages=merged_pages,
        warnings=docling.warnings
        + tuple(warning for candidate in used_pages for warning in candidate.warnings),
        quality_signals=docling.quality_signals + signals,
    )


def _merge_page(
    docling_page: StructuredPage,
    paddle_lookup: dict[int, CanonicalParserPage],
    decisions: tuple[MergeSelection, ...],
) -> StructuredPage:
    if not decisions:
        return docling_page
    candidate = paddle_lookup.get(docling_page.page_number)
    if candidate is None:
        raise ValueError("every merge decision requires a Paddle result for the same page")
    paddle_page = candidate.page
    if paddle_page.width != docling_page.width or paddle_page.height != docling_page.height:
        raise ValueError("Paddle and Docling page dimensions must match exactly")

    blocks = {block.block_id: block for block in docling_page.blocks}
    tables = {table.table_id: table for table in docling_page.tables}
    paddle_blocks = {block.block_id: block for block in paddle_page.blocks}
    paddle_tables = {table.table_id: table for table in paddle_page.tables}
    for decision in decisions:
        if decision.boundary_kind == "block":
            original = blocks.get(decision.docling_id)
            selected = paddle_blocks.get(decision.paddle_id)
            if original is None or selected is None:
                raise ValueError("block merge identities must exist in both parser results")
            blocks[decision.docling_id] = _replace_block(original.block_id, selected)
        else:
            original_table = tables.get(decision.docling_id)
            selected_table = paddle_tables.get(decision.paddle_id)
            if original_table is None or selected_table is None:
                raise ValueError("table merge identities must exist in both parser results")
            tables[decision.docling_id] = _replace_table(original_table.table_id, selected_table)

    return docling_page.model_copy(
        update={
            "blocks": tuple(blocks[block.block_id] for block in docling_page.blocks),
            "tables": tuple(tables[table.table_id] for table in docling_page.tables),
        }
    )


def _replace_block(target_id: str, selected: StructuredBlock) -> StructuredBlock:
    return selected.model_copy(update={"block_id": target_id, "source_method": "ocr"})


def _replace_table(target_id: str, selected: StructuredTable) -> StructuredTable:
    return selected.model_copy(
        update={
            "table_id": target_id,
            "cells": tuple(
                cell.model_copy(update={"source_method": "ocr"}) for cell in selected.cells
            ),
        }
    )


def _validate_paddle_identity(
    docling: StructuredKnowledgeDocumentArtifact,
    paddle_pages: tuple[CanonicalParserPage, ...],
) -> None:
    for candidate in paddle_pages:
        if (
            candidate.document_id != docling.document_id
            or candidate.revision_id != docling.revision_id
            or candidate.original_sha256 != docling.original_sha256
        ):
            raise ValueError("Paddle result identity must match the Docling artifact")


def _combined_build(
    docling: StructuredArtifactBuildIdentity,
    selected_pages: tuple[CanonicalParserPage, ...],
) -> StructuredArtifactBuildIdentity:
    if not selected_pages:
        return docling
    paddle_builds = tuple(dict.fromkeys(page.build_identity for page in selected_pages))
    identity_payload = {
        "docling": docling.model_dump(mode="json"),
        "paddle": [build.model_dump(mode="json") for build in paddle_builds],
    }
    digest = hashlib.sha256(
        json.dumps(identity_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return StructuredArtifactBuildIdentity(
        build_id=f"skab-{digest}",
        source_sha256=docling.source_sha256,
        parser_adapter="docling+paddle",
        parser_revision="+".join(
            (docling.parser_revision, *(b.parser_revision for b in paddle_builds))
        ),
        model_digests=tuple(
            dict.fromkeys(
                (*docling.model_digests, *(d for b in paddle_builds for d in b.model_digests))
            )
        ),
        canonical_schema_version=docling.canonical_schema_version,
        configuration_sha256=digest,
    )
