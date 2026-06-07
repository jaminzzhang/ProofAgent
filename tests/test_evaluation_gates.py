from pathlib import Path

from proof_agent.contracts import (
    EvaluationArtifactSufficiencyStatus,
    EvaluationArtifactRef,
    EvaluationCase,
    EvaluationCaseExpected,
    EvaluationCaseRef,
    EvaluationExpectedResolution,
    EvaluationGateName,
    EvaluationGateStatus,
    EvaluationResponseProjection,
    EvaluationResponseProjectionAudience,
    EvaluationSubject,
    ReceiptOutcome,
)
from proof_agent.evaluation.artifact_reader import read_evaluation_artifacts
from proof_agent.evaluation.errors import EvaluationInputError
from proof_agent.evaluation.gate_profiles import get_gate_profile
from proof_agent.evaluation.gates import evaluate_case_gates
import pytest


def test_core_gate_profile_lists_required_and_diagnostic_gates() -> None:
    profile = get_gate_profile("core_analyzer_gates.v1")

    assert profile.profile_id == "core_analyzer_gates.v1"
    assert EvaluationGateName.SUBJECT_MAPPING in profile.required_gates
    assert EvaluationGateName.ARTIFACT_SUFFICIENCY in profile.required_gates
    assert EvaluationGateName.FORBIDDEN_CLAIM in profile.diagnostic_gates


def test_unknown_gate_profile_is_rejected() -> None:
    with pytest.raises(EvaluationInputError, match="Unknown evaluation gate profile"):
        get_gate_profile("unknown")


def test_gates_pass_supported_answer_with_required_evidence(tmp_path: Path) -> None:
    case = EvaluationCase(
        case_id="supported_travel_meal",
        question="What is the reimbursement rule for travel meals?",
        intent_type="service_process_guidance",
        expected_resolution=EvaluationExpectedResolution.ANSWER_WITH_CITATIONS,
        risk_class="low_business_fact",
        capability_path="retrieval_only",
        expected=EvaluationCaseExpected(
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            required_citation_refs=("customer-support-policy",),
        ),
    )
    subject = _subject(tmp_path)
    artifacts = read_evaluation_artifacts(subject)

    gates = {result.gate: result for result in evaluate_case_gates(case, subject, artifacts)}

    assert gates[EvaluationGateName.OUTCOME].status == EvaluationGateStatus.PASSED
    assert gates[EvaluationGateName.CONTROL_ENVELOPE_COVERAGE].status == (
        EvaluationGateStatus.PASSED
    )
    assert gates[EvaluationGateName.EVIDENCE_STRUCTURAL].status == EvaluationGateStatus.PASSED


def test_gates_fail_when_trace_and_receipt_outcomes_disagree(tmp_path: Path) -> None:
    case = EvaluationCase(
        case_id="supported_travel_meal",
        question="What is the reimbursement rule for travel meals?",
        intent_type="service_process_guidance",
        expected_resolution=EvaluationExpectedResolution.ANSWER_WITH_CITATIONS,
        risk_class="low_business_fact",
        capability_path="retrieval_only",
        expected=EvaluationCaseExpected(outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS),
    )
    subject = _subject(tmp_path)
    subject.receipt.ref.write_text(
        "# Governance Receipt\n\n## Final Outcome\n\nREFUSED_NO_EVIDENCE\n",
        encoding="utf-8",
    )
    artifacts = read_evaluation_artifacts(subject)

    gates = {result.gate: result for result in evaluate_case_gates(case, subject, artifacts)}

    assert gates[EvaluationGateName.OUTCOME].status == EvaluationGateStatus.PASSED
    assert gates[EvaluationGateName.AUDIT_ARTIFACT].status == EvaluationGateStatus.FAILED
    assert "trace outcome did not match receipt outcome" in gates[
        EvaluationGateName.AUDIT_ARTIFACT
    ].reason


def test_artifact_sufficiency_gate_fails_on_hash_mismatch(tmp_path: Path) -> None:
    case = EvaluationCase(
        case_id="supported_travel_meal",
        question="What is the reimbursement rule for travel meals?",
        intent_type="service_process_guidance",
        expected_resolution=EvaluationExpectedResolution.ANSWER_WITH_CITATIONS,
        risk_class="low_business_fact",
        capability_path="retrieval_only",
        expected=EvaluationCaseExpected(outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS),
    )
    original = _subject(tmp_path)
    subject = EvaluationSubject(
        case_ref=original.case_ref,
        trace=EvaluationArtifactRef(ref=original.trace.ref, sha256="not-the-real-hash"),
        receipt=original.receipt,
        response_projection=original.response_projection,
    )
    artifacts = read_evaluation_artifacts(subject)

    gates = {result.gate: result for result in evaluate_case_gates(case, subject, artifacts)}

    assert gates[EvaluationGateName.ARTIFACT_SUFFICIENCY].status == EvaluationGateStatus.FAILED
    assert gates[EvaluationGateName.ARTIFACT_SUFFICIENCY].sufficiency == (
        EvaluationArtifactSufficiencyStatus.INSUFFICIENT
    )
    assert "hash mismatch" in gates[EvaluationGateName.ARTIFACT_SUFFICIENCY].reason


def _subject(tmp_path: Path) -> EvaluationSubject:
    trace_path = tmp_path / "trace.jsonl"
    receipt_path = tmp_path / "governance_receipt.md"
    response_path = tmp_path / "operator_response.txt"
    trace_path.write_text(
        '{"run_id":"run_123","event_type":"run_started","sequence":1,"status":"ok"}\n'
        '{"run_id":"run_123","event_type":"retrieval_step","sequence":2,"status":"ok"}\n'
        '{"run_id":"run_123","event_type":"retrieval_result","sequence":3,"status":"ok",'
        '"payload":{"source_refs":["customer-support-policy"]}}\n'
        '{"run_id":"run_123","event_type":"evidence_evaluation","sequence":4,"status":"ok",'
        '"payload":{"metadata":{"accepted_count":1},'
        '"accepted_sources":["customer-support-policy"]}}\n'
        '{"run_id":"run_123","event_type":"policy_decision","sequence":5,"status":"ok"}\n'
        '{"run_id":"run_123","event_type":"final_output","sequence":6,"status":"ok",'
        '"payload":{"outcome":"ANSWERED_WITH_CITATIONS","message":"Travel meals."}}\n',
        encoding="utf-8",
    )
    receipt_path.write_text(
        "# Governance Receipt\n\n## Final Outcome\n\nANSWERED_WITH_CITATIONS\n",
        encoding="utf-8",
    )
    response_path.write_text("Travel meals are reimbursed with receipts.", encoding="utf-8")
    return EvaluationSubject(
        case_ref=EvaluationCaseRef(case_id="supported_travel_meal"),
        trace=EvaluationArtifactRef(ref=trace_path),
        receipt=EvaluationArtifactRef(ref=receipt_path),
        response_projection=EvaluationResponseProjection(
            audience=EvaluationResponseProjectionAudience.OPERATOR,
            ref=response_path,
        ),
    )
