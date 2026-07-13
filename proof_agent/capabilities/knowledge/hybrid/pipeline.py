"""Explicit boundary-level selection of Docling and Paddle canonical results."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, StrictStr, StringConstraints, model_validator

from proof_agent.capabilities.knowledge.hybrid.canonicalizer import CanonicalParserPage
from proof_agent.contracts._base import FrozenModel
from proof_agent.contracts.hybrid_documents import (
    ParserWarning,
    StructuredArtifactBuildIdentity,
    StructuredBlock,
    StructuredKnowledgeDocumentArtifact,
    StructuredPage,
    StructuredQualitySignal,
    StructuredTable,
)


NonBlankStr = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256 = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


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


class MergeRecord(FrozenModel):
    """Immutable evidence of one complete canonical-boundary parser selection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    page_number: int = Field(ge=1)
    boundary_kind: Literal["block", "table"]
    target_id: NonBlankStr
    docling_source_id: NonBlankStr
    paddle_source_id: NonBlankStr
    docling_build_id: NonBlankStr
    paddle_build_id: NonBlankStr
    decision: Literal["REPLACE_WITH_PADDLE"]
    reason: NonBlankStr


class CanonicalMergeResult(FrozenModel):
    """Canonical artifact plus complete merge and source-build lineage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact: StructuredKnowledgeDocumentArtifact
    merge_records: tuple[MergeRecord, ...]
    source_build_identities: tuple[StructuredArtifactBuildIdentity, ...]
    canonical_content_sha256: Sha256
    artifact_sha256: Sha256


def merge_selected_results(
    docling: StructuredKnowledgeDocumentArtifact,
    paddle_pages: tuple[CanonicalParserPage, ...],
    *,
    decisions: tuple[MergeSelection, ...],
) -> CanonicalMergeResult:
    """Apply complete-boundary replacements; text is never concatenated across parsers."""

    _validate_paddle_identity(docling, paddle_pages)
    page_lookup = {candidate.page.page_number: candidate for candidate in paddle_pages}
    if len(page_lookup) != len(paddle_pages):
        raise ValueError("Paddle page numbers must be unique")
    normalized_decisions = tuple(
        sorted(
            decisions,
            key=lambda item: (
                item.page_number,
                item.boundary_kind,
                item.docling_id,
                item.paddle_id,
                item.reason,
            ),
        )
    )
    decision_keys = [
        (item.page_number, item.boundary_kind, item.docling_id) for item in normalized_decisions
    ]
    if len(decision_keys) != len(set(decision_keys)):
        raise ValueError("a canonical boundary may be selected only once")

    by_page: dict[int, list[MergeSelection]] = {}
    for decision in normalized_decisions:
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
        for decision in normalized_decisions
    )
    used_pages = tuple(page_lookup[number] for number in sorted(by_page))
    records = tuple(
        MergeRecord(
            page_number=decision.page_number,
            boundary_kind=decision.boundary_kind,
            target_id=decision.docling_id,
            docling_source_id=decision.docling_id,
            paddle_source_id=decision.paddle_id,
            docling_build_id=docling.build_identity.build_id,
            paddle_build_id=page_lookup[decision.page_number].build_identity.build_id,
            decision="REPLACE_WITH_PADDLE",
            reason=decision.reason,
        )
        for decision in normalized_decisions
    )
    warnings = docling.warnings + tuple(
        warning for candidate in used_pages for warning in candidate.warnings
    )
    content_sha256 = _canonical_content_digest(
        docling=docling,
        pages=merged_pages,
        warnings=warnings,
        quality_signals=docling.quality_signals + signals,
    )
    source_builds = _source_builds(docling.build_identity, used_pages)
    artifact = StructuredKnowledgeDocumentArtifact(
        schema_version=docling.schema_version,
        document_id=docling.document_id,
        revision_id=docling.revision_id,
        original_sha256=docling.original_sha256,
        build_identity=_combined_build(
            source_builds=source_builds,
            records=records,
            canonical_content_sha256=content_sha256,
        ),
        pages=merged_pages,
        warnings=warnings,
        quality_signals=docling.quality_signals + signals,
    )
    return CanonicalMergeResult(
        artifact=artifact,
        merge_records=records,
        source_build_identities=source_builds,
        canonical_content_sha256=content_sha256,
        artifact_sha256=_sha256_json(artifact.model_dump(mode="json")),
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
        if candidate.original_sha256 != candidate.build_identity.source_sha256:
            raise ValueError("Paddle page original SHA must match its build identity")
        if (
            candidate.document_id != docling.document_id
            or candidate.revision_id != docling.revision_id
            or candidate.original_sha256 != docling.original_sha256
        ):
            raise ValueError("Paddle result identity must match the Docling artifact")


def _source_builds(
    docling: StructuredArtifactBuildIdentity,
    selected_pages: tuple[CanonicalParserPage, ...],
) -> tuple[StructuredArtifactBuildIdentity, ...]:
    paddle_builds = tuple(dict.fromkeys(page.build_identity for page in selected_pages))
    return (docling, *paddle_builds)


def _combined_build(
    *,
    source_builds: tuple[StructuredArtifactBuildIdentity, ...],
    records: tuple[MergeRecord, ...],
    canonical_content_sha256: str,
) -> StructuredArtifactBuildIdentity:
    docling, *paddle_builds = source_builds
    if not paddle_builds:
        return docling
    configuration_sha256 = _sha256_json(
        [
            {
                "parser_adapter": build.parser_adapter,
                "configuration_sha256": build.configuration_sha256,
            }
            for build in source_builds
        ]
    )
    identity_payload = {
        "source_build_identities": [build.model_dump(mode="json") for build in source_builds],
        "merge_records": [record.model_dump(mode="json") for record in records],
        "canonical_content_sha256": canonical_content_sha256,
    }
    digest = _sha256_json(identity_payload)
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
        configuration_sha256=configuration_sha256,
    )


def _canonical_content_digest(
    *,
    docling: StructuredKnowledgeDocumentArtifact,
    pages: tuple[StructuredPage, ...],
    warnings: tuple[ParserWarning, ...],
    quality_signals: tuple[StructuredQualitySignal, ...],
) -> str:
    return _sha256_json(
        {
            "schema_version": docling.schema_version,
            "document_id": docling.document_id,
            "revision_id": docling.revision_id,
            "original_sha256": docling.original_sha256,
            "pages": [page.model_dump(mode="json") for page in pages],
            "warnings": [warning.model_dump(mode="json") for warning in warnings],
            "quality_signals": [signal.model_dump(mode="json") for signal in quality_signals],
        }
    )


def _sha256_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
