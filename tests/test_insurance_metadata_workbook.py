from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from threading import Event, Thread
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
        f'<Relationship Id="rUnsafe" Type="urn:test" Target="{target_value}" />'
    ).encode()
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


def _fixture_with_evil_macro_content_type() -> bytes:
    output = BytesIO()
    declaration = b'<Default Extension="bin" ContentType="application/vnd.ms-office.vbaProject"/>'
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
    repository.resolve(
        source_id=first.items[0].source_id,
        review_id=first.items[0].review_id,
        expected_review_version=first.items[0].review_version,
        expected_review_identity=first.items[0].review_identity,
        action="approve",
        actor="reviewer",
        reason="Advance the index generation without changing its ordering.",
    )
    second = repository.list_page(base.source_id, limit=2, cursor=first.next_cursor)
    assert len(second.items) == 1
    assert second.next_cursor is None

    with pytest.raises(WorkbookValidationError):
        repository.list_page(base.source_id, limit=101)
    with pytest.raises(WorkbookValidationError):
        repository.list_page(base.source_id, cursor="not-a-valid-cursor")


def _review_with_sequence(
    base: workbook_module.InsuranceMetadataReview,
    sequence: int,
) -> workbook_module.InsuranceMetadataReview:
    candidate = base.model_copy(
        update={
            "review_id": f"metadata_review_scale_{sequence:05d}",
            "review_identity": "0" * 64,
            "workbook_row_number": sequence + 1,
        }
    )
    return candidate.model_copy(
        update={"review_identity": workbook_module._review_identity(candidate)}
    )


def test_review_page_parses_only_selected_files_for_ten_thousand_entry_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FilesystemInsuranceMetadataReviewRepository(tmp_path)
    base = _reconcile(
        tmp_path,
        _draft(origin="pdf", authority="national"),
        _draft(origin="workbook", authority="national"),
    )
    entries = []
    source_dir = repository._source_dir(base.source_id)
    source_dir.mkdir(parents=True)
    for sequence in range(10_000):
        review = _review_with_sequence(base, sequence)
        entries.append(workbook_module._review_index_entry(review))
        if sequence < 200:
            repository._review_path(base.source_id, review.review_id).write_text(
                review.model_dump_json()
            )
    ordered = tuple(entries)
    index = workbook_module._InsuranceMetadataReviewIndex(
        source_id=base.source_id,
        generation=1,
        entries=ordered,
        summary=workbook_module._review_summary_from_entries(ordered),
    )
    repository._write_payload(
        repository._review_index_path(base.source_id),
        index.model_dump(mode="json"),
    )
    parse_count = 0
    original_parse = workbook_module.InsuranceMetadataReview.model_validate_json

    def counted_parse(payload: bytes | str, *args: object, **kwargs: object):
        nonlocal parse_count
        parse_count += 1
        return original_parse(payload, *args, **kwargs)

    monkeypatch.setattr(
        workbook_module.InsuranceMetadataReview,
        "model_validate_json",
        staticmethod(counted_parse),
    )

    first = repository.list_page(base.source_id, limit=100)
    second = repository.list_page(base.source_id, limit=100, cursor=first.next_cursor)

    assert first.total == 10_000
    assert len(first.items) == len(second.items) == 100
    assert parse_count == 200


def test_failed_review_batch_rolls_back_files_and_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FilesystemInsuranceMetadataReviewRepository(tmp_path)
    base = _reconcile(
        tmp_path,
        _draft(origin="pdf", authority="national"),
        _draft(origin="workbook", authority="national"),
    )
    reviews = (_review_with_sequence(base, 1), _review_with_sequence(base, 2))
    original_write = repository._write
    write_count = 0

    def fail_second_write(review: workbook_module.InsuranceMetadataReview) -> None:
        nonlocal write_count
        write_count += 1
        if write_count == 2:
            raise OSError("simulated batch write failure")
        original_write(review)

    monkeypatch.setattr(repository, "_write", fail_second_write)
    with pytest.raises(OSError, match="simulated batch"):
        repository.put_many(reviews)

    page = FilesystemInsuranceMetadataReviewRepository(tmp_path).list_page(base.source_id)
    assert page.items == ()
    assert page.summary.total == 0


