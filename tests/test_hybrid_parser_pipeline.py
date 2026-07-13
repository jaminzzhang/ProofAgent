from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import pytest
from pydantic import ValidationError

from proof_agent.capabilities.knowledge.hybrid.canonicalizer import (
    canonicalize_docling,
    canonicalize_paddle_page,
)
from proof_agent.capabilities.knowledge.hybrid.parser_clients import (
    ParserServiceAttestation,
    ParserServiceRequest,
    ParserServiceResponse,
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
            vendor_json=payload,
        ),
    )


def test_docling_fixture_maps_page_bbox_reading_order_and_table_cells() -> None:
    artifact = canonicalize_docling(parser_response("docling-complex-table.json"), build=build_id())

    assert artifact.pages[0].page_number == 12
    assert artifact.pages[0].blocks[0].reading_order == 0
    assert artifact.pages[0].tables[0].cells
    assert artifact.pages[0].tables[0].cells[0].bbox.x1 > 0
    assert artifact.pages[0].tables[0].cells[0].source_method == "native"
    assert artifact.build_identity == build_id()


def merged_block(*, reason: str = "native text missing", paddle_text: str | None = None):
    docling = canonicalize_docling(parser_response("docling-simple.json"), build=build_id())
    response = parser_response(
        "paddle-ocr-page.json", adapter="paddle", configuration_sha256="c" * 64
    )
    if paddle_text is not None:
        response = response.model_copy(
            update={
                "attestation": response.attestation.model_copy(
                    update={
                        "vendor_json": {
                            **response.vendor_json,
                            "page": {
                                **response.vendor_json["page"],
                                "blocks": [
                                    {
                                        **response.vendor_json["page"]["blocks"][0],
                                        "text": paddle_text,
                                    }
                                ],
                            },
                        }
                    }
                )
            }
        )
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
    response = response.model_copy(
        update={"attestation": response.attestation.model_copy(update={"vendor_json": payload})}
    )
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
    table_response = table_response.model_copy(
        update={
            "attestation": table_response.attestation.model_copy(
                update={"vendor_json": table_payload}
            )
        }
    )
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
    response = response.model_copy(
        update={"attestation": response.attestation.model_copy(update={"vendor_json": payload})}
    )
    ambiguous = canonicalize_docling(response, build=build_id())
    assert (
        assess_page_quality(ambiguous.pages[0], warnings=()).outcome
        is QualityOutcome.REVIEW_REQUIRED
    )


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
    response = PrivateDoclingClient(transport=transport).parse(exact_request())

    assert response.attestation == transport.attestation
    assert response.attestation.original_ref.sha256 == "a" * 64
    assert transport.follow_redirects == [False]


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
        PrivateDoclingClient(transport=RecordingTransport(attestation)).parse(exact_request())


def test_private_client_rejects_vendor_payload_outside_attested_source_binding() -> None:
    attestation = parser_response("docling-simple.json").attestation
    attestation = attestation.model_copy(
        update={"vendor_json": {**attestation.vendor_json, "source_sha256": "d" * 64}}
    )
    with pytest.raises(ValueError, match="service attestation"):
        PrivateDoclingClient(transport=RecordingTransport(attestation)).parse(exact_request())


def test_canonicalizer_rejects_build_not_bound_to_service_attestation() -> None:
    response = parser_response("docling-simple.json")
    mislabeled = build_id().model_copy(update={"parser_revision": "invented-revision"})
    with pytest.raises(ValueError, match="service attestation"):
        canonicalize_docling(response, build=mislabeled)


def test_document_quality_reviews_unresolved_cross_page_table_continuation() -> None:
    payload = load_fixture("docling-complex-table.json")
    payload["pages"][0]["tables"][0]["continuation_of"] = "missing-table"
    response = parser_response("docling-complex-table.json")
    response = response.model_copy(
        update={"attestation": response.attestation.model_copy(update={"vendor_json": payload})}
    )
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
