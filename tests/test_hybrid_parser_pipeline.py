from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any, Literal

import pytest
from pydantic import ValidationError

from proof_agent.capabilities.knowledge.hybrid.canonicalizer import (
    CanonicalParserPage,
    canonicalize_docling,
    canonicalize_paddle_page,
)
from proof_agent.capabilities.knowledge.hybrid.parser_clients import (
    ParserServiceAttestation,
    ParserServiceRequest,
    ParserServiceResponse,
    PrivateDoclingClient,
    PrivatePaddleClient,
    canonical_vendor_json_bytes,
)
from proof_agent.capabilities.knowledge.hybrid.model_clients import (
    ImmediateKnowledgeModelWorkScheduler,
    KnowledgeModelCancellation,
    PrivateHostPolicy,
    PrivateKnowledgeModelWorkSchedulerClient,
    SchedulerLease,
)
from proof_agent.capabilities.knowledge.hybrid.pipeline import (
    MergeSelection,
    PrivateHybridParserPipeline,
    merge_selected_results,
)
from proof_agent.capabilities.knowledge.ingestion.hybrid_worker import (
    HybridArtifactBuildRequest,
    hybrid_build_request_sha256,
)
from proof_agent.capabilities.knowledge.hybrid.quality import (
    QualityOutcome,
    assess_document_quality,
    assess_page_quality,
)
from proof_agent.contracts.hybrid_documents import StructuredArtifactBuildIdentity
from proof_agent.contracts.knowledge_index import ExactArtifactRef


FIXTURES = Path(__file__).parent / "fixtures" / "knowledge" / "hybrid"


def load_fixture(name: str) -> dict[str, Any]:
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def build_id(
    *, adapter: str = "docling", configuration_sha256: str = "b" * 64
) -> StructuredArtifactBuildIdentity:
    return StructuredArtifactBuildIdentity(
        build_id=f"build-{adapter}",
        source_sha256="a" * 64,
        parser_adapter=adapter,
        parser_revision="2.112.0" if adapter == "docling" else "3.7.0",
        model_digests=("sha256:model-digest",),
        canonical_schema_version="structured-knowledge.v1",
        configuration_sha256=configuration_sha256,
    )


def original_ref() -> ExactArtifactRef:
    return ExactArtifactRef(
        artifact_uri="s3://private/originals/document.pdf",
        version_id="version-1",
        sha256="a" * 64,
        size_bytes=123,
        media_type="application/pdf",
    )


def hybrid_build_request() -> HybridArtifactBuildRequest:
    request = HybridArtifactBuildRequest(
        job_id="job-1",
        request_identity="request-1",
        source_id="source-1",
        document_id="doc-simple",
        revision_id="rev-simple",
        original_ref=original_ref(),
        page_numbers=(1,),
        parser_revision="2.112.0",
        model_digests=("sha256:model-digest",),
        configuration_sha256="b" * 64,
    )
    return request.model_copy(update={"request_sha256": hybrid_build_request_sha256(request)})


def parser_response(
    fixture: str,
    *,
    adapter: Literal["docling", "paddle"] = "docling",
    configuration_sha256: str = "b" * 64,
) -> ParserServiceResponse:
    payload = load_fixture(fixture)
    pages = payload.get("pages")
    if isinstance(pages, list):
        page_numbers = tuple(int(page["page_number"]) for page in pages)
    else:
        page_numbers = (int(payload["page"]["page_number"]),)
    parser_revision = "2.112.0" if adapter == "docling" else "3.7.0"
    request = ParserServiceRequest(
        original_ref=original_ref(),
        page_numbers=page_numbers,
        parser_revision=parser_revision,
        model_digests=("sha256:model-digest",),
        configuration_sha256=configuration_sha256,
    )
    vendor_json_bytes = canonical_vendor_json_bytes(payload)
    return ParserServiceResponse(
        adapter=adapter,
        request=request,
        attestation=ParserServiceAttestation(
            parser_adapter=adapter,
            original_ref=original_ref(),
            page_numbers=page_numbers,
            parser_revision=parser_revision,
            model_digests=("sha256:model-digest",),
            configuration_sha256=configuration_sha256,
            vendor_json_sha256=hashlib.sha256(vendor_json_bytes).hexdigest(),
            vendor_json_bytes=vendor_json_bytes,
        ),
    )


