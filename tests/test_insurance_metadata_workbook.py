from __future__ import annotations

from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

import proof_agent.capabilities.knowledge.hybrid.workbook as workbook_module
from proof_agent.capabilities.knowledge.hybrid.workbook import (
    FilesystemInsuranceMetadataReviewRepository,
    InsuranceMetadataDraftInput,
    WorkbookKnownAnchor,
    WorkbookValidationError,
    import_metadata_workbook,
    reconcile_metadata_drafts,
)
from proof_agent.configuration.hybrid_knowledge_repository import (
    FileSystemKnowledgeArtifactStore,
)


FIXTURE = Path("tests/fixtures/knowledge/hybrid/metadata-workbook.xlsx")


def _known_anchor() -> WorkbookKnownAnchor:
    return WorkbookKnownAnchor(
        source_id="ks_hybrid_index",
        document_id="doc_policy_terms",
        revision_id="rev_2026_01",
        canonical_anchor="section:eligibility",
    )


def _formula_authority_fixture() -> bytes:
    output = BytesIO()
    with ZipFile(FIXTURE) as source, ZipFile(output, "w", ZIP_DEFLATED) as target:
        for member in source.infolist():
            payload = source.read(member.filename)
            if member.filename == "xl/worksheets/sheet1.xml":
                payload = payload.replace(
                    b'<x:c r="F6" s="29" t="str"><x:v>national</x:v></x:c>',
                    b'<x:c r="F6" s="29"><x:f>1+1</x:f><x:v>2</x:v></x:c>',
                )
            target.writestr(member, payload)
    return output.getvalue()


def _fixture_with_external_relationship() -> bytes:
    output = BytesIO()
    relationship = (
        b'<Relationship Id="rExternal" Type="urn:test" '
        b'Target = " https://external.example/workbook.xlsx " '
        b'TargetMode = " External " />'
    )
    with ZipFile(FIXTURE) as source, ZipFile(output, "w", ZIP_DEFLATED) as target:
        for member in source.infolist():
            payload = source.read(member.filename)
            if member.filename == "xl/_rels/workbook.xml.rels":
                payload = payload.replace(b"</Relationships>", relationship + b"</Relationships>")
            target.writestr(member, payload)
    return output.getvalue()


def _fixture_with_far_cell() -> bytes:
    output = BytesIO()
    far_row = b'<x:row r="1048576"><x:c r="XFD1048576" t="str"><x:v>hidden</x:v></x:c></x:row>'
    with ZipFile(FIXTURE) as source, ZipFile(output, "w", ZIP_DEFLATED) as target:
        for member in source.infolist():
            payload = source.read(member.filename)
            if member.filename == "xl/worksheets/sheet1.xml":
                payload = payload.replace(b"</x:sheetData>", far_row + b"</x:sheetData>")
            target.writestr(member, payload)
    return output.getvalue()


def test_imports_versioned_literal_workbook_as_non_authoritative_draft(
    tmp_path: Path,
) -> None:
    with FileSystemKnowledgeArtifactStore(tmp_path / "artifacts") as artifact_store:
        result = import_metadata_workbook(
            FIXTURE,
            known_anchors=(_known_anchor(),),
            artifact_store=artifact_store,
        )
        assert artifact_store.get_exact(result.original_ref) == FIXTURE.read_bytes()
        assert b'"schema_version":"insurance-metadata-workbook-normalized.v1"' in (
            artifact_store.get_exact(result.normalized_ref)
        )

    assert result.template_revision == "insurance-rule-metadata.v1"
    assert result.original_ref.sha256 == result.original_sha256
    assert result.original_ref.media_type == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert result.normalized_ref.media_type == "application/json"
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.source_id == "ks_hybrid_index"
    assert row.canonical_anchor == "section:eligibility"
    assert row.metadata.authoritative is False
    assert row.metadata.authority == "national"
    assert row.metadata.effective_from.isoformat() == "2026-01-01"


def test_workbook_rejects_formula_authority_cells() -> None:
    with pytest.raises(WorkbookValidationError, match="literal cells"):
        import_metadata_workbook(
            _formula_authority_fixture(),
            known_anchors=(_known_anchor(),),
        )


