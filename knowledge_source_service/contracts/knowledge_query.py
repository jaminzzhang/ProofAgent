"""Public Knowledge Query V1 request contract."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from knowledge_source_service.contracts.base import NonBlankText, StrictContract
from knowledge_source_service.contracts.results import KnowledgeQueryResult


QueryFilterScalar = str | int | float | bool | None
KnowledgeQueryState = Literal["queued", "running", "succeeded", "failed", "cancelled", "expired"]
KnowledgeQueryResultAvailability = Literal["pending", "available", "unavailable", "expired"]


class QueryFilter(StrictContract):
    """Backend-neutral typed narrowing predicate proposed by a caller."""

    field: NonBlankText
    operator: Literal["eq", "ne", "lt", "lte", "gt", "gte", "in", "between", "is_null"]
    value: QueryFilterScalar | tuple[QueryFilterScalar, ...] = None

    @model_validator(mode="after")
    def require_operator_specific_value_shape(self) -> Self:
        if self.operator == "is_null":
            if self.value is not None:
                raise ValueError("is_null does not accept a comparison value")
        elif self.operator == "in":
            if not isinstance(self.value, tuple) or not self.value:
                raise ValueError("in requires a nonempty tuple of values")
        elif self.operator == "between":
            if not isinstance(self.value, tuple) or len(self.value) != 2:
                raise ValueError("between requires exactly two values")
        elif isinstance(self.value, tuple) or self.value is None:
            raise ValueError("comparison operator requires one scalar value")
        return self


class StructuredQuerySort(StrictContract):
    field: NonBlankText
    direction: Literal["asc", "desc"] = "asc"
    nulls: Literal["first", "last"] = "last"


class StructuredQueryAggregation(StrictContract):
    function: Literal["count", "sum", "avg", "min", "max", "exact_distinct_count"]
    field: NonBlankText | None = None
    output_field: NonBlankText

    @model_validator(mode="after")
    def require_aggregation_field(self) -> Self:
        if self.function != "count" and self.field is None:
            raise ValueError("only count may omit its input field")
        return self


class BoundedStructuredQuery(StrictContract):
    """Versioned backend-neutral structured query; never SQL or backend DSL."""

    schema_version: Literal["bounded-structured-query.v1"] = (
        "bounded-structured-query.v1"
    )
    dataset_revision_id: NonBlankText
    projections: tuple[NonBlankText, ...] = Field(default=(), max_length=64)
    filters: tuple[QueryFilter, ...] = Field(default=(), max_length=64)
    group_by: tuple[NonBlankText, ...] = Field(default=(), max_length=8)
    aggregations: tuple[StructuredQueryAggregation, ...] = Field(
        default=(),
        max_length=16,
    )
    sort: tuple[StructuredQuerySort, ...] = Field(default=(), max_length=4)
    limit: int = Field(default=100, ge=1, le=1000)

    @model_validator(mode="after")
    def reject_ambiguous_or_duplicate_output(self) -> Self:
        for values in (self.projections, self.group_by):
            if len(set(values)) != len(values):
                raise ValueError("structured query fields must be unique")
        aliases = tuple(item.output_field for item in self.aggregations)
        if len(set(aliases)) != len(aliases):
            raise ValueError("structured aggregation output fields must be unique")
        if self.aggregations or self.group_by:
            if not self.aggregations:
                raise ValueError("group_by requires at least one aggregation")
            if self.projections:
                raise ValueError("aggregate query cannot declare record projections")
            if set(aliases) & set(self.group_by):
                raise ValueError("aggregate output cannot shadow a group field")
        return self


class QueryConstraints(StrictContract):
    """Typed constraints admitted by the selected Knowledge Base Release."""

    as_of: AwareDatetime | None = None
    filters: tuple[QueryFilter, ...] = ()
    structured_queries: tuple[BoundedStructuredQuery, ...] = Field(
        default=(),
        max_length=16,
    )

    @model_validator(mode="after")
    def reject_ambiguous_global_and_explicit_filters(self) -> Self:
        if self.filters and self.structured_queries:
            raise ValueError(
                "global filters and explicit structured queries cannot be combined"
            )
        return self


class AccessNarrowingContext(StrictContract):
    """Opaque signed assertion that can only narrow an existing service grant."""

    assertion_token: NonBlankText


class KnowledgeQueryExecutionBudget(StrictContract):
    """Caller-requested upper bounds before service-side narrowing."""

    max_rounds: int = Field(gt=0)
    max_model_calls: int = Field(gt=0)
    max_candidates: int = Field(gt=0)
    max_model_tokens: int = Field(gt=0)
    max_duration_ms: int = Field(gt=0)


class CreateKnowledgeQueryRequest(StrictContract):
    """Create one Knowledge Query against an exact immutable Release."""

    knowledge_base_release_id: NonBlankText
    question: NonBlankText
    strategy: Literal["single_pass", "agentic"] = "single_pass"
    query_constraints: QueryConstraints = Field(default_factory=QueryConstraints)
    access_narrowing_context: AccessNarrowingContext | None = None
    execution_budget: KnowledgeQueryExecutionBudget
    deadline_at: AwareDatetime


class KnowledgeQueryLinks(StrictContract):
    """Stable controls for one Knowledge Query resource."""

    self: NonBlankText
    cancel: NonBlankText


class KnowledgeServiceProblemBlocker(StrictContract):
    """Bounded safe fact explaining why an operation is blocked."""

    code: NonBlankText
    detail: NonBlankText


class KnowledgeServiceProblem(StrictContract):
    """Trace-safe RFC 9457 extension used by public service errors."""

    type: NonBlankText
    title: NonBlankText
    status: int = Field(ge=400, le=599)
    code: NonBlankText
    detail: NonBlankText
    trace_id: NonBlankText
    retryable: bool
    blockers: tuple[KnowledgeServiceProblemBlocker, ...] = ()


class KnowledgeQuery(StrictContract):
    """Pollable public state of one durable Knowledge Query execution."""

    schema_version: Literal["knowledge-query.v1"] = "knowledge-query.v1"
    knowledge_query_id: NonBlankText
    knowledge_base_release_id: NonBlankText
    state: KnowledgeQueryState
    submitted_at: AwareDatetime
    started_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    deadline_at: AwareDatetime
    cancel_requested_at: AwareDatetime | None = None
    result_availability: KnowledgeQueryResultAvailability
    result_expires_at: AwareDatetime | None = None
    result: KnowledgeQueryResult | None = None
    problem: KnowledgeServiceProblem | None = None
    links: KnowledgeQueryLinks

    @model_validator(mode="after")
    def expose_result_only_for_succeeded_available_query(self) -> Self:
        compatible_availability = {
            "queued": {"pending"},
            "running": {"pending"},
            "succeeded": {"available", "expired"},
            "failed": {"unavailable"},
            "cancelled": {"unavailable"},
            "expired": {"unavailable"},
        }
        if self.result_availability not in compatible_availability[self.state]:
            raise ValueError("result_availability is incompatible with execution state")
        if self.result is not None and (
            self.state != "succeeded" or self.result_availability != "available"
        ):
            raise ValueError("only a succeeded available Query may expose result")
        if (
            self.state == "succeeded"
            and self.result_availability == "available"
            and (self.result is None or self.result_expires_at is None)
        ):
            raise ValueError("available result requires content and expiry")
        return self
