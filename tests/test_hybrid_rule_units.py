from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from proof_agent.capabilities.knowledge.hybrid.rule_units import (
    RuleUnitProjectionLimits,
    InsuranceRuleUnitDraft,
    RuleUnitProjectionReviewRequired,
    RuleUnitProjectionWorkCounter,
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
    units = project_rule_units(
        canonical_artifact(), document_defaults=defaults(), source_id="source-1"
    )
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
    first = project_rule_units(artifact, document_defaults=defaults(), source_id="source-1")
    second = project_rule_units(artifact, document_defaults=defaults(), source_id="source-1")

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

    units = project_rule_units(artifact, document_defaults=defaults(), source_id="source-1")
    group = next(unit for unit in units if unit.unit_kind == "row_group")
    assert group.row_numbers == (1, 2)
    assert "18-60" in group.content
    assert "61-64 review" in group.content
    assert len(group.cell_coordinates) == 3


def test_projection_rejects_wrong_metadata_lineage_and_invalid_artifact_order() -> None:
    wrong = defaults().model_copy(update={"revision_id": "rev-other"})
    with pytest.raises(ValueError, match="metadata draft lineage"):
        project_rule_units(canonical_artifact(), document_defaults=wrong, source_id="source-1")

    artifact = canonical_artifact()
    invalid = artifact.model_copy(update={"pages": tuple(reversed(artifact.pages))})
    with pytest.raises(ValueError, match="strictly increasing"):
        project_rule_units(invalid, document_defaults=defaults(), source_id="source-1")


def test_rule_unit_draft_rejects_isolated_cell_and_inconsistent_lineage() -> None:
    unit = project_rule_units(
        canonical_artifact(), document_defaults=defaults(), source_id="source-1"
    )[0]
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
        for unit in project_rule_units(
            canonical_artifact(), document_defaults=defaults(), source_id="source-1"
        )
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
    draft = project_rule_units(
        canonical_artifact(), document_defaults=defaults(), source_id="source-1"
    )[0]
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
    first_draft = project_rule_units(
        canonical_artifact(), document_defaults=defaults(), source_id="source-1"
    )[0]
    artifact = canonical_artifact().model_copy(
        update={
            "revision_id": "rev-2",
            "build_identity": build(build_id="build-2"),
        }
    )
    revised_defaults = defaults().model_copy(update={"revision_id": "rev-2"})
    second_draft = project_rule_units(
        artifact, document_defaults=revised_defaults, source_id="source-1"
    )[0]

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
    assert first_revision.lineage.source_id == "source-1"
    assert other_revision.lineage.source_id == "source-2"
    assert first_revision.rule_unit_revision_id != other_revision.rule_unit_revision_id


def test_projection_rejects_empty_artifacts_and_out_of_page_geometry() -> None:
    artifact = canonical_artifact()
    empty_page = artifact.pages[0].model_copy(update={"blocks": (), "tables": ()})
    empty = artifact.model_copy(update={"pages": (empty_page,)})
    with pytest.raises(ValueError, match="no coherent rule units"):
        project_rule_units(empty, document_defaults=defaults(), source_id="source-1")

    bad_block = artifact.pages[0].blocks[0].model_copy(update={"bbox": bbox(40, 40, 700, 70)})
    bad_page = artifact.pages[0].model_copy(
        update={"blocks": (bad_block, *artifact.pages[0].blocks[1:])}
    )
    invalid = artifact.model_copy(update={"pages": (bad_page, *artifact.pages[1:])})
    with pytest.raises(ValueError, match="within page geometry"):
        project_rule_units(invalid, document_defaults=defaults(), source_id="source-1")


def test_unrelated_adjacent_rows_do_not_rescue_an_isolated_cell() -> None:
    artifact = canonical_artifact()
    page = artifact.pages[1]
    table = page.tables[0]
    cells = (
        *table.cells[:2],
        table.cells[3],
        StructuredTableCell(
            row=2,
            column=0,
            text="Premium",
            bbox=bbox(40, 170, 220, 210),
        ),
        StructuredTableCell(
            row=2,
            column=1,
            text="18-65",
            bbox=bbox(220, 170, 400, 210),
        ),
    )
    artifact = artifact.model_copy(
        update={
            "pages": (
                artifact.pages[0],
                page.model_copy(update={"tables": (table.model_copy(update={"cells": cells}),)}),
            )
        }
    )

    with pytest.raises(RuleUnitProjectionReviewRequired, match="canonical row-group"):
        project_rule_units(artifact, document_defaults=defaults(), source_id="source-1")


def test_unmergeable_isolated_table_cell_blocks_projection() -> None:
    artifact = canonical_artifact()
    page = artifact.pages[1]
    table = page.tables[0]
    isolated = (*table.cells[:2], table.cells[3])
    artifact = artifact.model_copy(
        update={
            "pages": (
                artifact.pages[0],
                page.model_copy(update={"tables": (table.model_copy(update={"cells": isolated}),)}),
            )
        }
    )

    with pytest.raises(RuleUnitProjectionReviewRequired, match="isolated cell"):
        project_rule_units(artifact, document_defaults=defaults(), source_id="source-1")


def test_same_table_rows_have_distinct_exact_citation_anchors() -> None:
    artifact = canonical_artifact()
    page = artifact.pages[1]
    table = page.tables[0]
    cells = table.cells + (
        StructuredTableCell(
            row=2,
            column=0,
            text="Premium",
            bbox=bbox(40, 170, 220, 210),
        ),
        StructuredTableCell(
            row=2,
            column=1,
            text="18-65",
            bbox=bbox(220, 170, 400, 210),
        ),
    )
    artifact = artifact.model_copy(
        update={
            "pages": (
                artifact.pages[0],
                page.model_copy(update={"tables": (table.model_copy(update={"cells": cells}),)}),
            )
        }
    )

    rows = [
        unit
        for unit in project_rule_units(artifact, document_defaults=defaults(), source_id="source-1")
        if unit.unit_kind == "table_row"
    ]

    assert len(rows) == 2
    assert rows[0].citation_uri != rows[1].citation_uri
    assert "rows-1" in rows[0].citation_uri
    assert "rows-2" in rows[1].citation_uri


def test_materialized_revision_retains_inspectable_coherent_lineage() -> None:
    row = next(
        unit
        for unit in project_rule_units(
            canonical_artifact(), document_defaults=defaults(), source_id="source-1"
        )
        if unit.unit_kind == "table_row"
    )
    revision = materialize_rule_unit_revision(
        row,
        approved_metadata=approved_metadata(),
        approved_visibility=visibility(),
    )

    assert revision.lineage.source_id == "source-1"
    assert revision.lineage.original_sha256 == "a" * 64
    assert revision.lineage.page_numbers == (2,)
    assert revision.lineage.table_title == "Eligibility limits"
    assert revision.lineage.table_headers == ("Plan", "Age")
    assert revision.lineage.row_header == "Standard"
    assert revision.lineage.row_numbers == (1,)
    assert revision.lineage.cell_coordinates
    assert revision.lineage.page_bboxes[0].bbox == bbox(40, 90, 572, 280)

    continuation = next(
        unit
        for unit in project_rule_units(
            canonical_artifact(), document_defaults=defaults(), source_id="source-1"
        )
        if unit.table_continuation_id is not None
    )
    continued_revision = materialize_rule_unit_revision(
        continuation,
        approved_metadata=approved_metadata(),
        approved_visibility=visibility(),
    )
    assert continued_revision.lineage.table_continuation_id == "table-eligibility"


def test_projection_requires_explicit_source_identity() -> None:
    with pytest.raises(TypeError):
        project_rule_units(canonical_artifact(), document_defaults=defaults())  # type: ignore[call-arg]


def test_table_between_two_headings_uses_nearest_preceding_heading() -> None:
    artifact = canonical_artifact()
    page = artifact.pages[1].model_copy(
        update={
            "blocks": (
                StructuredBlock(
                    block_id="heading-a",
                    kind="heading",
                    text="Section A",
                    bbox=bbox(40, 40, 572, 70),
                    reading_order=0,
                    heading_level=1,
                    heading_path=("Section A",),
                ),
                StructuredBlock(
                    block_id="heading-b",
                    kind="heading",
                    text="Section B",
                    bbox=bbox(40, 320, 572, 350),
                    reading_order=1,
                    heading_level=1,
                    heading_path=("Section B",),
                ),
            )
        }
    )
    artifact = artifact.model_copy(update={"pages": (page,)})

    units = project_rule_units(artifact, document_defaults=defaults(), source_id="source-1")

    assert {unit.heading_path for unit in units} == {("Section A",)}
    assert all(unit.block_ids != ("heading-a",) for unit in units)
    assert all(unit.block_ids != ("heading-b",) for unit in units)


def test_overlapping_table_cell_spans_require_review() -> None:
    artifact = canonical_artifact()
    page = artifact.pages[1]
    table = page.tables[0]
    overlapping = table.cells[:2] + (
        table.cells[2].model_copy(update={"column_span": 2}),
        table.cells[3],
    )
    page = page.model_copy(update={"tables": (table.model_copy(update={"cells": overlapping}),)})
    artifact = artifact.model_copy(update={"pages": (artifact.pages[0], page)})

    with pytest.raises(RuleUnitProjectionReviewRequired, match="overlap"):
        project_rule_units(artifact, document_defaults=defaults(), source_id="source-1")


def test_overlapping_row_spans_require_review_without_grid_expansion() -> None:
    artifact = canonical_artifact()
    page = artifact.pages[1]
    table = page.tables[0]
    cells = table.cells + (
        StructuredTableCell(
            row=2,
            column=0,
            text="overlap",
            bbox=bbox(40, 170, 220, 210),
        ),
    )
    cells = (*cells[:2], cells[2].model_copy(update={"row_span": 2}), *cells[3:])
    page = page.model_copy(update={"tables": (table.model_copy(update={"cells": cells}),)})
    artifact = artifact.model_copy(update={"pages": (artifact.pages[0], page)})

    with pytest.raises(RuleUnitProjectionReviewRequired, match="overlap"):
        project_rule_units(artifact, document_defaults=defaults(), source_id="source-1")


def test_dedicated_definition_section_is_attached_by_explicit_term_reference() -> None:
    artifact = canonical_artifact()
    definitions_page = artifact.pages[0].model_copy(
        update={
            "blocks": (
                StructuredBlock(
                    block_id="heading-definitions",
                    kind="heading",
                    text="Definitions",
                    bbox=bbox(40, 40, 572, 70),
                    reading_order=0,
                    heading_level=1,
                    heading_path=("Definitions",),
                ),
                artifact.pages[0]
                .blocks[1]
                .model_copy(update={"heading_path": ("Definitions",), "reading_order": 1}),
                StructuredBlock(
                    block_id="heading-eligibility-after-definitions",
                    kind="heading",
                    text="Eligibility",
                    bbox=bbox(40, 120, 572, 150),
                    reading_order=2,
                    heading_level=1,
                    heading_path=("Eligibility",),
                ),
                artifact.pages[0]
                .blocks[2]
                .model_copy(
                    update={
                        "heading_path": ("Eligibility",),
                        "reading_order": 3,
                        "bbox": bbox(40, 160, 572, 190),
                    }
                ),
            )
        }
    )
    artifact = artifact.model_copy(update={"pages": (definitions_page,)})

    clause = next(
        unit
        for unit in project_rule_units(artifact, document_defaults=defaults(), source_id="source-1")
        if unit.block_ids == ("clause-age",)
    )

    assert clause.definitions == ("Applicant means the person applying for cover.",)


def test_ambiguous_duplicate_referenced_definitions_require_review() -> None:
    artifact = canonical_artifact()
    page = artifact.pages[0]
    duplicate = page.blocks[1].model_copy(
        update={
            "block_id": "definition-applicant-duplicate",
            "text": "Applicant means an insured person.",
            "reading_order": 2,
        }
    )
    clause = page.blocks[2].model_copy(update={"reading_order": 3})
    page = page.model_copy(update={"blocks": (*page.blocks[:2], duplicate, clause)})
    artifact = artifact.model_copy(update={"pages": (page,)})

    with pytest.raises(RuleUnitProjectionReviewRequired, match="duplicate definitions"):
        project_rule_units(artifact, document_defaults=defaults(), source_id="source-1")


@pytest.mark.parametrize(
    "cross_reference",
    (
        "详见本合同释义章节。",
        "See the definition section.",
        "本条所指的投保人须签字。",
    ),
)
def test_generic_definition_cross_references_are_ordinary_content(
    cross_reference: str,
) -> None:
    artifact = canonical_artifact()
    page = artifact.pages[0].model_copy(
        update={
            "blocks": (
                StructuredBlock(
                    block_id="definition-cross-reference",
                    kind="paragraph",
                    text=cross_reference,
                    bbox=bbox(40, 40, 572, 70),
                    reading_order=0,
                ),
            ),
            "tables": (),
        }
    )
    artifact = artifact.model_copy(update={"pages": (page,)})

    units = project_rule_units(
        artifact,
        document_defaults=defaults(),
        source_id="source-1",
    )

    assert len(units) == 1
    assert units[0].content == cross_reference
    assert units[0].definitions == ()


@pytest.mark.parametrize(
    "ambiguous_text",
    (
        "箭头：指向右侧。",
        "本条：指出本合同无效。",
        "该标志：指示投保人签字。",
        "保险金申请人：指向保险人提出给付保险金申请的人。",
    ),
)
def test_unquoted_bare_zhi_compound_continuations_require_review(
    ambiguous_text: str,
) -> None:
    artifact = canonical_artifact()
    page = artifact.pages[0].model_copy(
        update={
            "blocks": (
                StructuredBlock(
                    block_id="ambiguous-bare-zhi",
                    kind="paragraph",
                    text=ambiguous_text,
                    bbox=bbox(40, 40, 572, 70),
                    reading_order=0,
                ),
            ),
            "tables": (),
        }
    )
    artifact = artifact.model_copy(update={"pages": (page,)})

    with pytest.raises(RuleUnitProjectionReviewRequired, match="ambiguous compound-verb"):
        project_rule_units(
            artifact,
            document_defaults=defaults(),
            source_id="source-1",
        )


@pytest.mark.parametrize(
    ("definition_text", "reference_text"),
    (
        ("Applicant: means the person applying for cover.", "Applicants must be adults."),
        ("投保人，是指申请保险保障的人。", "投保人必须年满十八周岁。"),
        ("“投保人”，是指申请保险保障的人。", "投保人必须年满十八周岁。"),
        ("投保人：是指申请保险保障的人。", "投保人必须年满十八周岁。"),
        ("“投保人”指申请保险保障的人。", "投保人必须年满十八周岁。"),
        ("投保人：指申请保险保障的人。", "投保人必须年满十八周岁。"),
        (
            "“保险金申请人”指向保险人提出给付保险金申请的人。",
            "保险金申请人须提交申请材料。",
        ),
    ),
)
def test_definition_separator_punctuation_preserves_reference_attachment(
    definition_text: str,
    reference_text: str,
) -> None:
    artifact = canonical_artifact()
    page = artifact.pages[0].model_copy(
        update={
            "blocks": (
                StructuredBlock(
                    block_id="punctuated-definition",
                    kind="paragraph",
                    text=definition_text,
                    bbox=bbox(40, 40, 572, 70),
                    reading_order=0,
                ),
                StructuredBlock(
                    block_id="punctuated-definition-reference",
                    kind="list_item",
                    text=reference_text,
                    bbox=bbox(40, 80, 572, 110),
                    reading_order=1,
                ),
            ),
            "tables": (),
        }
    )
    artifact = artifact.model_copy(update={"pages": (page,)})

    reference = next(
        unit
        for unit in project_rule_units(
            artifact,
            document_defaults=defaults(),
            source_id="source-1",
        )
        if unit.block_ids == ("punctuated-definition-reference",)
    )

    assert reference.definitions == (definition_text,)


@pytest.mark.parametrize(
    "definition_text",
    (
        "本合同所称“投保人”是指申请保险保障的人。",
        "本保险合同所称投保人，是指申请保险保障的人。",
    ),
)
def test_suocheng_definition_extracts_only_the_terminal_term(
    definition_text: str,
) -> None:
    artifact = canonical_artifact()
    page = artifact.pages[0].model_copy(
        update={
            "blocks": (
                StructuredBlock(
                    block_id="suocheng-definition",
                    kind="paragraph",
                    text=definition_text,
                    bbox=bbox(40, 40, 572, 70),
                    reading_order=0,
                ),
                StructuredBlock(
                    block_id="suocheng-reference",
                    kind="list_item",
                    text="投保人必须年满十八周岁。",
                    bbox=bbox(40, 80, 572, 110),
                    reading_order=1,
                ),
            ),
            "tables": (),
        }
    )
    artifact = artifact.model_copy(update={"pages": (page,)})

    reference = next(
        unit
        for unit in project_rule_units(
            artifact,
            document_defaults=defaults(),
            source_id="source-1",
        )
        if unit.block_ids == ("suocheng-reference",)
    )

    assert reference.definitions == (definition_text,)


def test_unbounded_unquoted_suocheng_term_requires_review() -> None:
    artifact = canonical_artifact()
    page = artifact.pages[0].model_copy(
        update={
            "blocks": (
                StructuredBlock(
                    block_id="unbounded-suocheng-definition",
                    kind="paragraph",
                    text="本合同所称投保人 及被保险人，是指申请保险保障的人。",
                    bbox=bbox(40, 40, 572, 70),
                    reading_order=0,
                ),
            ),
            "tables": (),
        }
    )
    artifact = artifact.model_copy(update={"pages": (page,)})

    with pytest.raises(RuleUnitProjectionReviewRequired, match="reliably bounded term"):
        project_rule_units(
            artifact,
            document_defaults=defaults(),
            source_id="source-1",
        )


@pytest.mark.parametrize(
    "composite_term",
    (
        "投保人及被保险人",
        "投保人和被保险人",
        "投保人与被保险人",
        "投保人或被保险人",
        "投保人以及被保险人",
    ),
)
def test_unquoted_suocheng_conjunction_terms_require_review(
    composite_term: str,
) -> None:
    artifact = canonical_artifact()
    page = artifact.pages[0].model_copy(
        update={
            "blocks": (
                StructuredBlock(
                    block_id="conjoined-suocheng-definition",
                    kind="paragraph",
                    text=f"本合同所称{composite_term}，是指申请保险保障的人。",
                    bbox=bbox(40, 40, 572, 70),
                    reading_order=0,
                ),
            ),
            "tables": (),
        }
    )
    artifact = artifact.model_copy(update={"pages": (page,)})

    with pytest.raises(RuleUnitProjectionReviewRequired, match="conjunction markers"):
        project_rule_units(
            artifact,
            document_defaults=defaults(),
            source_id="source-1",
        )


def test_quoted_suocheng_composite_term_remains_exact() -> None:
    artifact = canonical_artifact()
    definition_text = "本合同所称“投保人及被保险人”是指申请或接受保险保障的人。"
    page = artifact.pages[0].model_copy(
        update={
            "blocks": (
                StructuredBlock(
                    block_id="quoted-composite-suocheng-definition",
                    kind="paragraph",
                    text=definition_text,
                    bbox=bbox(40, 40, 572, 70),
                    reading_order=0,
                ),
                StructuredBlock(
                    block_id="quoted-composite-suocheng-reference",
                    kind="list_item",
                    text="投保人及被保险人须共同签字。",
                    bbox=bbox(40, 80, 572, 110),
                    reading_order=1,
                ),
            ),
            "tables": (),
        }
    )
    artifact = artifact.model_copy(update={"pages": (page,)})

    reference = next(
        unit
        for unit in project_rule_units(
            artifact,
            document_defaults=defaults(),
            source_id="source-1",
        )
        if unit.block_ids == ("quoted-composite-suocheng-reference",)
    )

    assert reference.definitions == (definition_text,)


def test_ten_thousand_cells_stay_within_deterministic_work_bound() -> None:
    artifact = canonical_artifact()
    header = artifact.pages[1].tables[0].cells[:2]
    cells = header + tuple(
        StructuredTableCell(
            row=row,
            column=column,
            text=f"row-{row}" if column == 0 else "value",
            bbox=bbox(40 + column * 180, 130, 220 + column * 180, 170),
        )
        for row in range(1, 5_000)
        for column in range(2)
    )
    assert len(cells) == 10_000
    page = artifact.pages[1].model_copy(
        update={
            "blocks": (
                StructuredBlock(
                    block_id="heading-large-table",
                    kind="heading",
                    text="Large Table",
                    bbox=bbox(40, 40, 572, 70),
                    reading_order=0,
                    heading_level=1,
                    heading_path=("Large Table",),
                ),
            ),
            "tables": (artifact.pages[1].tables[0].model_copy(update={"cells": cells}),),
        }
    )
    artifact = artifact.model_copy(update={"pages": (page,)})
    limits = RuleUnitProjectionLimits(max_work_units=1_000_000)
    first_counter = RuleUnitProjectionWorkCounter(1_000_000)
    second_counter = RuleUnitProjectionWorkCounter(1_000_000)

    first = project_rule_units(
        artifact,
        document_defaults=defaults(),
        source_id="source-1",
        limits=limits,
        work_counter=first_counter,
    )
    second = project_rule_units(
        artifact,
        document_defaults=defaults(),
        source_id="source-1",
        limits=limits,
        work_counter=second_counter,
    )

    assert len(first) == 4_999
    assert first == second
    assert first_counter.used == second_counter.used
    assert first_counter.used < 1_000_000


def test_thousand_by_thousand_span_serializes_each_cell_once() -> None:
    artifact = canonical_artifact()
    payload = "x" * 2_000
    page = artifact.pages[1].model_copy(
        update={
            "blocks": (
                StructuredBlock(
                    block_id="heading-spanning-table",
                    kind="heading",
                    text="Spanning Table",
                    bbox=bbox(40, 40, 572, 70),
                    reading_order=0,
                    heading_level=1,
                    heading_path=("Spanning Table",),
                ),
            ),
            "tables": (
                StructuredTable(
                    table_id="table-thousand-span",
                    title="Large spans",
                    bbox=bbox(40, 90, 572, 280),
                    cells=(
                        StructuredTableCell(
                            row=0, column=0, text="Label", bbox=bbox(40, 90, 220, 130)
                        ),
                        StructuredTableCell(
                            row=0,
                            column=1_000,
                            text="Value",
                            bbox=bbox(220, 90, 400, 130),
                        ),
                        StructuredTableCell(
                            row=1,
                            column=0,
                            row_span=1_000,
                            column_span=1_000,
                            text=payload,
                            bbox=bbox(40, 130, 220, 170),
                        ),
                        StructuredTableCell(
                            row=1,
                            column=1_000,
                            row_span=1_000,
                            text="edge",
                            bbox=bbox(220, 130, 400, 170),
                        ),
                    ),
                ),
            ),
        }
    )
    artifact = artifact.model_copy(update={"pages": (page,)})
    first_counter = RuleUnitProjectionWorkCounter(100_000)
    second_counter = RuleUnitProjectionWorkCounter(100_000)
    limits = RuleUnitProjectionLimits(max_work_units=100_000)

    first = project_rule_units(
        artifact,
        document_defaults=defaults(),
        source_id="source-1",
        limits=limits,
        work_counter=first_counter,
    )
    second = project_rule_units(
        artifact,
        document_defaults=defaults(),
        source_id="source-1",
        limits=limits,
        work_counter=second_counter,
    )

    assert first == second
    assert len(first) == 1
    assert first[0].row_numbers == tuple(range(1, 1_001))
    assert first[0].content == f"{payload} | edge"
    assert first[0].content.count(payload) == 1
    assert first_counter.used == second_counter.used
    assert first_counter.used < 50_000


@pytest.mark.parametrize("limit_scope", ("unit", "document"))
def test_output_limits_require_review_without_returning_partial_units(
    limit_scope: str,
) -> None:
    artifact = canonical_artifact()
    first_text = "First bounded clause."
    second_text = "Second bounded clause."
    page = artifact.pages[0].model_copy(
        update={
            "blocks": (
                StructuredBlock(
                    block_id="first-bounded-clause",
                    kind="list_item",
                    text=first_text,
                    bbox=bbox(40, 40, 572, 70),
                    reading_order=0,
                ),
                StructuredBlock(
                    block_id="second-bounded-clause",
                    kind="list_item",
                    text=second_text,
                    bbox=bbox(40, 80, 572, 110),
                    reading_order=1,
                ),
            ),
            "tables": (),
        }
    )
    artifact = artifact.model_copy(update={"pages": (page,)})
    if limit_scope == "unit":
        limits = RuleUnitProjectionLimits(
            max_unit_output_characters=len(first_text) - 1,
            max_document_output_characters=100,
        )
        message = "rule-unit output"
    else:
        limits = RuleUnitProjectionLimits(
            max_unit_output_characters=100,
            max_document_output_characters=len(first_text) + len(second_text) - 1,
        )
        message = "document output"

    with pytest.raises(RuleUnitProjectionReviewRequired, match=message):
        project_rule_units(
            artifact,
            document_defaults=defaults(),
            source_id="source-1",
            limits=limits,
        )


@pytest.mark.parametrize(
    ("heading_text", "definition_text", "clause_text", "expected_definition"),
    (
        (
            "Definition",
            "Applicant means the person applying for cover.",
            "Applicants must be adults.",
            "Applicant means the person applying for cover.",
        ),
        (
            "Definitions",
            "Applicant means the person applying for cover.",
            "Applicants must be adults.",
            "Applicant means the person applying for cover.",
        ),
        (
            "释义",
            "投保人是指申请保险保障的人。",
            "投保人必须年满十八周岁。",
            "投保人是指申请保险保障的人。",
        ),
    ),
)
def test_definition_headings_are_context_while_body_statements_are_indexed(
    heading_text: str,
    definition_text: str,
    clause_text: str,
    expected_definition: str,
) -> None:
    artifact = canonical_artifact()
    page = artifact.pages[0].model_copy(
        update={
            "blocks": (
                StructuredBlock(
                    block_id="definition-context-heading",
                    kind="heading",
                    text=heading_text,
                    bbox=bbox(40, 40, 572, 70),
                    reading_order=0,
                    heading_level=1,
                    heading_path=(heading_text,),
                ),
                StructuredBlock(
                    block_id="definition-context-body",
                    kind="paragraph",
                    text=definition_text,
                    bbox=bbox(40, 80, 572, 110),
                    reading_order=1,
                    heading_path=(heading_text,),
                ),
                StructuredBlock(
                    block_id="definition-reference-heading",
                    kind="heading",
                    text="Eligibility",
                    bbox=bbox(40, 120, 572, 150),
                    reading_order=2,
                    heading_level=1,
                    heading_path=("Eligibility",),
                ),
                StructuredBlock(
                    block_id="definition-reference-clause",
                    kind="list_item",
                    text=clause_text,
                    bbox=bbox(40, 160, 572, 190),
                    reading_order=3,
                    heading_path=("Eligibility",),
                ),
            ),
            "tables": (),
        }
    )
    artifact = artifact.model_copy(update={"pages": (page,)})

    clause = next(
        unit
        for unit in project_rule_units(
            artifact,
            document_defaults=defaults(),
            source_id="source-1",
        )
        if unit.block_ids == ("definition-reference-clause",)
    )

    assert clause.definitions == (expected_definition,)
