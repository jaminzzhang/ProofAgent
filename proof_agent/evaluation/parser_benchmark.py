"""Deterministic parser benchmark aggregation for insurance Knowledge documents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeVar

from proof_agent.contracts.evaluation import (
    InsuranceParserCase,
    InsuranceParserObservation,
    ParserBenchmarkMetrics,
    ParserBenchmarkReport,
    ParserBenchmarkSliceMetrics,
    ParserExpectedTableCell,
)


@dataclass(frozen=True, slots=True)
class _ParserMeasurement:
    character_recall: float
    reading_order_recall: float
    table_cell_recall: float
    continuation_recall: float
    anchor_recall: float
    review_expected: int
    review_detected: int


_ParserItem = TypeVar("_ParserItem", InsuranceParserCase, InsuranceParserObservation)
_SliceDimension = Literal["query_type", "document", "parser", "acl"]


def evaluate_parser_benchmark(
    *,
    cases: tuple[InsuranceParserCase, ...],
    observations: tuple[InsuranceParserObservation, ...],
) -> ParserBenchmarkReport:
    """Evaluate parser output through one aggregate and sliced interface."""

    if not cases:
        raise ValueError("parser benchmark requires at least one case")
    cases_by_id = _unique_by_case_id(cases, label="case")
    observations_by_id = _unique_by_case_id(observations, label="observation")
    if set(cases_by_id) != set(observations_by_id):
        raise ValueError("parser observations must cover exactly the benchmark cases")
    measured = {
        case_id: _measure(case, observations_by_id[case_id])
        for case_id, case in cases_by_id.items()
    }
    dimensions: tuple[_SliceDimension, ...] = (
        "query_type",
        "document",
        "parser",
        "acl",
    )
    slices: list[ParserBenchmarkSliceMetrics] = []
    for dimension in dimensions:
        for value in sorted({_slice_value(case, dimension) for case in cases}):
            selected = tuple(
                measured[case.case_id] for case in cases if _slice_value(case, dimension) == value
            )
            slices.append(
                ParserBenchmarkSliceMetrics(
                    dimension=dimension,
                    value=value,
                    case_count=len(selected),
                    metrics=_aggregate(selected),
                )
            )
    return ParserBenchmarkReport(
        case_count=len(cases),
        overall=_aggregate(tuple(measured.values())),
        slices=tuple(slices),
    )


def _slice_value(case: InsuranceParserCase, dimension: _SliceDimension) -> str:
    if dimension == "query_type":
        return case.query_slice
    if dimension == "document":
        return case.document_slice
    if dimension == "parser":
        return case.parser_slice
    return case.acl_slice


def _unique_by_case_id(items: tuple[_ParserItem, ...], *, label: str) -> dict[str, _ParserItem]:
    result: dict[str, _ParserItem] = {}
    for item in items:
        if item.case_id in result:
            raise ValueError(f"duplicate parser {label} case_id: {item.case_id}")
        result[item.case_id] = item
    return result


def _measure(
    case: InsuranceParserCase,
    observation: InsuranceParserObservation,
) -> _ParserMeasurement:
    expected_text = "".join(case.expected_ocr_text.split())
    observed_text = "".join(observation.observed_ocr_text.split())
    return _ParserMeasurement(
        character_recall=_sequence_recall(tuple(expected_text), tuple(observed_text)),
        reading_order_recall=_sequence_recall(
            case.expected_reading_order,
            observation.observed_reading_order,
        ),
        table_cell_recall=_set_recall(
            tuple(_cell_identity(item) for item in case.expected_table_cells),
            tuple(_cell_identity(item) for item in observation.observed_table_cells),
        ),
        continuation_recall=_set_recall(
            case.expected_cross_page_continuation_ids,
            observation.observed_cross_page_continuation_ids,
        ),
        anchor_recall=_set_recall(
            case.expected_citation_anchors,
            observation.observed_citation_anchors,
        ),
        review_expected=int(case.mandatory_review_expected),
        review_detected=int(case.mandatory_review_expected and observation.review_required),
    )


def _cell_identity(cell: ParserExpectedTableCell) -> tuple[str, int, int, int, str]:
    return (cell.table_id, cell.page_number, cell.row, cell.column, cell.text)


def _sequence_recall(expected: tuple[object, ...], observed: tuple[object, ...]) -> float:
    if not expected:
        return 1.0
    previous = [0] * (len(observed) + 1)
    for expected_item in expected:
        current = [0]
        for index, observed_item in enumerate(observed, start=1):
            current.append(
                previous[index - 1] + 1
                if expected_item == observed_item
                else max(previous[index], current[index - 1])
            )
        previous = current
    return previous[-1] / len(expected)


def _set_recall(expected: tuple[object, ...], observed: tuple[object, ...]) -> float:
    if not expected:
        return 1.0
    return len(set(expected).intersection(observed)) / len(set(expected))


def _aggregate(measurements: tuple[_ParserMeasurement, ...]) -> ParserBenchmarkMetrics:
    if not measurements:
        raise ValueError("parser metric aggregation requires at least one case")
    count = len(measurements)
    review_expected = sum(item.review_expected for item in measurements)
    return ParserBenchmarkMetrics(
        character_recall=sum(item.character_recall for item in measurements) / count,
        reading_order_recall=sum(item.reading_order_recall for item in measurements) / count,
        table_cell_recall=sum(item.table_cell_recall for item in measurements) / count,
        cross_page_continuation_recall=(
            sum(item.continuation_recall for item in measurements) / count
        ),
        citation_anchor_recall=sum(item.anchor_recall for item in measurements) / count,
        review_required_recall=(
            sum(item.review_detected for item in measurements) / review_expected
            if review_expected
            else 1.0
        ),
    )


__all__ = ["evaluate_parser_benchmark"]
