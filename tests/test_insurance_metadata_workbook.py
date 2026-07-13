from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

import proof_agent.capabilities.knowledge.hybrid.workbook as workbook_module
from proof_agent.capabilities.knowledge.hybrid.workbook import (
    FilesystemInsuranceMetadataReviewRepository,
    InsuranceMetadataDraftInput,
    WorkbookImportRecord,
    WorkbookImportRowIdentity,
    WorkbookKnownAnchor,
    WorkbookReviewConflictError,
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


def _fixture_with_member_name(member_name: str) -> bytes:
    output = BytesIO()
    with ZipFile(FIXTURE) as source, ZipFile(output, "w", ZIP_DEFLATED) as target:
        for member in source.infolist():
            target.writestr(member, source.read(member.filename))
        target.writestr(member_name, b"unsafe")
    return output.getvalue()


def _fixture_with_relationship_target(target_value: str) -> bytes:
    output = BytesIO()
    relationship = (
        '<Relationship Id="rUnsafe" Type="urn:test" '
        f'Target="{target_value}" />'
    ).encode()
    with ZipFile(FIXTURE) as source, ZipFile(output, "w", ZIP_DEFLATED) as target:
        for member in source.infolist():
            payload = source.read(member.filename)
            if member.filename == "xl/_rels/workbook.xml.rels":
                payload = payload.replace(
                    b"</Relationships>", relationship + b"</Relationships>"
                )
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


def _fixture_with_evil_macro_content_type() -> bytes:
    output = BytesIO()
    declaration = (
        b'<Default Extension="bin" '
        b'ContentType="application/vnd.ms-office.vbaProject"/>'
    )
    with ZipFile(FIXTURE) as source, ZipFile(output, "w", ZIP_DEFLATED) as target:
        for member in source.infolist():
            payload = source.read(member.filename)
            if member.filename == "[Content_Types].xml":
                payload = payload.replace(b"</Types>", declaration + b"</Types>")
            target.writestr(member, payload)
        target.writestr("xl/evil.bin", b"not executable but declared as VBA")
    return output.getvalue()


def _fixture_with_row_10007() -> bytes:
    output = BytesIO()
    row = b'<x:row r="10007"><x:c r="A10007" t="str"><x:v>hidden</x:v></x:c></x:row>'
    with ZipFile(FIXTURE) as source, ZipFile(output, "w", ZIP_DEFLATED) as target:
        for member in source.infolist():
            payload = source.read(member.filename)
            if member.filename == "xl/worksheets/sheet1.xml":
                payload = payload.replace(b"</x:sheetData>", row + b"</x:sheetData>")
            target.writestr(member, payload)
    return output.getvalue()


def _fixture_with_string_date(value: str) -> bytes:
    output = BytesIO()
    replacement = f'<x:c r="G6" s="31" t="str"><x:v>{value}</x:v></x:c>'.encode()
    with ZipFile(FIXTURE) as source, ZipFile(output, "w", ZIP_DEFLATED) as target:
        for member in source.infolist():
            payload = source.read(member.filename)
            if member.filename == "xl/worksheets/sheet1.xml":
                payload = payload.replace(
                    b'<x:c r="G6" s="31" t="n"><x:v>46023</x:v></x:c>',
                    replacement,
                )
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


@pytest.mark.parametrize(
    "member_name",
    [r"xl\evil.xml", "/absolute.xml", "C:/evil.xml", "//server/share.xml"],
)
def test_workbook_rejects_cross_platform_unsafe_member_paths(member_name: str) -> None:
    with pytest.raises(WorkbookValidationError, match="unsafe path"):
        import_metadata_workbook(
            _fixture_with_member_name(member_name),
            known_anchors=(_known_anchor(),),
        )


@pytest.mark.parametrize(
    "target_value",
    [r"..\evil.xml", r"C:\evil.xml", r"\\server\share.xml", "../../evil.xml", "/missing.xml"],
)
def test_workbook_rejects_relationship_targets_outside_exact_package(
    target_value: str,
) -> None:
    with pytest.raises(WorkbookValidationError, match="external|escapes|contained"):
        import_metadata_workbook(
            _fixture_with_relationship_target(target_value),
            known_anchors=(_known_anchor(),),
        )


def test_workbook_rejects_nonempty_cells_beyond_template_bounds() -> None:
    with pytest.raises(WorkbookValidationError, match="template bounds"):
        import_metadata_workbook(
            _fixture_with_far_cell(),
            known_anchors=(_known_anchor(),),
        )


def test_workbook_rejects_macro_content_type_with_arbitrary_filename() -> None:
    with pytest.raises(WorkbookValidationError, match="executable or embedded"):
        import_metadata_workbook(
            _fixture_with_evil_macro_content_type(),
            known_anchors=(_known_anchor(),),
        )


def test_workbook_bounds_are_relative_to_the_discovered_header() -> None:
    with pytest.raises(WorkbookValidationError, match="template bounds"):
        import_metadata_workbook(
            _fixture_with_row_10007(),
            known_anchors=(_known_anchor(),),
        )


@pytest.mark.parametrize("value", ["20260101", "2026-W01-1"])
def test_workbook_string_dates_require_exact_calendar_format(value: str) -> None:
    with pytest.raises(WorkbookValidationError, match="YYYY-MM-DD"):
        import_metadata_workbook(
            _fixture_with_string_date(value),
            known_anchors=(_known_anchor(),),
        )


def _draft(*, origin: str, authority: str) -> InsuranceMetadataDraftInput:
    return InsuranceMetadataDraftInput(
        metadata_draft_id=f"{origin}-metadata-draft",
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


def _reconcile(
    tmp_path: Path,
    pdf_draft: InsuranceMetadataDraftInput,
    workbook_draft: InsuranceMetadataDraftInput,
):
    with FileSystemKnowledgeArtifactStore(tmp_path / "lineage-artifacts") as artifact_store:
        imported = import_metadata_workbook(
            FIXTURE,
            known_anchors=(_known_anchor(),),
            artifact_store=artifact_store,
        )
    row = imported.rows[0]
    record = WorkbookImportRecord(
        import_id=imported.import_id,
        template_revision=imported.template_revision,
        source_id=row.source_id,
        document_id=row.document_id,
        revision_id=row.revision_id,
        created_by="reviewer",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        original_ref=imported.original_ref,
        normalized_ref=imported.normalized_ref,
        rows=(
            WorkbookImportRowIdentity(
                row_number=row.row_number,
                source_id=row.source_id,
                document_id=row.document_id,
                revision_id=row.revision_id,
                canonical_anchor=row.canonical_anchor,
                metadata_draft_id=row.metadata.metadata_draft_id,
            ),
        ),
    )
    return reconcile_metadata_drafts(
        pdf_draft,
        workbook_draft,
        import_record=record,
        row=row,
    )


def test_pdf_and_workbook_disagreement_blocks_readiness(tmp_path: Path) -> None:
    result = _reconcile(
        tmp_path,
        _draft(origin="pdf", authority="national"),
        _draft(origin="workbook", authority="regional"),
    )

    assert result.state == "review_required"
    assert result.publication_blocked is True
    assert result.conflicts[0].field == "authority"
    assert result.conflicts[0].pdf_value == "national"
    assert result.conflicts[0].workbook_value == "regional"


def test_matching_drafts_are_ready_but_not_approved_or_publishable(tmp_path: Path) -> None:
    result = _reconcile(
        tmp_path,
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
        {"authority": None},
        {"taxonomy_id": None},
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
        _reconcile(
            tmp_path,
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


def test_approval_constructs_strict_governed_metadata_revision(tmp_path: Path) -> None:
    repository = FilesystemInsuranceMetadataReviewRepository(tmp_path)
    review = repository.put(
        _reconcile(
            tmp_path,
            _draft(origin="pdf", authority="national"),
            _draft(origin="workbook", authority="national"),
        )
    )

    approved = repository.resolve(
        source_id=review.source_id,
        review_id=review.review_id,
        expected_review_version=review.review_version,
        expected_review_identity=review.review_identity,
        action="approve",
        actor="reviewer",
        reason="Verified against the exact signed revision.",
    )

    assert approved.state == "approved"
    assert approved.publication_blocked is False
    assert approved.approved_metadata_revision_id is not None
    assert approved.approved_metadata_revision_id.startswith("approved_metadata_")


def test_approval_fails_closed_when_required_metadata_is_absent(tmp_path: Path) -> None:
    repository = FilesystemInsuranceMetadataReviewRepository(tmp_path)
    missing_pdf = _draft(origin="pdf", authority="national").model_copy(
        update={"taxonomy_id": None}
    )
    missing_workbook = _draft(origin="workbook", authority="national").model_copy(
        update={"taxonomy_id": None}
    )
    review = repository.put(_reconcile(tmp_path, missing_pdf, missing_workbook))
    assert review.state == "ready_for_review"

    with pytest.raises(WorkbookReviewConflictError, match="required insurance rule metadata"):
        repository.resolve(
            source_id=review.source_id,
            review_id=review.review_id,
            expected_review_version=review.review_version,
            expected_review_identity=review.review_identity,
            action="approve",
            actor="reviewer",
            reason="This incomplete proposal must remain blocked.",
        )

    assert repository.get(review.source_id, review.review_id) == review


@pytest.mark.parametrize("terminal_action", ["approve", "correct", "reject"])
def test_approved_review_is_immutable_without_revocation(
    tmp_path: Path,
    terminal_action: str,
) -> None:
    repository = FilesystemInsuranceMetadataReviewRepository(tmp_path)
    review = repository.put(
        _reconcile(
            tmp_path,
            _draft(origin="pdf", authority="national"),
            _draft(origin="workbook", authority="national"),
        )
    )
    approved = repository.resolve(
        source_id=review.source_id,
        review_id=review.review_id,
        expected_review_version=review.review_version,
        expected_review_identity=review.review_identity,
        action="approve",
        actor="reviewer",
        reason="Final approval.",
    )

    with pytest.raises(WorkbookReviewConflictError, match="terminal"):
        repository.resolve(
            source_id=approved.source_id,
            review_id=approved.review_id,
            expected_review_version=approved.review_version,
            expected_review_identity=approved.review_identity,
            action=terminal_action,  # type: ignore[arg-type]
            actor="reviewer",
            reason="Attempted terminal mutation.",
            corrections={"authority": "regional"} if terminal_action == "correct" else None,
        )

    assert repository.get(approved.source_id, approved.review_id) == approved


@pytest.mark.parametrize("terminal_action", ["approve", "correct", "reject"])
def test_rejected_review_is_immutable_without_revocation(
    tmp_path: Path,
    terminal_action: str,
) -> None:
    repository = FilesystemInsuranceMetadataReviewRepository(tmp_path)
    review = repository.put(
        _reconcile(
            tmp_path,
            _draft(origin="pdf", authority="national"),
            _draft(origin="workbook", authority="regional"),
        )
    )
    rejected = repository.resolve(
        source_id=review.source_id,
        review_id=review.review_id,
        expected_review_version=review.review_version,
        expected_review_identity=review.review_identity,
        action="reject",
        actor="reviewer",
        reason="Rejected as unsupported.",
    )

    with pytest.raises(WorkbookReviewConflictError, match="terminal"):
        repository.resolve(
            source_id=rejected.source_id,
            review_id=rejected.review_id,
            expected_review_version=rejected.review_version,
            expected_review_identity=rejected.review_identity,
            action=terminal_action,  # type: ignore[arg-type]
            actor="reviewer",
            reason="Attempted terminal mutation.",
            corrections={"authority": "national"} if terminal_action == "correct" else None,
        )

    assert repository.get(rejected.source_id, rejected.review_id) == rejected


def test_review_pages_are_bounded_and_include_global_server_summary(tmp_path: Path) -> None:
    repository = FilesystemInsuranceMetadataReviewRepository(tmp_path)
    base = _reconcile(
        tmp_path,
        _draft(origin="pdf", authority="national"),
        _draft(origin="workbook", authority="national"),
    )
    reviews = []
    for index in range(3):
        candidate = base.model_copy(
            update={
                "review_id": f"metadata_review_page_{index}",
                "review_identity": "0" * 64,
                "workbook_row_number": index + 1,
            }
        )
        reviews.append(
            candidate.model_copy(
                update={"review_identity": workbook_module._review_identity(candidate)}
            )
        )
    repository.put_many(reviews)

    first = repository.list_page(base.source_id, limit=2)
    assert len(first.items) == 2
    assert first.next_cursor is not None
    assert first.total == 3
    assert first.summary.total == 3
    assert first.summary.ready_for_review == 3
    assert first.summary.all_approved is False
    second = repository.list_page(base.source_id, limit=2, cursor=first.next_cursor)
    assert len(second.items) == 1
    assert second.next_cursor is None

    with pytest.raises(WorkbookValidationError):
        repository.list_page(base.source_id, limit=101)
    with pytest.raises(WorkbookValidationError):
        repository.list_page(base.source_id, cursor="not-a-valid-cursor")
