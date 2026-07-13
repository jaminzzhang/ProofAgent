from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from proof_agent.capabilities.knowledge.hybrid.rule_units import (
    InsuranceRuleUnitDraft,
    project_rule_units,
)
from proof_agent.capabilities.knowledge.hybrid.versioning import (
    materialize_rule_unit_revision,
)
from proof_agent.contracts.hybrid_documents import (
    BoundingBox,
    StructuredArtifactBuildIdentity,
    StructuredBlock,
    StructuredKnowledgeDocumentArtifact,
    StructuredPage,
    StructuredTable,
    StructuredTableCell,
)
from proof_agent.contracts.insurance_rules import (
    ApprovedInsuranceKnowledgeVisibilityScope,
    ApprovedInsuranceRuleMetadataRevision,
    InsuranceRuleApplicability,
    InsuranceRuleMetadataDraft,
    InsuranceRulePrecedence,
    ProposedInsuranceKnowledgeVisibilityScope,
    ScopeDimension,
    TaxonomyCondition,
)


def bbox(x0: float, y0: float, x1: float, y1: float) -> BoundingBox:
    return BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1)


def build(*, build_id: str = "build-1") -> StructuredArtifactBuildIdentity:
    return StructuredArtifactBuildIdentity(
        build_id=build_id,
        source_sha256="a" * 64,
        parser_adapter="docling",
        parser_revision="2.112.0",
        model_digests=("sha256:model",),
        canonical_schema_version="structured-knowledge.v1",
        configuration_sha256="b" * 64,
    )


def defaults() -> InsuranceRuleMetadataDraft:
    return InsuranceRuleMetadataDraft(
        metadata_draft_id="metadata-draft-1",
        document_id="doc-1",
        revision_id="rev-1",
        applicability=InsuranceRuleApplicability(
            taxonomy_id="insurance-scope",
            taxonomy_revision_id="taxonomy-v1",
            conditions=(TaxonomyCondition(key="product", operator="EQ", values=("P-1",)),),
        ),
        effective_from=date(2026, 1, 1),
        authority="underwriting-manual",
        precedence=InsuranceRulePrecedence(
            policy_revision_id="precedence-v1",
            authority_tier="product-rule",
            order=10,
        ),
        proposed_visibility=ProposedInsuranceKnowledgeVisibilityScope(
            visibility="RESTRICTED",
            institutions=ScopeDimension(mode="ALL"),
            regions=ScopeDimension(mode="ALL"),
            channels=ScopeDimension(mode="ALL"),
            roles=ScopeDimension(mode="ALL"),
            business_lines=ScopeDimension(mode="ALL"),
        ),
    )


