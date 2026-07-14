"""Control Plane admission and governed request construction for Hybrid Knowledge."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from proof_agent.contracts._base import FrozenDict, FrozenModel, freeze_value
from proof_agent.contracts.react_workflow import (
    InsuranceConditionAdmission,
    InsuranceConditionProposal,
)
from proof_agent.contracts.insurance_authorization import InstitutionAuthorizationContext
from proof_agent.contracts.insurance_rules import (
    EvidenceRequirementKind,
    InsuranceEvidenceSlotRequirement,
    TaxonomyCondition,
)
from proof_agent.contracts.knowledge_index import KnowledgeRetrievalProfileRevision
from proof_agent.contracts.knowledge_resolution import ResolvedHybridKnowledgeBinding
from proof_agent.contracts.react_workflow import IntentResolution, RetrievalQueryItem


InsuranceKnowledgeQueryType = Literal[
    "clause_lookup",
    "conditional_guidance",
    "comparison",
]


class HybridCandidateBudgets(FrozenModel):
    lexical: int = Field(gt=0)
    dense: int = Field(gt=0)
    rrf_window: int = Field(gt=0)
    rerank: int = Field(gt=0)
    final: int = Field(gt=0)


class GovernedHybridRetrievalRequest(FrozenModel):
    """Provider-neutral Hybrid request containing no backend DSL or mutable selector."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str = Field(min_length=1, max_length=300)
    binding: ResolvedHybridKnowledgeBinding
    retrieval_profile: KnowledgeRetrievalProfileRevision
    authorization: InstitutionAuthorizationContext
    normalized_conditions: Mapping[str, str] = Field(default_factory=FrozenDict)
    applicability_filters: tuple[TaxonomyCondition, ...] = ()
    query_set: tuple[RetrievalQueryItem, ...] = Field(min_length=1)
    query_type: InsuranceKnowledgeQueryType
    required_evidence_slots: tuple[InsuranceEvidenceSlotRequirement, ...] = Field(min_length=1)
    as_of_time: datetime
    candidate_budgets: HybridCandidateBudgets

    @field_validator("normalized_conditions", mode="after")
    @classmethod
    def freeze_normalized_conditions(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_validator("as_of_time", mode="after")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of_time must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_pinned_profile(self) -> GovernedHybridRetrievalRequest:
        if self.binding.retrieval_profile_revision_id != self.retrieval_profile.profile_revision_id:
            raise ValueError("retrieval profile must match the exact Hybrid binding")
        return self


class HybridRequestClarification(FrozenModel):
    missing_fields: tuple[str, ...] = Field(min_length=1)
    reason: Literal["missing_authority_fields"] = "missing_authority_fields"


class GovernedHybridRequestBuildResult(FrozenModel):
    request: GovernedHybridRetrievalRequest | None = None
    clarification: HybridRequestClarification | None = None
    no_recommendation_reason: str | None = None

    @model_validator(mode="after")
    def require_exactly_one_outcome(self) -> GovernedHybridRequestBuildResult:
        outcomes = (
            self.request is not None,
            self.clarification is not None,
            self.no_recommendation_reason is not None,
        )
        if sum(outcomes) != 1:
            raise ValueError("Hybrid request build requires exactly one terminal outcome")
        return self


class ApprovedInsuranceConditionTaxonomy(FrozenModel):
    """Business-approved keys and canonical scalar values accepted from intent output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    taxonomy_id: str = Field(min_length=1)
    taxonomy_revision_id: str = Field(min_length=1)
    allowed_values: Mapping[str, tuple[str, ...]]
    authority_required_fields: tuple[str, ...] = ()

    @field_validator("allowed_values", mode="before")
    @classmethod
    def canonicalize_allowed_values(cls, value: Any) -> Any:
        if not isinstance(value, Mapping) or not value:
            raise ValueError("allowed_values must be a non-empty mapping")
        canonical: dict[str, tuple[str, ...]] = {}
        for raw_key, raw_values in value.items():
            if not isinstance(raw_key, str) or not raw_key.strip():
                raise ValueError("taxonomy keys must be non-empty strings")
            if not isinstance(raw_values, list | tuple) or not raw_values:
                raise ValueError("taxonomy values must be non-empty arrays")
            key = raw_key.strip()
            values: list[str] = []
            casefolded: set[str] = set()
            for raw_item in raw_values:
                if not isinstance(raw_item, str) or not raw_item.strip():
                    raise ValueError("taxonomy values must be non-empty strings")
                item = raw_item.strip()
                folded = item.casefold()
                if folded in casefolded:
                    raise ValueError("taxonomy values must be case-insensitively unique")
                casefolded.add(folded)
                values.append(item)
            if key in canonical:
                raise ValueError("taxonomy keys must be unique")
            canonical[key] = tuple(values)
        return FrozenDict({key: canonical[key] for key in sorted(canonical)})

    @field_validator("allowed_values", mode="after")
    @classmethod
    def freeze_allowed_values(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_validator("authority_required_fields", mode="before")
    @classmethod
    def canonicalize_required_fields(cls, value: Any) -> Any:
        if not isinstance(value, list | tuple):
            raise ValueError("authority_required_fields must be an array")
        if not all(isinstance(item, str) and item.strip() for item in value):
            raise ValueError("authority_required_fields must contain non-empty strings")
        fields = tuple(sorted({item.strip() for item in value}))
        if len(fields) != len(value):
            raise ValueError("authority_required_fields must be unique non-empty strings")
        return fields

    @model_validator(mode="after")
    def validate_required_fields(self) -> ApprovedInsuranceConditionTaxonomy:
        unknown = set(self.authority_required_fields) - set(self.allowed_values)
        if unknown:
            raise ValueError("authority-required fields must exist in allowed_values")
        return self


@dataclass(frozen=True)
class GovernedHybridRequestFactory:
    """Bind intent and trusted run scope to one exact Hybrid request contract."""

    binding: ResolvedHybridKnowledgeBinding
    retrieval_profile: KnowledgeRetrievalProfileRevision
    taxonomy: ApprovedInsuranceConditionTaxonomy
    clock: Callable[[], datetime]

    def build(
        self,
        intent: IntentResolution,
        authorization: InstitutionAuthorizationContext,
    ) -> GovernedHybridRequestBuildResult:
        return build_governed_hybrid_request(
            intent=intent,
            authorization=authorization,
            binding=self.binding,
            retrieval_profile=self.retrieval_profile,
            taxonomy=self.taxonomy,
            as_of_time=self.clock(),
        )


def admit_insurance_conditions(
    proposal: InsuranceConditionProposal,
    *,
    taxonomy: ApprovedInsuranceConditionTaxonomy,
) -> InsuranceConditionAdmission:
    """Normalize only approved keys and values; never infer authority-bearing values."""

    unknown_keys = tuple(sorted(set(proposal.values) - set(taxonomy.allowed_values)))
    if unknown_keys:
        return InsuranceConditionAdmission(
            admitted=False,
            normalized_values={},
            reason="unknown_condition_key",
        )

    normalized: dict[str, str] = {}
    for key in sorted(proposal.values):
        raw_value = proposal.values[key]
        if not isinstance(raw_value, str) or not raw_value.strip():
            return InsuranceConditionAdmission(
                admitted=False,
                normalized_values={},
                reason="unknown_condition_value",
            )
        canonical_by_folded = {value.casefold(): value for value in taxonomy.allowed_values[key]}
        canonical = canonical_by_folded.get(raw_value.strip().casefold())
        if canonical is None:
            return InsuranceConditionAdmission(
                admitted=False,
                normalized_values={},
                reason="unknown_condition_value",
            )
        normalized[key] = canonical

    missing = tuple(
        field for field in taxonomy.authority_required_fields if field not in normalized
    )
    return InsuranceConditionAdmission(
        admitted=not missing,
        normalized_values=normalized,
        missing_authority_fields=missing,
        reason="admitted" if not missing else "missing_authority_fields",
    )


def build_governed_hybrid_request(
    *,
    intent: IntentResolution,
    authorization: InstitutionAuthorizationContext,
    binding: ResolvedHybridKnowledgeBinding,
    retrieval_profile: KnowledgeRetrievalProfileRevision,
    taxonomy: ApprovedInsuranceConditionTaxonomy,
    as_of_time: datetime,
) -> GovernedHybridRequestBuildResult:
    """Build one exact request or stop before provider execution."""

    if binding.retrieval_profile_revision_id != retrieval_profile.profile_revision_id:
        return GovernedHybridRequestBuildResult(
            no_recommendation_reason="retrieval_profile_mismatch"
        )
    proposed_values = dict(intent.insurance_condition_proposal.values)
    _merge_trusted_authorization_values(
        proposed_values,
        authorization=authorization,
        taxonomy=taxonomy,
    )
    admission = admit_insurance_conditions(
        InsuranceConditionProposal(values=proposed_values),
        taxonomy=taxonomy,
    )
    if admission.reason in {"unknown_condition_key", "unknown_condition_value"}:
        return GovernedHybridRequestBuildResult(no_recommendation_reason=admission.reason)
    if admission.missing_authority_fields:
        return GovernedHybridRequestBuildResult(
            clarification=HybridRequestClarification(
                missing_fields=admission.missing_authority_fields
            )
        )
    if not intent.retrieval_query_set:
        return GovernedHybridRequestBuildResult(no_recommendation_reason="missing_retrieval_query")

    query_type = _query_type(intent.domain_intent)
    normalized = dict(admission.normalized_values)
    return GovernedHybridRequestBuildResult(
        request=GovernedHybridRetrievalRequest(
            request_id=f"hybrid:{intent.resolution_id}:{binding.binding_id}",
            binding=binding,
            retrieval_profile=retrieval_profile,
            authorization=authorization,
            normalized_conditions=normalized,
            applicability_filters=tuple(
                TaxonomyCondition(key=key, operator="EQ", values=(value,))
                for key, value in sorted(normalized.items())
            ),
            query_set=intent.retrieval_query_set,
            query_type=query_type,
            required_evidence_slots=_required_evidence_slots(
                query_type,
                normalized_conditions=normalized,
            ),
            as_of_time=as_of_time,
            candidate_budgets=HybridCandidateBudgets(
                lexical=retrieval_profile.lexical_budget,
                dense=retrieval_profile.dense_budget,
                rrf_window=retrieval_profile.rrf_window,
                rerank=retrieval_profile.rerank_budget,
                final=retrieval_profile.final_budget,
            ),
        )
    )


def _merge_trusted_authorization_values(
    values: dict[str, str],
    *,
    authorization: InstitutionAuthorizationContext,
    taxonomy: ApprovedInsuranceConditionTaxonomy,
) -> None:
    dimension_keys = {
        "institution": authorization.institutions,
        "region": authorization.regions,
        "channel": authorization.channels,
        "role": authorization.roles,
        "business_line": authorization.business_lines,
    }
    for key, admitted_values in dimension_keys.items():
        if key in taxonomy.allowed_values and key not in values and len(admitted_values) == 1:
            values[key] = admitted_values[0]


def _query_type(domain_intent: str) -> InsuranceKnowledgeQueryType:
    normalized = domain_intent.casefold()
    if "comparison" in normalized:
        return "comparison"
    if "conditional" in normalized or "guidance" in normalized:
        return "conditional_guidance"
    return "clause_lookup"


def _required_evidence_slots(
    query_type: InsuranceKnowledgeQueryType,
    *,
    normalized_conditions: Mapping[str, str],
) -> tuple[InsuranceEvidenceSlotRequirement, ...]:
    if query_type == "clause_lookup":
        return (
            InsuranceEvidenceSlotRequirement(
                slot_id="requested-clause",
                requirement_kind="requested_clause",
                subject_id="requested-clause",
            ),
        )
    if query_type == "conditional_guidance":
        requirements: tuple[tuple[str, EvidenceRequirementKind], ...] = (
            ("governing-rule", "governing_rule"),
            ("applicable-condition", "applicable_condition"),
            ("exclusion-or-exception", "exclusion_or_exception"),
            ("precedence-source", "precedence_source"),
        )
        return tuple(
            InsuranceEvidenceSlotRequirement(
                slot_id=slot_id,
                requirement_kind=requirement_kind,
                subject_id=normalized_conditions.get("product", "requested-product"),
            )
            for slot_id, requirement_kind in requirements
        )
    products = tuple(
        value for key, value in sorted(normalized_conditions.items()) if key.startswith("product")
    ) or ("comparison-left", "comparison-right")
    return tuple(
        InsuranceEvidenceSlotRequirement(
            slot_id=f"comparison:{product}",
            requirement_kind="comparison_basis",
            subject_id=product,
        )
        for product in products
    )


__all__ = [
    "ApprovedInsuranceConditionTaxonomy",
    "GovernedHybridRequestBuildResult",
    "GovernedHybridRequestFactory",
    "GovernedHybridRetrievalRequest",
    "HybridCandidateBudgets",
    "HybridRequestClarification",
    "InsuranceConditionAdmission",
    "InsuranceConditionProposal",
    "admit_insurance_conditions",
    "build_governed_hybrid_request",
]
