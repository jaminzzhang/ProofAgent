"""Provider-neutral hybrid retrieval over one exact immutable Release."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import cmp_to_key
from math import sqrt
import re
from typing import Any

from knowledge_source_service.contracts.knowledge_query import (
    BoundedStructuredQuery,
    QueryFilter,
    StructuredQueryAggregation,
    StructuredQuerySort,
)
from knowledge_source_service.contracts.results import KnowledgeQueryResult
from knowledge_source_service.domain.knowledge_catalog import (
    DatasetSourceVersion,
    DocxParagraphDocumentCitation,
    DocxTableCellDocumentCitation,
    DocumentEvidenceUnit,
    DocumentSourceVersion,
    HtmlDomDocumentCitation,
    KnowledgeBaseReleaseSnapshot,
    OcrRegionDocumentCitation,
    PptxShapeDocumentCitation,
    StructuredField,
    StructuredRecord,
)
from knowledge_source_service.domain.identities import (
    content_identifier as _identifier,
    sha256_json as _digest_json,
)
from knowledge_source_service.ports.knowledge_catalog import KnowledgeCatalogReader
from knowledge_source_service.ports.retrieval import AdmittedKnowledgeQuery


_RRF_K = 60
_LANE_WEIGHTS = {"lexical": 1.0, "sparse": 0.8, "dense": 0.8}
@dataclass(frozen=True)
class _RankedDocumentUnit:
    source: DocumentSourceVersion
    unit: DocumentEvidenceUnit
    native_scores: dict[str, float]
    lane_ranks: dict[str, int]
    fused_score: float


@dataclass(frozen=True)
class _StructuredOutputRow:
    fields: tuple[StructuredField, ...]
    input_records: tuple[StructuredRecord, ...]
    row_identity: str


class HybridKnowledgeRetrievalEngine:
    """Return Candidate Evidence; never perform Evidence Admission or answer generation."""

    def __init__(self, *, catalog: KnowledgeCatalogReader) -> None:
        self._catalog = catalog

    def retrieve(self, query: AdmittedKnowledgeQuery) -> KnowledgeQueryResult:
        release = self._required_release(query)
        source_versions = tuple(
            self._required_source_version(source_version_id)
            for source_version_id in release.knowledge_source_version_ids
        )
        documents = tuple(
            version for version in source_versions if isinstance(version, DocumentSourceVersion)
        )
        datasets = tuple(
            version for version in source_versions if isinstance(version, DatasetSourceVersion)
        )
        query_digest = _digest_json(
            {
                "question": query.request.question,
                "constraints": query.request.query_constraints.model_dump(mode="json"),
            }
        )
        relevance_candidates = self._retrieve_documents(
            query=query,
            release=release,
            documents=documents,
            query_digest=query_digest,
        )
        structured_groups = self._retrieve_structured_groups(
            query=query,
            release=release,
            datasets=datasets,
            max_candidates=max(
                0,
                query.request.execution_budget.max_candidates
                - len(relevance_candidates),
            ),
        )
        planned_lanes = tuple(
            lane
            for lane, enabled in (
                ("lexical", bool(documents)),
                ("sparse", bool(documents)),
                ("dense", bool(documents)),
                ("structured", bool(datasets)),
            )
            if enabled
        )
        plan_digest = _digest_json(
            {
                "schema": "knowledge-query-plan.v1",
                "release": release.knowledge_base_release_id,
                "lanes": planned_lanes,
                "query_digest": query_digest,
            }
        )
        candidate_count = len(relevance_candidates) + sum(
            len(group["candidate_evidence"]) for group in structured_groups
        )
        groups: list[dict[str, Any]] = []
        if documents:
            groups.append(
                {
                    "evidence_group_id": _identifier("relevance-group", plan_digest),
                    "group_type": "relevance_ranked",
                    "ordering": {
                        "kind": "relevance",
                        "final_rank_field": "fused_rank",
                    },
                    "candidate_evidence": relevance_candidates,
                }
            )
        groups.extend(structured_groups)
        if not groups:
            raise ValueError("the exact Knowledge Base Release contains no queryable source versions")

        return KnowledgeQueryResult.model_validate(
            {
                "schema_version": "knowledge-query-result.v1",
                "evidence_groups": groups,
                "query_plan_summary": {
                    "plan_revision": 1,
                    "planned_lanes": planned_lanes,
                    "structured_query_count": (
                        len(query.request.query_constraints.structured_queries)
                        if query.request.query_constraints.structured_queries
                        else (1 if datasets else 0)
                    ),
                    "plan_digest": plan_digest,
                },
                "execution_summary": {
                    "strategy": query.request.strategy,
                    "rounds": 1,
                    "stop_reason": (
                        "no_candidates"
                        if candidate_count == 0
                        else (
                            "single_pass_complete"
                            if query.request.strategy == "single_pass"
                            else "coverage_complete"
                        )
                    ),
                    "degraded": False,
                    "budget_usage": {
                        "rounds": 1,
                        "model_calls": 0,
                        "candidates": candidate_count,
                        "model_tokens": 0,
                        "duration_ms": 0,
                    },
                },
                "retrieval_lineage": {
                    "knowledge_base_release_id": release.knowledge_base_release_id,
                    "release_manifest_digest": release.release_manifest_digest,
                    "access_scope_digest": (
                        query.admission.effective_access_scope_digest
                    ),
                    "plan_revision_digests": [plan_digest],
                },
            }
        )

    def _required_release(
        self, query: AdmittedKnowledgeQuery
    ) -> KnowledgeBaseReleaseSnapshot:
        release = self._catalog.get_release(query.request.knowledge_base_release_id)
        if release is None:
            raise ValueError("unknown exact Knowledge Base Release")
        if release.knowledge_space_id != query.admission.knowledge_space_id:
            raise ValueError("admission Space does not own the selected Release")
        return release

    def _required_source_version(
        self, source_version_id: str
    ) -> DocumentSourceVersion | DatasetSourceVersion:
        version = self._catalog.get_source_version(source_version_id)
        if version is None:
            raise ValueError("Release references an unavailable Source Version")
        return version

    def _retrieve_documents(
        self,
        *,
        query: AdmittedKnowledgeQuery,
        release: KnowledgeBaseReleaseSnapshot,
        documents: tuple[DocumentSourceVersion, ...],
        query_digest: str,
    ) -> list[dict[str, Any]]:
        ranked = _rank_document_units(query.request.question, documents)
        limited = ranked[: query.request.execution_budget.max_candidates]
        candidates: list[dict[str, Any]] = []
        for fused_rank, ranked_unit in enumerate(limited, start=1):
            lane_contributions = [
                {
                    "lane": lane,
                    "native_score": ranked_unit.native_scores[lane],
                    "lane_rank": ranked_unit.lane_ranks[lane],
                    "weight": weight,
                    "rrf_contribution": weight
                    / (_RRF_K + ranked_unit.lane_ranks[lane]),
                }
                for lane, weight in _LANE_WEIGHTS.items()
            ]
            unit = ranked_unit.unit
            source = ranked_unit.source
            candidates.append(
                {
                    "candidate_evidence_id": _identifier(
                        "candidate",
                        _digest_json(
                            {
                                "release": release.knowledge_base_release_id,
                                "unit": unit.evidence_unit_id,
                                "query": query_digest,
                            }
                        ),
                    ),
                    "knowledge_space_id": release.knowledge_space_id,
                    "knowledge_base_id": release.knowledge_base_id,
                    "knowledge_base_version_id": release.knowledge_base_version_id,
                    "knowledge_base_release_id": release.knowledge_base_release_id,
                    "knowledge_source_id": source.knowledge_source_id,
                    "knowledge_source_version_id": source.knowledge_source_version_id,
                    "evidence_unit_id": unit.evidence_unit_id,
                    "content": {"media_type": source.media_type, "text": unit.text},
                    "content_hash": unit.content_hash,
                    "citation_locator": _document_citation(unit),
                    "context_evidence_units": [],
                    "ranking": {
                        "kind": "relevance",
                        "lane_contributions": lane_contributions,
                        "fused_rank": fused_rank,
                        "reranked_rank": None,
                    },
                    "retrieval_lineage": {
                        "retrieval_round": 1,
                        "plan_revision": 1,
                        "index_identity": (
                            f"{release.knowledge_base_release_id}:hybrid-memory-v1"
                        ),
                        "query_digest": query_digest,
                        "access_scope_digest": (
                            query.admission.effective_access_scope_digest
                        ),
                    },
                }
            )
        return candidates

    def _retrieve_structured_groups(
        self,
        *,
        query: AdmittedKnowledgeQuery,
        release: KnowledgeBaseReleaseSnapshot,
        datasets: tuple[DatasetSourceVersion, ...],
        max_candidates: int,
    ) -> list[dict[str, Any]]:
        explicit_queries = query.request.query_constraints.structured_queries
        if not datasets:
            if explicit_queries:
                raise ValueError(
                    "structured query references a Release without Dataset Revisions"
                )
            return []
        if not explicit_queries:
            candidates = self._retrieve_legacy_structured(
                query=query,
                release=release,
                datasets=datasets,
                max_candidates=max_candidates,
            )
            digest = _digest_json(
                query.request.query_constraints.model_dump(mode="json")
            )
            return [
                {
                    "evidence_group_id": _identifier("structured-group", digest),
                    "group_type": "structured",
                    "ordering": {
                        "kind": "typed",
                        "fields": [_structured_order(datasets)],
                    },
                    "candidate_evidence": candidates,
                }
            ]

        datasets_by_revision = {
            dataset.dataset_revision_id: dataset for dataset in datasets
        }
        groups: list[dict[str, Any]] = []
        remaining = max_candidates
        for structured_query in explicit_queries:
            dataset = datasets_by_revision.get(structured_query.dataset_revision_id)
            if dataset is None:
                raise ValueError(
                    "structured query references a Dataset Revision outside the Release"
                )
            typed_query_digest = _digest_json(
                structured_query.model_dump(mode="json")
            )
            rows = _execute_structured_query(dataset, structured_query)
            rows = rows[: min(structured_query.limit, remaining)]
            candidates = [
                _explicit_structured_candidate(
                    query=query,
                    release=release,
                    dataset=dataset,
                    structured_query=structured_query,
                    typed_query_digest=typed_query_digest,
                    row=row,
                    structured_order=structured_order,
                )
                for structured_order, row in enumerate(rows, start=1)
            ]
            remaining -= len(candidates)
            groups.append(
                {
                    "evidence_group_id": _identifier(
                        "structured-group",
                        typed_query_digest,
                    ),
                    "group_type": "structured",
                    "ordering": {
                        "kind": "typed",
                        "fields": _structured_query_order(structured_query),
                    },
                    "candidate_evidence": candidates,
                }
            )
        return groups

    def _retrieve_legacy_structured(
        self,
        *,
        query: AdmittedKnowledgeQuery,
        release: KnowledgeBaseReleaseSnapshot,
        datasets: tuple[DatasetSourceVersion, ...],
        max_candidates: int,
    ) -> list[dict[str, Any]]:
        typed_query_digest = _digest_json(
            query.request.query_constraints.model_dump(mode="json")
        )
        selected: list[tuple[DatasetSourceVersion, StructuredRecord]] = []
        for dataset in datasets:
            schema = _dataset_schema(dataset)
            for query_filter in query.request.query_constraints.filters:
                if query_filter.field not in schema:
                    raise ValueError(
                        "global structured filter references an unknown field"
                    )
                _validate_filter_type(query_filter, schema[query_filter.field])
            selected.extend(
                (dataset, record)
                for record in dataset.records
                if _matches_typed_filters(
                    record,
                    query.request.query_constraints.filters,
                    schema=schema,
                )
            )
        selected.sort(key=lambda item: item[1].record_id)
        selected = selected[:max_candidates]
        input_set_digest = _digest_json([record.record_id for _, record in selected])
        candidates: list[dict[str, Any]] = []
        for structured_order, (dataset, record) in enumerate(selected, start=1):
            fields = [_field_payload(field) for field in record.fields]
            candidates.append(
                {
                    "candidate_evidence_id": _identifier(
                        "candidate",
                        _digest_json(
                            {
                                "release": release.knowledge_base_release_id,
                                "record": record.record_id,
                                "query": typed_query_digest,
                            }
                        ),
                    ),
                    "knowledge_space_id": release.knowledge_space_id,
                    "knowledge_base_id": release.knowledge_base_id,
                    "knowledge_base_version_id": release.knowledge_base_version_id,
                    "knowledge_base_release_id": release.knowledge_base_release_id,
                    "knowledge_source_id": dataset.knowledge_source_id,
                    "knowledge_source_version_id": dataset.knowledge_source_version_id,
                    "evidence_unit_id": f"dataset-record-unit-{record.record_id}",
                    "content": {
                        "media_type": (
                            "application/vnd.knowledge.structured-record+json"
                        ),
                        "text": ", ".join(
                            f"{field.field}={field.value}" for field in record.fields
                        ),
                        "structured_data": {
                            "schema_revision_id": dataset.schema_revision_id,
                            "fields": fields,
                        },
                    },
                    "content_hash": record.content_hash,
                    "citation_locator": {
                        "kind": "dataset_records",
                        "dataset_revision_id": dataset.dataset_revision_id,
                        "record_ids": [record.record_id],
                        "typed_query_digest": typed_query_digest,
                        "input_set_digest": input_set_digest,
                    },
                    "context_evidence_units": [],
                    "ranking": {
                        "kind": "structured",
                        "structured_order": structured_order,
                    },
                    "retrieval_lineage": {
                        "retrieval_round": 1,
                        "plan_revision": 1,
                        "index_identity": dataset.dataset_revision_id,
                        "query_digest": typed_query_digest,
                        "access_scope_digest": (
                            query.admission.effective_access_scope_digest
                        ),
                    },
                }
            )
        return candidates


def _execute_structured_query(
    dataset: DatasetSourceVersion,
    structured_query: BoundedStructuredQuery,
) -> list[_StructuredOutputRow]:
    schema = _dataset_schema(dataset)
    output_fields = _validate_structured_query(
        schema=schema,
        structured_query=structured_query,
    )
    selected = [
        record
        for record in dataset.records
        if _matches_typed_filters(
            record,
            structured_query.filters,
            schema=schema,
        )
    ]
    if structured_query.aggregations:
        grouped: dict[tuple[tuple[str, object], ...], list[StructuredRecord]] = {}
        for record in selected:
            fields = _record_fields(record)
            key = tuple(
                (fields[field].value_type, fields[field].value)
                for field in structured_query.group_by
            )
            grouped.setdefault(key, []).append(record)
        if not structured_query.group_by and selected:
            grouped[()] = selected
        rows = [
            _aggregate_row(
                records=tuple(records),
                group_by=structured_query.group_by,
                aggregations=structured_query.aggregations,
                typed_query_digest=_digest_json(
                    structured_query.model_dump(mode="json")
                ),
            )
            for _key, records in grouped.items()
        ]
    else:
        projections = structured_query.projections or tuple(output_fields)
        rows = [
            _StructuredOutputRow(
                fields=tuple(_record_fields(record)[field] for field in projections),
                input_records=(record,),
                row_identity=record.record_id,
            )
            for record in selected
        ]
    def compare(left: _StructuredOutputRow, right: _StructuredOutputRow) -> int:
        return _compare_structured_rows(left, right, structured_query.sort)

    return sorted(rows, key=cmp_to_key(compare))


def _validate_structured_query(
    *,
    schema: dict[str, str],
    structured_query: BoundedStructuredQuery,
) -> tuple[str, ...]:
    known_fields = set(schema)
    referenced_fields = {
        *(item.field for item in structured_query.filters),
        *structured_query.projections,
        *structured_query.group_by,
        *(
            item.field
            for item in structured_query.aggregations
            if item.field is not None
        ),
    }
    if not referenced_fields <= known_fields:
        raise ValueError("structured query references an unknown dynamic field")
    for query_filter in structured_query.filters:
        _validate_filter_type(query_filter, schema[query_filter.field])
    for aggregation in structured_query.aggregations:
        if aggregation.field is None:
            continue
        value_type = schema[aggregation.field]
        if aggregation.function in {"sum", "avg"} and value_type not in {
            "integer",
            "decimal",
        }:
            raise ValueError("structured numeric aggregation requires a numeric field")
        if aggregation.function in {"min", "max"} and value_type in {
            "boolean",
            "null",
        }:
            raise ValueError("structured ordered aggregation requires an ordered field")
    output_fields = (
        structured_query.group_by
        + tuple(item.output_field for item in structured_query.aggregations)
        if structured_query.aggregations
        else (structured_query.projections or tuple(schema))
    )
    if any(item.field not in output_fields for item in structured_query.sort):
        raise ValueError("structured sort must reference an output field")
    if len({item.field for item in structured_query.sort}) != len(
        structured_query.sort
    ):
        raise ValueError("structured sort fields must be unique")
    return output_fields


def _dataset_schema(dataset: DatasetSourceVersion) -> dict[str, str]:
    schema: dict[str, str] = {field: "null" for field in dataset.field_order}
    for record in dataset.records:
        fields = _record_fields(record)
        if tuple(fields) != dataset.field_order:
            raise ValueError("Dataset Revision record schema is inconsistent")
        for field, value in fields.items():
            if value.value_type == "null":
                continue
            existing = schema[field]
            if existing not in {"null", value.value_type}:
                raise ValueError("Dataset Revision field type drift is forbidden")
            schema[field] = value.value_type
    return schema


def _record_fields(record: StructuredRecord) -> dict[str, StructuredField]:
    fields = {field.field: field for field in record.fields}
    if len(fields) != len(record.fields):
        raise ValueError("structured record repeats a field")
    return fields


def _aggregate_row(
    *,
    records: tuple[StructuredRecord, ...],
    group_by: tuple[str, ...],
    aggregations: tuple[StructuredQueryAggregation, ...],
    typed_query_digest: str,
) -> _StructuredOutputRow:
    if not records:
        raise ValueError("aggregate row requires at least one input record")
    first = _record_fields(records[0])
    fields = [first[field] for field in group_by]
    fields.extend(
        _aggregate_field(records=records, aggregation=aggregation)
        for aggregation in aggregations
    )
    input_ids = tuple(sorted(record.record_id for record in records))
    return _StructuredOutputRow(
        fields=tuple(fields),
        input_records=records,
        row_identity=_identifier(
            "aggregate-row",
            _digest_json(
                {
                    "typed_query_digest": typed_query_digest,
                    "input_record_ids": input_ids,
                }
            ),
        ),
    )


def _aggregate_field(
    *,
    records: tuple[StructuredRecord, ...],
    aggregation: StructuredQueryAggregation,
) -> StructuredField:
    values = (
        []
        if aggregation.field is None
        else [
            _record_fields(record)[aggregation.field]
            for record in records
        ]
    )
    non_null = [value for value in values if value.value_type != "null"]
    if aggregation.function == "count":
        count = len(records) if aggregation.field is None else len(non_null)
        return StructuredField(
            field=aggregation.output_field,
            value_type="integer",
            value=count,
        )
    if aggregation.function == "exact_distinct_count":
        distinct = {(value.value_type, value.value) for value in non_null}
        return StructuredField(
            field=aggregation.output_field,
            value_type="integer",
            value=len(distinct),
        )
    if not non_null:
        return StructuredField(
            field=aggregation.output_field,
            value_type="null",
            value=None,
        )
    if aggregation.function in {"sum", "avg"}:
        value_type = non_null[0].value_type
        if value_type == "integer":
            total_integer = 0
            for value in non_null:
                if type(value.value) is not int:
                    raise ValueError("integer aggregation input is inconsistent")
                total_integer += value.value
            if aggregation.function == "sum":
                _require_numeric_bound(Decimal(total_integer))
                return StructuredField(
                    field=aggregation.output_field,
                    value_type="integer",
                    value=total_integer,
                )
            aggregate_decimal = Decimal(total_integer) / Decimal(len(non_null))
        else:
            aggregate_decimal = sum(
                (Decimal(str(value.value)) for value in non_null),
                start=Decimal(0),
            )
            if aggregation.function == "avg":
                aggregate_decimal /= Decimal(len(non_null))
        _require_numeric_bound(aggregate_decimal)
        return StructuredField(
            field=aggregation.output_field,
            value_type="decimal",
            value=format(aggregate_decimal, "f"),
        )
    def compare_fields(left: StructuredField, right: StructuredField) -> int:
        return _compare_comparable(
            _field_comparable(left),
            _field_comparable(right),
        )

    ordered = sorted(non_null, key=cmp_to_key(compare_fields))
    selected = ordered[0] if aggregation.function == "min" else ordered[-1]
    return StructuredField(
        field=aggregation.output_field,
        value_type=selected.value_type,
        value=selected.value,
    )


def _require_numeric_bound(value: Decimal) -> None:
    if not value.is_finite() or value.copy_abs() >= Decimal("1e38"):
        raise ValueError("structured numeric aggregation overflowed its exact bound")


def _compare_structured_rows(
    left: _StructuredOutputRow,
    right: _StructuredOutputRow,
    sort: tuple[StructuredQuerySort, ...],
) -> int:
    left_fields = _record_fields_from_tuple(left.fields)
    right_fields = _record_fields_from_tuple(right.fields)
    effective_sort = sort or tuple(
        StructuredQuerySort(field=field, direction="asc", nulls="last")
        for field in left_fields
    )
    for item in effective_sort:
        compared = _compare_structured_field(
            left_fields[item.field],
            right_fields[item.field],
            item,
        )
        if compared:
            return compared
    return (left.row_identity > right.row_identity) - (
        left.row_identity < right.row_identity
    )


def _record_fields_from_tuple(
    fields: tuple[StructuredField, ...],
) -> dict[str, StructuredField]:
    mapped = {field.field: field for field in fields}
    if len(mapped) != len(fields):
        raise ValueError("structured output fields must be unique")
    return mapped


def _compare_structured_field(
    left: StructuredField,
    right: StructuredField,
    sort: StructuredQuerySort,
) -> int:
    left_null = left.value_type == "null"
    right_null = right.value_type == "null"
    if left_null or right_null:
        if left_null and right_null:
            return 0
        return -1 if left_null == (sort.nulls == "first") else 1
    left_value = _field_comparable(left)
    right_value = _field_comparable(right)
    compared = _compare_comparable(left_value, right_value)
    return compared if sort.direction == "asc" else -compared


def _field_comparable(field: StructuredField) -> Any:
    if field.value_type == "decimal":
        return Decimal(str(field.value))
    if field.value_type == "date":
        return date.fromisoformat(str(field.value))
    if field.value_type == "datetime":
        parsed = datetime.fromisoformat(str(field.value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc)
    if field.value_type == "null":
        raise ValueError("null has no ordered comparison value")
    return field.value


def _compare_comparable(left: Any, right: Any) -> int:
    if type(left) is not type(right):
        raise ValueError("structured comparison types are inconsistent")
    if left == right:
        return 0
    return -1 if left < right else 1


def _matches_typed_filters(
    record: StructuredRecord,
    filters: Iterable[QueryFilter],
    *,
    schema: dict[str, str],
) -> bool:
    fields = _record_fields(record)
    return all(
        _matches_typed_filter(
            fields[query_filter.field],
            query_filter,
            declared_type=schema[query_filter.field],
        )
        for query_filter in filters
    )


def _validate_filter_type(query_filter: QueryFilter, declared_type: str) -> None:
    if query_filter.operator in {"lt", "lte", "gt", "gte", "between"} and (
        declared_type in {"boolean", "null"}
    ):
        raise ValueError("structured ordered predicate requires an ordered field")
    values = (
        query_filter.value
        if isinstance(query_filter.value, tuple)
        else (query_filter.value,)
    )
    if query_filter.operator != "is_null":
        for value in values:
            _typed_comparable(value, declared_type)


def _matches_typed_filter(
    actual: StructuredField,
    query_filter: QueryFilter,
    *,
    declared_type: str,
) -> bool:
    if query_filter.operator == "is_null":
        return actual.value_type == "null"
    if actual.value_type == "null":
        return query_filter.operator == "ne"
    actual_value = _field_comparable(actual)
    expected = query_filter.value
    if query_filter.operator in {"eq", "ne"}:
        expected_value = _typed_comparable(expected, declared_type)
        matches = actual_value == expected_value
        return matches if query_filter.operator == "eq" else not matches
    if not isinstance(expected, tuple):
        expected_value = _typed_comparable(expected, declared_type)
        compared = _compare_comparable(actual_value, expected_value)
        if query_filter.operator == "lt":
            return compared < 0
        if query_filter.operator == "lte":
            return compared <= 0
        if query_filter.operator == "gt":
            return compared > 0
        if query_filter.operator == "gte":
            return compared >= 0
        raise ValueError("structured predicate operator is inconsistent")
    expected_values = tuple(
        _typed_comparable(value, declared_type) for value in expected
    )
    if query_filter.operator == "in":
        return actual_value in expected_values
    return (
        _compare_comparable(expected_values[0], actual_value) <= 0
        and _compare_comparable(actual_value, expected_values[1]) <= 0
    )


def _typed_comparable(value: object, declared_type: str) -> object:
    if declared_type == "string" and type(value) is str:
        return value
    if declared_type == "integer" and type(value) is int:
        return value
    if declared_type == "decimal" and type(value) is str:
        try:
            decimal_value = Decimal(value)
        except InvalidOperation as error:
            raise ValueError("structured decimal predicate is invalid") from error
        if decimal_value.is_finite():
            return decimal_value
    if declared_type == "boolean" and type(value) is bool:
        return value
    if declared_type == "date" and type(value) is str:
        try:
            return date.fromisoformat(value)
        except ValueError as error:
            raise ValueError("structured date predicate is invalid") from error
    if declared_type == "datetime" and type(value) is str:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("structured datetime predicate is invalid") from error
        if parsed.tzinfo is not None and parsed.utcoffset() is not None:
            return parsed.astimezone(timezone.utc)
    raise ValueError("structured predicate value does not match the field type")


def _structured_query_order(
    structured_query: BoundedStructuredQuery,
) -> list[str]:
    if structured_query.sort:
        return [
            f"{item.field} {item.direction} nulls {item.nulls}"
            for item in structured_query.sort
        ]
    fields = (
        structured_query.group_by
        or structured_query.projections
        or tuple(item.output_field for item in structured_query.aggregations)
    )
    return [f"{field} asc nulls last" for field in fields[:1]]


def _explicit_structured_candidate(
    *,
    query: AdmittedKnowledgeQuery,
    release: KnowledgeBaseReleaseSnapshot,
    dataset: DatasetSourceVersion,
    structured_query: BoundedStructuredQuery,
    typed_query_digest: str,
    row: _StructuredOutputRow,
    structured_order: int,
) -> dict[str, Any]:
    field_payloads = [_field_payload(field) for field in row.fields]
    content_hash = _digest_json(field_payloads)
    input_record_ids = tuple(sorted(record.record_id for record in row.input_records))
    input_set_digest = _digest_json(input_record_ids)
    aggregate = bool(structured_query.aggregations)
    evidence_unit_id = _identifier(
        "dataset-aggregate-unit" if aggregate else "dataset-record-unit",
        _digest_json(
            {
                "dataset_revision_id": dataset.dataset_revision_id,
                "typed_query_digest": typed_query_digest,
                "row_identity": row.row_identity,
            }
        ),
    )
    citation: dict[str, object]
    if aggregate:
        citation = {
            "kind": "dataset_aggregate",
            "dataset_revision_id": dataset.dataset_revision_id,
            "typed_query_digest": typed_query_digest,
            "input_predicate_digest": _digest_json(
                [item.model_dump(mode="json") for item in structured_query.filters]
            ),
            "input_record_count": len(input_record_ids),
            "input_set_digest": input_set_digest,
        }
    else:
        citation = {
            "kind": "dataset_records",
            "dataset_revision_id": dataset.dataset_revision_id,
            "record_ids": input_record_ids,
            "typed_query_digest": typed_query_digest,
            "input_set_digest": input_set_digest,
        }
    return {
        "candidate_evidence_id": _identifier(
            "candidate",
            _digest_json(
                {
                    "release": release.knowledge_base_release_id,
                    "unit": evidence_unit_id,
                    "query": typed_query_digest,
                }
            ),
        ),
        "knowledge_space_id": release.knowledge_space_id,
        "knowledge_base_id": release.knowledge_base_id,
        "knowledge_base_version_id": release.knowledge_base_version_id,
        "knowledge_base_release_id": release.knowledge_base_release_id,
        "knowledge_source_id": dataset.knowledge_source_id,
        "knowledge_source_version_id": dataset.knowledge_source_version_id,
        "evidence_unit_id": evidence_unit_id,
        "content": {
            "media_type": (
                "application/vnd.knowledge.structured-aggregate+json"
                if aggregate
                else "application/vnd.knowledge.structured-record+json"
            ),
            "text": ", ".join(
                f"{field.field}={field.value}" for field in row.fields
            ),
            "structured_data": {
                "schema_revision_id": dataset.schema_revision_id,
                "fields": field_payloads,
            },
        },
        "content_hash": content_hash,
        "citation_locator": citation,
        "context_evidence_units": [],
        "ranking": {
            "kind": "structured",
            "structured_order": structured_order,
        },
        "retrieval_lineage": {
            "retrieval_round": 1,
            "plan_revision": 1,
            "index_identity": dataset.dataset_revision_id,
            "query_digest": typed_query_digest,
            "access_scope_digest": query.admission.effective_access_scope_digest,
        },
    }


def _rank_document_units(
    question: str,
    documents: tuple[DocumentSourceVersion, ...],
) -> list[_RankedDocumentUnit]:
    query_terms = _terms(question)
    units = [
        (document, unit, _terms(unit.text))
        for document in documents
        for unit in document.evidence_units
    ]
    scored: list[tuple[DocumentSourceVersion, DocumentEvidenceUnit, dict[str, float]]] = []
    for document, unit, unit_terms in units:
        overlap = query_terms & unit_terms
        if not overlap:
            continue
        scores = {
            "lexical": float(len(overlap)),
            "sparse": sum(1.0 / (1.0 + len(term)) for term in overlap),
            "dense": len(overlap) / sqrt(len(query_terms) * len(unit_terms)),
        }
        scored.append((document, unit, scores))

    lane_ranks: dict[str, dict[str, int]] = {}
    for lane in _LANE_WEIGHTS:
        ordered = sorted(
            scored,
            key=lambda item: (-item[2][lane], item[1].evidence_unit_id),
        )
        lane_ranks[lane] = {
            item[1].evidence_unit_id: rank for rank, item in enumerate(ordered, start=1)
        }

    ranked = [
        _RankedDocumentUnit(
            source=document,
            unit=unit,
            native_scores=scores,
            lane_ranks={
                lane: lane_ranks[lane][unit.evidence_unit_id] for lane in _LANE_WEIGHTS
            },
            fused_score=sum(
                weight / (_RRF_K + lane_ranks[lane][unit.evidence_unit_id])
                for lane, weight in _LANE_WEIGHTS.items()
            ),
        )
        for document, unit, scores in scored
    ]
    return sorted(ranked, key=lambda item: (-item.fused_score, item.unit.evidence_unit_id))


def _terms(value: str) -> set[str]:
    normalized = value.casefold()
    terms = set(re.findall(r"[a-z0-9_]+", normalized))
    for run in re.findall(r"[\u3400-\u9fff]+", normalized):
        terms.update(run)
        terms.update(run[index : index + 2] for index in range(max(0, len(run) - 1)))
    return terms or {normalized}


def _field_payload(field: StructuredField) -> dict[str, object]:
    return {"field": field.field, "value_type": field.value_type, "value": field.value}


def _document_citation(unit: DocumentEvidenceUnit) -> dict[str, object]:
    locator = unit.citation_locator
    if locator.kind == "pdf_page":
        return {"kind": "pdf_page", "page_number": locator.page_number}
    if isinstance(locator, DocxParagraphDocumentCitation):
        return {
            "kind": "docx_paragraph",
            "paragraph_number": locator.paragraph_number,
        }
    if isinstance(locator, DocxTableCellDocumentCitation):
        return {
            "kind": "docx_table_cell",
            "table_number": locator.table_number,
            "row_number": locator.row_number,
            "column_number": locator.column_number,
        }
    if isinstance(locator, PptxShapeDocumentCitation):
        return {
            "kind": "pptx_shape",
            "slide_number": locator.slide_number,
            "shape_id": locator.shape_id,
        }
    if isinstance(locator, HtmlDomDocumentCitation):
        return {
            "kind": "html_dom",
            "dom_path": locator.dom_path,
        }
    if isinstance(locator, OcrRegionDocumentCitation):
        return {
            "kind": "ocr_region",
            "page_number": locator.page_number,
            "bounding_box": {
                "x_min": locator.x_min,
                "y_min": locator.y_min,
                "x_max": locator.x_max,
                "y_max": locator.y_max,
            },
        }
    return {
        "kind": "text_lines",
        "start_line": locator.start_line,
        "end_line": locator.end_line,
    }


def _structured_order(datasets: tuple[DatasetSourceVersion, ...]) -> str:
    first_field = datasets[0].field_order[0]
    return f"{first_field} asc"
