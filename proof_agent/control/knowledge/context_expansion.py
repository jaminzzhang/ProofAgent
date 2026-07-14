"""Metadata-first, independently authorized Rule Unit context expansion."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any, Literal, Protocol

from pydantic import Field, field_validator

from proof_agent.contracts._base import FrozenDict, FrozenModel, freeze_value
from proof_agent.contracts.insurance_authorization import InstitutionAuthorizationContext


ExpansionKind = Literal["heading", "table_header", "row_group", "continuation", "definition"]


class ExpansionSeed(FrozenModel):
    rule_unit_revision_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_publication_seq: int = Field(gt=0)
    as_of_date: date
    authorization: InstitutionAuthorizationContext
    normalized_conditions: Mapping[str, str] = Field(default_factory=FrozenDict)
    allowed_expansion_kinds: tuple[ExpansionKind, ...] = Field(min_length=1)

    @field_validator("normalized_conditions", mode="after")
    @classmethod
    def freeze_conditions(cls, value: Any) -> Any:
        return freeze_value(value)


class ExpansionCandidateMetadata(FrozenModel):
    rule_unit_revision_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_publication_seq_from: int = Field(gt=0)
    source_publication_seq_to: int | None = Field(default=None, gt=0)
    visibility: Literal["PUBLIC", "RESTRICTED"]
    allowed_institutions: tuple[str, ...] = ()
    effective_from: date | None = None
    effective_to: date | None = None
    applicability_conditions: Mapping[str, str] = Field(default_factory=FrozenDict)
    expansion_kind: ExpansionKind

    @field_validator("applicability_conditions", mode="after")
    @classmethod
    def freeze_conditions(cls, value: Any) -> Any:
        return freeze_value(value)


class RuleContextExpansionStore(Protocol):
    def expansion_metadata(self, seed: ExpansionSeed) -> tuple[ExpansionCandidateMetadata, ...]: ...

    def load_content(self, rule_unit_revision_ids: tuple[str, ...]) -> Mapping[str, str]: ...


class ExpandedInsuranceContext(FrozenModel):
    unit_ids: tuple[str, ...]
    content_by_unit_id: Mapping[str, str] = Field(default_factory=FrozenDict)
    excluded_count: int = Field(ge=0)

    @field_validator("content_by_unit_id", mode="after")
    @classmethod
    def freeze_content(cls, value: Any) -> Any:
        return freeze_value(value)


def expand_context(
    seed: ExpansionSeed,
    *,
    store: RuleContextExpansionStore,
) -> ExpandedInsuranceContext:
    """Read all candidate metadata, then fetch content only for independently admitted ids."""

    metadata = store.expansion_metadata(seed)
    admitted = tuple(
        item.rule_unit_revision_id for item in metadata if _metadata_admitted(item, seed)
    )
    loaded = dict(store.load_content(admitted)) if admitted else {}
    if set(loaded) != set(admitted):
        raise ValueError("context store must return exactly the admitted expansion ids")
    return ExpandedInsuranceContext(
        unit_ids=admitted,
        content_by_unit_id=loaded,
        excluded_count=len(metadata) - len(admitted),
    )


def _metadata_admitted(item: ExpansionCandidateMetadata, seed: ExpansionSeed) -> bool:
    if item.source_id != seed.source_id or item.expansion_kind not in seed.allowed_expansion_kinds:
        return False
    if not (
        item.source_publication_seq_from <= seed.source_publication_seq
        and (
            item.source_publication_seq_to is None
            or item.source_publication_seq_to >= seed.source_publication_seq
        )
    ):
        return False
    if item.effective_from is not None and item.effective_from > seed.as_of_date:
        return False
    if item.effective_to is not None and item.effective_to < seed.as_of_date:
        return False
    if item.visibility == "RESTRICTED" and (
        seed.authorization.public_only
        or (
            item.allowed_institutions
            and not set(item.allowed_institutions).intersection(seed.authorization.institutions)
        )
    ):
        return False
    return all(
        seed.normalized_conditions.get(key) == value
        for key, value in item.applicability_conditions.items()
    )


__all__ = [
    "ExpandedInsuranceContext",
    "ExpansionCandidateMetadata",
    "ExpansionSeed",
    "RuleContextExpansionStore",
    "expand_context",
]
