from __future__ import annotations

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
    model_validator,
)

from proof_agent.contracts._base import FrozenModel


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
    authoritative: Literal[False] = False
    applicability: InsuranceRuleApplicability | None = None
    effective_from: BusinessDate | None = None
    effective_to: BusinessDate | None = None
    authority: NonBlankStr | None = None
    precedence: InsuranceRulePrecedence | None = None
    supersedes_rule_unit_revision_ids: CanonicalIdentifierSet = ()
    proposed_visibility: ProposedInsuranceKnowledgeVisibilityScope | None = None

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
    passed: bool
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
