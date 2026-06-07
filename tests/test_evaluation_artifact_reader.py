from pathlib import Path

from proof_agent.contracts import (
    EvaluationArtifactRef,
    EvaluationCaseRef,
    EvaluationResponseProjection,
    EvaluationResponseProjectionAudience,
    EvaluationSubject,
    ReceiptOutcome,
)
from proof_agent.evaluation.artifact_reader import read_evaluation_artifacts


def test_artifact_reader_reads_trace_receipt_and_response_projection(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    receipt_path = tmp_path / "governance_receipt.md"
    response_path = tmp_path / "operator_response.txt"
    trace_path.write_text(
        '{"run_id":"run_123","event_type":"run_started","sequence":1,"status":"ok"}\n'
        '{"run_id":"run_123","event_type":"final_output","sequence":2,"status":"ok",'
        '"payload":{"outcome":"ANSWERED_WITH_CITATIONS","message":"Travel meals."}}\n',
        encoding="utf-8",
    )
    receipt_path.write_text(
        "# Governance Receipt\n\n## Final Outcome\n\nANSWERED_WITH_CITATIONS\n",
        encoding="utf-8",
    )
    response_path.write_text("Travel meals are reimbursed with receipts.", encoding="utf-8")
    subject = EvaluationSubject(
        case_ref=EvaluationCaseRef(case_id="supported_travel_meal"),
        trace=EvaluationArtifactRef(ref=trace_path),
        receipt=EvaluationArtifactRef(ref=receipt_path),
        response_projection=EvaluationResponseProjection(
            audience=EvaluationResponseProjectionAudience.OPERATOR,
            ref=response_path,
        ),
    )

    artifacts = read_evaluation_artifacts(subject)

    assert artifacts.actual_outcome == ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert artifacts.receipt_outcome == ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert artifacts.response_text == "Travel meals are reimbursed with receipts."
    assert [event.event_type for event in artifacts.trace_events] == [
        "run_started",
        "final_output",
    ]
