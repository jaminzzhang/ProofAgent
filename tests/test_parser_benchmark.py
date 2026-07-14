from proof_agent.contracts.evaluation import (
    InsuranceParserCase,
    InsuranceParserObservation,
    ParserExpectedTableCell,
)
from proof_agent.evaluation.parser_benchmark import evaluate_parser_benchmark


def test_parser_benchmark_scores_structure_ocr_anchors_and_review_recall() -> None:
    case = InsuranceParserCase(
        case_id="parser-table-cross-page",
        document_id="doc-1",
        revision_id="rev-1",
        document_slice="underwriting-table",
        parser_slice="paddle-fallback",
        query_slice="conditional_guidance",
        acl_slice="restricted",
        expected_reading_order=("heading", "paragraph", "table"),
        expected_table_cells=(
            ParserExpectedTableCell(
                table_id="table-1", page_number=1, row=0, column=0, text="职业"
            ),
            ParserExpectedTableCell(
                table_id="table-1", page_number=2, row=1, column=0, text="一类"
            ),
        ),
        expected_cross_page_continuation_ids=("continuation-1", "continuation-2"),
        expected_ocr_text="保险责任",
        expected_citation_anchors=("page=1", "page=2"),
        mandatory_review_expected=True,
    )
    observation = InsuranceParserObservation(
        case_id=case.case_id,
        observed_reading_order=("heading", "table"),
        observed_table_cells=(case.expected_table_cells[0],),
        observed_cross_page_continuation_ids=("continuation-1",),
        observed_ocr_text="保险责",
        observed_citation_anchors=("page=1",),
        review_required=False,
    )

    report = evaluate_parser_benchmark(cases=(case,), observations=(observation,))

    assert report.overall.character_recall == 0.75
    assert report.overall.reading_order_recall == 2 / 3
    assert report.overall.table_cell_recall == 0.5
    assert report.overall.cross_page_continuation_recall == 0.5
    assert report.overall.citation_anchor_recall == 0.5
    assert report.overall.review_required_recall == 0.0
    assert {(item.dimension, item.value) for item in report.slices} == {
        ("query_type", "conditional_guidance"),
        ("document", "underwriting-table"),
        ("parser", "paddle-fallback"),
        ("acl", "restricted"),
    }
