from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Annotated, Literal, Self, TypeAlias

from pydantic import (
    AfterValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from proof_agent.contracts._base import FrozenModel
from proof_agent.contracts.hybrid_documents import BoundingBox


NonBlankStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
FiniteStrictFloat = Annotated[float, Field(strict=True, allow_inf_nan=False)]
TaxonomyValue: TypeAlias = StrictStr | StrictInt | StrictBool | FiniteStrictFloat
BusinessDate = Annotated[date, Field(strict=True)]


def _canonicalize_identifier_set(values: tuple[str, ...]) -> tuple[str, ...]:
    if len(values) != len(set(values)):
        raise ValueError("identifier collection values must be unique")
    return tuple(sorted(values))


CanonicalIdentifierSet = Annotated[
    tuple[NonBlankStr, ...], AfterValidator(_canonicalize_identifier_set)
]


class _InsuranceRuleModel(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ScopeDimension(_InsuranceRuleModel):
    mode: Literal["ALL", "ALLOWLIST"]
    values: CanonicalIdentifierSet = ()

    @model_validator(mode="after")
    def validate_values(self) -> Self:
        if self.mode == "ALLOWLIST" and not self.values:
            raise ValueError("ALLOWLIST requires at least one value")
        if self.mode == "ALL" and self.values:
            raise ValueError("ALL does not accept values")
        return self


class _InsuranceKnowledgeVisibilityScope(_InsuranceRuleModel):
    visibility: Literal["PUBLIC", "RESTRICTED"]
    institutions: ScopeDimension | None = None
    regions: ScopeDimension | None = None
    channels: ScopeDimension | None = None
    roles: ScopeDimension | None = None
    business_lines: ScopeDimension | None = None

    @model_validator(mode="after")
    def validate_dimensions(self) -> Self:
        dimensions = (
            self.institutions,
            self.regions,
            self.channels,
            self.roles,
            self.business_lines,
        )
        if self.visibility == "RESTRICTED" and any(value is None for value in dimensions):
            raise ValueError("RESTRICTED visibility requires every dimension mode")
        if self.visibility == "PUBLIC" and any(value is not None for value in dimensions):
            raise ValueError("PUBLIC visibility does not accept dimension scopes")
        return self


class ProposedInsuranceKnowledgeVisibilityScope(_InsuranceKnowledgeVisibilityScope):
    """Non-authoritative visibility values awaiting business approval."""


class ApprovedInsuranceKnowledgeVisibilityScope(_InsuranceKnowledgeVisibilityScope):
    revision_id: NonBlankStr


class TaxonomyCondition(_InsuranceRuleModel):
    key: NonBlankStr
    operator: Literal["EQ", "IN", "NOT_EQ", "NOT_IN"]
    values: tuple[TaxonomyValue, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_cardinality(self) -> Self:
        if self.operator in {"EQ", "NOT_EQ"} and len(self.values) != 1:
            raise ValueError(f"{self.operator} requires exactly one value")
        value_types = {type(value) for value in self.values}
        if len(value_types) != 1:
            raise ValueError("taxonomy condition values must use one exact scalar type")
        typed_values = {(type(value), value) for value in self.values}
        if len(typed_values) != len(self.values):
            raise ValueError("taxonomy condition values must be unique")
        return self


class InsuranceRuleApplicability(_InsuranceRuleModel):
    taxonomy_id: NonBlankStr
    taxonomy_revision_id: NonBlankStr
    conditions: tuple[TaxonomyCondition, ...] = ()

    @model_validator(mode="after")
    def validate_unique_keys(self) -> Self:
        keys = [condition.key for condition in self.conditions]
        if len(keys) != len(set(keys)):
            raise ValueError("applicability condition keys must be unique")
        return self


class InsuranceRulePrecedence(_InsuranceRuleModel):
    policy_revision_id: NonBlankStr
    authority_tier: NonBlankStr
    order: Annotated[StrictInt, Field(ge=0)]


class _InsuranceRuleMetadata(_InsuranceRuleModel):
    applicability: InsuranceRuleApplicability
    effective_from: BusinessDate | None = None
    effective_to: BusinessDate | None = None
    authority: NonBlankStr
    precedence: InsuranceRulePrecedence
    supersedes_rule_unit_revision_ids: CanonicalIdentifierSet = ()

    @model_validator(mode="after")
    def validate_effective_period(self) -> Self:
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_to < self.effective_from
        ):
            raise ValueError("effective_to must be on or after effective_from")
        return self


class InsuranceRuleMetadataDraft(_InsuranceRuleModel):
    metadata_draft_id: NonBlankStr
    document_id: NonBlankStr
    revision_id: NonBlankStr
    authoritative: StrictBool = False
    applicability: InsuranceRuleApplicability | None = None
    effective_from: BusinessDate | None = None
    effective_to: BusinessDate | None = None
    authority: NonBlankStr | None = None
    precedence: InsuranceRulePrecedence | None = None
    supersedes_rule_unit_revision_ids: CanonicalIdentifierSet = ()
    proposed_visibility: ProposedInsuranceKnowledgeVisibilityScope | None = None

    @field_validator("authoritative")
    @classmethod
    def validate_non_authoritative(cls, value: bool) -> bool:
        if value:
            raise ValueError("an Insurance Rule Metadata Draft is never authoritative")
        return value

    @model_validator(mode="after")
    def validate_effective_period(self) -> Self:
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_to < self.effective_from
        ):
            raise ValueError("effective_to must be on or after effective_from")
        return self


class ApprovedInsuranceRuleMetadataRevision(_InsuranceRuleMetadata):
    metadata_revision_id: NonBlankStr


class InsuranceRulePageBoundingBox(_InsuranceRuleModel):
    page_number: Annotated[StrictInt, Field(gt=0)]
    bbox: BoundingBox

    @model_validator(mode="after")
    def validate_nonnegative_geometry(self) -> Self:
        if min(self.bbox.x0, self.bbox.y0, self.bbox.x1, self.bbox.y1) < 0:
            raise ValueError("rule lineage page geometry must be nonnegative")
        return self


class InsuranceRuleCellCoordinate(_InsuranceRuleModel):
    page_number: Annotated[StrictInt, Field(gt=0)]
    row: Annotated[StrictInt, Field(ge=0)]
    column: Annotated[StrictInt, Field(ge=0)]
    row_span: Annotated[StrictInt, Field(gt=0)]
    column_span: Annotated[StrictInt, Field(gt=0)]
    bbox: BoundingBox


class InsuranceRuleUnitLineage(_InsuranceRuleModel):
    """Inspectable canonical context retained by one immutable rule-unit revision."""

    source_id: NonBlankStr
    original_sha256: Sha256
    heading_path: tuple[NonBlankStr, ...] = ()
    definitions: tuple[NonBlankStr, ...] = ()
    page_numbers: tuple[Annotated[StrictInt, Field(gt=0)], ...] = Field(min_length=1)
    page_bboxes: tuple[InsuranceRulePageBoundingBox, ...] = Field(min_length=1)
    block_ids: tuple[NonBlankStr, ...] = ()
    table_id: NonBlankStr | None = None
    table_continuation_id: NonBlankStr | None = None
    table_title: NonBlankStr | None = None
    table_headers: tuple[NonBlankStr, ...] = ()
    row_header: NonBlankStr | None = None
    row_numbers: tuple[Annotated[StrictInt, Field(ge=0)], ...] = ()
    header_cell_coordinates: tuple[InsuranceRuleCellCoordinate, ...] = ()
    cell_coordinates: tuple[InsuranceRuleCellCoordinate, ...] = ()

    @model_validator(mode="after")
    def validate_canonical_lineage(self) -> Self:
        if tuple(sorted(set(self.page_numbers))) != self.page_numbers:
            raise ValueError("lineage page_numbers must be strictly increasing and unique")
        bbox_pages = tuple(item.page_number for item in self.page_bboxes)
        if tuple(sorted(set(bbox_pages))) != bbox_pages:
            raise ValueError("lineage page_bboxes must contain one region per page")
        if set(bbox_pages) != set(self.page_numbers):
            raise ValueError("lineage page_bboxes must cover exactly the page_numbers")
        if len(self.block_ids) != len(set(self.block_ids)):
            raise ValueError("lineage block_ids must be unique")
        if len(self.definitions) != len(set(self.definitions)):
            raise ValueError("lineage definitions must be unique")
        if tuple(sorted(set(self.row_numbers))) != self.row_numbers:
            raise ValueError("lineage row_numbers must be strictly increasing and unique")
        if self.table_continuation_id is not None and self.table_continuation_id == self.table_id:
            raise ValueError("lineage table continuation cannot reference itself")
        page_regions = {item.page_number: item.bbox for item in self.page_bboxes}
        coordinates = (*self.header_cell_coordinates, *self.cell_coordinates)
        coordinate_keys = [(item.page_number, item.row, item.column) for item in coordinates]
        if len(coordinate_keys) != len(set(coordinate_keys)):
            raise ValueError("lineage table cell coordinate anchors must be unique")
        for coordinate in coordinates:
            region = page_regions.get(coordinate.page_number)
            if region is None or not _bbox_contains(region, coordinate.bbox):
                raise ValueError("lineage table cell coordinates must stay within page geometry")
        return self


class InsuranceRuleUnitRevision(_InsuranceRuleModel):
    rule_unit_revision_id: NonBlankStr
    logical_rule_key: NonBlankStr
    unit_kind: Literal["document", "clause", "section", "table_row", "row_group"]
    document_id: NonBlankStr
    revision_id: NonBlankStr
    structured_build_id: NonBlankStr
    content: NonBlankStr
    citation_uri: NonBlankStr
    metadata_revision_id: NonBlankStr
    visibility_scope: ApprovedInsuranceKnowledgeVisibilityScope
    content_sha256: Sha256
    authority_sha256: Sha256
    lineage: InsuranceRuleUnitLineage

    @model_validator(mode="after")
    def validate_coherent_lineage(self) -> Self:
        table_kind = self.unit_kind in {"table_row", "row_group"}
        lineage = self.lineage
        table_fields_present = any(
            (
                lineage.table_id is not None,
                lineage.table_continuation_id is not None,
                lineage.table_title is not None,
                bool(lineage.table_headers),
                lineage.row_header is not None,
                bool(lineage.row_numbers),
                bool(lineage.header_cell_coordinates),
                bool(lineage.cell_coordinates),
            )
        )
        if table_kind:
            if lineage.table_id is None or lineage.row_header is None or not lineage.row_numbers:
                raise ValueError("table rule revisions require table and row lineage")
            if len(lineage.cell_coordinates) < 2:
                raise ValueError("table rule revisions require coherent multi-cell evidence")
            if len({coordinate.column for coordinate in lineage.cell_coordinates}) < 2:
                raise ValueError("table rule revisions require row-header and data columns")
            covered_rows = _merge_integer_intervals(
                (
                    (coordinate.row, coordinate.row + coordinate.row_span - 1)
                    for coordinate in lineage.cell_coordinates
                )
            )
            expected_rows = _merge_integer_intervals(
                (row_number, row_number) for row_number in lineage.row_numbers
            )
            if covered_rows != expected_rows:
                raise ValueError("table cell coordinates must cover exactly the lineage rows")
            if self.unit_kind == "table_row" and len(lineage.row_numbers) != 1:
                raise ValueError("table_row revisions require exactly one row")
            if self.unit_kind == "row_group" and len(lineage.row_numbers) < 2:
                raise ValueError("row_group revisions require at least two rows")
            if lineage.block_ids:
                raise ValueError("table rule revisions cannot claim block lineage")
        elif table_fields_present:
            raise ValueError("non-table rule revisions cannot contain table lineage")
        elif self.unit_kind in {"clause", "section"} and not lineage.block_ids:
            raise ValueError("clause and section revisions require block lineage")
        return self


def _bbox_contains(outer: BoundingBox, inner: BoundingBox) -> bool:
    return (
        outer.x0 <= inner.x0 <= inner.x1 <= outer.x1
        and outer.y0 <= inner.y0 <= inner.y1 <= outer.y1
    )


def _merge_integer_intervals(
    intervals: Iterable[tuple[int, int]],
) -> tuple[tuple[int, int], ...]:
    ordered = sorted(intervals)
    if not ordered:
        return ()
    merged: list[tuple[int, int]] = []
    current_start, current_end = ordered[0]
    for start, end in ordered[1:]:
        if start <= current_end + 1:
            current_end = max(current_end, end)
        else:
            merged.append((current_start, current_end))
            current_start, current_end = start, end
    merged.append((current_start, current_end))
    return tuple(merged)


EvidenceRequirementKind: TypeAlias = Literal[
    "requested_clause",
    "required_definition",
    "governing_rule",
    "applicable_condition",
    "exclusion_or_exception",
    "precedence_source",
    "comparison_basis",
]


class InsuranceEvidenceSlotRequirement(_InsuranceRuleModel):
    slot_id: NonBlankStr
    requirement_kind: EvidenceRequirementKind
    subject_id: NonBlankStr
    scope: InsuranceRuleApplicability | None = None
    required_rule_unit_revision_ids: CanonicalIdentifierSet = ()


AuthorityGateCheckName: TypeAlias = Literal[
    "published_version",
    "visibility",
    "publication_membership",
    "effective_period",
    "applicability",
    "precedence",
    "authorization",
    "citation",
    "metadata_digest",
    "visibility_digest",
]

_REQUIRED_AUTHORITY_CHECKS = frozenset(
    {
        "published_version",
        "visibility",
        "publication_membership",
        "effective_period",
        "applicability",
        "precedence",
        "authorization",
        "citation",
        "metadata_digest",
        "visibility_digest",
    }
)


class AuthorityGateCheck(_InsuranceRuleModel):
    check: AuthorityGateCheckName
    passed: StrictBool
    reason_code: NonBlankStr | None = None

    @model_validator(mode="after")
    def validate_reason(self) -> Self:
        if not self.passed and self.reason_code is None:
            raise ValueError("a failed authority check requires a reason_code")
        if self.passed and self.reason_code is not None:
            raise ValueError("a passing authority check does not accept a reason_code")
        return self


class InsuranceRuleAuthorityGateResult(_InsuranceRuleModel):
    outcome: Literal["PASS", "FAIL"]
    rule_unit_revision_id: NonBlankStr
    checks: tuple[AuthorityGateCheck, ...]
    failure_handling: Literal["clarify", "conflict", "no_recommendation"] | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        check_names = [check.check for check in self.checks]
        if len(check_names) != len(set(check_names)):
            raise ValueError("authority checks must not be duplicated")
        if set(check_names) != _REQUIRED_AUTHORITY_CHECKS:
            raise ValueError("authority gate requires every authority check exactly once")

        all_passed = all(check.passed for check in self.checks)
        if self.outcome == "PASS" and not all_passed:
            raise ValueError("PASS requires every authority check to pass")
        if self.outcome == "PASS" and self.failure_handling is not None:
            raise ValueError("PASS does not accept failure_handling")
        if self.outcome == "FAIL" and all_passed:
            raise ValueError("FAIL requires at least one failed authority check")
        if self.outcome == "FAIL" and self.failure_handling is None:
            raise ValueError("FAIL requires terminal failure_handling")
        return self
