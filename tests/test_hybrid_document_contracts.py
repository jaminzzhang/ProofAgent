from proof_agent.contracts.hybrid_documents import (
    BoundingBox,
    StructuredArtifactBuildIdentity,
    StructuredKnowledgeDocumentArtifact,
    StructuredPage,
    StructuredTable,
    StructuredTableCell,
)


def test_structured_artifact_preserves_table_cells_and_parser_lineage() -> None:
    artifact = StructuredKnowledgeDocumentArtifact(
        schema_version="structured-knowledge.v1",
        document_id="doc_1",
        revision_id="rev_1",
        original_sha256="a" * 64,
        build_identity=StructuredArtifactBuildIdentity(
            build_id="skab_1",
            source_sha256="a" * 64,
            parser_adapter="docling",
            parser_revision="2.112.0",
            model_digests=("sha256:model",),
            canonical_schema_version="structured-knowledge.v1",
            configuration_sha256="b" * 64,
        ),
        pages=(
            StructuredPage(
                page_number=12,
                width=612,
                height=792,
                blocks=(),
                tables=(
                    StructuredTable(
                        table_id="tbl_1",
                        title="Eligibility",
                        bbox=BoundingBox(x0=10, y0=20, x1=500, y1=700),
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
    )
    assert artifact.pages[0].tables[0].cells[0].text == "Age 18-60"
    assert artifact.build_identity.parser_adapter == "docling"
