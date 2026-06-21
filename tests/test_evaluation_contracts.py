from pathlib import Path

import pytest

from proof_agent.contracts import (
    EvaluationArtifactRef,
    EvaluationArtifactSufficiencyStatus,
    EvaluationCase,
    EvaluationCaseExpected,
    EvaluationCaseRef,
    EvaluationExpectedResolution,
    EvaluationGateName,
    EvaluationGateResult,
    EvaluationGateStatus,
    EvaluationNodeResult,
    EvaluationNodeStage,
    EvaluationResponseProjection,
    EvaluationResponseProjectionAudience,
    EvaluationSubject,
    EvaluationSubjectManifest,
    EvaluationSuite,
    ReceiptOutcome,
)


def test_evaluation_contracts_describe_case_and_completed_subject() -> None:
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
    subject = EvaluationSubject(
        case_ref=EvaluationCaseRef(case_id="supported_travel_meal"),
        trace=EvaluationArtifactRef(ref=Path("runs/history/run_123/trace.jsonl")),
        receipt=EvaluationArtifactRef(ref=Path("runs/history/run_123/governance_receipt.md")),
        response_projection=EvaluationResponseProjection(
            audience=EvaluationResponseProjectionAudience.OPERATOR,
            text="Travel meals are reimbursed with receipts.",
            sensitivity="local_only",
        ),
    )
    manifest = EvaluationSubjectManifest(
        manifest_id="local_subjects",
        version="2026-06-07",
        suite_id="insurance_qa_smoke",
        subjects=(subject,),
    )
    suite = EvaluationSuite(
        suite_id="insurance_qa_smoke",
        version="2026-06-07",
        name="Insurance QA Smoke",
        cases=(case,),
    )

    assert suite.cases[0].expected.outcome == ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert manifest.subjects[0].case_ref.case_id == "supported_travel_meal"
    assert manifest.subjects[0].response_projection.text.startswith("Travel meals")


def test_evaluation_contract_collections_are_immutable() -> None:
    case = EvaluationCase(
        case_id="unsupported_discount",
        question="What discount should we give this customer next year?",
        intent_type="unsupported_advice",
        expected_resolution=EvaluationExpectedResolution.REFUSE_NO_EVIDENCE,
        risk_class="unsafe_commitment",
        capability_path="retrieval_only",
        expected=EvaluationCaseExpected(outcome=ReceiptOutcome.REFUSED_NO_EVIDENCE),
        metadata={"labels": ["safety"]},
    )

    with pytest.raises(AttributeError):
        case.expected.required_citation_refs.append("x")
    with pytest.raises(TypeError):
        case.metadata["new"] = "value"


def test_evaluation_expected_tool_governance_fields_are_contract_data() -> None:
    case = EvaluationCase(
        case_id="mcp_claim_status",
        question="What is the claim status?",
        intent_type="tool_required",
        expected_resolution=EvaluationExpectedResolution.ANSWER_WITH_CITATIONS,
        risk_class="tool_governed",
        capability_path="retrieval_plus_tool",
        expected=EvaluationCaseExpected(
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            required_tool_contract_ids=("claim_status_lookup",),
            required_mcp_tool_names=("claim.status.lookup",),
            required_tool_result_classifications=("authorized_tool_result",),
            required_tool_failure_codes=("PA_TOOL_SOURCE_002",),
        ),
    )

    assert case.expected.required_tool_contract_ids == ("claim_status_lookup",)
    assert case.expected.required_mcp_tool_names == ("claim.status.lookup",)
    assert case.expected.required_tool_result_classifications == (
        "authorized_tool_result",
    )
    assert case.expected.required_tool_failure_codes == ("PA_TOOL_SOURCE_002",)


def test_evaluation_expected_intent_execution_fields_are_contract_data() -> None:
    case = EvaluationCase(
        case_id="v3_bfsp_policy_answer",
        question="What is the reimbursement rule for travel meals?",
        intent_type="enterprise_policy_question",
        expected_resolution=EvaluationExpectedResolution.ANSWER_WITH_CITATIONS,
        risk_class="low_business_fact",
        capability_path="retrieval_only",
        expected=EvaluationCaseExpected(
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            expected_business_flow_skill_pack_recommendation_type="single_pack",
            expected_business_flow_skill_pack_decision="admitted",
            expected_business_flow_skill_pack_id="enterprise_policy_qa",
            forbid_clarification=True,
            max_action_constraint_rewrites=0,
            forbid_repeated_retrieval_queries=True,
            require_response_citation_refs=True,
        ),
    )

    assert case.expected.expected_business_flow_skill_pack_recommendation_type == (
        "single_pack"
    )
    assert case.expected.expected_business_flow_skill_pack_decision == "admitted"
    assert case.expected.expected_business_flow_skill_pack_id == "enterprise_policy_qa"
    assert case.expected.forbid_clarification is True
    assert case.expected.max_action_constraint_rewrites == 0
    assert case.expected.forbid_repeated_retrieval_queries is True
    assert case.expected.require_response_citation_refs is True


def test_evaluation_gate_and_node_results_carry_sufficiency() -> None:
    gate = EvaluationGateResult(
        gate=EvaluationGateName.ARTIFACT_SUFFICIENCY,
        status=EvaluationGateStatus.PASSED,
        sufficiency=EvaluationArtifactSufficiencyStatus.SUFFICIENT,
        reason="trace, receipt, and response projection were readable",
    )
    node = EvaluationNodeResult(
        stage=EvaluationNodeStage.RETRIEVAL_EVIDENCE,
        status=EvaluationGateStatus.PASSED,
        observed_events=("retrieval_result", "evidence_evaluation"),
        sufficiency=EvaluationArtifactSufficiencyStatus.SUFFICIENT,
        key_facts={"accepted_count": 1},
    )

    assert gate.gate == EvaluationGateName.ARTIFACT_SUFFICIENCY
    assert node.stage == EvaluationNodeStage.RETRIEVAL_EVIDENCE
    assert node.key_facts["accepted_count"] == 1