def test_invalid_parser_attestation_cancels_without_completing_remote_lease() -> None:
    valid = parser_response("docling-simple.json")
    invalid = valid.attestation.model_copy(update={"parser_revision": "9.9.9"})

    class ParserTransport:
        def parse(self, request, *, follow_redirects):
            del request, follow_redirects
            return invalid

    class SchedulerTransport:
        def __init__(self) -> None:
            self.completed = 0
            self.cancelled = 0

        def acquire(self, **kwargs):
            del kwargs
            return SchedulerLease(
                work_id="work-invalid-parser",
                lease_token="lease-invalid-parser",
                queue_time_ms=0.0,
            )

        def complete(self, *args, **kwargs):
            del args, kwargs
            self.completed += 1

        def cancel(self, *args, **kwargs):
            del args, kwargs
            self.cancelled += 1

        def close(self):
            return None

    scheduler_transport = SchedulerTransport()
    scheduler = PrivateKnowledgeModelWorkSchedulerClient(
        endpoint="https://scheduler.internal",
        namespace="insurance-knowledge",
        allowed_hosts=PrivateHostPolicy.from_entries(("scheduler.internal",)),
        transport=scheduler_transport,
    )
    client = PrivateDoclingClient(transport=ParserTransport(), scheduler=scheduler)

    with pytest.raises(ValidationError, match="parser_revision"):
        client.parse(valid.request)

    assert scheduler_transport.cancelled == 1
    assert scheduler_transport.completed == 0
    scheduler.close()


def with_vendor_payload(
    response: ParserServiceResponse,
    payload: dict[str, Any],
    *,
    update_digest: bool = True,
) -> ParserServiceResponse:
    vendor_json_bytes = canonical_vendor_json_bytes(payload)
    update: dict[str, object] = {"vendor_json_bytes": vendor_json_bytes}
    if update_digest:
        update["vendor_json_sha256"] = hashlib.sha256(vendor_json_bytes).hexdigest()
    return response.model_copy(
        update={"attestation": response.attestation.model_copy(update=update)}
    )


def test_private_pipeline_builds_passing_docling_artifact_through_shared_scheduler() -> None:
    scheduler = ImmediateKnowledgeModelWorkScheduler()
    calls: list[tuple[str, str]] = []

    class Docling:
        def __init__(self) -> None:
            self.scheduler = scheduler

        def parse(self, request, *, priority, timeout_seconds, cancellation=None):
            del timeout_seconds, cancellation
            calls.append(("docling", priority))
            assert request == parser_response("docling-simple.json").request
            return parser_response("docling-simple.json")

    class Paddle:
        def __init__(self) -> None:
            self.scheduler = scheduler

        def parse(self, *args, **kwargs):
            raise AssertionError((args, kwargs))

    pipeline = PrivateHybridParserPipeline(docling=Docling(), paddle=Paddle())  # type: ignore[arg-type]

    result = pipeline.build(
        hybrid_build_request(),
        cancellation=KnowledgeModelCancellation(),
    )

    assert result.artifact.document_id == "doc-simple"
    assert result.artifact.build_identity.parser_adapter == "docling"
    assert tuple(vendor.adapter for vendor in result.vendor_artifacts) == ("docling",)
    assert calls == [("docling", "offline")]


def test_private_pipeline_never_auto_replaces_an_escalated_whole_page() -> None:
    scheduler = ImmediateKnowledgeModelWorkScheduler()
    docling = parser_response("docling-simple.json")
    docling_payload = docling.vendor_json
    docling_payload["pages"][0]["native_text_ratio"] = 0.0
    docling_payload["pages"][0]["blocks"] = []
    docling = with_vendor_payload(docling, docling_payload)
    paddle = parser_response("paddle-ocr-page.json", adapter="paddle")
    paddle_request = paddle.request.model_copy(update={"parser_revision": "2.112.0"})
    paddle = ParserServiceResponse(
        adapter="paddle",
        request=paddle_request,
        attestation=paddle.attestation.model_copy(update={"parser_revision": "2.112.0"}),
    )

    class Client:
        def __init__(self, response: ParserServiceResponse) -> None:
            self.scheduler = scheduler
            self.response = response

        def parse(self, request, **kwargs):
            del kwargs
            assert request == self.response.request
            return self.response

    pipeline = PrivateHybridParserPipeline(
        docling=Client(docling),  # type: ignore[arg-type]
        paddle=Client(paddle),  # type: ignore[arg-type]
    )

    result = pipeline.build(
        hybrid_build_request(),
        cancellation=KnowledgeModelCancellation(),
    )

    assert result.artifact.pages[0].blocks == ()
    assert any(signal.requires_review for signal in result.artifact.quality_signals)
    assert tuple(vendor.adapter for vendor in result.vendor_artifacts) == ("docling", "paddle")