def test_malformed_derived_review_index_is_quarantined_and_rebuilt(tmp_path: Path) -> None:
    repository = FilesystemInsuranceMetadataReviewRepository(tmp_path)
    review = repository.put(
        _reconcile(
            tmp_path,
            _draft(origin="pdf", authority="national"),
            _draft(origin="workbook", authority="national"),
        )
    )
    index_path = repository._review_index_path(review.source_id)
    index_path.write_bytes(b'{"schema_version":"partial-index"')

    page = FilesystemInsuranceMetadataReviewRepository(tmp_path).list_page(review.source_id)

    assert page.items == (review,)
    assert page.summary.total == 1
    assert tuple(index_path.parent.glob(f"{index_path.name}.invalid-*"))


def test_pending_review_batch_is_redone_after_rollback_itself_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FilesystemInsuranceMetadataReviewRepository(tmp_path)
    base = _reconcile(
        tmp_path,
        _draft(origin="pdf", authority="national"),
        _draft(origin="workbook", authority="national"),
    )
    reviews = (_review_with_sequence(base, 11), _review_with_sequence(base, 12))
    original_write = repository._write
    write_count = 0

    def fail_second_write_once(review: workbook_module.InsuranceMetadataReview) -> None:
        nonlocal write_count
        write_count += 1
        if write_count == 2:
            raise OSError("simulated process interruption")
        original_write(review)

    monkeypatch.setattr(repository, "_write", fail_second_write_once)
    monkeypatch.setattr(
        repository,
        "_rollback_review_transaction_unlocked",
        lambda _transaction: (_ for _ in ()).throw(OSError("rollback interrupted")),
    )
    with pytest.raises(OSError, match="process interruption"):
        repository.put_many(reviews)

    recovered = FilesystemInsuranceMetadataReviewRepository(tmp_path).list_page(base.source_id)
    assert {review.review_id for review in recovered.items} == {
        review.review_id for review in reviews
    }
    assert recovered.summary.total == 2


def test_cross_instance_reader_never_observes_partial_review_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = FilesystemInsuranceMetadataReviewRepository(tmp_path)
    reader = FilesystemInsuranceMetadataReviewRepository(tmp_path)
    base = _reconcile(
        tmp_path,
        _draft(origin="pdf", authority="national"),
        _draft(origin="workbook", authority="national"),
    )
    reviews = (_review_with_sequence(base, 21), _review_with_sequence(base, 22))
    first_file_written = Event()
    release_writer = Event()
    reader_finished = Event()
    original_write = writer._write
    write_count = 0
    observed: list[workbook_module.InsuranceMetadataReviewPage] = []

    def paused_write(review: workbook_module.InsuranceMetadataReview) -> None:
        nonlocal write_count
        original_write(review)
        write_count += 1
        if write_count == 1:
            first_file_written.set()
            assert release_writer.wait(timeout=5)

    monkeypatch.setattr(writer, "_write", paused_write)
    writer_thread = Thread(target=lambda: writer.put_many(reviews))
    reader_thread = Thread(
        target=lambda: (
            observed.append(reader.list_page(base.source_id)),
            reader_finished.set(),
        )
    )
    writer_thread.start()
    assert first_file_written.wait(timeout=5)
    reader_thread.start()
    assert not reader_finished.wait(timeout=0.1)
    release_writer.set()
    writer_thread.join(timeout=5)
    reader_thread.join(timeout=5)

    assert not writer_thread.is_alive()
    assert not reader_thread.is_alive()
    assert len(observed) == 1
    assert {review.review_id for review in observed[0].items} == {
        review.review_id for review in reviews
    }