def canonical_artifact() -> StructuredKnowledgeDocumentArtifact:
    return StructuredKnowledgeDocumentArtifact(
        schema_version="structured-knowledge.v1",
        document_id="doc-1",
        revision_id="rev-1",
        original_sha256="a" * 64,
        build_identity=build(),
        pages=(
            StructuredPage(
                page_number=1,
                width=612,
                height=792,
                native_text_ratio=1,
                blocks=(
                    StructuredBlock(
                        block_id="heading-eligibility",
                        kind="heading",
                        text="Eligibility",
                        bbox=bbox(40, 40, 572, 70),
                        reading_order=0,
                        heading_level=1,
                        heading_path=("Eligibility",),
                    ),
                    StructuredBlock(
                        block_id="definition-applicant",
                        kind="paragraph",
                        text="Applicant means the person applying for cover.",
                        bbox=bbox(40, 80, 572, 110),
                        reading_order=1,
                        heading_path=("Eligibility",),
                    ),
                    StructuredBlock(
                        block_id="clause-age",
                        kind="list_item",
                        text="Applicants must be between 18 and 60 years old.",
                        bbox=bbox(40, 120, 572, 150),
                        reading_order=2,
                        heading_path=("Eligibility",),
                    ),
                ),
                tables=(),
            ),
            StructuredPage(
                page_number=2,
                width=612,
                height=792,
                native_text_ratio=0.9,
                blocks=(),
                tables=(
                    StructuredTable(
                        table_id="table-eligibility",
                        title="Eligibility limits",
                        bbox=bbox(40, 90, 572, 280),
                        cells=(
                            StructuredTableCell(
                                row=0, column=0, text="Plan", bbox=bbox(40, 90, 220, 130)
                            ),
                            StructuredTableCell(
                                row=0, column=1, text="Age", bbox=bbox(220, 90, 400, 130)
                            ),
                            StructuredTableCell(
                                row=1,
                                column=0,
                                text="Standard",
                                bbox=bbox(40, 130, 220, 170),
                            ),
                            StructuredTableCell(
                                row=1,
                                column=1,
                                text="18-60",
                                bbox=bbox(220, 130, 400, 170),
                            ),
                        ),
                    ),
                ),
            ),
            StructuredPage(
                page_number=3,
                width=612,
                height=792,
                native_text_ratio=0.8,
                blocks=(),
                tables=(
                    StructuredTable(
                        table_id="table-eligibility-p2",
                        title="Eligibility limits (continued)",
                        continuation_of="table-eligibility",
                        bbox=bbox(40, 90, 572, 230),
                        cells=(
                            StructuredTableCell(
                                row=0, column=0, text="Plan", bbox=bbox(40, 90, 220, 130)
                            ),
                            StructuredTableCell(
                                row=0, column=1, text="Age", bbox=bbox(220, 90, 400, 130)
                            ),
                            StructuredTableCell(
                                row=1,
                                column=0,
                                text="Premium",
                                bbox=bbox(40, 130, 220, 170),
                            ),
                            StructuredTableCell(
                                row=1,
                                column=1,
                                text="18-65",
                                bbox=bbox(220, 130, 400, 170),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )


def approved_metadata(*, revision: str = "metadata-v1") -> ApprovedInsuranceRuleMetadataRevision:
    draft = defaults()
    assert draft.applicability is not None
    assert draft.authority is not None
    assert draft.precedence is not None
    return ApprovedInsuranceRuleMetadataRevision(
        metadata_revision_id=revision,
        applicability=draft.applicability,
        effective_from=draft.effective_from,
        authority=draft.authority,
        precedence=draft.precedence,
    )


def visibility(*, revision: str = "visibility-v1") -> ApprovedInsuranceKnowledgeVisibilityScope:
    return ApprovedInsuranceKnowledgeVisibilityScope(visibility="PUBLIC", revision_id=revision)


def test_projects_sections_clauses_and_definition_context_without_token_chunks() -> None:
    units = project_rule_units(
        canonical_artifact(), document_defaults=defaults(), source_id="source-1"
    )

    section = next(unit for unit in units if unit.unit_kind == "section")
    clause = next(unit for unit in units if unit.block_ids == ("clause-age",))
    assert section.content == (
        "Eligibility\nApplicant means the person applying for cover.\n"
        "Applicants must be between 18 and 60 years old."
    )
    assert section.block_ids == (
        "heading-eligibility",
        "definition-applicant",
        "clause-age",
    )
    assert clause.block_ids == ("clause-age",)
    assert clause.definitions == ("Applicant means the person applying for cover.",)
    assert clause.heading_path == ("Eligibility",)
    assert clause.inherited_metadata == defaults()
    assert clause.source_id == "source-1"


def test_table_cells_project_as_one_row_rule_unit_with_headers() -> None:
    units = project_rule_units(canonical_artifact(), document_defaults=defaults())
    rows = [unit for unit in units if unit.unit_kind == "table_row"]

    assert len(rows) == 2
    assert "Eligibility limits" in rows[0].table_context
    assert "Age" in rows[0].table_context
    assert "Standard" in rows[0].content
    assert "18-60" in rows[0].content
    assert rows[0].row_header == "Standard"
    assert rows[0].cell_coordinates
    assert rows[0].page_bboxes[0].page_number == 2
    assert all(unit.unit_kind != "cell" for unit in units)


def test_cross_page_table_continuation_and_deterministic_order_are_preserved() -> None:
    artifact = canonical_artifact()
    first = project_rule_units(artifact, document_defaults=defaults())
    second = project_rule_units(artifact, document_defaults=defaults())

    assert first == second
    assert [unit.ordinal for unit in first] == list(range(len(first)))
    continuation = next(unit for unit in first if unit.table_id == "table-eligibility-p2")
    assert continuation.table_continuation_id == "table-eligibility"
    assert continuation.logical_rule_key != "table-eligibility"


def test_row_spans_project_as_one_row_group_instead_of_isolated_cells() -> None:
    artifact = canonical_artifact()
    page = artifact.pages[1]
    table = page.tables[0].model_copy(
        update={
            "cells": page.tables[0].cells
            + (
                StructuredTableCell(
                    row=2, column=1, text="61-64 review", bbox=bbox(220, 170, 400, 210)
                ),
            )
        }
    )
    spanning_header = table.cells[2].model_copy(
        update={"row_span": 2, "bbox": bbox(40, 130, 220, 210)}
    )
    table = table.model_copy(
        update={"cells": table.cells[:2] + (spanning_header,) + table.cells[3:]}
    )
    artifact = artifact.model_copy(
        update={"pages": (artifact.pages[0], page.model_copy(update={"tables": (table,)}))}
    )

    units = project_rule_units(artifact, document_defaults=defaults())
    group = next(unit for unit in units if unit.unit_kind == "row_group")
    assert group.row_numbers == (1, 2)
    assert "18-60" in group.content
    assert "61-64 review" in group.content
    assert len(group.cell_coordinates) == 3


def test_projection_rejects_wrong_metadata_lineage_and_invalid_artifact_order() -> None:
    wrong = defaults().model_copy(update={"revision_id": "rev-other"})
    with pytest.raises(ValueError, match="metadata draft lineage"):
        project_rule_units(canonical_artifact(), document_defaults=wrong)

    artifact = canonical_artifact()
    invalid = artifact.model_copy(update={"pages": tuple(reversed(artifact.pages))})
    with pytest.raises(ValueError, match="strictly increasing"):
        project_rule_units(invalid, document_defaults=defaults())


def test_rule_unit_draft_rejects_isolated_cell_and_inconsistent_lineage() -> None:
    unit = project_rule_units(canonical_artifact(), document_defaults=defaults())[0]
    payload = unit.model_dump()
    payload["unit_kind"] = "cell"
    with pytest.raises(ValidationError):
        InsuranceRuleUnitDraft.model_validate(payload)

    payload = unit.model_dump()
    payload["structured_build_id"] = "other-build"
    with pytest.raises(ValidationError, match="structured build"):
        InsuranceRuleUnitDraft.model_validate(payload)


def test_immutable_revision_identity_covers_content_build_metadata_and_visibility() -> None:
    draft = next(
        unit
        for unit in project_rule_units(canonical_artifact(), document_defaults=defaults())
        if unit.unit_kind == "clause"
    )
    original = materialize_rule_unit_revision(
        draft, approved_metadata=approved_metadata(), approved_visibility=visibility()
    )
    content_changed = materialize_rule_unit_revision(
        draft.model_copy(update={"content": draft.content + " Updated."}),
        approved_metadata=approved_metadata(),
        approved_visibility=visibility(),
    )
    build_changed = materialize_rule_unit_revision(
        draft.model_copy(
            update={
                "structured_build_id": "build-2",
                "structured_build_identity": build(build_id="build-2"),
            }
        ),
        approved_metadata=approved_metadata(),
        approved_visibility=visibility(),
    )
    metadata_changed = materialize_rule_unit_revision(
        draft,
        approved_metadata=approved_metadata(revision="metadata-v2"),
        approved_visibility=visibility(),
    )
    visibility_changed = materialize_rule_unit_revision(
        draft,
        approved_metadata=approved_metadata(),
        approved_visibility=visibility(revision="visibility-v2"),
    )

    identities = {
        original.rule_unit_revision_id,
        content_changed.rule_unit_revision_id,
        build_changed.rule_unit_revision_id,
        metadata_changed.rule_unit_revision_id,
        visibility_changed.rule_unit_revision_id,
    }
    assert len(identities) == 5
    assert original.content_sha256 != content_changed.content_sha256
    assert original.authority_sha256 != metadata_changed.authority_sha256
    assert original.authority_sha256 != visibility_changed.authority_sha256


def test_logical_rule_key_is_review_only_and_does_not_determine_runtime_identity() -> None:
    draft = project_rule_units(canonical_artifact(), document_defaults=defaults())[0]
    changed_key = draft.model_copy(update={"logical_rule_key": "review-key-changed"})

    first = materialize_rule_unit_revision(
        draft, approved_metadata=approved_metadata(), approved_visibility=visibility()
    )
    second = materialize_rule_unit_revision(
        changed_key, approved_metadata=approved_metadata(), approved_visibility=visibility()
    )

    assert first.logical_rule_key != second.logical_rule_key
    assert first.rule_unit_revision_id == second.rule_unit_revision_id


def test_logical_rule_key_stays_stable_across_structurally_aligned_document_revisions() -> None:
    first_draft = project_rule_units(canonical_artifact(), document_defaults=defaults())[0]
    artifact = canonical_artifact().model_copy(
        update={
            "revision_id": "rev-2",
            "build_identity": build(build_id="build-2"),
        }
    )
    revised_defaults = defaults().model_copy(update={"revision_id": "rev-2"})
    second_draft = project_rule_units(artifact, document_defaults=revised_defaults)[0]

    assert first_draft.logical_rule_key == second_draft.logical_rule_key
    first_revision = materialize_rule_unit_revision(
        first_draft,
        approved_metadata=approved_metadata(),
        approved_visibility=visibility(),
    )
    second_revision = materialize_rule_unit_revision(
        second_draft,
        approved_metadata=approved_metadata(),
        approved_visibility=visibility(),
    )
    assert first_revision.rule_unit_revision_id != second_revision.rule_unit_revision_id


def test_explicit_source_binding_participates_in_lineage_and_is_normalized() -> None:
    first = project_rule_units(
        canonical_artifact(), document_defaults=defaults(), source_id=" source-1 "
    )[0]
    same = project_rule_units(
        canonical_artifact(), document_defaults=defaults(), source_id="source-1"
    )[0]
    other = project_rule_units(
        canonical_artifact(), document_defaults=defaults(), source_id="source-2"
    )[0]

    assert first == same
    assert first.source_id == "source-1"
    assert first.logical_rule_key != other.logical_rule_key
    first_revision = materialize_rule_unit_revision(
        first,
        approved_metadata=approved_metadata(),
        approved_visibility=visibility(),
    )
    other_revision = materialize_rule_unit_revision(
        other,
        approved_metadata=approved_metadata(),
        approved_visibility=visibility(),
    )
    assert first_revision.rule_unit_revision_id != other_revision.rule_unit_revision_id


def test_projection_rejects_empty_artifacts_and_out_of_page_geometry() -> None:
    artifact = canonical_artifact()
    empty_page = artifact.pages[0].model_copy(update={"blocks": (), "tables": ()})
    empty = artifact.model_copy(update={"pages": (empty_page,)})
    with pytest.raises(ValueError, match="no coherent rule units"):
        project_rule_units(empty, document_defaults=defaults())

    bad_block = artifact.pages[0].blocks[0].model_copy(update={"bbox": bbox(40, 40, 700, 70)})
    bad_page = artifact.pages[0].model_copy(
        update={"blocks": (bad_block, *artifact.pages[0].blocks[1:])}
    )
    invalid = artifact.model_copy(update={"pages": (bad_page, *artifact.pages[1:])})
    with pytest.raises(ValueError, match="within page geometry"):
        project_rule_units(invalid, document_defaults=defaults())