def test_docling_fixture_maps_page_bbox_reading_order_and_table_cells() -> None:
    artifact = canonicalize_docling(parser_response("docling-complex-table.json"), build=build_id())

    assert artifact.pages[0].page_number == 12
    assert artifact.pages[0].blocks[0].reading_order == 0
    assert artifact.pages[0].tables[0].cells
    assert artifact.pages[0].tables[0].cells[0].bbox.x1 > 0
    assert artifact.pages[0].tables[0].cells[0].source_method == "native"
    assert artifact.build_identity == build_id()


def test_attested_vendor_payload_is_copy_safe_and_digest_rechecked() -> None:
    response = parser_response("docling-simple.json")
    exposed = response.vendor_json
    exposed["pages"][0]["blocks"][0]["text"] = "mutated after validation"

    artifact = canonicalize_docling(response, build=build_id())
    assert artifact.pages[0].blocks[0].text == "Eligibility"

    changed = response.vendor_json
    changed["pages"][0]["blocks"][0]["text"] = "digest bypass"
    stale_digest = with_vendor_payload(response, changed, update_digest=False)
    with pytest.raises(ValidationError, match="vendor JSON digest"):
        canonicalize_docling(stale_digest, build=build_id())


def test_attestation_rejects_noncanonical_and_deep_vendor_json_bytes() -> None:
    response = parser_response("docling-simple.json")
    noncanonical = response.attestation.vendor_json_bytes + b" "
    invalid = {
        **response.attestation.model_dump(),
        "vendor_json_bytes": noncanonical,
        "vendor_json_sha256": hashlib.sha256(noncanonical).hexdigest(),
    }
    with pytest.raises(ValidationError, match="canonical JSON"):
        ParserServiceAttestation.model_validate(invalid)

    payload = response.vendor_json
    nested: dict[str, Any] = {}
    cursor = nested
    for _ in range(40):
        child: dict[str, Any] = {}
        cursor["child"] = child
        cursor = child
    payload["nested"] = nested
    too_deep = with_vendor_payload(response, payload)
    with pytest.raises(ValidationError, match="nesting-depth"):
        canonicalize_docling(too_deep, build=build_id())

    payload = response.vendor_json
    payload["oversized"] = "x" * 1_000_001
    oversized = with_vendor_payload(response, payload)
    with pytest.raises(ValidationError, match="string exceeds"):
        canonicalize_docling(oversized, build=build_id())


def test_parser_and_canonical_structure_bounds_are_enforced() -> None:
    with pytest.raises(ValidationError):
        ParserServiceRequest(
            original_ref=original_ref(),
            page_numbers=tuple(range(1, 502)),
            parser_revision="2.112.0",
            model_digests=("sha256:model-digest",),
            configuration_sha256="b" * 64,
        )

    response = parser_response("docling-simple.json")
    payload = response.vendor_json
    payload["pages"][0]["blocks"][0]["reading_order"] = 10_000
    with pytest.raises(ValueError, match="reading_order"):
        canonicalize_docling(with_vendor_payload(response, payload), build=build_id())

    response = parser_response("docling-complex-table.json")
    payload = response.vendor_json
    payload["pages"][0]["tables"][0]["cells"][0]["row_span"] = 10_001
    with pytest.raises(ValueError, match="row_span"):
        canonicalize_docling(with_vendor_payload(response, payload), build=build_id())

    response = parser_response("docling-simple.json")
    payload = response.vendor_json
    one_block = payload["pages"][0]["blocks"][0]
    payload["pages"][0]["blocks"] = [one_block] * 10_001
    with pytest.raises(ValueError, match="blocks exceeds"):
        canonicalize_docling(with_vendor_payload(response, payload), build=build_id())


def merged_block(*, reason: str = "native text missing", paddle_text: str | None = None):
    docling = canonicalize_docling(parser_response("docling-simple.json"), build=build_id())
    response = parser_response(
        "paddle-ocr-page.json", adapter="paddle", configuration_sha256="c" * 64
    )
    if paddle_text is not None:
        payload = response.vendor_json
        payload["page"]["blocks"][0]["text"] = paddle_text
        response = with_vendor_payload(response, payload)
    paddle_page = canonicalize_paddle_page(
        response, build=build_id(adapter="paddle", configuration_sha256="c" * 64)
    )
    return merge_selected_results(
        docling,
        (paddle_page,),
        decisions=(
            MergeSelection(
                page_number=1,
                boundary_kind="block",
                docling_id="paragraph-1",
                paddle_id="ocr-paragraph-1",
                reason=reason,
            ),
        ),
    )


