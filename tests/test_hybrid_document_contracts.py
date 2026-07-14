import json

import pytest
from pydantic import ValidationError

import proof_agent.contracts as contracts
from proof_agent.contracts import (
    BoundingBox,
    ParserWarning,
    StructuredArtifactBuildIdentity,
    StructuredBlock,
    StructuredKnowledgeDocumentArtifact,
    StructuredPage,
    StructuredQualitySignal,
    StructuredTable,
    StructuredTableCell,
)


def _build_identity(**overrides: object) -> StructuredArtifactBuildIdentity:
    values: dict[str, object] = {
        "build_id": "skab_1",
        "source_sha256": "a" * 64,
        "parser_adapter": "docling",
        "parser_revision": "2.112.0",
        "model_digests": ("sha256:model",),
        "canonical_schema_version": "structured-knowledge.v1",
        "configuration_sha256": "b" * 64,
    }
    values.update(overrides)
    return StructuredArtifactBuildIdentity(**values)  # type: ignore[arg-type]


def _artifact() -> StructuredKnowledgeDocumentArtifact:
    return StructuredKnowledgeDocumentArtifact(
        schema_version="structured-knowledge.v1",
        document_id="doc_1",
        revision_id="rev_1",
        original_sha256="a" * 64,
        build_identity=_build_identity(),
        pages=(
            StructuredPage(
                page_number=12,
                width=612,
                height=792,
                native_text_ratio=0.9,
                blocks=(
                    StructuredBlock(
                        block_id="blk_1",
                        block_type="heading",
                        text="Eligibility",
                        bbox=BoundingBox(x0=10, y0=20, x1=500, y1=40),
                        reading_order=0,
                        heading_level=1,
                        heading_path=("Eligibility",),
                    ),
                ),
                tables=(
                    StructuredTable(
                        table_id="tbl_1",
                        title="Eligibility",
                        bbox=BoundingBox(x0=10, y0=20, x1=500, y1=700),
                        continuation_of="tbl_0",
                        cells=(
                            StructuredTableCell(
                                row=1,
                                column=2,
                                text="Age 18-60",
                                bbox=BoundingBox(x0=100, y0=50, x1=200, y1=80),
                            ),
                        ),
                    ),
                ),
            ),
        ),
        warnings=(
            ParserWarning(
                code="table_continuation",
                message="Table continues from the preceding page.",
                page_number=12,
                table_id="tbl_1",
            ),
        ),
        quality_signals=(
            StructuredQualitySignal(
                code="table_structure_confidence",
                score=0.93,
                page_number=12,
                table_id="tbl_1",
            ),
        ),
    )


def test_structured_artifact_preserves_canonical_structure_and_lineage() -> None:
    artifact = _artifact()

    assert artifact.pages[0].native_text_ratio == 0.9
    assert artifact.pages[0].blocks[0].heading_path == ("Eligibility",)
    assert artifact.pages[0].tables[0].continuation_of == "tbl_0"
    assert artifact.pages[0].tables[0].cells[0].text == "Age 18-60"
    assert artifact.build_identity.parser_adapter == "docling"
    assert artifact.quality_signals[0].score == 0.93


def test_structured_contracts_are_exported_from_package() -> None:
    expected_exports = {
        "BoundingBox",
        "ParserWarning",
        "StructuredArtifactBuildIdentity",
        "StructuredBlock",
        "StructuredKnowledgeDocumentArtifact",
        "StructuredPage",
        "StructuredQualitySignal",
        "StructuredTable",
        "StructuredTableCell",
    }

    assert expected_exports <= set(contracts.__all__)
    assert all(hasattr(contracts, name) for name in expected_exports)


def test_structured_artifact_json_round_trip_preserves_canonical_schema() -> None:
    artifact = _artifact()

    payload = json.loads(artifact.model_dump_json())
    restored = StructuredKnowledgeDocumentArtifact.model_validate_json(artifact.model_dump_json())

    assert restored == artifact
    assert payload["schema_version"] == "structured-knowledge.v1"
    assert payload["pages"][0]["blocks"][0]["kind"] == "heading"
    assert payload["pages"][0]["tables"][0]["cells"][0]["row_span"] == 1
    assert payload["quality_signals"][0]["code"] == "table_structure_confidence"


def test_structured_artifact_and_nested_collections_are_immutable() -> None:
    artifact = _artifact()

    with pytest.raises(ValidationError):
        artifact.document_id = "other"
    with pytest.raises(ValidationError):
        artifact.pages[0].width = 100
    with pytest.raises(TypeError):
        artifact.pages[0].blocks[0].heading_path[0] = "Changed"  # type: ignore[index]


