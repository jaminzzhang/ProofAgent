from pathlib import Path

from proof_agent.contracts import (
    EvaluationArtifactRef,
    EvaluationCaseRef,
    EvaluationGateStatus,
    EvaluationNodeStage,
    EvaluationResponseProjection,
    EvaluationResponseProjectionAudience,
    EvaluationSubject,
)
from proof_agent.evaluation.artifact_reader import read_evaluation_artifacts
from proof_agent.evaluation.node_results import extract_evaluation_node_results


def test_node_results_extract_five_aggregate_stages(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    receipt_path = tmp_path / "governance_receipt.md"
    response_path = tmp_path / "operator_response.txt"
    trace_path.write_text(
        '{"event_type":"reasoning_summary","status":"ok","payload":{"summary":"plan"}}\n'
        '{"event_type":"retrieval_result","status":"ok","payload":{"source_refs":["policy"]}}\n'
        '{"event_type":"evidence_evaluation","status":"ok",'
        '"payload":{"metadata":{"accepted_count":1}}}\n'
        '{"event_type":"policy_decision","status":"ok","payload":{"decision":"allow"}}\n'
        '{"event_type":"model_response","status":"ok","payload":{"usage":{"total_tokens":42}}}\n'
        '{"event_type":"final_output","status":"ok",'
        '"payload":{"outcome":"ANSWERED_WITH_CITATIONS"}}\n',
        encoding="utf-8",
    )
    receipt_path.write_text(
        "# Governance Receipt\n\n## Final Outcome\n\nANSWERED_WITH_CITATIONS\n",
        encoding="utf-8",
    )
    response_path.write_text("Answer", encoding="utf-8")
    subject = EvaluationSubject(
        case_ref=EvaluationCaseRef(case_id="case_1"),
        trace=EvaluationArtifactRef(ref=trace_path),
        receipt=EvaluationArtifactRef(ref=receipt_path),
        response_projection=EvaluationResponseProjection(
            audience=EvaluationResponseProjectionAudience.OPERATOR,
            ref=response_path,
        ),
    )
    artifacts = read_evaluation_artifacts(subject)

    results = {result.stage: result for result in extract_evaluation_node_results(artifacts)}

    assert tuple(results) == (
        EvaluationNodeStage.PLANNING,
        EvaluationNodeStage.RETRIEVAL_EVIDENCE,
        EvaluationNodeStage.POLICY_TOOL,
        EvaluationNodeStage.MODEL_VALIDATION,
        EvaluationNodeStage.AUDIT_PROJECTION,
    )
    assert results[EvaluationNodeStage.RETRIEVAL_EVIDENCE].status == EvaluationGateStatus.PASSED
    assert "retrieval_result" in results[EvaluationNodeStage.RETRIEVAL_EVIDENCE].observed_events
    assert results[EvaluationNodeStage.RETRIEVAL_EVIDENCE].key_facts["accepted_count"] == 1
