"""Metadata Review V2 authority-neutral domain behavior."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
import hashlib
import json
import os
from pathlib import Path
from typing import Annotated, Literal, Self
from uuid import uuid4

from filelock import FileLock
from pydantic import ConfigDict, Field, StrictBool, StrictStr, StringConstraints, model_validator

from proof_agent.capabilities.knowledge.hybrid.workbook import InsuranceMetadataDraftInput
from proof_agent.contracts._base import FrozenModel
from proof_agent.contracts.insurance_rules import (
    ApprovedInsuranceRuleMetadataRevision,
    InsuranceRuleApplicability,
    InsuranceRuleMetadataDraft,
    InsuranceRulePrecedence,
)


NonBlankStr = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256 = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class _MetadataReviewModel(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class InsuranceMetadataProfileValue(_MetadataReviewModel):
    """Stable governed code plus its operator-facing label."""

    code: NonBlankStr
    label: NonBlankStr
    replacement_code: NonBlankStr | None = None


class InsuranceMetadataProfileRevision(_MetadataReviewModel):
    """One immutable published vocabulary used by metadata review."""

    schema_version: Literal["insurance-metadata-profile.v1"] = (
        "insurance-metadata-profile.v1"
    )
    profile_id: NonBlankStr
    profile_revision_id: NonBlankStr
    reference_only: StrictBool = False
    authority_codes: tuple[NonBlankStr, ...] = Field(min_length=1, max_length=10_000)
    authority_values: tuple[InsuranceMetadataProfileValue, ...] = Field(
        default=(), max_length=10_000
    )
    taxonomy_id: NonBlankStr
    taxonomy_revision_id: NonBlankStr
    precedence_policy_revision_id: NonBlankStr
    precedence_authority_tiers: tuple[NonBlankStr, ...] = Field(
        min_length=1, max_length=10_000
    )
    precedence_authority_tier_values: tuple[
        InsuranceMetadataProfileValue, ...
    ] = Field(default=(), max_length=10_000)

    @model_validator(mode="after")
    def validate_codes(self) -> Self:
        if len(self.authority_codes) != len(set(self.authority_codes)):
            raise ValueError("metadata Profile authority codes must be unique")
        if len(self.precedence_authority_tiers) != len(
            set(self.precedence_authority_tiers)
        ):
            raise ValueError("metadata Profile precedence tiers must be unique")
        self._validate_labeled_values(
            self.authority_values,
            self.authority_codes,
            "authority",
        )
        self._validate_labeled_values(
            self.precedence_authority_tier_values,
            self.precedence_authority_tiers,
            "precedence authority tier",
        )
        return self

    @staticmethod
    def _validate_labeled_values(
        values: tuple[InsuranceMetadataProfileValue, ...],
        codes: tuple[str, ...],
        field: str,
    ) -> None:
        if not values:
            return
        value_codes = tuple(value.code for value in values)
        if len(value_codes) != len(set(value_codes)) or set(value_codes) != set(codes):
            raise ValueError(f"metadata Profile {field} labels must cover exact codes")
        if any(
            value.replacement_code is not None
            and value.replacement_code not in set(codes)
            for value in values
        ):
            raise ValueError(
                f"metadata Profile {field} replacement must target a current code"
            )


class InsuranceMetadataReviewV2(_MetadataReviewModel):
    schema_version: Literal["insurance-metadata-review.v2"] = (
        "insurance-metadata-review.v2"
    )
    review_id: NonBlankStr
    review_identity: Sha256
    review_version: int = Field(ge=1, strict=True)
    source_id: NonBlankStr
    document_id: NonBlankStr
    revision_id: NonBlankStr
    structured_build_id: NonBlankStr
    profile_revision_id: NonBlankStr
    scope: Literal["document_default", "rule_unit_override"]
    canonical_anchor: NonBlankStr | None = None
    state: Literal["needs_input", "ready_for_approval", "approved", "rejected"]
    current: StrictBool = True
    parser_proposal: InsuranceRuleMetadataDraft
    current_draft: InsuranceRuleMetadataDraft
    approved_metadata_revision_id: NonBlankStr | None = None

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        if (self.scope == "document_default") != (self.canonical_anchor is None):
            raise ValueError("metadata review scope and canonical anchor do not match")
        return self


class InsuranceMetadataReviewSet(_MetadataReviewModel):
    schema_version: Literal["insurance-metadata-review-set.v2"] = (
        "insurance-metadata-review-set.v2"
    )
    review_set_id: NonBlankStr
    review_set_identity: Sha256
    generation: int = Field(default=1, ge=1, strict=True)
    source_id: NonBlankStr
    document_id: NonBlankStr
    revision_id: NonBlankStr
    structured_build_id: NonBlankStr
    profile_revision_id: NonBlankStr
    reviews: tuple[InsuranceMetadataReviewV2, ...] = Field(min_length=1, max_length=10_001)

    @model_validator(mode="after")
    def validate_review_coverage(self) -> Self:
        defaults = [review for review in self.reviews if review.scope == "document_default"]
        if len(defaults) != 1 or self.reviews[0] != defaults[0]:
            raise ValueError("metadata Review Set requires one leading Document Default")
        anchors = [
            review.canonical_anchor
            for review in self.reviews
            if review.scope == "rule_unit_override"
        ]
        if len(anchors) != len(set(anchors)):
            raise ValueError("metadata Review Set override anchors must be unique")
        expected = (
            self.source_id,
            self.document_id,
            self.revision_id,
            self.structured_build_id,
            self.profile_revision_id,
        )
        for review in self.reviews:
            if (
                review.source_id,
                review.document_id,
                review.revision_id,
                review.structured_build_id,
                review.profile_revision_id,
            ) != expected:
                raise ValueError("metadata Review Set contains mixed authority identities")
        return self


class InsuranceMetadataReviewSummaryV2(_MetadataReviewModel):
    total: int = Field(ge=0, strict=True)
    unresolved: int = Field(ge=0, strict=True)
    needs_input: int = Field(ge=0, strict=True)
    ready_for_approval: int = Field(ge=0, strict=True)
    approved: int = Field(ge=0, strict=True)
    rejected: int = Field(ge=0, strict=True)
    all_approved: StrictBool


class InsuranceMetadataReviewPageV2(_MetadataReviewModel):
    items: tuple[InsuranceMetadataReviewV2, ...]
    next_cursor: StrictStr | None = None
    total: int = Field(ge=0, strict=True)
    summary: InsuranceMetadataReviewSummaryV2


class InsuranceMetadataReviewDecisionV2(_MetadataReviewModel):
    schema_version: Literal["insurance-metadata-review-decision.v2"] = (
        "insurance-metadata-review-decision.v2"
    )
    decision_id: NonBlankStr
    prior_review_identity: Sha256
    resulting_review_identity: Sha256
    action: Literal["save_draft", "workbook_apply", "approve", "reject"]
    actor: NonBlankStr
    reason: NonBlankStr
    changed_fields: tuple[NonBlankStr, ...] = ()


class MetadataReviewCommandResult(_MetadataReviewModel):
    review: InsuranceMetadataReviewV2
    decision: InsuranceMetadataReviewDecisionV2


class MetadataReviewSetCommandResult(_MetadataReviewModel):
    review_set: InsuranceMetadataReviewSet
    decision: InsuranceMetadataReviewDecisionV2


class MetadataReviewConflictError(RuntimeError):
    """A command did not match the exact current Review revision."""


class MetadataReviewValidationError(ValueError):
    """A Review draft command contains invalid governed input."""


class MetadataProfileBindingRequiredError(MetadataReviewValidationError):
    """A Source has no published Metadata Profile binding for review materialization."""


class FilesystemInsuranceMetadataReviewV2Repository:
    """Local adapter for exact current Review Sets used by local composition."""

    def __init__(self, root_dir: Path) -> None:
        self._root = root_dir / "insurance_metadata_review_sets_v2"
        self._root.mkdir(parents=True, exist_ok=True)

    def put_current(
        self, review_set: InsuranceMetadataReviewSet
    ) -> InsuranceMetadataReviewSet:
        path = self._path(
            source_id=review_set.source_id,
            document_id=review_set.document_id,
            revision_id=review_set.revision_id,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(f"{path}.lock"):
            if path.exists():
                current = self._read(path)
                if current != review_set:
                    raise MetadataReviewConflictError(
                        "current metadata Review Set identity already exists"
                    )
                return current
            self._write(path, review_set)
        return review_set

    def save_draft(
        self,
        *,
        source_id: str,
        document_id: str,
        revision_id: str,
        review_id: str,
        profile: InsuranceMetadataProfileRevision,
        expected_review_version: int,
        expected_review_identity: str,
        actor: str,
        reason: str,
        changes: Mapping[str, str | int | date | None],
    ) -> MetadataReviewCommandResult:
        path = self._path(
            source_id=source_id,
            document_id=document_id,
            revision_id=revision_id,
        )
        with FileLock(f"{path}.lock"):
            if not path.exists():
                raise KeyError(review_id)
            current_set = self._read(path)
            current = next(
                (review for review in current_set.reviews if review.review_id == review_id),
                None,
            )
            if current is None:
                raise KeyError(review_id)
            result = save_metadata_review_draft(
                current,
                profile=profile,
                expected_review_version=expected_review_version,
                expected_review_identity=expected_review_identity,
                actor=actor,
                reason=reason,
                changes=changes,
            )
            self._write(path, _replace_review(current_set, result.review))
        return result

    @staticmethod
    def _write(path: Path, review_set: InsuranceMetadataReviewSet) -> None:
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        payload = review_set.model_dump_json().encode("utf-8")
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
            )
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    descriptor = -1
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
            os.replace(temporary, path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def get_current(
        self,
        *,
        source_id: str,
        document_id: str,
        revision_id: str,
    ) -> InsuranceMetadataReviewSet | None:
        path = self._path(
            source_id=source_id,
            document_id=document_id,
            revision_id=revision_id,
        )
        if not path.exists():
            return None
        review_set = self._read(path)
        if (
            review_set.source_id,
            review_set.document_id,
            review_set.revision_id,
        ) != (source_id, document_id, revision_id):
            raise MetadataReviewValidationError(
                "stored metadata Review Set identity does not match its path"
            )
        return review_set

    def _path(self, *, source_id: str, document_id: str, revision_id: str) -> Path:
        identity = _sha256(
            {
                "source_id": source_id,
                "document_id": document_id,
                "revision_id": revision_id,
            }
        )
        return self._root / identity[:2] / f"{identity}.json"

    @staticmethod
    def _read(path: Path) -> InsuranceMetadataReviewSet:
        try:
            return InsuranceMetadataReviewSet.model_validate_json(path.read_bytes())
        except (OSError, ValueError) as exc:
            raise MetadataReviewValidationError(
                "stored metadata Review Set failed validation"
            ) from exc


def proofagent_insurance_reference_profile() -> InsuranceMetadataProfileRevision:
    """Return the checked-in local reference Profile; never production authority."""

    return InsuranceMetadataProfileRevision(
        profile_id="proofagent-insurance-reference",
        profile_revision_id="proofagent-insurance-reference.v1",
        reference_only=True,
        authority_codes=("institution", "national", "provincial"),
        authority_values=(
            InsuranceMetadataProfileValue(
                code="institution", label="Institution authority"
            ),
            InsuranceMetadataProfileValue(
                code="national", label="National authority"
            ),
            InsuranceMetadataProfileValue(
                code="provincial", label="Provincial authority"
            ),
        ),
        taxonomy_id="insurance-product-applicability",
        taxonomy_revision_id="taxonomy-2026-01",
        precedence_policy_revision_id="precedence-2026-01",
        precedence_authority_tiers=(
            "institution_exception",
            "policy_terms",
            "sales_rules",
            "underwriting_rules",
        ),
        precedence_authority_tier_values=(
            InsuranceMetadataProfileValue(
                code="institution_exception",
                label="Institution exception",
            ),
            InsuranceMetadataProfileValue(
                code="policy_terms",
                label="Policy terms",
            ),
            InsuranceMetadataProfileValue(
                code="sales_rules",
                label="Sales rules",
            ),
            InsuranceMetadataProfileValue(
                code="underwriting_rules",
                label="Underwriting rules",
            ),
        ),
    )


def require_production_metadata_profile(
    profile: InsuranceMetadataProfileRevision,
) -> InsuranceMetadataProfileRevision:
    """Reject reference-only Profiles at the production authority seam."""

    if profile.reference_only:
        raise MetadataReviewValidationError(
            "production metadata binding rejects a reference-only Profile"
        )
    if (
        {value.code for value in profile.authority_values}
        != set(profile.authority_codes)
        or {
            value.code for value in profile.precedence_authority_tier_values
        }
        != set(profile.precedence_authority_tiers)
    ):
        raise MetadataReviewValidationError(
            "production metadata Profile requires labels for every governed code"
        )
    return profile


def _replace_review(
    current: InsuranceMetadataReviewSet,
    updated: InsuranceMetadataReviewV2,
) -> InsuranceMetadataReviewSet:
    replacements = tuple(
        updated if review.review_id == updated.review_id else review
        for review in current.reviews
    )
    if replacements == current.reviews:
        raise KeyError(updated.review_id)
    generation = current.generation + 1
    identity = _sha256(
        {
            "source_id": current.source_id,
            "document_id": current.document_id,
            "revision_id": current.revision_id,
            "structured_build_id": current.structured_build_id,
            "profile_revision_id": current.profile_revision_id,
            "generation": generation,
            "reviews": [review.review_identity for review in replacements],
        }
    )
    return InsuranceMetadataReviewSet.model_validate(
        {
            **current.model_dump(),
            "review_set_identity": identity,
            "generation": generation,
            "reviews": tuple(review.model_dump() for review in replacements),
        }
    )


def advance_insurance_metadata_review_set(
    current: InsuranceMetadataReviewSet,
    updated_review: InsuranceMetadataReviewV2,
) -> InsuranceMetadataReviewSet:
    """Advance one Review Set generation after an exact review command."""

    return _replace_review(current, updated_review)


def create_insurance_metadata_override(
    current: InsuranceMetadataReviewSet,
    *,
    canonical_anchor: str,
    profile: InsuranceMetadataProfileRevision,
    actor: str,
    reason: str,
    changes: Mapping[str, str | int | date | None],
    action: Literal["save_draft", "workbook_apply"] = "save_draft",
) -> MetadataReviewSetCommandResult:
    """Create one explicit current Rule Unit exception from the Document Default."""

    anchor = _nonblank(canonical_anchor, "canonical_anchor")
    if current.profile_revision_id != profile.profile_revision_id:
        raise MetadataReviewConflictError("metadata Profile binding changed")
    if any(review.canonical_anchor == anchor for review in current.reviews[1:]):
        raise MetadataReviewConflictError("metadata override already exists")
    default = current.reviews[0]
    baseline_identity = _sha256(
        {
            "source_id": current.source_id,
            "document_id": current.document_id,
            "revision_id": current.revision_id,
            "structured_build_id": current.structured_build_id,
            "canonical_anchor": anchor,
            "kind": "operator_override_baseline",
        }
    )
    baseline = default.current_draft.model_copy(
        update={
            "metadata_draft_id": f"operator-baseline-{baseline_identity[:24]}"
        }
    )
    initial = _review(
        source_id=current.source_id,
        structured_build_id=current.structured_build_id,
        profile=profile,
        scope="rule_unit_override",
        canonical_anchor=anchor,
        proposal=baseline,
    )
    command = save_metadata_review_draft(
        initial,
        profile=profile,
        expected_review_version=initial.review_version,
        expected_review_identity=initial.review_identity,
        actor=actor,
        reason=reason,
        changes=changes,
        action=action,
    )
    generation = current.generation + 1
    reviews = (*current.reviews, command.review)
    review_set_identity = _sha256(
        {
            "source_id": current.source_id,
            "document_id": current.document_id,
            "revision_id": current.revision_id,
            "structured_build_id": current.structured_build_id,
            "profile_revision_id": current.profile_revision_id,
            "generation": generation,
            "reviews": [review.review_identity for review in reviews],
        }
    )
    review_set = InsuranceMetadataReviewSet.model_validate(
        {
            **current.model_dump(),
            "review_set_identity": review_set_identity,
            "generation": generation,
            "reviews": tuple(review.model_dump() for review in reviews),
        }
    )
    return MetadataReviewSetCommandResult(
        review_set=review_set,
        decision=command.decision,
    )


def create_insurance_metadata_review_set(
    *,
    source_id: str,
    structured_build_id: str,
    profile: InsuranceMetadataProfileRevision,
    document_default: InsuranceRuleMetadataDraft,
    parser_proposals: Iterable[InsuranceMetadataDraftInput],
    canonical_anchors: Iterable[str] | None = None,
) -> InsuranceMetadataReviewSet:
    """Create one complete current Review Set without requiring a Workbook."""

    supplied_proposals = tuple(parser_proposals)
    document_id = document_default.document_id
    revision_id = document_default.revision_id
    anchors = [proposal.canonical_anchor for proposal in supplied_proposals]
    if any(anchor is None for anchor in anchors) or len(anchors) != len(set(anchors)):
        raise ValueError("metadata parser proposals require unique Rule Unit anchors")
    for proposal in supplied_proposals:
        if (
            proposal.origin != "pdf"
            or proposal.source_id != source_id
            or proposal.document_id != document_id
            or proposal.revision_id != revision_id
        ):
            raise ValueError("metadata parser proposal does not match the completed build")
    expected_anchors = (
        tuple(canonical_anchors)
        if canonical_anchors is not None
        else tuple(anchor for anchor in anchors if anchor is not None)
    )
    if (
        any(not anchor.strip() for anchor in expected_anchors)
        or len(expected_anchors) != len(set(expected_anchors))
    ):
        raise ValueError("metadata canonical anchors must be nonblank and unique")
    proposal_by_anchor = {
        proposal.canonical_anchor: proposal for proposal in supplied_proposals
    }
    if set(proposal_by_anchor) - set(expected_anchors):
        raise ValueError("metadata parser proposal is outside the canonical anchor set")
    proposals: list[InsuranceMetadataDraftInput] = []
    for anchor in expected_anchors:
        selected_proposal = proposal_by_anchor.get(anchor)
        if selected_proposal is None:
            material = {
                "source_id": source_id,
                "document_id": document_id,
                "revision_id": revision_id,
                "structured_build_id": structured_build_id,
                "canonical_anchor": anchor,
                "proposal": "missing",
            }
            selected_proposal = InsuranceMetadataDraftInput(
                metadata_draft_id=f"pdf-metadata-{_sha256(material)[:24]}",
                origin="pdf",
                source_id=source_id,
                document_id=document_id,
                revision_id=revision_id,
                canonical_anchor=anchor,
            )
        proposals.append(selected_proposal)

    reviews = [
        _review(
            source_id=source_id,
            structured_build_id=structured_build_id,
            profile=profile,
            scope="document_default",
            canonical_anchor=None,
            proposal=document_default,
        )
    ]
    for proposal in proposals:
        normalized = _normalize_parser_proposal(proposal)
        if not _is_complete(normalized, profile) or not _same_metadata_values(
            normalized, document_default
        ):
            reviews.append(
                _review(
                    source_id=source_id,
                    structured_build_id=structured_build_id,
                    profile=profile,
                    scope="rule_unit_override",
                    canonical_anchor=proposal.canonical_anchor,
                    proposal=normalized,
                )
            )

    identity_material = {
        "source_id": source_id,
        "document_id": document_id,
        "revision_id": revision_id,
        "structured_build_id": structured_build_id,
        "profile_revision_id": profile.profile_revision_id,
        "reviews": [review.review_identity for review in reviews],
    }
    identity = _sha256(identity_material)
    return InsuranceMetadataReviewSet(
        review_set_id=f"metadata-review-set-{identity[:24]}",
        review_set_identity=identity,
        source_id=source_id,
        document_id=document_id,
        revision_id=revision_id,
        structured_build_id=structured_build_id,
        profile_revision_id=profile.profile_revision_id,
        reviews=tuple(reviews),
    )


def save_metadata_review_draft(
    current: InsuranceMetadataReviewV2,
    *,
    profile: InsuranceMetadataProfileRevision,
    expected_review_version: int,
    expected_review_identity: str,
    actor: str,
    reason: str,
    changes: Mapping[str, str | int | date | None],
    action: Literal["save_draft", "workbook_apply"] = "save_draft",
) -> MetadataReviewCommandResult:
    """Explicitly save one optimistic Current Review Draft change."""

    _require_current_identity(
        current,
        expected_review_version=expected_review_version,
        expected_review_identity=expected_review_identity,
    )
    if current.state in {"approved", "rejected"}:
        raise MetadataReviewConflictError(
            "terminal metadata review requires a new current revision"
        )
    if current.profile_revision_id != profile.profile_revision_id:
        raise MetadataReviewConflictError("metadata Profile binding changed")
    normalized_actor = _nonblank(actor, "actor")
    normalized_reason = _nonblank(reason, "reason")
    if not changes:
        raise MetadataReviewValidationError("Save Draft requires at least one change")
    allowed = {
        "authority",
        "effective_from",
        "effective_to",
        "taxonomy_id",
        "taxonomy_revision_id",
        "precedence_policy_revision_id",
        "precedence_authority_tier",
        "precedence_order",
    }
    unknown = set(changes) - allowed
    if unknown:
        raise MetadataReviewValidationError("Save Draft contains unknown metadata fields")
    values = _flat_metadata_values(current.current_draft)
    values.update(changes)
    draft = _draft_from_flat_values(current.current_draft, values)
    state: Literal["needs_input", "ready_for_approval"] = (
        "ready_for_approval" if _is_complete(draft, profile) else "needs_input"
    )
    provisional = InsuranceMetadataReviewV2.model_validate(
        {
            **current.model_dump(),
            "review_identity": "0" * 64,
            "review_version": current.review_version + 1,
            "state": state,
            "current_draft": draft.model_dump(),
        }
    )
    resulting_identity = _sha256(
        provisional.model_dump(mode="json", exclude={"review_identity"})
    )
    updated = InsuranceMetadataReviewV2.model_validate(
        {**provisional.model_dump(), "review_identity": resulting_identity}
    )
    decision_material = {
        "review_id": current.review_id,
        "prior_review_identity": current.review_identity,
        "resulting_review_identity": resulting_identity,
        "action": action,
        "actor": normalized_actor,
        "reason": normalized_reason,
        "changed_fields": sorted(changes),
    }
    decision = InsuranceMetadataReviewDecisionV2(
        decision_id=f"metadata-review-decision-{_sha256(decision_material)[:24]}",
        prior_review_identity=current.review_identity,
        resulting_review_identity=resulting_identity,
        action=action,
        actor=normalized_actor,
        reason=normalized_reason,
        changed_fields=tuple(sorted(changes)),
    )
    return MetadataReviewCommandResult(review=updated, decision=decision)


def approve_metadata_review(
    current: InsuranceMetadataReviewV2,
    *,
    profile: InsuranceMetadataProfileRevision,
    expected_review_version: int,
    expected_review_identity: str,
    actor: str,
    reason: str,
) -> MetadataReviewCommandResult:
    """Approve one exact ready Current Review revision."""

    _require_current_identity(
        current,
        expected_review_version=expected_review_version,
        expected_review_identity=expected_review_identity,
    )
    if current.profile_revision_id != profile.profile_revision_id:
        raise MetadataReviewConflictError("metadata Profile binding changed")
    if current.state != "ready_for_approval" or not _is_complete(
        current.current_draft, profile
    ):
        raise MetadataReviewConflictError(
            "only a complete ready metadata review can be approved"
        )
    normalized_actor = _nonblank(actor, "actor")
    normalized_reason = _nonblank(reason, "reason")
    approved_material = {
        "source_id": current.source_id,
        "document_id": current.document_id,
        "revision_id": current.revision_id,
        "structured_build_id": current.structured_build_id,
        "profile_revision_id": current.profile_revision_id,
        "scope": current.scope,
        "canonical_anchor": current.canonical_anchor,
        "metadata": current.current_draft.model_dump(mode="json"),
    }
    approved_id = f"approved-metadata-{_sha256(approved_material)[:24]}"
    provisional = InsuranceMetadataReviewV2.model_validate(
        {
            **current.model_dump(),
            "review_identity": "0" * 64,
            "review_version": current.review_version + 1,
            "state": "approved",
            "approved_metadata_revision_id": approved_id,
        }
    )
    resulting_identity = _sha256(
        provisional.model_dump(mode="json", exclude={"review_identity"})
    )
    updated = InsuranceMetadataReviewV2.model_validate(
        {**provisional.model_dump(), "review_identity": resulting_identity}
    )
    decision_material = {
        "review_id": current.review_id,
        "prior_review_identity": current.review_identity,
        "resulting_review_identity": resulting_identity,
        "action": "approve",
        "actor": normalized_actor,
        "reason": normalized_reason,
    }
    decision = InsuranceMetadataReviewDecisionV2(
        decision_id=f"metadata-review-decision-{_sha256(decision_material)[:24]}",
        prior_review_identity=current.review_identity,
        resulting_review_identity=resulting_identity,
        action="approve",
        actor=normalized_actor,
        reason=normalized_reason,
    )
    return MetadataReviewCommandResult(review=updated, decision=decision)


def reject_metadata_review(
    current: InsuranceMetadataReviewV2,
    *,
    expected_review_version: int,
    expected_review_identity: str,
    actor: str,
    reason: str,
) -> MetadataReviewCommandResult:
    """Reject one exact non-terminal Current Review revision."""

    _require_current_identity(
        current,
        expected_review_version=expected_review_version,
        expected_review_identity=expected_review_identity,
    )
    if current.state in {"approved", "rejected"}:
        raise MetadataReviewConflictError(
            "terminal metadata review requires a new current revision"
        )
    normalized_actor = _nonblank(actor, "actor")
    normalized_reason = _nonblank(reason, "reason")
    provisional = InsuranceMetadataReviewV2.model_validate(
        {
            **current.model_dump(),
            "review_identity": "0" * 64,
            "review_version": current.review_version + 1,
            "state": "rejected",
            "approved_metadata_revision_id": None,
        }
    )
    resulting_identity = _sha256(
        provisional.model_dump(mode="json", exclude={"review_identity"})
    )
    updated = InsuranceMetadataReviewV2.model_validate(
        {**provisional.model_dump(), "review_identity": resulting_identity}
    )
    decision_material = {
        "review_id": current.review_id,
        "prior_review_identity": current.review_identity,
        "resulting_review_identity": resulting_identity,
        "action": "reject",
        "actor": normalized_actor,
        "reason": normalized_reason,
    }
    decision = InsuranceMetadataReviewDecisionV2(
        decision_id=f"metadata-review-decision-{_sha256(decision_material)[:24]}",
        prior_review_identity=current.review_identity,
        resulting_review_identity=resulting_identity,
        action="reject",
        actor=normalized_actor,
        reason=normalized_reason,
    )
    return MetadataReviewCommandResult(review=updated, decision=decision)


def approved_insurance_metadata_revision(
    review: InsuranceMetadataReviewV2,
) -> ApprovedInsuranceRuleMetadataRevision:
    """Reconstruct and verify one immutable approved V2 metadata authority."""

    if (
        not review.current
        or review.state != "approved"
        or review.approved_metadata_revision_id is None
    ):
        raise MetadataReviewConflictError(
            "metadata review is not current approved authority"
        )
    draft = review.current_draft
    if (
        draft.authority is None
        or draft.applicability is None
        or draft.precedence is None
    ):
        raise MetadataReviewConflictError("approved metadata review is incomplete")
    approved_material = {
        "source_id": review.source_id,
        "document_id": review.document_id,
        "revision_id": review.revision_id,
        "structured_build_id": review.structured_build_id,
        "profile_revision_id": review.profile_revision_id,
        "scope": review.scope,
        "canonical_anchor": review.canonical_anchor,
        "metadata": draft.model_dump(mode="json"),
    }
    expected_id = f"approved-metadata-{_sha256(approved_material)[:24]}"
    if review.approved_metadata_revision_id != expected_id:
        raise MetadataReviewConflictError(
            "approved metadata revision identity diverged"
        )
    return ApprovedInsuranceRuleMetadataRevision(
        metadata_revision_id=expected_id,
        applicability=draft.applicability,
        effective_from=draft.effective_from,
        effective_to=draft.effective_to,
        authority=draft.authority,
        precedence=draft.precedence,
        supersedes_rule_unit_revision_ids=(
            draft.supersedes_rule_unit_revision_ids
        ),
    )


def approved_insurance_metadata_for_anchor(
    review_set: InsuranceMetadataReviewSet,
    canonical_anchor: str,
) -> ApprovedInsuranceRuleMetadataRevision:
    """Resolve one Rule Unit through approved Override then approved Default."""

    anchor = _nonblank(canonical_anchor, "canonical_anchor")
    selected = next(
        (
            review
            for review in review_set.reviews[1:]
            if review.canonical_anchor == anchor
        ),
        review_set.reviews[0],
    )
    return approved_insurance_metadata_revision(selected)


def _review(
    *,
    source_id: str,
    structured_build_id: str,
    profile: InsuranceMetadataProfileRevision,
    scope: Literal["document_default", "rule_unit_override"],
    canonical_anchor: str | None,
    proposal: InsuranceRuleMetadataDraft,
) -> InsuranceMetadataReviewV2:
    state: Literal["needs_input", "ready_for_approval"] = (
        "ready_for_approval" if _is_complete(proposal, profile) else "needs_input"
    )
    material = {
        "source_id": source_id,
        "document_id": proposal.document_id,
        "revision_id": proposal.revision_id,
        "structured_build_id": structured_build_id,
        "profile_revision_id": profile.profile_revision_id,
        "scope": scope,
        "canonical_anchor": canonical_anchor,
        "parser_proposal": proposal.model_dump(mode="json"),
        "state": state,
    }
    identity = _sha256(material)
    return InsuranceMetadataReviewV2(
        review_id=f"metadata-review-{identity[:24]}",
        review_identity=identity,
        review_version=1,
        source_id=source_id,
        document_id=proposal.document_id,
        revision_id=proposal.revision_id,
        structured_build_id=structured_build_id,
        profile_revision_id=profile.profile_revision_id,
        scope=scope,
        canonical_anchor=canonical_anchor,
        state=state,
        parser_proposal=proposal,
        current_draft=proposal,
    )


def _normalize_parser_proposal(
    proposal: InsuranceMetadataDraftInput,
) -> InsuranceRuleMetadataDraft:
    applicability = None
    if proposal.taxonomy_id is not None and proposal.taxonomy_revision_id is not None:
        applicability = InsuranceRuleApplicability(
            taxonomy_id=proposal.taxonomy_id,
            taxonomy_revision_id=proposal.taxonomy_revision_id,
        )
    precedence = None
    if (
        proposal.precedence_policy_revision_id is not None
        and proposal.precedence_authority_tier is not None
        and proposal.precedence_order is not None
    ):
        precedence = InsuranceRulePrecedence(
            policy_revision_id=proposal.precedence_policy_revision_id,
            authority_tier=proposal.precedence_authority_tier,
            order=proposal.precedence_order,
        )
    return InsuranceRuleMetadataDraft(
        metadata_draft_id=proposal.metadata_draft_id,
        document_id=proposal.document_id,
        revision_id=proposal.revision_id,
        applicability=applicability,
        effective_from=proposal.effective_from,
        effective_to=proposal.effective_to,
        authority=proposal.authority,
        precedence=precedence,
    )


def _is_complete(
    proposal: InsuranceRuleMetadataDraft,
    profile: InsuranceMetadataProfileRevision,
) -> bool:
    applicability = proposal.applicability
    precedence = proposal.precedence
    return bool(
        proposal.authority in profile.authority_codes
        and applicability is not None
        and applicability.taxonomy_id == profile.taxonomy_id
        and applicability.taxonomy_revision_id == profile.taxonomy_revision_id
        and precedence is not None
        and precedence.policy_revision_id == profile.precedence_policy_revision_id
        and precedence.authority_tier in profile.precedence_authority_tiers
    )


def _same_metadata_values(
    left: InsuranceRuleMetadataDraft,
    right: InsuranceRuleMetadataDraft,
) -> bool:
    excluded = {"metadata_draft_id", "document_id", "revision_id", "authoritative"}
    return left.model_dump(exclude=excluded) == right.model_dump(exclude=excluded)


def _flat_metadata_values(
    draft: InsuranceRuleMetadataDraft,
) -> dict[str, str | int | date | None]:
    applicability = draft.applicability
    precedence = draft.precedence
    return {
        "authority": draft.authority,
        "effective_from": draft.effective_from,
        "effective_to": draft.effective_to,
        "taxonomy_id": None if applicability is None else applicability.taxonomy_id,
        "taxonomy_revision_id": (
            None if applicability is None else applicability.taxonomy_revision_id
        ),
        "precedence_policy_revision_id": (
            None if precedence is None else precedence.policy_revision_id
        ),
        "precedence_authority_tier": (
            None if precedence is None else precedence.authority_tier
        ),
        "precedence_order": None if precedence is None else precedence.order,
    }


def _draft_from_flat_values(
    prior: InsuranceRuleMetadataDraft,
    values: Mapping[str, str | int | date | None],
) -> InsuranceRuleMetadataDraft:
    taxonomy_id = values["taxonomy_id"]
    taxonomy_revision_id = values["taxonomy_revision_id"]
    applicability = None
    if isinstance(taxonomy_id, str) and isinstance(taxonomy_revision_id, str):
        applicability = InsuranceRuleApplicability(
            taxonomy_id=taxonomy_id,
            taxonomy_revision_id=taxonomy_revision_id,
        )
    policy_revision_id = values["precedence_policy_revision_id"]
    authority_tier = values["precedence_authority_tier"]
    order = values["precedence_order"]
    precedence = None
    if (
        isinstance(policy_revision_id, str)
        and isinstance(authority_tier, str)
        and type(order) is int
    ):
        precedence = InsuranceRulePrecedence(
            policy_revision_id=policy_revision_id,
            authority_tier=authority_tier,
            order=order,
        )
    material = {
        "prior_draft_id": prior.metadata_draft_id,
        "values": dict(values),
    }
    effective_from = values["effective_from"]
    effective_to = values["effective_to"]
    authority = values["authority"]
    if effective_from is not None and not isinstance(effective_from, date):
        raise MetadataReviewValidationError("effective_from must be a date")
    if effective_to is not None and not isinstance(effective_to, date):
        raise MetadataReviewValidationError("effective_to must be a date")
    if authority is not None and not isinstance(authority, str):
        raise MetadataReviewValidationError("authority must be text")
    return InsuranceRuleMetadataDraft(
        metadata_draft_id=f"metadata-review-draft-{_sha256(material)[:24]}",
        document_id=prior.document_id,
        revision_id=prior.revision_id,
        applicability=applicability,
        effective_from=effective_from,
        effective_to=effective_to,
        authority=authority,
        precedence=precedence,
        supersedes_rule_unit_revision_ids=prior.supersedes_rule_unit_revision_ids,
        proposed_visibility=prior.proposed_visibility,
    )


def _require_current_identity(
    current: InsuranceMetadataReviewV2,
    *,
    expected_review_version: int,
    expected_review_identity: str,
) -> None:
    if not current.current:
        raise MetadataReviewConflictError("metadata review is historical")
    if (
        current.review_version != expected_review_version
        or current.review_identity != expected_review_identity
    ):
        raise MetadataReviewConflictError("metadata review changed; reload exact identity")


def _nonblank(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise MetadataReviewValidationError(f"{field} must not be blank")
    return normalized


def _sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "FilesystemInsuranceMetadataReviewV2Repository",
    "InsuranceMetadataProfileRevision",
    "InsuranceMetadataProfileValue",
    "InsuranceMetadataReviewDecisionV2",
    "InsuranceMetadataReviewPageV2",
    "InsuranceMetadataReviewSet",
    "InsuranceMetadataReviewSummaryV2",
    "InsuranceMetadataReviewV2",
    "MetadataReviewCommandResult",
    "MetadataReviewSetCommandResult",
    "MetadataReviewConflictError",
    "MetadataReviewValidationError",
    "approved_insurance_metadata_for_anchor",
    "approved_insurance_metadata_revision",
    "approve_metadata_review",
    "advance_insurance_metadata_review_set",
    "create_insurance_metadata_review_set",
    "create_insurance_metadata_override",
    "proofagent_insurance_reference_profile",
    "reject_metadata_review",
    "require_production_metadata_profile",
    "save_metadata_review_draft",
]