def test_paddle_escalation_replaces_one_block_and_retains_exact_record() -> None:
    result = merged_block()
    artifact = result.artifact

    assert artifact.pages[0].blocks[1].source_method == "ocr"
    assert artifact.pages[0].blocks[1].text == "selected paddle text"
    assert "Applicants must" not in artifact.pages[0].blocks[1].text
    assert result.merge_records[0].model_dump() == {
        "page_number": 1,
        "boundary_kind": "block",
        "target_id": "paragraph-1",
        "docling_source_id": "paragraph-1",
        "paddle_source_id": "ocr-paragraph-1",
        "docling_build_id": "build-docling",
        "paddle_build_id": "build-paddle",
        "decision": "REPLACE_WITH_PADDLE",
        "reason": "native text missing",
    }
    assert [build.configuration_sha256 for build in result.source_build_identities] == [
        "b" * 64,
        "c" * 64,
    ]


def test_merge_build_identity_covers_decisions_and_canonical_result_not_config_lineage() -> None:
    first = merged_block(reason="native text missing")
    changed_reason = merged_block(reason="table reading order failure")
    changed_content = merged_block(paddle_text="different selected text")

    assert first.artifact.build_identity.build_id != changed_reason.artifact.build_identity.build_id
    assert (
        first.artifact.build_identity.build_id != changed_content.artifact.build_identity.build_id
    )
    assert first.canonical_content_sha256 != changed_content.canonical_content_sha256
    assert (
        first.artifact.build_identity.configuration_sha256
        == changed_reason.artifact.build_identity.configuration_sha256
        == changed_content.artifact.build_identity.configuration_sha256
    )
    assert first.artifact.build_identity.configuration_sha256 != first.artifact_sha256


def test_paddle_page_and_merge_reject_inconsistent_source_build_provenance() -> None:
    docling = canonicalize_docling(parser_response("docling-simple.json"), build=build_id())
    paddle_page = canonicalize_paddle_page(
        parser_response("paddle-ocr-page.json", adapter="paddle", configuration_sha256="c" * 64),
        build=build_id(adapter="paddle", configuration_sha256="c" * 64),
    )
    invalid_payload = paddle_page.model_dump()
    invalid_payload["original_sha256"] = "d" * 64
    with pytest.raises(ValidationError, match="build identity source_sha256"):
        CanonicalParserPage.model_validate(invalid_payload)

    bypassed = paddle_page.model_copy(update={"original_sha256": "d" * 64})
    with pytest.raises(ValueError, match="Paddle page original SHA"):
        merge_selected_results(
            docling,
            (bypassed,),
            decisions=(
                MergeSelection(
                    page_number=1,
                    boundary_kind="block",
                    docling_id="paragraph-1",
                    paddle_id="ocr-paragraph-1",
                    reason="native text missing",
                ),
            ),
        )


def test_merge_rejects_duplicate_boundaries_before_dict_projection() -> None:
    docling = canonicalize_docling(parser_response("docling-simple.json"), build=build_id())
    page = docling.pages[0]
    duplicated = page.model_copy(update={"blocks": (page.blocks[0], page.blocks[0])})
    invalid_docling = docling.model_copy(update={"pages": (duplicated,)})
    paddle_page = canonicalize_paddle_page(
        parser_response("paddle-ocr-page.json", adapter="paddle", configuration_sha256="c" * 64),
        build=build_id(adapter="paddle", configuration_sha256="c" * 64),
    )

    with pytest.raises(ValueError, match="duplicate block identities"):
        merge_selected_results(
            invalid_docling,
            (paddle_page,),
            decisions=(
                MergeSelection(
                    page_number=1,
                    boundary_kind="block",
                    docling_id="heading-1",
                    paddle_id="ocr-paragraph-1",
                    reason="bad duplicate target",
                ),
            ),
        )


def test_merge_rejects_duplicate_docling_page_numbers() -> None:
    docling = canonicalize_docling(parser_response("docling-simple.json"), build=build_id())
    duplicate_pages = docling.model_copy(update={"pages": (docling.pages[0], docling.pages[0])})
    paddle_page = canonicalize_paddle_page(
        parser_response("paddle-ocr-page.json", adapter="paddle", configuration_sha256="c" * 64),
        build=build_id(adapter="paddle", configuration_sha256="c" * 64),
    )

    with pytest.raises(ValueError, match="strictly increasing and unique"):
        merge_selected_results(
            duplicate_pages,
            (paddle_page,),
            decisions=(
                MergeSelection(
                    page_number=1,
                    boundary_kind="block",
                    docling_id="paragraph-1",
                    paddle_id="ocr-paragraph-1",
                    reason="duplicate page regression",
                ),
            ),
        )