@pytest.mark.parametrize(
    "failure_phase",
    ["journal_before", "journal_after", "review", "index", "decision", "finalize"],
)
def test_review_decision_transaction_rolls_back_every_write_phase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_phase: str,
) -> None:
    repository = FilesystemInsuranceMetadataReviewRepository(tmp_path)
    review = repository.put(
        _reconcile(
            tmp_path,
            _draft(origin="pdf", authority="national"),
            _draft(origin="workbook", authority="national"),
        )
    )
    original_write_payload = repository._write_payload
    original_finalize = repository._finalize_review_transaction_unlocked
    failed = False

    def fail_phase(path: Path, value: object) -> None:
        nonlocal failed
        is_target = {
            "journal_before": path == repository._review_index_pending_path(review.source_id),
            "journal_after": path == repository._review_index_pending_path(review.source_id),
            "review": path == repository._review_path(review.source_id, review.review_id),
            "index": path == repository._review_index_path(review.source_id),
            "decision": repository._decisions_root in path.parents,
            "finalize": False,
        }[failure_phase]
        if is_target and not failed:
            failed = True
            if failure_phase == "journal_after":
                original_write_payload(path, value)
            raise OSError(f"simulated {failure_phase} write failure")
        original_write_payload(path, value)

    def fail_finalize_once(path: Path) -> None:
        nonlocal failed
        if failure_phase == "finalize" and not failed:
            failed = True
            raise OSError("simulated finalize write failure")
        original_finalize(path)

    monkeypatch.setattr(repository, "_write_payload", fail_phase)
    monkeypatch.setattr(
        repository,
        "_finalize_review_transaction_unlocked",
        fail_finalize_once,
    )
    with pytest.raises(OSError, match=failure_phase):
        repository.resolve(
            source_id=review.source_id,
            review_id=review.review_id,
            expected_review_version=review.review_version,
            expected_review_identity=review.review_identity,
            action="approve",
            actor="reviewer",
            reason="This approval is fault injected.",
        )
    monkeypatch.setattr(repository, "_write_payload", original_write_payload)
    monkeypatch.setattr(
        repository,
        "_finalize_review_transaction_unlocked",
        original_finalize,
    )

    assert repository.get(review.source_id, review.review_id) == review
    assert tuple(repository._decisions_root.rglob("*.json")) == ()
    rejected = repository.resolve(
        source_id=review.source_id,
        review_id=review.review_id,
        expected_review_version=review.review_version,
        expected_review_identity=review.review_identity,
        action="reject",
        actor="reviewer",
        reason="Alternative decision after rolled-back approval.",
    )
    assert rejected.state == "rejected"
    assert len(tuple(repository._decisions_root.rglob("*.json"))) == 1


def test_interrupted_decision_rollback_is_redone_before_next_reader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FilesystemInsuranceMetadataReviewRepository(tmp_path)
    review = repository.put(
        _reconcile(
            tmp_path,
            _draft(origin="pdf", authority="national"),
            _draft(origin="workbook", authority="national"),
        )
    )
    original_write_payload = repository._write_payload
    failed = False

    def fail_decision_once(path: Path, value: object) -> None:
        nonlocal failed
        if repository._decisions_root in path.parents and not failed:
            failed = True
            raise OSError("simulated decision interruption")
        original_write_payload(path, value)

    monkeypatch.setattr(repository, "_write_payload", fail_decision_once)
    monkeypatch.setattr(
        repository,
        "_rollback_review_transaction_unlocked",
        lambda _transaction: (_ for _ in ()).throw(OSError("rollback interrupted")),
    )
    with pytest.raises(OSError, match="decision interruption"):
        repository.resolve(
            source_id=review.source_id,
            review_id=review.review_id,
            expected_review_version=review.review_version,
            expected_review_identity=review.review_identity,
            action="approve",
            actor="reviewer",
            reason="Approval must be completed by redo recovery.",
        )

    recovered_repository = FilesystemInsuranceMetadataReviewRepository(tmp_path)
    recovered = recovered_repository.get(review.source_id, review.review_id)
    replayed = recovered_repository.get(review.source_id, review.review_id)

    assert recovered is not None and recovered.state == "approved"
    assert replayed == recovered
    decision_files = tuple(recovered_repository._decisions_root.rglob("*.json"))
    assert len(decision_files) == 1
    decision = workbook_module.InsuranceMetadataReviewDecision.model_validate_json(
        decision_files[0].read_bytes()
    )
    assert decision.action == "approve"