def test_workbook_rejects_unknown_exact_anchor() -> None:
    with pytest.raises(WorkbookValidationError, match="exact Source/document/revision/anchor"):
        import_metadata_workbook(
            FIXTURE,
            known_anchors=(
                _known_anchor().model_copy(update={"canonical_anchor": "section:other"}),
            ),
        )


def test_workbook_dependency_is_loaded_only_when_import_is_invoked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def blocked_import(name: str) -> object:
        if name == "openpyxl":
            raise ModuleNotFoundError("simulated optional dependency absence")
        raise AssertionError(name)

    monkeypatch.setattr(workbook_module, "import_module", blocked_import)
    with FileSystemKnowledgeArtifactStore(tmp_path / "artifacts") as artifact_store:
        with pytest.raises(WorkbookValidationError, match="hybrid extra"):
            import_metadata_workbook(
                FIXTURE,
                known_anchors=(_known_anchor(),),
                artifact_store=artifact_store,
            )


def test_workbook_rejects_structural_external_relationships_with_spaced_attributes() -> None:
    with pytest.raises(WorkbookValidationError, match="external links"):
        import_metadata_workbook(
            _fixture_with_external_relationship(),
            known_anchors=(_known_anchor(),),
        )


def test_workbook_rejects_nonempty_cells_beyond_template_bounds() -> None:
    with pytest.raises(WorkbookValidationError, match="template bounds"):
        import_metadata_workbook(
            _fixture_with_far_cell(),
            known_anchors=(_known_anchor(),),
        )


def _draft(*, origin: str, authority: str) -> InsuranceMetadataDraftInput:
    return InsuranceMetadataDraftInput(
        origin=origin,
        source_id="ks_hybrid_index",
        document_id="doc_policy_terms",
        revision_id="rev_2026_01",
        canonical_anchor="section:eligibility",
        authority=authority,
        effective_from="2026-01-01",
        effective_to="2026-12-31",
        taxonomy_id="insurance-product-applicability",
        taxonomy_revision_id="taxonomy-2026-01",
        precedence_policy_revision_id="precedence-2026-01",
        precedence_authority_tier="policy_terms",
        precedence_order=10,
    )


def test_pdf_and_workbook_disagreement_blocks_readiness() -> None:
    result = reconcile_metadata_drafts(
        _draft(origin="pdf", authority="national"),
        _draft(origin="workbook", authority="regional"),
    )

    assert result.state == "review_required"
    assert result.publication_blocked is True
    assert result.conflicts[0].field == "authority"
    assert result.conflicts[0].pdf_value == "national"
    assert result.conflicts[0].workbook_value == "regional"


def test_matching_drafts_are_ready_but_not_approved_or_publishable() -> None:
    result = reconcile_metadata_drafts(
        _draft(origin="pdf", authority="national"),
        _draft(origin="workbook", authority="national"),
    )

    assert result.state == "ready_for_review"
    assert result.publication_blocked is True
    assert result.conflicts == ()


@pytest.mark.parametrize(
    "corrections",
    [
        {"authority": "x" * 5_000_000},
        {"effective_from": "not-a-date"},
        {"effective_from": "2027-01-01", "effective_to": "2026-01-01"},
    ],
)
def test_review_corrections_reject_unsafe_or_invalid_metadata(
    tmp_path: Path,
    corrections: dict[str, str],
) -> None:
    repository = FilesystemInsuranceMetadataReviewRepository(tmp_path)
    review = repository.put(
        reconcile_metadata_drafts(
            _draft(origin="pdf", authority="national"),
            _draft(origin="workbook", authority="regional"),
        )
    )

    with pytest.raises(WorkbookValidationError):
        repository.resolve(
            source_id=review.source_id,
            review_id=review.review_id,
            expected_review_version=review.review_version,
            expected_review_identity=review.review_identity,
            action="correct",
            actor="reviewer",
            reason="Invalid proposal must fail closed.",
            corrections=corrections,
        )

    assert repository.get(review.source_id, review.review_id) == review
