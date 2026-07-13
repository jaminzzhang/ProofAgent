from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from proof_agent.capabilities.knowledge.hybrid.canonicalizer import (
    canonicalize_docling,
    canonicalize_paddle_page,
)
from proof_agent.capabilities.knowledge.hybrid.parser_clients import (
    ParserServiceRequest,
    PrivateDoclingClient,
)
from proof_agent.capabilities.knowledge.hybrid.pipeline import (
    MergeSelection,
    merge_selected_results,
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


def build_id(*, adapter: str = "docling") -> StructuredArtifactBuildIdentity:
    return StructuredArtifactBuildIdentity(
        build_id=f"build-{adapter}",
        source_sha256="a" * 64,
        parser_adapter=adapter,
        parser_revision="2.112.0" if adapter == "docling" else "3.7.0",
        model_digests=("sha256:model-digest",),
        canonical_schema_version="structured-knowledge.v1",
        configuration_sha256="b" * 64,
    )


def original_ref() -> ExactArtifactRef:
    return ExactArtifactRef(
        artifact_uri="s3://private/originals/document.pdf",
        version_id="version-1",
        sha256="a" * 64,
        size_bytes=123,
        media_type="application/pdf",
    )


def test_docling_fixture_maps_page_bbox_reading_order_and_table_cells() -> None:
    artifact = canonicalize_docling(load_fixture("docling-complex-table.json"), build=build_id())

    assert artifact.pages[0].page_number == 12
    assert artifact.pages[0].blocks[0].reading_order == 0
    assert artifact.pages[0].tables[0].cells
    assert artifact.pages[0].tables[0].cells[0].bbox.x1 > 0
    assert artifact.pages[0].tables[0].cells[0].source_method == "native"
    assert artifact.build_identity == build_id()


def test_paddle_escalation_replaces_one_block_without_mixing_text() -> None:
    docling = canonicalize_docling(load_fixture("docling-simple.json"), build=build_id())
    paddle_page = canonicalize_paddle_page(
        load_fixture("paddle-ocr-page.json"), build=build_id(adapter="paddle")
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
                reason="native text missing",
            ),
        ),
    )

    assert result.pages[0].blocks[1].source_method == "ocr"
    assert result.pages[0].blocks[1].text == "selected paddle text"
    assert "Applicants must" not in result.pages[0].blocks[1].text
    assert any(signal.code == "paddle_block_replacement" for signal in result.quality_signals)


@pytest.mark.parametrize(
    ("fixture", "outcome"),
    [
        ("docling-simple.json", QualityOutcome.PASS),
        ("docling-complex-table.json", QualityOutcome.PASS),
    ],
)
def test_quality_gate_passes_complete_docling_pages(fixture: str, outcome: QualityOutcome) -> None:
    artifact = canonicalize_docling(load_fixture(fixture), build=build_id())
    assert assess_page_quality(artifact.pages[0], warnings=artifact.warnings).outcome is outcome


def test_quality_gate_escalates_missing_text_and_reviews_structural_ambiguity() -> None:
    payload = load_fixture("docling-simple.json")
    page = payload["pages"][0]
    page["native_text_ratio"] = 0.0
    page["blocks"] = []
    missing = canonicalize_docling(payload, build=build_id())
    assert (
        assess_page_quality(missing.pages[0], warnings=()).outcome is QualityOutcome.ESCALATE_PAGE
    )

    payload = load_fixture("docling-complex-table.json")
    payload["pages"][0]["tables"][0]["cells"].append(
        {"row": 0, "column": 0, "text": "duplicate", "bbox": [40, 90, 220, 130]}
    )
    ambiguous = canonicalize_docling(payload, build=build_id())
    assert (
        assess_page_quality(ambiguous.pages[0], warnings=()).outcome
        is QualityOutcome.REVIEW_REQUIRED
    )


class RecordingTransport:
    def __init__(self) -> None:
        self.requests: list[ParserServiceRequest] = []
        self.follow_redirects: list[bool] = []

    def parse(self, request: ParserServiceRequest, *, follow_redirects: bool) -> dict[str, Any]:
        self.requests.append(request)
        self.follow_redirects.append(follow_redirects)
        return load_fixture("docling-simple.json")


def test_private_client_preserves_exact_identity_and_disables_redirects() -> None:
    transport = RecordingTransport()
    client = PrivateDoclingClient(transport=transport)
    request = ParserServiceRequest(
        original_ref=original_ref(),
        page_numbers=(1,),
        parser_revision="2.112.0",
        model_digests=("sha256:model-digest",),
        configuration_sha256="b" * 64,
    )

    response = client.parse(request)

    assert response.request == request
    assert response.request.original_ref.sha256 == "a" * 64
    assert transport.follow_redirects == [False]


def test_private_client_rejects_response_for_different_original() -> None:
    class WrongTransport(RecordingTransport):
        def parse(self, request: ParserServiceRequest, *, follow_redirects: bool) -> dict[str, Any]:
            payload = super().parse(request, follow_redirects=follow_redirects)
            payload["source_sha256"] = "c" * 64
            return payload

    with pytest.raises(ValueError, match="exact original"):
        PrivateDoclingClient(transport=WrongTransport()).parse(
            ParserServiceRequest(
                original_ref=original_ref(),
                page_numbers=(1,),
                parser_revision="2.112.0",
                model_digests=("sha256:model-digest",),
                configuration_sha256="b" * 64,
            )
        )


def test_document_quality_reviews_unresolved_cross_page_table_continuation() -> None:
    payload = load_fixture("docling-complex-table.json")
    payload["pages"][0]["tables"][0]["continuation_of"] = "missing-table"
    artifact = canonicalize_docling(payload, build=build_id())

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