def test_merge_rejects_replacement_that_leaves_ambiguous_reading_order() -> None:
    docling = canonicalize_docling(parser_response("docling-simple.json"), build=build_id())
    paddle_page = canonicalize_paddle_page(
        parser_response("paddle-ocr-page.json", adapter="paddle", configuration_sha256="c" * 64),
        build=build_id(adapter="paddle", configuration_sha256="c" * 64),
    )
    selected = paddle_page.page.blocks[0]
    wrong_order = selected.model_copy(update={"reading_order": 0})
    incompatible_page = paddle_page.page.model_copy(update={"blocks": (wrong_order,)})
    incompatible = paddle_page.model_copy(update={"page": incompatible_page})

    with pytest.raises(ValueError, match="reading order"):
        merge_selected_results(
            docling,
            (incompatible,),
            decisions=(
                MergeSelection(
                    page_number=1,
                    boundary_kind="block",
                    docling_id="paragraph-1",
                    paddle_id="ocr-paragraph-1",
                    reason="wrong boundary",
                ),
            ),
        )


def test_merge_allows_explicit_paddle_reading_order_correction() -> None:
    response = parser_response("docling-simple.json")
    payload = response.vendor_json
    payload["pages"][0]["blocks"][1]["reading_order"] = 2
    docling = canonicalize_docling(with_vendor_payload(response, payload), build=build_id())
    assert [block.reading_order for block in docling.pages[0].blocks] == [0, 2]

    paddle_page = canonicalize_paddle_page(
        parser_response("paddle-ocr-page.json", adapter="paddle", configuration_sha256="c" * 64),
        build=build_id(adapter="paddle", configuration_sha256="c" * 64),
    )
    result = merge_selected_results(
        docling,
        (paddle_page,),
        decisions=(
            MergeSelection(
                page_number=1,
                boundary_kind="block",
                docling_id="paragraph-1",
                paddle_id="ocr-paragraph-1",
                reason="correct Docling reading-order gap",
            ),
        ),
    )

    assert [block.reading_order for block in result.artifact.pages[0].blocks] == [0, 1]
    assert result.merge_records[0].reason == "correct Docling reading-order gap"

    selected = paddle_page.page.blocks[0]
    far_bbox = selected.bbox.model_copy(update={"y0": 300.0, "y1": 340.0})
    far_block = selected.model_copy(update={"bbox": far_bbox})
    far_page = paddle_page.page.model_copy(update={"blocks": (far_block,)})
    incompatible = paddle_page.model_copy(update={"page": far_page})
    with pytest.raises(ValueError, match="geometry policy"):
        merge_selected_results(
            docling,
            (incompatible,),
            decisions=(
                MergeSelection(
                    page_number=1,
                    boundary_kind="block",
                    docling_id="paragraph-1",
                    paddle_id="ocr-paragraph-1",
                    reason="wrong geometry",
                ),
            ),
        )


def test_merge_allows_explicit_table_continuation_correction() -> None:
    response = parser_response("docling-complex-table.json")
    payload = response.vendor_json
    payload["pages"][0]["tables"][0]["continuation_of"] = "missing-table"
    docling = canonicalize_docling(with_vendor_payload(response, payload), build=build_id())
    source_table = docling.pages[0].tables[0]
    paddle_table = source_table.model_copy(
        update={
            "table_id": "paddle-table",
            "continuation_of": None,
            "cells": tuple(
                cell.model_copy(update={"source_method": "ocr"}) for cell in source_table.cells
            ),
        }
    )
    paddle_page = docling.pages[0].model_copy(
        update={"native_text_ratio": 0.0, "blocks": (), "tables": (paddle_table,)}
    )
    candidate = CanonicalParserPage(
        document_id=docling.document_id,
        revision_id=docling.revision_id,
        original_sha256=docling.original_sha256,
        build_identity=build_id(adapter="paddle", configuration_sha256="c" * 64),
        page=paddle_page,
    )

    result = merge_selected_results(
        docling,
        (candidate,),
        decisions=(
            MergeSelection(
                page_number=12,
                boundary_kind="table",
                docling_id="table-4",
                paddle_id="paddle-table",
                reason="correct unresolved continuation",
            ),
        ),
    )

    assert result.artifact.pages[0].tables[0].continuation_of is None
    assert result.artifact.pages[0].tables[0].cells[0].source_method == "ocr"


