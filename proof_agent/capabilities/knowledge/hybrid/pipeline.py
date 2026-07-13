"""Explicit boundary-level selection of Docling and Paddle canonical results."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, StrictStr, StringConstraints, model_validator

from proof_agent.capabilities.knowledge.hybrid.canonicalizer import (
    CanonicalParserPage,
    canonicalize_docling,
    canonicalize_paddle_page,
    validate_page_geometry_and_bounds,
)
from proof_agent.capabilities.knowledge.hybrid.model_clients import (
    KnowledgeModelCancellation,
    KnowledgeModelWorkScheduler,
)
from proof_agent.capabilities.knowledge.hybrid.parser_clients import (
    ParserServiceRequest,
    ParserServiceResponse,
    PrivateDoclingClient,
    PrivatePaddleClient,
)
from proof_agent.capabilities.knowledge.hybrid.quality import (
    QualityOutcome,
    assess_document_quality,
    assess_page_quality,
)
from proof_agent.capabilities.knowledge.ingestion.hybrid_worker import (
    HybridArtifactBuildRequest,
    HybridInsuranceMetadataArtifact,
    HybridParserBuildOutput,
    HybridVendorArtifact,
)
from proof_agent.contracts._base import FrozenModel
from proof_agent.contracts.hybrid_documents import (
    BoundingBox,
    ParserWarning,
    StructuredArtifactBuildIdentity,
    StructuredBlock,
    StructuredKnowledgeDocumentArtifact,
    StructuredPage,
    StructuredQualitySignal,
    StructuredTable,
)
from proof_agent.contracts.insurance_rules import InsuranceRuleMetadataDraft


NonBlankStr = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256 = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


@dataclass(frozen=True)
class PrivateHybridParserPipeline:
    """Scheduled private parser calls used by Hybrid build orchestration."""

    docling: PrivateDoclingClient
    paddle: PrivatePaddleClient

    def __post_init__(self) -> None:
        if self.docling.scheduler is not self.paddle.scheduler:
            raise ValueError("Hybrid parser clients must share one scheduler instance")

    @property
    def scheduler(self) -> KnowledgeModelWorkScheduler:
        return self.docling.scheduler

    def parse_document(
        self,
        request: ParserServiceRequest,
        *,
        timeout_seconds: float,
        cancellation: KnowledgeModelCancellation | None = None,
    ) -> ParserServiceResponse:
        return self.docling.parse(
            request,
            priority="offline",
            timeout_seconds=timeout_seconds,
            cancellation=cancellation,
        )

    def parse_ocr_page(
        self,
        request: ParserServiceRequest,
        *,
        timeout_seconds: float,
        cancellation: KnowledgeModelCancellation | None = None,
    ) -> ParserServiceResponse:
        return self.paddle.parse(
            request,
            priority="offline",
            timeout_seconds=timeout_seconds,
            cancellation=cancellation,
        )

    def build(
        self,
        request: HybridArtifactBuildRequest,
        *,
        cancellation: KnowledgeModelCancellation,
    ) -> HybridParserBuildOutput:
        """Build one canonical artifact through scheduled Docling/Paddle calls."""

        cancellation.raise_if_cancelled()
        parser_request = ParserServiceRequest(
            original_ref=request.original_ref,
            page_numbers=request.page_numbers,
            parser_revision=request.parser_revision,
            model_digests=request.model_digests,
            configuration_sha256=request.configuration_sha256,
        )
        cancellation.raise_if_cancelled()
        docling_response = self.parse_document(
            parser_request,
            timeout_seconds=120.0,
            cancellation=cancellation,
        )
        cancellation.raise_if_cancelled()
        docling_build = _service_build_identity(
            request,
            adapter="docling",
            vendor_sha256=docling_response.attestation.vendor_json_sha256,
        )
        cancellation.raise_if_cancelled()
        docling_artifact = canonicalize_docling(docling_response, build=docling_build)
        cancellation.raise_if_cancelled()
        decisions = assess_document_quality(docling_artifact)
        pages = {page.page_number: page for page in docling_artifact.pages}
        warnings = list(docling_artifact.warnings)
        signals = list(docling_artifact.quality_signals)
        vendor_artifacts = [
            HybridVendorArtifact(
                adapter="docling",
                content=docling_response.attestation.vendor_json_bytes,
            )
        ]
        for decision in decisions:
            cancellation.raise_if_cancelled()
            if decision.outcome is QualityOutcome.PASS:
                continue
            if decision.outcome is QualityOutcome.REVIEW_REQUIRED:
                signals.append(
                    StructuredQualitySignal(
                        code="docling_review_required",
                        score=0.0,
                        page_number=decision.page_number,
                        requires_review=True,
                    )
                )
                continue
            paddle_request = parser_request.model_copy(
                update={"page_numbers": (decision.page_number,)}
            )
            cancellation.raise_if_cancelled()
            paddle_response = self.parse_ocr_page(
                paddle_request,
                timeout_seconds=120.0,
                cancellation=cancellation,
            )
            cancellation.raise_if_cancelled()
            paddle_build = _service_build_identity(
                request,
                adapter="paddle",
                vendor_sha256=paddle_response.attestation.vendor_json_sha256,
                page_number=decision.page_number,
            )
            cancellation.raise_if_cancelled()
            paddle_page = canonicalize_paddle_page(paddle_response, build=paddle_build)
            vendor_artifacts.append(
                HybridVendorArtifact(
                    adapter="paddle",
                    content=paddle_response.attestation.vendor_json_bytes,
                )
            )
            paddle_quality = assess_page_quality(
                paddle_page.page,
                warnings=paddle_page.warnings,
            )
            docling_page = pages[decision.page_number]
            if (
                paddle_quality.outcome is QualityOutcome.PASS
                and paddle_page.page.width == docling_page.width
                and paddle_page.page.height == docling_page.height
            ):
                signals.append(
                    StructuredQualitySignal(
                        code="paddle_page_available_review_required",
                        score=0.0,
                        page_number=decision.page_number,
                        requires_review=True,
                    )
                )
            else:
                signals.append(
                    StructuredQualitySignal(
                        code="paddle_review_required",
                        score=0.0,
                        page_number=decision.page_number,
                        requires_review=True,
                    )
                )
        cancellation.raise_if_cancelled()
        final_pages = tuple(pages[number] for number in request.page_numbers)
        final_build = docling_build
        cancellation.raise_if_cancelled()
        artifact = StructuredKnowledgeDocumentArtifact(
            schema_version="structured-knowledge.v1",
            document_id=docling_artifact.document_id,
            revision_id=docling_artifact.revision_id,
            original_sha256=docling_artifact.original_sha256,
            build_identity=final_build,
            pages=final_pages,
            warnings=tuple(warnings),
            quality_signals=tuple(signals),
        )
        metadata_id = hashlib.sha256(
            f"{request.source_id}:{request.revision_id}:{final_build.build_id}".encode()
        ).hexdigest()
        cancellation.raise_if_cancelled()
        return HybridParserBuildOutput(
            artifact=artifact,
            vendor_artifacts=tuple(vendor_artifacts),
            insurance_metadata=HybridInsuranceMetadataArtifact(
                source_id=request.source_id,
                document_id=request.document_id,
                revision_id=request.revision_id,
                structured_build_id=final_build.build_id,
                original_sha256=request.original_ref.sha256,
                document_defaults=InsuranceRuleMetadataDraft(
                    metadata_draft_id=f"metadata-draft-{metadata_id}",
                    document_id=request.document_id,
                    revision_id=request.revision_id,
                ),
                pdf_drafts=(),
            ),
        )


def _service_build_identity(
    request: HybridArtifactBuildRequest,
    *,
    adapter: Literal["docling", "paddle"],
    vendor_sha256: str,
    page_number: int | None = None,
) -> StructuredArtifactBuildIdentity:
    digest = _sha256_json(
        {
            "request_sha256": request.request_sha256,
            "adapter": adapter,
            "vendor_sha256": vendor_sha256,
            "page_number": page_number,
        }
    )
    return StructuredArtifactBuildIdentity(
        build_id=f"skab-{digest}",
        source_sha256=request.original_ref.sha256,
        parser_adapter=adapter,
        parser_revision=request.parser_revision,
        model_digests=request.model_digests,
        canonical_schema_version="structured-knowledge.v1",
        configuration_sha256=request.configuration_sha256,
    )


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
    docling_page_numbers = [page.page_number for page in docling.pages]
    if any(
        current <= previous
        for previous, current in zip(docling_page_numbers, docling_page_numbers[1:])
    ):
        raise ValueError("Docling canonical page numbers must be strictly increasing and unique")
    for page in docling.pages:
        validate_page_geometry_and_bounds(page)
        _require_unique_boundary_ids(page, parser="Docling")
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
    _validate_merged_continuations(merged_pages)
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
    artifact = StructuredKnowledgeDocumentArtifact.model_validate(artifact.model_dump())
    for page in artifact.pages:
        validate_page_geometry_and_bounds(page)
        _require_unique_boundary_ids(page, parser="merged")
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
    _require_unique_boundary_ids(paddle_page, parser="Paddle")
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
            _validate_block_replacement(original, selected)
            blocks[decision.docling_id] = _replace_block(original.block_id, selected)
        else:
            original_table = tables.get(decision.docling_id)
            selected_table = paddle_tables.get(decision.paddle_id)
            if original_table is None or selected_table is None:
                raise ValueError("table merge identities must exist in both parser results")
            _validate_table_replacement(original_table, selected_table)
            tables[decision.docling_id] = _replace_table(original_table.table_id, selected_table)

    merged = docling_page.model_copy(
        update={
            "blocks": tuple(blocks[block.block_id] for block in docling_page.blocks),
            "tables": tuple(tables[table.table_id] for table in docling_page.tables),
        }
    )
    validate_page_geometry_and_bounds(merged)
    _require_unique_boundary_ids(merged, parser="merged")
    _validate_merged_reading_order(merged)
    return merged


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


def _require_unique_boundary_ids(page: StructuredPage, *, parser: str) -> None:
    block_ids = [block.block_id for block in page.blocks]
    table_ids = [table.table_id for table in page.tables]
    if len(block_ids) != len(set(block_ids)):
        raise ValueError(f"{parser} page contains duplicate block identities")
    if len(table_ids) != len(set(table_ids)):
        raise ValueError(f"{parser} page contains duplicate table identities")


def _validate_block_replacement(original: StructuredBlock, selected: StructuredBlock) -> None:
    if not _bbox_compatible(original.bbox, selected.bbox):
        raise ValueError("Paddle block violates the canonical boundary geometry policy")


def _validate_table_replacement(original: StructuredTable, selected: StructuredTable) -> None:
    if not _bbox_compatible(original.bbox, selected.bbox):
        raise ValueError("Paddle table violates the canonical boundary geometry policy")


def _validate_merged_reading_order(page: StructuredPage) -> None:
    orders = sorted(block.reading_order for block in page.blocks)
    if any(actual != expected for expected, actual in enumerate(orders)):
        raise ValueError("merged page reading order remains ambiguous")


def _validate_merged_continuations(pages: tuple[StructuredPage, ...]) -> None:
    prior_table_ids: set[str] = set()
    for page in pages:
        for table in page.tables:
            if table.continuation_of is not None and table.continuation_of not in prior_table_ids:
                raise ValueError("merged table continuation remains unresolved")
        prior_table_ids.update(table.table_id for table in page.tables)


def _bbox_compatible(original: BoundingBox, selected: BoundingBox) -> bool:
    intersection_width = max(0.0, min(original.x1, selected.x1) - max(original.x0, selected.x0))
    intersection_height = max(0.0, min(original.y1, selected.y1) - max(original.y0, selected.y0))
    intersection = intersection_width * intersection_height
    original_area = (original.x1 - original.x0) * (original.y1 - original.y0)
    selected_area = (selected.x1 - selected.x0) * (selected.y1 - selected.y0)
    smaller_area = min(original_area, selected_area)
    if smaller_area == 0:
        return original == selected
    union = original_area + selected_area - intersection
    return union > 0 and intersection / union >= 0.5


def _validate_paddle_identity(
    docling: StructuredKnowledgeDocumentArtifact,
    paddle_pages: tuple[CanonicalParserPage, ...],
) -> None:
    for candidate in paddle_pages:
        validate_page_geometry_and_bounds(candidate.page)
        _require_unique_boundary_ids(candidate.page, parser="Paddle")
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
