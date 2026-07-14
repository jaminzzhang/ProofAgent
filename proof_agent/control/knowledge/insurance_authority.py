"""Deterministic authority gate for insurance Rule Unit candidates."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any, Literal

from pydantic import Field, StrictBool, field_validator, model_validator

from proof_agent.contracts._base import FrozenDict, FrozenModel, freeze_value
from proof_agent.contracts.insurance_authorization import InstitutionAuthorizationContext
from proof_agent.contracts.insurance_rules import (
    AuthorityGateCheck,
    InsuranceRuleAuthorityGateResult,
)


class InsuranceAuthorityContext(FrozenModel):
    source_id: str = Field(min_length=1)
    index_generation_id: str = Field(min_length=1)
    index_uuid: str = Field(min_length=1)
    source_publication_seq: int = Field(gt=0)
    as_of_date: date
    authorization: InstitutionAuthorizationContext
    normalized_conditions: Mapping[str, str] = Field(default_factory=FrozenDict)

    @field_validator("normalized_conditions", mode="after")
    @classmethod
    def freeze_conditions(cls, value: Any) -> Any:
        return freeze_value(value)


class InsuranceAuthorityCandidate(FrozenModel):
    """Provider-neutral facts independently checked after relevance ranking."""

    rule_unit_revision_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    index_generation_id: str = Field(min_length=1)
    index_uuid: str = Field(min_length=1)
    publication_seq_from: int = Field(gt=0)
    publication_seq_to: int | None = Field(default=None, gt=0)
    visibility: Literal["PUBLIC", "RESTRICTED"]
    allowed_institutions: tuple[str, ...] = ()
    allowed_regions: tuple[str, ...] = ()
    allowed_channels: tuple[str, ...] = ()
    allowed_roles: tuple[str, ...] = ()
    allowed_business_lines: tuple[str, ...] = ()
    effective_from: date | None = None
    effective_to: date | None = None
    applicability_conditions: Mapping[str, str] = Field(default_factory=FrozenDict)
    precedence_conflict: StrictBool = False
    citation_uri: str = Field(min_length=1)
    manifest_citation_uri: str = Field(min_length=1)
    metadata_digest_valid: StrictBool
    visibility_digest_valid: StrictBool
    manifest_digest_valid: StrictBool

    @field_validator("applicability_conditions", mode="after")
    @classmethod
    def freeze_applicability(cls, value: Any) -> Any:
        return freeze_value(value)

    @model_validator(mode="after")
    def validate_intervals(self) -> InsuranceAuthorityCandidate:
        if (
            self.publication_seq_to is not None
            and self.publication_seq_to < self.publication_seq_from
        ):
            raise ValueError("publication membership interval is invalid")
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_to < self.effective_from
        ):
            raise ValueError("effective period is invalid")
        return self


class InsuranceAuthorityDecision(FrozenModel):
    admitted: bool
    outcome: Literal["admitted", "clarify", "conflict", "no_recommendation"]
    gate_result: InsuranceRuleAuthorityGateResult


_CHECK_ORDER = (
    "published_version",
    "metadata_digest",
    "visibility_digest",
    "publication_membership",
    "visibility",
    "authorization",
    "effective_period",
    "applicability",
    "precedence",
    "citation",
)


def evaluate_insurance_authority(
    candidate: InsuranceAuthorityCandidate,
    context: InsuranceAuthorityContext,
) -> InsuranceAuthorityDecision:
    """Apply the closed authority checks in a fixed, relevance-independent order."""

    checks_by_name: dict[str, tuple[bool, str]] = {
        "published_version": (
            candidate.source_id == context.source_id
            and candidate.index_generation_id == context.index_generation_id
            and candidate.index_uuid == context.index_uuid,
            "WRONG_PUBLISHED_VERSION",
        ),
        "metadata_digest": (
            candidate.metadata_digest_valid,
            "METADATA_DIGEST_MISMATCH",
        ),
        "visibility_digest": (
            candidate.visibility_digest_valid,
            "VISIBILITY_DIGEST_MISMATCH",
        ),
        "publication_membership": (
            candidate.manifest_digest_valid
            and candidate.publication_seq_from <= context.source_publication_seq
            and (
                candidate.publication_seq_to is None
                or candidate.publication_seq_to >= context.source_publication_seq
            ),
            "OUTSIDE_PUBLICATION_MEMBERSHIP",
        ),
        "visibility": (_visibility_shape_valid(candidate), "INVALID_VISIBILITY_SCOPE"),
        "authorization": (
            _authorization_allows(candidate, context.authorization),
            "ACL_MISMATCH",
        ),
        "effective_period": (
            _date_is_effective(candidate, context.as_of_date),
            "OUTSIDE_EFFECTIVE_PERIOD",
        ),
        "applicability": (
            _applicability_allows(candidate, context.normalized_conditions),
            "CONDITIONS_DO_NOT_MATCH",
        ),
        "precedence": (not candidate.precedence_conflict, "PRECEDENCE_CONFLICT"),
        "citation": (
            candidate.citation_uri == candidate.manifest_citation_uri,
            "CITATION_NOT_IN_MANIFEST",
        ),
    }
    checks = tuple(
        AuthorityGateCheck(
            check=name,  # type: ignore[arg-type]
            passed=checks_by_name[name][0],
            reason_code=None if checks_by_name[name][0] else checks_by_name[name][1],
        )
        for name in _CHECK_ORDER
    )
    failed_names = {check.check for check in checks if not check.passed}
    if not failed_names:
        gate = InsuranceRuleAuthorityGateResult(
            outcome="PASS",
            rule_unit_revision_id=candidate.rule_unit_revision_id,
            checks=checks,
        )
        return InsuranceAuthorityDecision(
            admitted=True,
            outcome="admitted",
            gate_result=gate,
        )
    failure_handling: Literal["clarify", "conflict", "no_recommendation"] = (
        "conflict"
        if "precedence" in failed_names
        else "clarify"
        if failed_names == {"applicability"}
        else "no_recommendation"
    )
    gate = InsuranceRuleAuthorityGateResult(
        outcome="FAIL",
        rule_unit_revision_id=candidate.rule_unit_revision_id,
        checks=checks,
        failure_handling=failure_handling,
    )
    return InsuranceAuthorityDecision(
        admitted=False,
        outcome=failure_handling,
        gate_result=gate,
    )


def _visibility_shape_valid(candidate: InsuranceAuthorityCandidate) -> bool:
    scopes = (
        candidate.allowed_institutions,
        candidate.allowed_regions,
        candidate.allowed_channels,
        candidate.allowed_roles,
        candidate.allowed_business_lines,
    )
    return candidate.visibility == "RESTRICTED" or not any(scopes)


def _authorization_allows(
    candidate: InsuranceAuthorityCandidate,
    authorization: InstitutionAuthorizationContext,
) -> bool:
    if candidate.visibility == "PUBLIC":
        return True
    if authorization.public_only:
        return False
    return all(
        not allowed or bool(set(allowed).intersection(admitted))
        for allowed, admitted in (
            (candidate.allowed_institutions, authorization.institutions),
            (candidate.allowed_regions, authorization.regions),
            (candidate.allowed_channels, authorization.channels),
            (candidate.allowed_roles, authorization.roles),
            (candidate.allowed_business_lines, authorization.business_lines),
        )
    )


def _date_is_effective(candidate: InsuranceAuthorityCandidate, as_of: date) -> bool:
    return not (
        (candidate.effective_from is not None and candidate.effective_from > as_of)
        or (candidate.effective_to is not None and candidate.effective_to < as_of)
    )


def _applicability_allows(
    candidate: InsuranceAuthorityCandidate,
    conditions: Mapping[str, str],
) -> bool:
    return all(
        conditions.get(key) == value for key, value in candidate.applicability_conditions.items()
    )


__all__ = [
    "InsuranceAuthorityCandidate",
    "InsuranceAuthorityContext",
    "InsuranceAuthorityDecision",
    "evaluate_insurance_authority",
]