@pytest.mark.parametrize(
    ("fixture", "outcome"),
    [
        ("docling-simple.json", QualityOutcome.PASS),
        ("docling-complex-table.json", QualityOutcome.PASS),
    ],
)
def test_quality_gate_passes_complete_docling_pages(fixture: str, outcome: QualityOutcome) -> None:
    artifact = canonicalize_docling(parser_response(fixture), build=build_id())
    assert assess_page_quality(artifact.pages[0], warnings=artifact.warnings).outcome is outcome


def test_quality_gate_uses_actual_text_not_native_ratio() -> None:
    payload = load_fixture("docling-simple.json")
    payload["pages"][0]["native_text_ratio"] = 1.0
    for block in payload["pages"][0]["blocks"]:
        block["text"] = "   "
    response = parser_response("docling-simple.json")
    response = with_vendor_payload(response, payload)
    missing = canonicalize_docling(response, build=build_id())

    assert (
        assess_page_quality(missing.pages[0], warnings=()).outcome is QualityOutcome.ESCALATE_PAGE
    )

    table_payload = load_fixture("docling-complex-table.json")
    table_payload["pages"][0]["blocks"] = []
    table_payload["pages"][0]["native_text_ratio"] = 1.0
    for cell in table_payload["pages"][0]["tables"][0]["cells"]:
        cell["text"] = ""
    table_response = parser_response("docling-complex-table.json")
    table_response = with_vendor_payload(table_response, table_payload)
    blank_table = canonicalize_docling(table_response, build=build_id())
    assert (
        assess_page_quality(blank_table.pages[0], warnings=()).outcome
        is QualityOutcome.ESCALATE_PAGE
    )


def test_quality_gate_reviews_structural_ambiguity() -> None:
    payload = load_fixture("docling-complex-table.json")
    payload["pages"][0]["tables"][0]["cells"].append(
        {"row": 0, "column": 0, "text": "duplicate", "bbox": [40, 90, 220, 130]}
    )
    response = parser_response("docling-complex-table.json")
    response = with_vendor_payload(response, payload)
    ambiguous = canonicalize_docling(response, build=build_id())
    assert (
        assess_page_quality(ambiguous.pages[0], warnings=()).outcome
        is QualityOutcome.REVIEW_REQUIRED
    )


def test_quality_detects_large_span_overlap_without_expanding_grid_coordinates() -> None:
    response = parser_response("docling-complex-table.json")
    payload = response.vendor_json
    payload["pages"][0]["tables"][0]["cells"][0]["row_span"] = 10_000
    artifact = canonicalize_docling(with_vendor_payload(response, payload), build=build_id())

    decision = assess_page_quality(artifact.pages[0], warnings=())
    assert decision.outcome is QualityOutcome.REVIEW_REQUIRED
    assert "table_cell_overlap" in decision.reasons


def test_quality_large_same_row_table_is_subquadratic_and_detects_overlap() -> None:
    artifact = canonicalize_docling(parser_response("docling-complex-table.json"), build=build_id())
    page = artifact.pages[0]
    table = page.tables[0]
    base_cell = table.cells[0]
    cell_count = 10_000
    width = table.bbox.x1 - table.bbox.x0
    cells = tuple(
        base_cell.model_copy(
            update={
                "row": 0,
                "column": index,
                "text": f"cell-{index}",
                "bbox": base_cell.bbox.model_copy(
                    update={
                        "x0": table.bbox.x0 + width * index / cell_count,
                        "x1": table.bbox.x0 + width * (index + 1) / cell_count,
                    }
                ),
            }
        )
        for index in range(cell_count)
    )
    large_table = table.model_copy(update={"cells": cells})
    large_page = page.model_copy(update={"tables": (large_table,)})

    assert assess_page_quality(large_page, warnings=()).outcome is QualityOutcome.PASS

    overlapping_cells = (*cells[:-1], cells[-1].model_copy(update={"column": cell_count - 2}))
    overlapping_table = large_table.model_copy(update={"cells": overlapping_cells})
    overlapping_page = large_page.model_copy(update={"tables": (overlapping_table,)})
    decision = assess_page_quality(overlapping_page, warnings=())
    assert decision.outcome is QualityOutcome.REVIEW_REQUIRED
    assert "table_cell_overlap" in decision.reasons