@pytest.mark.parametrize(
    ("model", "values"),
    [
        (BoundingBox, {"x0": 2, "y0": 0, "x1": 1, "y1": 1}),
        (BoundingBox, {"x0": 0, "y0": 2, "x1": 1, "y1": 1}),
        (
            StructuredPage,
            {"page_number": 1, "width": 0, "height": 10, "native_text_ratio": 1},
        ),
        (
            StructuredPage,
            {"page_number": 1, "width": 10, "height": 0, "native_text_ratio": 1},
        ),
        (
            StructuredPage,
            {"page_number": 0, "width": 10, "height": 10, "native_text_ratio": 1},
        ),
        (
            StructuredPage,
            {"page_number": 1, "width": 10, "height": 10, "native_text_ratio": 1.1},
        ),
        (
            StructuredTableCell,
            {
                "row": -1,
                "column": 0,
                "text": "x",
                "bbox": {"x0": 0, "y0": 0, "x1": 1, "y1": 1},
            },
        ),
        (
            StructuredTableCell,
            {
                "row": 0,
                "column": -1,
                "text": "x",
                "bbox": {"x0": 0, "y0": 0, "x1": 1, "y1": 1},
            },
        ),
        (
            StructuredTableCell,
            {
                "row": 0,
                "column": 0,
                "row_span": 0,
                "text": "x",
                "bbox": {"x0": 0, "y0": 0, "x1": 1, "y1": 1},
            },
        ),
        (
            StructuredTableCell,
            {
                "row": 0,
                "column": 0,
                "column_span": 0,
                "text": "x",
                "bbox": {"x0": 0, "y0": 0, "x1": 1, "y1": 1},
            },
        ),
        (
            StructuredTableCell,
            {
                "row": 0,
                "column": 0,
                "text": "x",
                "bbox": {"x0": 0, "y0": 0, "x1": 1, "y1": 1},
                "source_method": "vendor",
            },
        ),
        (
            StructuredBlock,
            {
                "block_id": "blk_1",
                "block_type": "vendor",
                "text": "x",
                "bbox": {"x0": 0, "y0": 0, "x1": 1, "y1": 1},
                "reading_order": 0,
            },
        ),
    ],
)
def test_structured_contracts_reject_invalid_structure(
    model: type[object], values: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        model(**values)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("build_id", " "),
        ("source_sha256", "A" * 64),
        ("source_sha256", "a" * 63),
        ("parser_adapter", ""),
        ("parser_revision", "\t"),
        ("model_digests", ("",)),
        ("configuration_sha256", "not-a-digest"),
        ("canonical_schema_version", "structured-knowledge.v2"),
    ],
)
def test_build_identity_rejects_blank_or_invalid_identity(
    field: str, invalid_value: object
) -> None:
    with pytest.raises(ValidationError):
        _build_identity(**{field: invalid_value})


@pytest.mark.parametrize("field", ["document_id", "revision_id"])
def test_artifact_rejects_blank_authority_id(field: str) -> None:
    values = _artifact().model_dump()
    values[field] = " "

    with pytest.raises(ValidationError):
        StructuredKnowledgeDocumentArtifact.model_validate(values)


def test_artifact_rejects_empty_pages_and_contradictory_source_hash() -> None:
    values = _artifact().model_dump()
    values["pages"] = ()
    with pytest.raises(ValidationError):
        StructuredKnowledgeDocumentArtifact.model_validate(values)

    values = _artifact().model_dump()
    values["original_sha256"] = "A" * 64
    with pytest.raises(ValidationError):
        StructuredKnowledgeDocumentArtifact.model_validate(values)

    values = _artifact().model_dump()
    values["original_sha256"] = "c" * 64
    with pytest.raises(ValidationError):
        StructuredKnowledgeDocumentArtifact.model_validate(values)


def test_heading_level_matches_block_type() -> None:
    values = _artifact().pages[0].blocks[0].model_dump()
    values["heading_level"] = None
    with pytest.raises(ValidationError):
        StructuredBlock.model_validate(values)

    values["kind"] = "paragraph"
    values["heading_level"] = 1
    with pytest.raises(ValidationError):
        StructuredBlock.model_validate(values)


def test_canonical_contracts_reject_unknown_fields() -> None:
    values = _artifact().model_dump()
    values["vendor_payload"] = {"docling": {}}

    with pytest.raises(ValidationError):
        StructuredKnowledgeDocumentArtifact.model_validate(values)

    with pytest.raises(ValidationError):
        BoundingBox(x0=0, y0=0, x1=1, y1=1, vendor_coordinate=1)  # type: ignore[call-arg]


def test_table_cannot_continue_itself() -> None:
    with pytest.raises(ValidationError):
        StructuredTable(
            table_id="tbl_1",
            title=None,
            bbox=BoundingBox(x0=0, y0=0, x1=1, y1=1),
            continuation_of="tbl_1",
        )
