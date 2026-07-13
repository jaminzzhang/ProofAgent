"""Versioned insurance metadata workbook intake and human-review contracts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime
import hashlib
from importlib import import_module
from io import BytesIO
import json
import os
from pathlib import Path
import re
from threading import RLock
from typing import Annotated, Any, Literal, Protocol
from urllib.parse import urlsplit
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from filelock import FileLock
from pydantic import (
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    ValidationError,
    model_validator,
)

from proof_agent.capabilities.knowledge.hybrid.ports import KnowledgeArtifactStore
from proof_agent.contracts._base import FrozenModel
from proof_agent.contracts.insurance_rules import (
    InsuranceRuleApplicability,
    InsuranceRuleMetadataDraft,
    InsuranceRulePrecedence,
)
from proof_agent.contracts.knowledge_index import ExactArtifactRef


NonBlankStr = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1)]
GovernedMetadataStr = Annotated[
    StrictStr,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4_096),
]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
Sha256 = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

TEMPLATE_REVISION: Literal["insurance-rule-metadata.v1"] = "insurance-rule-metadata.v1"
WORKBOOK_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
NORMALIZED_MEDIA_TYPE = "application/json"
_SHEET_NAME = "Metadata"
_HEADERS = (
    "template_revision",
    "source_id",
    "document_id",
    "revision_id",
    "canonical_anchor",
    "authority",
    "effective_from",
    "effective_to",
    "taxonomy_id",
    "taxonomy_revision_id",
    "precedence_policy_revision_id",
    "precedence_authority_tier",
    "precedence_order",
)
_AUTHORITY_FIELDS = frozenset(_HEADERS)
_FORMULA_PREFIXES = ("=", "+", "-", "@")
_EXTERNAL_LINK_MARKERS = ("xl/externalLinks/", "externalLink")
_MACRO_MARKERS = ("vbaProject.bin", "xl/macrosheets/", "xl/dialogsheets/")
_DANGEROUS_OFFICE_MARKERS = ("vba", "macroenabled", "activex", "oleobject", "ole/object")
_CONFLICT_FIELDS = (
    "authority",
    "effective_from",
    "effective_to",
    "taxonomy_id",
    "taxonomy_revision_id",
    "precedence_policy_revision_id",
    "precedence_authority_tier",
    "precedence_order",
)
_CELL_REFERENCE = re.compile(r"^([A-Z]{1,3})([1-9][0-9]*)$", re.IGNORECASE)


class _WorkbookModel(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class WorkbookValidationError(ValueError):
    """Workbook content cannot cross the controlled curation boundary."""


class WorkbookReviewConflictError(RuntimeError):
    """A review command did not match the exact optimistic review identity."""


class WorkbookImportLimits(_WorkbookModel):
    max_file_bytes: PositiveInt = 10 * 1024 * 1024
    max_rows: PositiveInt = 10_000
    max_columns: PositiveInt = len(_HEADERS)
    max_cell_characters: PositiveInt = 4_096
    max_normalized_bytes: PositiveInt = 32 * 1024 * 1024


DEFAULT_WORKBOOK_IMPORT_LIMITS = WorkbookImportLimits()


class WorkbookKnownAnchor(_WorkbookModel):
    source_id: NonBlankStr
    document_id: NonBlankStr
    revision_id: NonBlankStr
    canonical_anchor: NonBlankStr | None = None


class WorkbookMetadataRow(_WorkbookModel):
    row_number: PositiveInt
    source_id: NonBlankStr
    document_id: NonBlankStr
    revision_id: NonBlankStr
    canonical_anchor: NonBlankStr | None = None
    metadata: InsuranceRuleMetadataDraft


class InsuranceMetadataWorkbookImport(_WorkbookModel):
    schema_version: Literal["insurance-metadata-workbook-import.v1"] = (
        "insurance-metadata-workbook-import.v1"
    )
    import_id: NonBlankStr
    template_revision: Literal["insurance-rule-metadata.v1"]
    original_sha256: Sha256
    original_ref: ExactArtifactRef
    normalized_ref: ExactArtifactRef
    rows: tuple[WorkbookMetadataRow, ...] = Field(min_length=1)
    authoritative: StrictBool = False


class WorkbookImportRowIdentity(_WorkbookModel):
    row_number: PositiveInt
    source_id: NonBlankStr
    document_id: NonBlankStr
    revision_id: NonBlankStr
    canonical_anchor: NonBlankStr | None = None
    metadata_draft_id: NonBlankStr


class WorkbookImportRecord(_WorkbookModel):
    schema_version: Literal["insurance-metadata-workbook-import-record.v1"] = (
        "insurance-metadata-workbook-import-record.v1"
    )
    import_id: NonBlankStr
    template_revision: Literal["insurance-rule-metadata.v1"]
    source_id: NonBlankStr
    document_id: NonBlankStr
    revision_id: NonBlankStr
    original_ref: ExactArtifactRef
    normalized_ref: ExactArtifactRef
    rows: tuple[WorkbookImportRowIdentity, ...] = Field(min_length=1)


class InsuranceMetadataDraftInput(_WorkbookModel):
    """One parallel, non-authoritative PDF or workbook metadata proposal."""

    origin: Literal["pdf", "workbook"]
    source_id: NonBlankStr
    document_id: NonBlankStr
    revision_id: NonBlankStr
    canonical_anchor: NonBlankStr | None = None
    authority: GovernedMetadataStr | None = None
    effective_from: date | None = Field(default=None, strict=False)
    effective_to: date | None = Field(default=None, strict=False)
    taxonomy_id: GovernedMetadataStr | None = None
    taxonomy_revision_id: GovernedMetadataStr | None = None
    precedence_policy_revision_id: GovernedMetadataStr | None = None
    precedence_authority_tier: GovernedMetadataStr | None = None
    precedence_order: NonNegativeInt | None = None

    @model_validator(mode="after")
    def validate_governed_metadata(self) -> "InsuranceMetadataDraftInput":
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_to < self.effective_from
        ):
            raise ValueError("effective_to must be on or after effective_from")
        for field in (
            self.authority,
            self.taxonomy_id,
            self.taxonomy_revision_id,
            self.precedence_policy_revision_id,
            self.precedence_authority_tier,
        ):
            if field is not None and any(ord(character) < 32 for character in field):
                raise ValueError("governed metadata strings must not contain control characters")
        return self


class InsuranceMetadataAuthorityRecord(_WorkbookModel):
    """Server-authored canonical Rule Unit lineage."""

    schema_version: Literal["insurance-metadata-authority-record.v1"] = (
        "insurance-metadata-authority-record.v1"
    )
    source_id: NonBlankStr
    document_id: NonBlankStr
    revision_id: NonBlankStr
    canonical_anchor: NonBlankStr | None = None
    structured_build_id: NonBlankStr
    rule_unit_draft_id: NonBlankStr
    citation_uri: NonBlankStr


class InsuranceMetadataPdfDraftRecord(_WorkbookModel):
    """Persisted server-derived PDF metadata proposal for one canonical anchor."""

    schema_version: Literal["insurance-metadata-pdf-draft-record.v1"] = (
        "insurance-metadata-pdf-draft-record.v1"
    )
    source_id: NonBlankStr
    document_id: NonBlankStr
    revision_id: NonBlankStr
    canonical_anchor: NonBlankStr | None = None
    structured_build_id: NonBlankStr
    pdf_draft: InsuranceMetadataDraftInput

    @model_validator(mode="after")
    def validate_pdf_lineage(self) -> "InsuranceMetadataPdfDraftRecord":
        if (
            self.pdf_draft.origin != "pdf"
            or _draft_identity(self.pdf_draft)
            != (self.source_id, self.document_id, self.revision_id, self.canonical_anchor)
        ):
            raise ValueError("persisted PDF draft must match the exact authority lineage")
        return self


class InsuranceMetadataConflict(_WorkbookModel):
    field: NonBlankStr
    label: NonBlankStr
    pdf_value: StrictStr | StrictInt | date | None = None
    workbook_value: StrictStr | StrictInt | date | None = None


class InsuranceMetadataReviewDecision(_WorkbookModel):
    sequence: PositiveInt
    prior_review_identity: Sha256
    prior_state: Literal[
        "review_required", "ready_for_review", "approved", "corrected", "rejected"
    ]
    action: Literal["approve", "correct", "reject"]
    actor: NonBlankStr
    reason: NonBlankStr
    corrections: Mapping[StrictStr, StrictStr | StrictInt | date | None] = Field(
        default_factory=dict
    )
    resulting_state: Literal[
        "review_required", "ready_for_review", "approved", "corrected", "rejected"
    ]


class InsuranceMetadataReview(_WorkbookModel):
    schema_version: Literal["insurance-metadata-review.v1"] = "insurance-metadata-review.v1"
    review_id: NonBlankStr
    review_identity: Sha256
    review_version: PositiveInt
    import_id: NonBlankStr
    workbook_row_number: PositiveInt
    workbook_draft_id: NonBlankStr
    original_ref: ExactArtifactRef
    normalized_ref: ExactArtifactRef
    source_id: NonBlankStr
    document_id: NonBlankStr
    revision_id: NonBlankStr
    canonical_anchor: NonBlankStr | None = None
    citation_uri: NonBlankStr
    state: Literal["review_required", "ready_for_review", "approved", "corrected", "rejected"]
    publication_blocked: StrictBool
    pdf_draft: InsuranceMetadataDraftInput | None = None
    workbook_draft: InsuranceMetadataDraftInput
    conflicts: tuple[InsuranceMetadataConflict, ...] = ()
    resolved_values: Mapping[StrictStr, StrictStr | StrictInt | date | None] = Field(
        default_factory=dict
    )
    resolution_reason: NonBlankStr | None = None
    resolved_by: NonBlankStr | None = None
    decision_history: tuple[InsuranceMetadataReviewDecision, ...] = ()


class InsuranceMetadataReviewRepository(Protocol):
    def list(self, source_id: str) -> tuple[InsuranceMetadataReview, ...]: ...

    def get(self, source_id: str, review_id: str) -> InsuranceMetadataReview | None: ...

    def put(self, review: InsuranceMetadataReview) -> InsuranceMetadataReview: ...

    def put_many(
        self, reviews: Iterable[InsuranceMetadataReview]
    ) -> tuple[InsuranceMetadataReview, ...]: ...

    def resolve(
        self,
        *,
        source_id: str,
        review_id: str,
        expected_review_version: int,
        expected_review_identity: str,
        action: Literal["approve", "correct", "reject"],
        actor: str,
        reason: str,
        corrections: Mapping[str, str | int | None] | None = None,
    ) -> InsuranceMetadataReview: ...


def import_metadata_workbook(
    source: bytes | bytearray | Path | str,
    *,
    known_anchors: Iterable[WorkbookKnownAnchor],
    artifact_store: KnowledgeArtifactStore | None = None,
    limits: WorkbookImportLimits = DEFAULT_WORKBOOK_IMPORT_LIMITS,
) -> InsuranceMetadataWorkbookImport:
    """Validate and normalize a literal-only, exact-anchor workbook as drafts."""

    original = _read_source_bytes(source, limits=limits)
    original_sha256 = hashlib.sha256(original).hexdigest()
    _preflight_package(original, limits=limits)
    anchor_set = {
        (item.source_id, item.document_id, item.revision_id, item.canonical_anchor)
        for item in known_anchors
    }
    if not anchor_set:
        raise WorkbookValidationError("known canonical anchors are required")
    rows = _read_rows(original, anchor_set=anchor_set, limits=limits)
    normalized_payload = {
        "schema_version": "insurance-metadata-workbook-normalized.v1",
        "template_revision": TEMPLATE_REVISION,
        "original_sha256": original_sha256,
        "rows": [row.model_dump(mode="json") for row in rows],
    }
    normalized = _canonical_json(normalized_payload)
    if len(normalized) > limits.max_normalized_bytes:
        raise WorkbookValidationError("normalized workbook exceeds the configured size limit")
    if artifact_store is None:
        raise WorkbookValidationError(
            "an immutable artifact store is required to persist original and normalized artifacts"
        )
    import_id = f"metadata_import_{hashlib.sha256(normalized).hexdigest()[:24]}"
    original_ref = _put_artifact(
        artifact_store,
        key=f"metadata-workbooks/{original_sha256}/original.xlsx",
        content=original,
        media_type=WORKBOOK_MEDIA_TYPE,
    )
    normalized_ref = _put_artifact(
        artifact_store,
        key=f"metadata-workbooks/{original_sha256}/normalized.json",
        content=normalized,
        media_type=NORMALIZED_MEDIA_TYPE,
    )
    return InsuranceMetadataWorkbookImport(
        import_id=import_id,
        template_revision=TEMPLATE_REVISION,
        original_sha256=original_sha256,
        original_ref=original_ref,
        normalized_ref=normalized_ref,
        rows=rows,
    )


def reconcile_metadata_drafts(
    pdf_draft: InsuranceMetadataDraftInput,
    workbook_draft: InsuranceMetadataDraftInput,
    *,
    import_record: WorkbookImportRecord,
    row: WorkbookMetadataRow,
) -> InsuranceMetadataReview:
    """Keep parallel proposals visible and block every unresolved disagreement."""

    if pdf_draft.origin != "pdf" or workbook_draft.origin != "workbook":
        raise ValueError("reconciliation requires one PDF draft and one workbook draft")
    pdf_identity = _draft_identity(pdf_draft)
    workbook_identity = _draft_identity(workbook_draft)
    if pdf_identity != workbook_identity:
        raise ValueError("metadata drafts must bind the same exact revision and anchor")
    conflicts = tuple(
        InsuranceMetadataConflict(
            field=field,
            label=f"{field.replace('_', ' ').title()} conflict",
            pdf_value=getattr(pdf_draft, field),
            workbook_value=getattr(workbook_draft, field),
        )
        for field in _CONFLICT_FIELDS
        if getattr(pdf_draft, field) != getattr(workbook_draft, field)
    )
    seed = {
        "import_id": import_record.import_id,
        "row_number": row.row_number,
        "pdf": pdf_draft.model_dump(mode="json"),
        "workbook": workbook_draft.model_dump(mode="json"),
    }
    digest = hashlib.sha256(_canonical_json(seed)).hexdigest()
    review_id = f"metadata_review_{digest[:24]}"
    citation_uri = _citation_uri(*pdf_identity)
    draft_review = InsuranceMetadataReview(
        review_id=review_id,
        review_identity="0" * 64,
        review_version=1,
        import_id=import_record.import_id,
        workbook_row_number=row.row_number,
        workbook_draft_id=row.metadata.metadata_draft_id,
        original_ref=import_record.original_ref,
        normalized_ref=import_record.normalized_ref,
        source_id=pdf_draft.source_id,
        document_id=pdf_draft.document_id,
        revision_id=pdf_draft.revision_id,
        canonical_anchor=pdf_draft.canonical_anchor,
        citation_uri=citation_uri,
        state="review_required" if conflicts else "ready_for_review",
        publication_blocked=True,
        pdf_draft=pdf_draft,
        workbook_draft=workbook_draft,
        conflicts=conflicts,
    )
    return draft_review.model_copy(update={"review_identity": _review_identity(draft_review)})


def create_workbook_only_review(
    workbook_draft: InsuranceMetadataDraftInput,
    *,
    import_record: WorkbookImportRecord,
    row: WorkbookMetadataRow,
    citation_uri: str,
) -> InsuranceMetadataReview:
    """Create a blocked review without inventing missing PDF-derived authority facts."""

    if workbook_draft.origin != "workbook":
        raise ValueError("workbook-only review requires a workbook draft")
    seed = {
        "import_id": import_record.import_id,
        "row": row.model_dump(mode="json"),
        "workbook": workbook_draft.model_dump(mode="json"),
    }
    digest = hashlib.sha256(_canonical_json(seed)).hexdigest()
    draft_review = InsuranceMetadataReview(
        review_id=f"metadata_review_{digest[:24]}",
        review_identity="0" * 64,
        review_version=1,
        import_id=import_record.import_id,
        workbook_row_number=row.row_number,
        workbook_draft_id=row.metadata.metadata_draft_id,
        original_ref=import_record.original_ref,
        normalized_ref=import_record.normalized_ref,
        source_id=workbook_draft.source_id,
        document_id=workbook_draft.document_id,
        revision_id=workbook_draft.revision_id,
        canonical_anchor=workbook_draft.canonical_anchor,
        citation_uri=citation_uri,
        state="review_required",
        publication_blocked=True,
        pdf_draft=None,
        workbook_draft=workbook_draft,
    )
    return draft_review.model_copy(update={"review_identity": _review_identity(draft_review)})


class FilesystemInsuranceMetadataReviewRepository:
    """Atomic local review projection with exact optimistic command identity."""

    def __init__(self, root_dir: Path) -> None:
        self._root = root_dir / "insurance_metadata_reviews"
        self._imports_root = root_dir / "insurance_metadata_imports"
        self._authority_root = root_dir / "insurance_metadata_authority"
        self._pdf_drafts_root = root_dir / "insurance_metadata_pdf_drafts"
        self._decisions_root = root_dir / "insurance_metadata_review_decisions"
        self._root.mkdir(parents=True, exist_ok=True)
        self._imports_root.mkdir(parents=True, exist_ok=True)
        self._authority_root.mkdir(parents=True, exist_ok=True)
        self._pdf_drafts_root.mkdir(parents=True, exist_ok=True)
        self._decisions_root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._file_lock = FileLock(self._root / ".reviews.lock", timeout=10)

    def list(self, source_id: str) -> tuple[InsuranceMetadataReview, ...]:
        source_dir = self._source_dir(source_id)
        if not source_dir.exists():
            return ()
        reviews = tuple(
            InsuranceMetadataReview.model_validate_json(path.read_bytes())
            for path in sorted(source_dir.glob("*.json"))
            if path.is_file() and not path.is_symlink()
        )
        return tuple(sorted(reviews, key=lambda item: item.review_id))

    def get(self, source_id: str, review_id: str) -> InsuranceMetadataReview | None:
        path = self._review_path(source_id, review_id)
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_file():
            raise WorkbookValidationError("metadata review storage entry is not a regular file")
        return InsuranceMetadataReview.model_validate_json(path.read_bytes())

    def put(self, review: InsuranceMetadataReview) -> InsuranceMetadataReview:
        return self.put_many((review,))[0]

    def put_authority_record(
        self, record: InsuranceMetadataAuthorityRecord
    ) -> InsuranceMetadataAuthorityRecord:
        path = self._authority_path(record)
        with self._lock, self._file_lock:
            if path.exists():
                current = InsuranceMetadataAuthorityRecord.model_validate_json(path.read_bytes())
                if current != record:
                    raise WorkbookReviewConflictError(
                        "canonical metadata authority identity already exists"
                    )
                return current
            self._write_payload(path, record.model_dump(mode="json"))
        return record

    def list_authority_records(
        self,
        *,
        source_id: str,
        document_id: str,
        revision_id: str,
    ) -> tuple[InsuranceMetadataAuthorityRecord, ...]:
        root = self._authority_revision_dir(source_id, document_id, revision_id)
        if not root.exists():
            return ()
        records = tuple(
            InsuranceMetadataAuthorityRecord.model_validate_json(path.read_bytes())
            for path in sorted(root.glob("*.json"))
            if path.is_file() and not path.is_symlink()
        )
        return tuple(sorted(records, key=lambda item: item.canonical_anchor or ""))

    def put_pdf_draft_record(
        self, record: InsuranceMetadataPdfDraftRecord
    ) -> InsuranceMetadataPdfDraftRecord:
        path = self._pdf_draft_path(record)
        with self._lock, self._file_lock:
            if path.exists():
                current = InsuranceMetadataPdfDraftRecord.model_validate_json(path.read_bytes())
                if current != record:
                    raise WorkbookReviewConflictError(
                        "persisted PDF metadata draft identity already exists"
                    )
                return current
            self._write_payload(path, record.model_dump(mode="json"))
        return record

    def list_pdf_draft_records(
        self,
        *,
        source_id: str,
        document_id: str,
        revision_id: str,
    ) -> tuple[InsuranceMetadataPdfDraftRecord, ...]:
        root = self._pdf_draft_revision_dir(source_id, document_id, revision_id)
        if not root.exists():
            return ()
        records = tuple(
            InsuranceMetadataPdfDraftRecord.model_validate_json(path.read_bytes())
            for path in sorted(root.glob("*.json"))
            if path.is_file() and not path.is_symlink()
        )
        return tuple(sorted(records, key=lambda item: item.canonical_anchor or ""))

    def get_import_record(self, import_id: str) -> WorkbookImportRecord | None:
        path = self._imports_root / f"{_safe_identifier(import_id, 'import_id')}.json"
        if not path.exists():
            return None
        return WorkbookImportRecord.model_validate_json(path.read_bytes())

    def put_import_with_reviews(
        self,
        record: WorkbookImportRecord,
        reviews: Iterable[InsuranceMetadataReview],
    ) -> tuple[InsuranceMetadataReview, ...]:
        review_batch = tuple(reviews)
        if any(review.import_id != record.import_id for review in review_batch):
            raise WorkbookValidationError("review import lineage does not match import record")
        import_path = self._imports_root / f"{_safe_identifier(record.import_id, 'import_id')}.json"
        created_import = False
        with self._lock, self._file_lock:
            current_import = self.get_import_record(record.import_id)
            if current_import is not None and current_import != record:
                raise WorkbookReviewConflictError("workbook import identity already exists")
            if current_import is None:
                self._write_payload(import_path, record.model_dump(mode="json"))
                created_import = True
            try:
                return self._put_many_unlocked(review_batch)
            except Exception:
                if created_import:
                    import_path.unlink(missing_ok=True)
                raise

    def put_many(
        self, reviews: Iterable[InsuranceMetadataReview]
    ) -> tuple[InsuranceMetadataReview, ...]:
        review_batch = tuple(reviews)
        with self._lock, self._file_lock:
            return self._put_many_unlocked(review_batch)

    def _put_many_unlocked(
        self, review_batch: tuple[InsuranceMetadataReview, ...]
    ) -> tuple[InsuranceMetadataReview, ...]:
        created_paths: list[Path] = []
        if not review_batch:
            raise WorkbookValidationError("metadata review batch must not be empty")
        identities = {(review.source_id, review.review_id) for review in review_batch}
        if len(identities) != len(review_batch):
            raise WorkbookValidationError("metadata review batch contains duplicate identities")
        for review in review_batch:
            expected = _review_identity(review.model_copy(update={"review_identity": "0" * 64}))
            if review.review_identity != expected:
                raise WorkbookValidationError("metadata review identity does not match its content")
        try:
            for review in review_batch:
                current = self.get(review.source_id, review.review_id)
                if current is not None and current != review:
                    raise WorkbookReviewConflictError("metadata review identity already exists")
            for review in review_batch:
                path = self._review_path(review.source_id, review.review_id)
                if not path.exists():
                    created_paths.append(path)
                self._write(review)
        except Exception:
            for path in created_paths:
                path.unlink(missing_ok=True)
            raise
        return review_batch

    def resolve(
        self,
        *,
        source_id: str,
        review_id: str,
        expected_review_version: int,
        expected_review_identity: str,
        action: Literal["approve", "correct", "reject"],
        actor: str,
        reason: str,
        corrections: Mapping[str, str | int | None] | None = None,
    ) -> InsuranceMetadataReview:
        with self._lock, self._file_lock:
            current = self.get(source_id, review_id)
            if current is None:
                raise KeyError(review_id)
            if (
                current.review_version != expected_review_version
                or current.review_identity != expected_review_identity
            ):
                raise WorkbookReviewConflictError("metadata review changed; reload exact identity")
            normalized_reason = _require_nonblank(reason, "reason")
            normalized_actor = _require_nonblank(actor, "actor")
            decision_corrections: Mapping[str, str | int | date | None] = {}
            next_state: Literal[
                "review_required", "ready_for_review", "approved", "corrected", "rejected"
            ] = current.state
            updates: dict[str, object] = {
                "review_version": current.review_version + 1,
                "review_identity": "0" * 64,
                "resolution_reason": normalized_reason,
                "resolved_by": normalized_actor,
            }
            if action == "approve":
                if current.pdf_draft is None:
                    raise WorkbookReviewConflictError(
                        "persisted PDF metadata draft is required before approval"
                    )
                if current.conflicts:
                    raise WorkbookReviewConflictError(
                        "unresolved metadata conflicts block approval and publication"
                    )
                if current.state not in {"ready_for_review", "corrected"}:
                    raise WorkbookReviewConflictError(
                        "only a ready or corrected metadata review can be approved"
                    )
                _validate_resolved_draft(current, {})
                next_state = "approved"
                updates.update(state=next_state, publication_blocked=False)
            elif action == "reject":
                next_state = "rejected"
                updates.update(state=next_state, publication_blocked=True)
            else:
                if current.pdf_draft is None:
                    raise WorkbookReviewConflictError(
                        "persisted PDF metadata draft is required before correction"
                    )
                if current.state in {"approved", "rejected"}:
                    raise WorkbookReviewConflictError(
                        "terminal metadata reviews cannot be corrected"
                    )
                resolved = _validated_corrections(current, corrections or {})
                if not resolved:
                    raise WorkbookValidationError("correction requires at least one governed field")
                unresolved = tuple(
                    conflict for conflict in current.conflicts if conflict.field not in resolved
                )
                next_state = "corrected" if not unresolved else "review_required"
                decision_corrections = resolved
                updates.update(
                    state=next_state,
                    publication_blocked=True,
                    conflicts=unresolved,
                    resolved_values={**dict(current.resolved_values), **resolved},
                )
            decision = InsuranceMetadataReviewDecision(
                sequence=len(current.decision_history) + 1,
                prior_review_identity=current.review_identity,
                prior_state=current.state,
                action=action,
                actor=normalized_actor,
                reason=normalized_reason,
                corrections=decision_corrections,
                resulting_state=next_state,
            )
            updates["decision_history"] = (*current.decision_history, decision)
            updated = InsuranceMetadataReview.model_validate({**current.model_dump(), **updates})
            updated = InsuranceMetadataReview.model_validate(
                {**updated.model_dump(), "review_identity": _review_identity(updated)}
            )
            self._append_decision(current, decision)
            self._write(updated)
            return updated

    def _source_dir(self, source_id: str) -> Path:
        return self._root / _safe_identifier(source_id, "source_id")

    def _review_path(self, source_id: str, review_id: str) -> Path:
        return self._source_dir(source_id) / f"{_safe_identifier(review_id, 'review_id')}.json"

    def _authority_revision_dir(
        self, source_id: str, document_id: str, revision_id: str
    ) -> Path:
        return (
            self._authority_root
            / _safe_identifier(source_id, "source_id")
            / _safe_identifier(document_id, "document_id")
            / _safe_identifier(revision_id, "revision_id")
        )

    def _authority_path(self, record: InsuranceMetadataAuthorityRecord) -> Path:
        identity = hashlib.sha256(
            _canonical_json(
                {
                    "source_id": record.source_id,
                    "document_id": record.document_id,
                    "revision_id": record.revision_id,
                    "canonical_anchor": record.canonical_anchor,
                }
            )
        ).hexdigest()
        return self._authority_revision_dir(
            record.source_id, record.document_id, record.revision_id
        ) / f"{identity}.json"

    def _pdf_draft_revision_dir(
        self, source_id: str, document_id: str, revision_id: str
    ) -> Path:
        return (
            self._pdf_drafts_root
            / _safe_identifier(source_id, "source_id")
            / _safe_identifier(document_id, "document_id")
            / _safe_identifier(revision_id, "revision_id")
        )

    def _pdf_draft_path(self, record: InsuranceMetadataPdfDraftRecord) -> Path:
        identity = hashlib.sha256(
            _canonical_json(
                {
                    "source_id": record.source_id,
                    "document_id": record.document_id,
                    "revision_id": record.revision_id,
                    "canonical_anchor": record.canonical_anchor,
                    "structured_build_id": record.structured_build_id,
                }
            )
        ).hexdigest()
        return self._pdf_draft_revision_dir(
            record.source_id, record.document_id, record.revision_id
        ) / f"{identity}.json"

    def _append_decision(
        self,
        review: InsuranceMetadataReview,
        decision: InsuranceMetadataReviewDecision,
    ) -> None:
        path = (
            self._decisions_root
            / _safe_identifier(review.source_id, "source_id")
            / _safe_identifier(review.review_id, "review_id")
            / f"{decision.sequence:08d}-{decision.prior_review_identity}.json"
        )
        if path.exists():
            current = InsuranceMetadataReviewDecision.model_validate_json(path.read_bytes())
            if current != decision:
                raise WorkbookReviewConflictError("metadata review decision identity already exists")
            return
        self._write_payload(path, decision.model_dump(mode="json"))

    def _write(self, review: InsuranceMetadataReview) -> None:
        path = self._review_path(review.source_id, review.review_id)
        self._write_payload(path, review.model_dump(mode="json"))

    def _write_payload(self, path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = _canonical_json(value)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if temporary.exists():
                temporary.unlink()


def _read_source_bytes(
    source: bytes | bytearray | Path | str,
    *,
    limits: WorkbookImportLimits,
) -> bytes:
    if isinstance(source, bytes):
        content = source
    elif isinstance(source, bytearray):
        content = bytes(source)
    else:
        path = Path(source)
        if path.is_symlink() or not path.is_file():
            raise WorkbookValidationError("workbook input must be a regular non-symlink file")
        if path.stat().st_size > limits.max_file_bytes:
            raise WorkbookValidationError("workbook exceeds the configured file size limit")
        content = path.read_bytes()
    if not content or len(content) > limits.max_file_bytes:
        raise WorkbookValidationError("workbook exceeds the configured file size limit")
    if not content.startswith(b"PK\x03\x04"):
        raise WorkbookValidationError("workbook must be an XLSX ZIP package")
    return content


def _preflight_package(
    content: bytes,
    *,
    limits: WorkbookImportLimits,
    header_row: int | None = None,
) -> None:
    try:
        with ZipFile(BytesIO(content)) as archive:
            members = archive.infolist()
            names = tuple(member.filename for member in members)
            if len(names) != len(set(names)) or len(names) > 2_048:
                raise WorkbookValidationError("workbook package contains unsafe duplicate entries")
            if sum(member.file_size for member in members) > limits.max_file_bytes * 8:
                raise WorkbookValidationError(
                    "workbook expanded package exceeds the safe size limit"
                )
            if any(".." in Path(name).parts or name.startswith(("/", "\\")) for name in names):
                raise WorkbookValidationError("workbook package contains an unsafe path")
            folded_names = tuple(name.casefold() for name in names)
            if any(
                any(marker.casefold() in name for marker in _MACRO_MARKERS) for name in folded_names
            ):
                raise WorkbookValidationError("workbook macros are not accepted")
            if any(
                any(marker.casefold() in name for marker in _EXTERNAL_LINK_MARKERS)
                for name in folded_names
            ):
                raise WorkbookValidationError("workbook external links are not accepted")
            if "xl/workbook.xml" not in names or not any(
                name.startswith("xl/worksheets/") for name in names
            ):
                raise WorkbookValidationError("workbook package is incomplete")
            for member in members:
                if not member.filename.casefold().endswith((".xml", ".rels")):
                    continue
                markup = archive.read(member)
                folded_markup = markup.lower()
                if b"<!doctype" in folded_markup or b"<!entity" in folded_markup:
                    raise WorkbookValidationError("workbook XML declarations are not accepted")
                if b'targetmode="external"' in folded_markup:
                    raise WorkbookValidationError("workbook external links are not accepted")
                try:
                    root = ElementTree.fromstring(markup)
                except ElementTree.ParseError as exc:
                    raise WorkbookValidationError("workbook XML is malformed") from exc
                if member.filename.casefold().endswith(".rels"):
                    _validate_relationship_xml(root)
                if member.filename.casefold() == "[content_types].xml":
                    _validate_content_types_xml(root)
                if member.filename.casefold().startswith("xl/worksheets/"):
                    _validate_worksheet_bounds(root, limits=limits, header_row=header_row)
    except (BadZipFile, OSError) as exc:
        raise WorkbookValidationError("workbook package is malformed") from exc


def _read_rows(
    content: bytes,
    *,
    anchor_set: set[tuple[str, str, str, str | None]],
    limits: WorkbookImportLimits,
) -> tuple[WorkbookMetadataRow, ...]:
    try:
        load_workbook = _optional_load_workbook()
        workbook = load_workbook(
            BytesIO(content),
            read_only=True,
            data_only=False,
            keep_links=False,
        )
    except WorkbookValidationError:
        raise
    except Exception as exc:
        raise WorkbookValidationError("workbook cannot be parsed safely") from exc
    try:
        if workbook.sheetnames != [_SHEET_NAME]:
            raise WorkbookValidationError("workbook must contain only the versioned Metadata sheet")
        sheet = workbook[_SHEET_NAME]
        header_row = _find_header_row(sheet, limits=limits)
        _preflight_package(content, limits=limits, header_row=header_row)
        rows: list[WorkbookMetadataRow] = []
        identities: set[tuple[str, str, str, str | None]] = set()
        for row_number, cells in enumerate(
            sheet.iter_rows(
                min_row=header_row + 1,
                max_row=header_row + limits.max_rows + 1,
                max_col=len(_HEADERS) + 1,
            ),
            start=header_row + 1,
        ):
            if cells[-1].value is not None:
                raise WorkbookValidationError("workbook exceeds the configured column limit")
            cells = cells[:-1]
            if all(cell.value is None for cell in cells):
                continue
            if len(rows) >= limits.max_rows:
                raise WorkbookValidationError("workbook exceeds the configured row limit")
            values: dict[str, object] = {}
            for field, cell in zip(_HEADERS, cells, strict=True):
                if field in _AUTHORITY_FIELDS and (
                    cell.data_type == "f"
                    or (isinstance(cell.value, str) and cell.value.startswith(_FORMULA_PREFIXES))
                ):
                    raise WorkbookValidationError(
                        "authority fields require literal cells; formulas are rejected"
                    )
                values[field] = cell.value
            row = _normalize_row(row_number, values, limits=limits)
            identity = (row.source_id, row.document_id, row.revision_id, row.canonical_anchor)
            if identity not in anchor_set:
                raise WorkbookValidationError(
                    "workbook row does not match an exact Source/document/revision/anchor"
                )
            if identity in identities:
                raise WorkbookValidationError("duplicate exact workbook row identity")
            identities.add(identity)
            rows.append(row)
        if not rows:
            raise WorkbookValidationError("workbook must contain at least one metadata row")
        return tuple(rows)
    finally:
        workbook.close()


def _optional_load_workbook() -> Any:
    try:
        module = import_module("openpyxl")
    except ModuleNotFoundError as exc:
        raise WorkbookValidationError(
            "workbook import requires the optional hybrid extra"
        ) from exc
    loader = getattr(module, "load_workbook", None)
    if not callable(loader):
        raise WorkbookValidationError("openpyxl does not expose a safe workbook loader")
    return loader


def _validate_relationship_xml(root: ElementTree.Element) -> None:
    for relationship in root.iter():
        if _local_name(relationship.tag).casefold() != "relationship":
            continue
        attributes = {
            _local_name(key).casefold(): value.strip()
            for key, value in relationship.attrib.items()
        }
        target_mode = attributes.get("targetmode", "").casefold()
        target = attributes.get("target", "")
        relationship_type = attributes.get("type", "").casefold()
        parsed = urlsplit(target)
        if (
            target_mode == "external"
            or bool(parsed.scheme)
            or bool(parsed.netloc)
            or target.startswith("//")
        ):
            raise WorkbookValidationError("workbook external links are not accepted")
        if any(marker in relationship_type for marker in _DANGEROUS_OFFICE_MARKERS):
            raise WorkbookValidationError("workbook executable or embedded content is not accepted")


def _validate_content_types_xml(root: ElementTree.Element) -> None:
    for element in root.iter():
        content_type = "".join(
            value.strip().casefold()
            for key, value in element.attrib.items()
            if _local_name(key).casefold() == "contenttype"
        )
        if any(marker in content_type for marker in _DANGEROUS_OFFICE_MARKERS):
            raise WorkbookValidationError("workbook executable or embedded content is not accepted")


def _validate_worksheet_bounds(
    root: ElementTree.Element,
    *,
    limits: WorkbookImportLimits,
    header_row: int | None,
) -> None:
    maximum_row = limits.max_rows + (header_row if header_row is not None else 20)
    for element in root.iter():
        local_name = _local_name(element.tag).casefold()
        if local_name == "dimension":
            reference = element.attrib.get("ref", "").split(":")[-1]
            if reference:
                _require_cell_within_template(reference, maximum_row=maximum_row, limits=limits)
        elif local_name == "c":
            cell_reference = element.attrib.get("r")
            if cell_reference is None:
                raise WorkbookValidationError("workbook cell is missing a structural reference")
            _require_cell_within_template(
                cell_reference,
                maximum_row=maximum_row,
                limits=limits,
            )


def _require_cell_within_template(
    reference: str,
    *,
    maximum_row: int,
    limits: WorkbookImportLimits,
) -> None:
    match = _CELL_REFERENCE.fullmatch(reference.strip())
    if match is None:
        raise WorkbookValidationError("workbook cell reference is malformed")
    column_name, row_text = match.groups()
    column = 0
    for character in column_name.upper():
        column = column * 26 + ord(character) - ord("A") + 1
    if column > limits.max_columns or int(row_text) > maximum_row:
        raise WorkbookValidationError("workbook content exceeds the versioned template bounds")


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _find_header_row(sheet: object, *, limits: WorkbookImportLimits) -> int:
    iter_rows = getattr(sheet, "iter_rows")
    for row_number, cells in enumerate(
        iter_rows(min_row=1, max_row=20, max_col=len(_HEADERS)),
        start=1,
    ):
        values = tuple(cell.value for cell in cells)
        if values == _HEADERS:
            return row_number
        if any(value in _HEADERS for value in values if isinstance(value, str)):
            raise WorkbookValidationError(
                "workbook headers must match the versioned template exactly"
            )
        for value in values:
            if isinstance(value, str) and len(value) > limits.max_cell_characters:
                raise WorkbookValidationError("workbook cell exceeds the configured string limit")
    raise WorkbookValidationError("versioned workbook header row was not found")


def _normalize_row(
    row_number: int,
    values: Mapping[str, object],
    *,
    limits: WorkbookImportLimits,
) -> WorkbookMetadataRow:
    template_revision = _string(values["template_revision"], "template_revision", limits)
    if template_revision != TEMPLATE_REVISION:
        raise WorkbookValidationError("unsupported workbook template revision")
    source_id = _string(values["source_id"], "source_id", limits)
    document_id = _string(values["document_id"], "document_id", limits)
    revision_id = _string(values["revision_id"], "revision_id", limits)
    canonical_anchor = _optional_string(values["canonical_anchor"], "canonical_anchor", limits)
    authority = _string(values["authority"], "authority", limits)
    effective_from = _business_date(values["effective_from"], "effective_from")
    effective_to = _business_date(values["effective_to"], "effective_to")
    taxonomy_id = _string(values["taxonomy_id"], "taxonomy_id", limits)
    taxonomy_revision_id = _string(values["taxonomy_revision_id"], "taxonomy_revision_id", limits)
    policy_revision = _string(
        values["precedence_policy_revision_id"], "precedence_policy_revision_id", limits
    )
    authority_tier = _string(
        values["precedence_authority_tier"], "precedence_authority_tier", limits
    )
    precedence_order = values["precedence_order"]
    if type(precedence_order) is not int or precedence_order < 0:
        raise WorkbookValidationError("precedence_order must be a nonnegative literal integer")
    metadata_seed = {
        "source_id": source_id,
        "document_id": document_id,
        "revision_id": revision_id,
        "canonical_anchor": canonical_anchor,
        "authority": authority,
        "effective_from": effective_from.isoformat() if effective_from else None,
        "effective_to": effective_to.isoformat() if effective_to else None,
        "taxonomy_id": taxonomy_id,
        "taxonomy_revision_id": taxonomy_revision_id,
        "policy_revision": policy_revision,
        "authority_tier": authority_tier,
        "precedence_order": precedence_order,
    }
    draft_id = f"metadata_draft_{hashlib.sha256(_canonical_json(metadata_seed)).hexdigest()[:24]}"
    metadata = InsuranceRuleMetadataDraft(
        metadata_draft_id=draft_id,
        document_id=document_id,
        revision_id=revision_id,
        applicability=InsuranceRuleApplicability(
            taxonomy_id=taxonomy_id,
            taxonomy_revision_id=taxonomy_revision_id,
        ),
        effective_from=effective_from,
        effective_to=effective_to,
        authority=authority,
        precedence=InsuranceRulePrecedence(
            policy_revision_id=policy_revision,
            authority_tier=authority_tier,
            order=precedence_order,
        ),
    )
    return WorkbookMetadataRow(
        row_number=row_number,
        source_id=source_id,
        document_id=document_id,
        revision_id=revision_id,
        canonical_anchor=canonical_anchor,
        metadata=metadata,
    )


def _string(value: object, field: str, limits: WorkbookImportLimits) -> str:
    if type(value) is not str or not value.strip():
        raise WorkbookValidationError(f"{field} must be a non-empty literal string")
    normalized = value.strip()
    if len(normalized) > limits.max_cell_characters or any(ord(char) < 32 for char in normalized):
        raise WorkbookValidationError(f"{field} exceeds the safe string limit")
    return normalized


def _optional_string(value: object, field: str, limits: WorkbookImportLimits) -> str | None:
    if value is None:
        return None
    return _string(value, field, limits)


def _business_date(value: object, field: str) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.time() != datetime.min.time():
            raise WorkbookValidationError(f"{field} must be a date without a time")
        return value.date()
    if type(value) is date:
        return value
    if type(value) is str:
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
            raise WorkbookValidationError(f"{field} must use YYYY-MM-DD")
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise WorkbookValidationError(f"{field} must use YYYY-MM-DD") from exc
    raise WorkbookValidationError(f"{field} must be a literal date")


def _put_artifact(
    store: KnowledgeArtifactStore,
    *,
    key: str,
    content: bytes,
    media_type: str,
) -> ExactArtifactRef:
    return store.put_immutable(key=key, content=content, media_type=media_type)


def _draft_identity(draft: InsuranceMetadataDraftInput) -> tuple[str, str, str, str | None]:
    return draft.source_id, draft.document_id, draft.revision_id, draft.canonical_anchor


def _citation_uri(source_id: str, document_id: str, revision_id: str, anchor: str | None) -> str:
    suffix = f"#{anchor}" if anchor else ""
    return f"proofagent://knowledge/{source_id}/{document_id}/{revision_id}{suffix}"


def _review_identity(review: InsuranceMetadataReview) -> str:
    payload = review.model_dump(mode="json", exclude={"review_identity"})
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _validated_corrections(
    review: InsuranceMetadataReview,
    corrections: Mapping[str, str | int | None],
) -> dict[str, str | int | date | None]:
    unknown = set(corrections).difference(_CONFLICT_FIELDS)
    if unknown:
        raise WorkbookValidationError("corrections contain an unknown governed field")
    result: dict[str, str | int | date | None] = {}
    for key, value in corrections.items():
        if key == "precedence_order":
            if value is not None and (type(value) is not int or value < 0):
                raise WorkbookValidationError("precedence_order correction must be nonnegative")
            result[key] = value
        elif key in {"effective_from", "effective_to"}:
            if value is None:
                result[key] = None
            elif type(value) is not str:
                raise WorkbookValidationError(f"{key} correction must use YYYY-MM-DD")
            else:
                if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
                    raise WorkbookValidationError(f"{key} correction must use YYYY-MM-DD")
                try:
                    result[key] = date.fromisoformat(value)
                except ValueError as exc:
                    raise WorkbookValidationError(
                        f"{key} correction must use YYYY-MM-DD"
                    ) from exc
        else:
            if value is None:
                result[key] = None
                continue
            if type(value) is not str or not value.strip():
                raise WorkbookValidationError(f"{key} correction must be a non-empty literal")
            normalized = value.strip()
            if len(normalized) > 4_096 or any(ord(character) < 32 for character in normalized):
                raise WorkbookValidationError(f"{key} correction exceeds the safe string limit")
            result[key] = normalized
    _validate_resolved_draft(review, result)
    return result


def _validate_resolved_draft(
    review: InsuranceMetadataReview,
    additions: Mapping[str, str | int | date | None],
) -> None:
    seed = review.workbook_draft.model_dump()
    seed.update(dict(review.resolved_values))
    seed.update(additions)
    try:
        InsuranceMetadataDraftInput.model_validate(seed)
    except ValidationError as exc:
        raise WorkbookValidationError("corrected metadata is invalid") from exc


def _safe_identifier(value: str, field: str) -> str:
    normalized = _require_nonblank(value, field)
    if not all(character.isalnum() or character in "_-" for character in normalized):
        raise WorkbookValidationError(f"{field} contains unsafe characters")
    return normalized


def _require_nonblank(value: str, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise WorkbookValidationError(f"{field} must be non-empty")
    return value.strip()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