@pytest.mark.parametrize(
    "bbox",
    [
        [-1, 40, 100, 70],
        [40, 40, 700, 70],
        [100, 40, 40, 70],
    ],
)
def test_canonicalizer_rejects_invalid_or_out_of_page_bbox(bbox: list[int]) -> None:
    response = parser_response("docling-simple.json")
    payload = response.vendor_json
    payload["pages"][0]["blocks"][0]["bbox"] = bbox
    with pytest.raises((ValueError, ValidationError), match="bbox|coordinate|greater"):
        canonicalize_docling(with_vendor_payload(response, payload), build=build_id())


def test_canonicalizer_rejects_table_cell_bbox_outside_table() -> None:
    response = parser_response("docling-complex-table.json")
    payload = response.vendor_json
    payload["pages"][0]["tables"][0]["cells"][0]["bbox"] = [0, 0, 20, 20]
    with pytest.raises(ValueError, match="within its table bbox"):
        canonicalize_docling(with_vendor_payload(response, payload), build=build_id())


def test_quality_invalid_geometry_cannot_pass_and_blank_ocr_requires_review() -> None:
    artifact = canonicalize_docling(parser_response("docling-simple.json"), build=build_id())
    page = artifact.pages[0]
    invalid_bbox = page.blocks[0].bbox.model_copy(update={"x0": -1.0})
    invalid_block = page.blocks[0].model_copy(update={"bbox": invalid_bbox})
    invalid_page = page.model_copy(update={"blocks": (invalid_block, *page.blocks[1:])})
    invalid = assess_page_quality(invalid_page, warnings=())
    assert invalid.outcome is QualityOutcome.REVIEW_REQUIRED
    assert "invalid_page_geometry_or_bounds" in invalid.reasons

    response = parser_response(
        "paddle-ocr-page.json", adapter="paddle", configuration_sha256="c" * 64
    )
    payload = response.vendor_json
    payload["page"]["blocks"][0]["text"] = "  "
    blank_ocr = canonicalize_paddle_page(
        with_vendor_payload(response, payload),
        build=build_id(adapter="paddle", configuration_sha256="c" * 64),
    )
    decision = assess_page_quality(blank_ocr.page, warnings=())
    assert decision.outcome is QualityOutcome.REVIEW_REQUIRED
    assert "ocr_attempt_without_meaningful_text" in decision.reasons


class RecordingTransport:
    def __init__(self, attestation: ParserServiceAttestation | None = None) -> None:
        self.requests: list[ParserServiceRequest] = []
        self.follow_redirects: list[bool] = []
        self.attestation = attestation or parser_response("docling-simple.json").attestation

    def parse(
        self, request: ParserServiceRequest, *, follow_redirects: Literal[False]
    ) -> ParserServiceAttestation:
        self.requests.append(request)
        self.follow_redirects.append(follow_redirects)
        return self.attestation


def exact_request() -> ParserServiceRequest:
    return ParserServiceRequest(
        original_ref=original_ref(),
        page_numbers=(1,),
        parser_revision="2.112.0",
        model_digests=("sha256:model-digest",),
        configuration_sha256="b" * 64,
    )


def test_private_client_preserves_service_attestation_and_disables_redirects() -> None:
    transport = RecordingTransport()
    response = PrivateDoclingClient(
        transport=transport,
        scheduler=ImmediateKnowledgeModelWorkScheduler(),
    ).parse(exact_request())

    assert response.attestation == transport.attestation
    assert response.attestation.original_ref.sha256 == "a" * 64
    assert transport.follow_redirects == [False]


def test_paddle_client_rejects_multi_page_request_before_transport() -> None:
    request = exact_request().model_copy(update={"page_numbers": (1, 2)})
    transport = RecordingTransport()

    with pytest.raises(ValueError, match="exactly one page_number"):
        PrivatePaddleClient(
            transport=transport,
            scheduler=ImmediateKnowledgeModelWorkScheduler(),
        ).parse(request)
    assert transport.requests == []


@pytest.mark.parametrize("include_singular", [False, True])
def test_paddle_response_rejects_pages_array_payload(include_singular: bool) -> None:
    response = parser_response(
        "paddle-ocr-page.json", adapter="paddle", configuration_sha256="c" * 64
    )
    payload = response.vendor_json
    singular = payload.pop("page")
    payload["pages"] = [singular]
    if include_singular:
        payload["page"] = singular
    bypassed = with_vendor_payload(response, payload)

    with pytest.raises(ValidationError, match="exactly one singular page object"):
        canonicalize_paddle_page(
            bypassed,
            build=build_id(adapter="paddle", configuration_sha256="c" * 64),
        )


def test_paddle_response_rejects_multi_page_attestation() -> None:
    response = parser_response(
        "paddle-ocr-page.json", adapter="paddle", configuration_sha256="c" * 64
    )
    payload = response.vendor_json
    first = payload.pop("page")
    second = {**first, "page_number": 2}
    payload["pages"] = [first, second]
    vendor_json_bytes = canonical_vendor_json_bytes(payload)
    bypassed = response.model_copy(
        update={
            "request": response.request.model_copy(update={"page_numbers": (1, 2)}),
            "attestation": response.attestation.model_copy(
                update={
                    "page_numbers": (1, 2),
                    "vendor_json_bytes": vendor_json_bytes,
                    "vendor_json_sha256": hashlib.sha256(vendor_json_bytes).hexdigest(),
                }
            ),
        }
    )

    with pytest.raises(ValidationError, match="exactly one page_number"):
        canonicalize_paddle_page(
            bypassed,
            build=build_id(adapter="paddle", configuration_sha256="c" * 64),
        )


@pytest.mark.parametrize(
    ("field", "wrong"),
    [
        ("parser_adapter", "paddle"),
        ("original_ref", original_ref().model_copy(update={"sha256": "c" * 64})),
        ("page_numbers", (2,)),
        ("parser_revision", "wrong-revision"),
        ("model_digests", ("sha256:wrong-model",)),
        ("configuration_sha256", "d" * 64),
    ],
)
def test_private_client_rejects_each_mismatched_service_attestation(
    field: str, wrong: object
) -> None:
    attestation = parser_response("docling-simple.json").attestation.model_copy(
        update={field: wrong}
    )
    with pytest.raises(ValidationError, match="match"):
        PrivateDoclingClient(
            transport=RecordingTransport(attestation),
            scheduler=ImmediateKnowledgeModelWorkScheduler(),
        ).parse(exact_request())


def test_private_client_rejects_vendor_payload_outside_attested_source_binding() -> None:
    attestation = parser_response("docling-simple.json").attestation
    payload = parser_response("docling-simple.json").vendor_json
    payload["source_sha256"] = "d" * 64
    vendor_json_bytes = canonical_vendor_json_bytes(payload)
    attestation = attestation.model_copy(
        update={
            "vendor_json_bytes": vendor_json_bytes,
            "vendor_json_sha256": hashlib.sha256(vendor_json_bytes).hexdigest(),
        }
    )
    with pytest.raises(ValueError, match="service attestation"):
        PrivateDoclingClient(
            transport=RecordingTransport(attestation),
            scheduler=ImmediateKnowledgeModelWorkScheduler(),
        ).parse(exact_request())


def test_canonicalizer_rejects_build_not_bound_to_service_attestation() -> None:
    response = parser_response("docling-simple.json")
    mislabeled = build_id().model_copy(update={"parser_revision": "invented-revision"})
    with pytest.raises(ValueError, match="service attestation"):
        canonicalize_docling(response, build=mislabeled)


def test_canonicalizer_direct_call_rejects_vendor_page_outside_attestation() -> None:
    response = parser_response("docling-simple.json")
    payload = load_fixture("docling-simple.json")
    payload["pages"][0]["page_number"] = 2
    bypassed = with_vendor_payload(response, payload)

    with pytest.raises(ValidationError, match="vendor JSON pages"):
        canonicalize_docling(bypassed, build=build_id())


def test_document_quality_reviews_unresolved_cross_page_table_continuation() -> None:
    payload = load_fixture("docling-complex-table.json")
    payload["pages"][0]["tables"][0]["continuation_of"] = "missing-table"
    response = parser_response("docling-complex-table.json")
    response = with_vendor_payload(response, payload)
    artifact = canonicalize_docling(response, build=build_id())

    decision = assess_document_quality(artifact)[0]
    assert decision.outcome is QualityOutcome.REVIEW_REQUIRED
    assert "unresolved_cross_page_continuation" in decision.reasons


def test_parser_request_rejects_duplicate_pages_and_non_pdf_original() -> None:
    with pytest.raises(ValidationError):
        ParserServiceRequest(
            original_ref=original_ref(),
            page_numbers=(1, 1),
            parser_revision="2.112.0",
            model_digests=("sha256:model-digest",),
            configuration_sha256="b" * 64,
        )

    with pytest.raises(ValidationError):
        ParserServiceRequest(
            original_ref=original_ref().model_copy(update={"media_type": "text/plain"}),
            page_numbers=(1,),
            parser_revision="2.112.0",
            model_digests=("sha256:model-digest",),
            configuration_sha256="b" * 64,
        )
