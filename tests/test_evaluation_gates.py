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
    InsuranceKnowledgeEvaluationReport,
    InsuranceKnowledgeSliceMetrics,
    InsuranceRetrievalMetrics,
    ReceiptOutcome,
)
from proof_agent.evaluation.artifact_reader import read_evaluation_artifacts
from proof_agent.evaluation.errors import EvaluationInputError
from proof_agent.evaluation.gate_profiles import get_gate_profile
from proof_agent.evaluation.gates import evaluate_case_gates
from proof_agent.evaluation.knowledge_gates import (
    KnowledgeAcceptanceAggregate,
    KnowledgeHardGateFacts,
    evaluate_knowledge_release,
)
import pytest


def _knowledge_metrics(
    *, recall_50: float = 0.96, complete_top_10: float = 0.92
) -> InsuranceRetrievalMetrics:
    return InsuranceRetrievalMetrics(
        retrieval_case_count=100,
        required_evidence_recall_at_20=0.94,
        required_evidence_recall_at_50=recall_50,
        required_evidence_recall_at_100=0.99,
        complete_evidence_top_5_rate=0.88,
        complete_evidence_top_10_rate=complete_top_10,
        ndcg_at_10=0.93,
        mrr_at_10=0.95,
        citation_resolvability_rate=1.0,
    )


def _knowledge_aggregate(
    *,
    hard_facts: KnowledgeHardGateFacts | None = None,
    overall_recall_50: float = 0.96,
    conditional_complete_top_10: float = 0.92,
    retrieval_p95_seconds: float = 4.5,
) -> KnowledgeAcceptanceAggregate:
    slices = tuple(
        InsuranceKnowledgeSliceMetrics(
            dimension="query_type",
            value=query_type,
            case_count=case_count,
            metrics=_knowledge_metrics(
                complete_top_10=(
                    conditional_complete_top_10 if query_type == "conditional_guidance" else 0.92
                )
            ),
        )
        for query_type, case_count in (
            ("clause_lookup", 60),
            ("conditional_guidance", 100),
            ("comparison", 40),
        )
    )
    return KnowledgeAcceptanceAggregate(
        report=InsuranceKnowledgeEvaluationReport(
            case_count=200,
            overall=_knowledge_metrics(recall_50=overall_recall_50),
            slices=slices,
        ),
        hard_facts=hard_facts or KnowledgeHardGateFacts(),
        human_reviewed_support_precision=0.99,
        hybrid_retrieval_p95_seconds=retrieval_p95_seconds,
    )


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


def test_tool_governance_gate_passes_expected_mcp_tool_projection(
    tmp_path: Path,
) -> None:
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
        ),
    )
    subject = _mcp_subject(tmp_path)
    artifacts = read_evaluation_artifacts(subject)

    gates = {result.gate: result for result in evaluate_case_gates(case, subject, artifacts)}

    assert gates[EvaluationGateName.TOOL_GOVERNANCE_STRUCTURAL].status == (
        EvaluationGateStatus.PASSED
    )


def test_tool_proposal_scope_gate_passes_declared_scope_projection(
    tmp_path: Path,
) -> None:
    case = EvaluationCase(
        case_id="mcp_claim_status",
        question="What is the claim status?",
        intent_type="tool_required",
        expected_resolution=EvaluationExpectedResolution.ANSWER_WITH_CITATIONS,
        risk_class="tool_governed",
        capability_path="retrieval_plus_tool",
        expected=EvaluationCaseExpected(
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            required_tool_proposal_scope_contract_ids=("claim_status_lookup",),
        ),
    )
    subject = _tool_scope_subject(tmp_path)
    artifacts = read_evaluation_artifacts(subject)

    gates = {result.gate: result for result in evaluate_case_gates(case, subject, artifacts)}

    assert gates[EvaluationGateName.TOOL_PROPOSAL_SCOPE].status == EvaluationGateStatus.PASSED


def test_tool_proposal_scope_gate_fails_on_schema_projection_leakage(
    tmp_path: Path,
) -> None:
    case = EvaluationCase(
        case_id="mcp_claim_status",
        question="What is the claim status?",
        intent_type="tool_required",
        expected_resolution=EvaluationExpectedResolution.ANSWER_WITH_CITATIONS,
        risk_class="tool_governed",
        capability_path="retrieval_plus_tool",
        expected=EvaluationCaseExpected(
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            required_tool_proposal_scope_contract_ids=("claim_status_lookup",),
        ),
    )
    subject = _tool_scope_subject(tmp_path, leak_schema=True)
    artifacts = read_evaluation_artifacts(subject)

    gates = {result.gate: result for result in evaluate_case_gates(case, subject, artifacts)}

    assert gates[EvaluationGateName.TOOL_PROPOSAL_SCOPE].status == EvaluationGateStatus.FAILED
    assert (
        "scope projection exposed hidden field(s): input_schema"
        in gates[EvaluationGateName.TOOL_PROPOSAL_SCOPE].reason
    )


def test_tool_governance_gate_fails_when_expected_mcp_tool_is_missing(
    tmp_path: Path,
) -> None:
    case = EvaluationCase(
        case_id="mcp_claim_status",
        question="What is the claim status?",
        intent_type="tool_required",
        expected_resolution=EvaluationExpectedResolution.ANSWER_WITH_CITATIONS,
        risk_class="tool_governed",
        capability_path="retrieval_plus_tool",
        expected=EvaluationCaseExpected(
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            required_tool_contract_ids=("policy_lookup",),
            required_mcp_tool_names=("policy.lookup",),
            required_tool_result_classifications=("authorized_tool_result",),
        ),
    )
    subject = _mcp_subject(tmp_path)
    artifacts = read_evaluation_artifacts(subject)

    gates = {result.gate: result for result in evaluate_case_gates(case, subject, artifacts)}

    assert gates[EvaluationGateName.TOOL_GOVERNANCE_STRUCTURAL].status == (
        EvaluationGateStatus.FAILED
    )
    assert (
        "missing expected MCP tool(s): policy.lookup"
        in gates[EvaluationGateName.TOOL_GOVERNANCE_STRUCTURAL].reason
    )


def test_tool_governance_gate_fails_when_expected_mcp_failure_is_missing(
    tmp_path: Path,
) -> None:
    case = EvaluationCase(
        case_id="mcp_claim_status",
        question="What is the claim status?",
        intent_type="tool_required",
        expected_resolution=EvaluationExpectedResolution.ANSWER_WITH_CITATIONS,
        risk_class="tool_governed",
        capability_path="retrieval_plus_tool",
        expected=EvaluationCaseExpected(
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            required_tool_failure_codes=("PA_TOOL_SOURCE_002",),
        ),
    )
    subject = _mcp_subject(tmp_path)
    artifacts = read_evaluation_artifacts(subject)

    gates = {result.gate: result for result in evaluate_case_gates(case, subject, artifacts)}

    assert gates[EvaluationGateName.TOOL_GOVERNANCE_STRUCTURAL].status == (
        EvaluationGateStatus.FAILED
    )
    assert (
        "missing expected tool failure code(s): PA_TOOL_SOURCE_002"
        in gates[EvaluationGateName.TOOL_GOVERNANCE_STRUCTURAL].reason
    )


def test_tool_governance_gate_passes_expected_mcp_failure_code(
    tmp_path: Path,
) -> None:
    case = EvaluationCase(
        case_id="mcp_claim_status",
        question="What is the claim status?",
        intent_type="tool_required",
        expected_resolution=EvaluationExpectedResolution.ANSWER_WITH_CITATIONS,
        risk_class="tool_governed",
        capability_path="retrieval_plus_tool",
        expected=EvaluationCaseExpected(
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            required_tool_failure_codes=("PA_TOOL_SOURCE_002",),
        ),
    )
    subject = _mcp_subject(tmp_path)
    subject.trace.ref.write_text(
        subject.trace.ref.read_text(encoding="utf-8")
        .replace(
            '"event_type":"tool_result","sequence":3,"status":"ok"',
            '"event_type":"tool_result","sequence":3,"status":"error"',
        )
        .replace(
            '"result_schema_validation":"passed",',
            '"result_schema_validation":"failed","error_code":"PA_TOOL_SOURCE_002",',
        ),
        encoding="utf-8",
    )
    artifacts = read_evaluation_artifacts(subject)

    gates = {result.gate: result for result in evaluate_case_gates(case, subject, artifacts)}

    assert gates[EvaluationGateName.TOOL_GOVERNANCE_STRUCTURAL].status == (
        EvaluationGateStatus.PASSED
    )


def test_redaction_safety_gate_fails_on_raw_mcp_payload_leakage(
    tmp_path: Path,
) -> None:
    case = EvaluationCase(
        case_id="mcp_claim_status",
        question="What is the claim status?",
        intent_type="tool_required",
        expected_resolution=EvaluationExpectedResolution.ANSWER_WITH_CITATIONS,
        risk_class="tool_governed",
        capability_path="retrieval_plus_tool",
        expected=EvaluationCaseExpected(outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS),
    )
    subject = _mcp_subject(tmp_path)
    subject.trace.ref.write_text(
        subject.trace.ref.read_text(encoding="utf-8").replace(
            '"summary":{"claim_id":"CLM-001","status":"open"}',
            '"summary":{"claim_id":"CLM-001","status":"open"},'
            '"raw_payload":{"internal_note":"adjuster-only note",'
            '"token":"secret-token"}',
        ),
        encoding="utf-8",
    )
    artifacts = read_evaluation_artifacts(subject)

    gates = {result.gate: result for result in evaluate_case_gates(case, subject, artifacts)}

    assert gates[EvaluationGateName.REDACTION_SAFETY].status == EvaluationGateStatus.FAILED
    assert (
        "raw MCP payload marker found in trace" in gates[EvaluationGateName.REDACTION_SAFETY].reason
    )


def test_business_flow_skill_pack_gate_passes_when_admission_matches_expected_pack(
    tmp_path: Path,
) -> None:
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
            expected_business_flow_skill_pack_id="enterprise_policy_qa",
        ),
    )
    subject = _subject(tmp_path)
    trace = subject.trace.ref.read_text(encoding="utf-8")
    subject.trace.ref.write_text(
        trace.replace(
            '{"run_id":"run_123","event_type":"final_output"',
            '{"run_id":"run_123","event_type":"business_flow_skill_pack_admission",'
            '"sequence":6,"status":"ok","payload":{"decision":"admitted",'
            '"selected_pack_id":"enterprise_policy_qa",'
            '"recommendation_type":"single_pack",'
            '"candidate_packs":[{"pack_id":"enterprise_policy_qa",'
            '"confidence":0.9,"reason":"Relevant."}]}}\n'
            '{"run_id":"run_123","event_type":"final_output"',
        ),
        encoding="utf-8",
    )
    artifacts = read_evaluation_artifacts(subject)

    gates = {result.gate: result for result in evaluate_case_gates(case, subject, artifacts)}

    assert gates[EvaluationGateName.BUSINESS_FLOW_SKILL_PACK].status == (
        EvaluationGateStatus.PASSED
    )


def test_business_flow_skill_pack_gate_fails_when_selected_pack_differs(
    tmp_path: Path,
) -> None:
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
            expected_business_flow_skill_pack_id="enterprise_policy_qa",
        ),
    )
    subject = _subject(tmp_path)
    trace = subject.trace.ref.read_text(encoding="utf-8")
    subject.trace.ref.write_text(
        trace.replace(
            '{"run_id":"run_123","event_type":"final_output"',
            '{"run_id":"run_123","event_type":"business_flow_skill_pack_admission",'
            '"sequence":6,"status":"ok","payload":{"decision":"admitted",'
            '"selected_pack_id":"general_qa",'
            '"recommendation_type":"single_pack",'
            '"candidate_packs":[{"pack_id":"general_qa",'
            '"confidence":0.9,"reason":"Relevant."}]}}\n'
            '{"run_id":"run_123","event_type":"final_output"',
        ),
        encoding="utf-8",
    )
    artifacts = read_evaluation_artifacts(subject)

    gates = {result.gate: result for result in evaluate_case_gates(case, subject, artifacts)}

    assert gates[EvaluationGateName.BUSINESS_FLOW_SKILL_PACK].status == (
        EvaluationGateStatus.FAILED
    )
    assert (
        "expected Business Flow Skill Pack enterprise_policy_qa"
        in gates[EvaluationGateName.BUSINESS_FLOW_SKILL_PACK].reason
    )


def test_business_flow_skill_pack_gate_fails_when_expected_decision_differs(
    tmp_path: Path,
) -> None:
    case = EvaluationCase(
        case_id="supported_travel_meal",
        question="What is the reimbursement rule for travel meals?",
        intent_type="service_process_guidance",
        expected_resolution=EvaluationExpectedResolution.ANSWER_WITH_CITATIONS,
        risk_class="low_business_fact",
        capability_path="retrieval_only",
        expected=EvaluationCaseExpected(
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            expected_business_flow_skill_pack_decision="no_pack",
        ),
    )
    subject = _subject(tmp_path)
    trace = subject.trace.ref.read_text(encoding="utf-8")
    subject.trace.ref.write_text(
        trace.replace(
            '{"run_id":"run_123","event_type":"final_output"',
            '{"run_id":"run_123","event_type":"business_flow_skill_pack_admission",'
            '"sequence":6,"status":"blocked","payload":{"decision":"needs_clarification",'
            '"selected_pack_id":null,'
            '"recommendation_type":"ambiguous",'
            '"candidate_packs":[{"pack_id":"enterprise_policy_qa",'
            '"confidence":0.9,"reason":"Relevant."}]}}\n'
            '{"run_id":"run_123","event_type":"final_output"',
        ),
        encoding="utf-8",
    )
    artifacts = read_evaluation_artifacts(subject)

    gates = {result.gate: result for result in evaluate_case_gates(case, subject, artifacts)}

    assert gates[EvaluationGateName.BUSINESS_FLOW_SKILL_PACK].status == (
        EvaluationGateStatus.FAILED
    )
    assert (
        "expected Business Flow Skill Pack decision no_pack"
        in gates[EvaluationGateName.BUSINESS_FLOW_SKILL_PACK].reason
    )


def test_business_flow_skill_pack_gate_passes_expected_no_pack_decision(
    tmp_path: Path,
) -> None:
    case = EvaluationCase(
        case_id="supported_travel_meal",
        question="What is the reimbursement rule for travel meals?",
        intent_type="service_process_guidance",
        expected_resolution=EvaluationExpectedResolution.ANSWER_WITH_CITATIONS,
        risk_class="low_business_fact",
        capability_path="retrieval_only",
        expected=EvaluationCaseExpected(
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            expected_business_flow_skill_pack_decision="no_pack",
        ),
    )
    subject = _subject(tmp_path)
    trace = subject.trace.ref.read_text(encoding="utf-8")
    subject.trace.ref.write_text(
        trace.replace(
            '{"run_id":"run_123","event_type":"final_output"',
            '{"run_id":"run_123","event_type":"business_flow_skill_pack_admission",'
            '"sequence":6,"status":"ok","payload":{"decision":"no_pack",'
            '"selected_pack_id":null,'
            '"recommendation_type":"no_pack",'
            '"candidate_packs":[]}}\n'
            '{"run_id":"run_123","event_type":"final_output"',
        ),
        encoding="utf-8",
    )
    artifacts = read_evaluation_artifacts(subject)

    gates = {result.gate: result for result in evaluate_case_gates(case, subject, artifacts)}

    assert gates[EvaluationGateName.BUSINESS_FLOW_SKILL_PACK].status == (
        EvaluationGateStatus.PASSED
    )


def test_business_flow_skill_pack_gate_fails_when_expected_recommendation_differs(
    tmp_path: Path,
) -> None:
    case = EvaluationCase(
        case_id="supported_travel_meal",
        question="What is the reimbursement rule for travel meals?",
        intent_type="service_process_guidance",
        expected_resolution=EvaluationExpectedResolution.ANSWER_WITH_CITATIONS,
        risk_class="low_business_fact",
        capability_path="retrieval_only",
        expected=EvaluationCaseExpected(
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            expected_business_flow_skill_pack_recommendation_type="no_pack",
        ),
    )
    subject = _subject(tmp_path)
    trace = subject.trace.ref.read_text(encoding="utf-8")
    subject.trace.ref.write_text(
        trace.replace(
            '{"run_id":"run_123","event_type":"final_output"',
            '{"run_id":"run_123","event_type":"business_flow_skill_pack_recommendation",'
            '"sequence":6,"status":"ok","payload":{"recommendation_type":"ambiguous",'
            '"candidate_packs":[{"pack_id":"enterprise_policy_qa",'
            '"confidence":0.9,"reason":"Relevant."}]}}\n'
            '{"run_id":"run_123","event_type":"final_output"',
        ),
        encoding="utf-8",
    )
    artifacts = read_evaluation_artifacts(subject)

    gates = {result.gate: result for result in evaluate_case_gates(case, subject, artifacts)}

    assert gates[EvaluationGateName.BUSINESS_FLOW_SKILL_PACK].status == (
        EvaluationGateStatus.FAILED
    )
    assert (
        "expected Business Flow Skill Pack recommendation no_pack"
        in gates[EvaluationGateName.BUSINESS_FLOW_SKILL_PACK].reason
    )


def test_intent_execution_behavior_gate_fails_for_forbidden_clarification(
    tmp_path: Path,
) -> None:
    case = EvaluationCase(
        case_id="supported_travel_meal",
        question="What is the reimbursement rule for travel meals?",
        intent_type="service_process_guidance",
        expected_resolution=EvaluationExpectedResolution.ANSWER_WITH_CITATIONS,
        risk_class="low_business_fact",
        capability_path="retrieval_only",
        expected=EvaluationCaseExpected(
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            forbid_clarification=True,
        ),
    )
    subject = _subject(tmp_path)
    trace = subject.trace.ref.read_text(encoding="utf-8")
    subject.trace.ref.write_text(
        trace.replace(
            '{"run_id":"run_123","event_type":"final_output"',
            '{"run_id":"run_123","event_type":"clarification_requested",'
            '"sequence":6,"status":"waiting","payload":{"question":"Which pack?"}}\n'
            '{"run_id":"run_123","event_type":"final_output"',
        ),
        encoding="utf-8",
    )
    artifacts = read_evaluation_artifacts(subject)

    gates = {result.gate: result for result in evaluate_case_gates(case, subject, artifacts)}

    assert gates[EvaluationGateName.INTENT_EXECUTION_BEHAVIOR].status == (
        EvaluationGateStatus.FAILED
    )
    assert "clarification_requested" in gates[EvaluationGateName.INTENT_EXECUTION_BEHAVIOR].reason


def test_intent_execution_behavior_gate_fails_when_action_rewrites_exceed_limit(
    tmp_path: Path,
) -> None:
    case = EvaluationCase(
        case_id="supported_travel_meal",
        question="What is the reimbursement rule for travel meals?",
        intent_type="service_process_guidance",
        expected_resolution=EvaluationExpectedResolution.ANSWER_WITH_CITATIONS,
        risk_class="low_business_fact",
        capability_path="retrieval_only",
        expected=EvaluationCaseExpected(
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            max_action_constraint_rewrites=0,
        ),
    )
    subject = _subject(tmp_path)
    trace = subject.trace.ref.read_text(encoding="utf-8")
    subject.trace.ref.write_text(
        trace.replace(
            '{"run_id":"run_123","event_type":"final_output"',
            '{"run_id":"run_123","event_type":"action_constrained",'
            '"sequence":6,"status":"ok","payload":{"original_action_type":"plan_retrieval",'
            '"constrained_to":"generate_final_answer"}}\n'
            '{"run_id":"run_123","event_type":"final_output"',
        ),
        encoding="utf-8",
    )
    artifacts = read_evaluation_artifacts(subject)

    gates = {result.gate: result for result in evaluate_case_gates(case, subject, artifacts)}

    assert gates[EvaluationGateName.INTENT_EXECUTION_BEHAVIOR].status == (
        EvaluationGateStatus.FAILED
    )
    assert (
        "action_constrained count 1 exceeded limit 0"
        in gates[EvaluationGateName.INTENT_EXECUTION_BEHAVIOR].reason
    )


def test_intent_execution_behavior_gate_fails_for_repeated_retrieval_query(
    tmp_path: Path,
) -> None:
    case = EvaluationCase(
        case_id="supported_travel_meal",
        question="What is the reimbursement rule for travel meals?",
        intent_type="service_process_guidance",
        expected_resolution=EvaluationExpectedResolution.ANSWER_WITH_CITATIONS,
        risk_class="low_business_fact",
        capability_path="retrieval_only",
        expected=EvaluationCaseExpected(
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            forbid_repeated_retrieval_queries=True,
        ),
    )
    subject = _subject(tmp_path)
    trace = subject.trace.ref.read_text(encoding="utf-8")
    subject.trace.ref.write_text(
        trace.replace(
            '{"run_id":"run_123","event_type":"retrieval_result"',
            '{"run_id":"run_123","event_type":"retrieval_step","sequence":2,'
            '"status":"ok","payload":{"query":"Travel meal reimbursement"}}\n'
            '{"run_id":"run_123","event_type":"retrieval_step","sequence":3,'
            '"status":"ok","payload":{"query":" travel   meal reimbursement "}}\n'
            '{"run_id":"run_123","event_type":"retrieval_result"',
        ),
        encoding="utf-8",
    )
    artifacts = read_evaluation_artifacts(subject)

    gates = {result.gate: result for result in evaluate_case_gates(case, subject, artifacts)}

    assert gates[EvaluationGateName.INTENT_EXECUTION_BEHAVIOR].status == (
        EvaluationGateStatus.FAILED
    )
    assert (
        "repeated retrieval query: travel meal reimbursement"
        in gates[EvaluationGateName.INTENT_EXECUTION_BEHAVIOR].reason
    )


def test_response_projection_safety_gate_fails_when_required_citation_ref_missing(
    tmp_path: Path,
) -> None:
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
            require_response_citation_refs=True,
        ),
    )
    subject = _subject(tmp_path)
    artifacts = read_evaluation_artifacts(subject)

    gates = {result.gate: result for result in evaluate_case_gates(case, subject, artifacts)}

    assert gates[EvaluationGateName.RESPONSE_PROJECTION_SAFETY].status == (
        EvaluationGateStatus.FAILED
    )
    assert (
        "missing response citation refs: customer-support-policy"
        in gates[EvaluationGateName.RESPONSE_PROJECTION_SAFETY].reason
    )


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
    assert (
        "trace outcome did not match receipt outcome"
        in gates[EvaluationGateName.AUDIT_ARTIFACT].reason
    )


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


def _mcp_subject(tmp_path: Path) -> EvaluationSubject:
    trace_path = tmp_path / "mcp_trace.jsonl"
    receipt_path = tmp_path / "mcp_governance_receipt.md"
    response_path = tmp_path / "mcp_operator_response.txt"
    trace_path.write_text(
        '{"run_id":"run_mcp","event_type":"policy_decision","sequence":1,"status":"ok"}\n'
        '{"run_id":"run_mcp","event_type":"tool_request","sequence":2,"status":"ok",'
        '"payload":{"tool_contract_id":"claim_status_lookup",'
        '"mcp_tool_name":"claim.status.lookup","provider":"mcp"}}\n'
        '{"run_id":"run_mcp","event_type":"tool_result","sequence":3,"status":"ok",'
        '"payload":{"provider":"mcp","tool_source_id":"tool_mcp_claims_http",'
        '"tool_contract_id":"claim_status_lookup",'
        '"mcp_tool_name":"claim.status.lookup",'
        '"contract_snapshot_digest":"sha256:contract",'
        '"result_schema_validation":"passed",'
        '"result_classification":"authorized_tool_result",'
        '"summary_fields":["claim_id","status"],'
        '"summary":{"claim_id":"CLM-001","status":"open"}}}\n'
        '{"run_id":"run_mcp","event_type":"final_output","sequence":4,"status":"ok",'
        '"payload":{"outcome":"ANSWERED_WITH_CITATIONS"}}\n',
        encoding="utf-8",
    )
    receipt_path.write_text(
        "# Governance Receipt\n\n## Final Outcome\n\nANSWERED_WITH_CITATIONS\n\n"
        "claim_status_lookup claim.status.lookup authorized_tool_result\n",
        encoding="utf-8",
    )
    response_path.write_text("Claim CLM-001 is open.", encoding="utf-8")
    return EvaluationSubject(
        case_ref=EvaluationCaseRef(case_id="mcp_claim_status"),
        trace=EvaluationArtifactRef(ref=trace_path),
        receipt=EvaluationArtifactRef(ref=receipt_path),
        response_projection=EvaluationResponseProjection(
            audience=EvaluationResponseProjectionAudience.OPERATOR,
            ref=response_path,
        ),
    )


def _tool_scope_subject(
    tmp_path: Path,
    *,
    leak_schema: bool = False,
) -> EvaluationSubject:
    trace_path = tmp_path / "tool_scope_trace.jsonl"
    receipt_path = tmp_path / "tool_scope_governance_receipt.md"
    response_path = tmp_path / "tool_scope_operator_response.txt"
    interface_payload = (
        '{"tool_contract_id":"claim_status_lookup","purpose":"claim status lookup",'
        '"parameters":[{"name":"claim_id","required":true,'
        '"value_source":"user_supplied"}]}'
    )
    if leak_schema:
        interface_payload = (
            '{"tool_contract_id":"claim_status_lookup","purpose":"claim status lookup",'
            '"input_schema":{"type":"object"},'
            '"parameters":[{"name":"claim_id","required":true,'
            '"value_source":"user_supplied"}]}'
        )
    trace_path.write_text(
        '{"run_id":"run_scope","event_type":"tool_proposal_scope","sequence":1,'
        '"status":"ok","payload":{"schema_digest":"sha256:scope",'
        '"tool_interfaces":[' + interface_payload + "]}}\n"
        '{"run_id":"run_scope","event_type":"policy_decision","sequence":2,"status":"ok"}\n'
        '{"run_id":"run_scope","event_type":"tool_request","sequence":3,"status":"ok",'
        '"payload":{"tool_contract_id":"claim_status_lookup",'
        '"mcp_tool_name":"claim.status.lookup","provider":"mcp",'
        '"scope_digest":"sha256:scope","parameter_digest":"sha256:params"}}\n'
        '{"run_id":"run_scope","event_type":"tool_result","sequence":4,"status":"ok",'
        '"payload":{"provider":"mcp","tool_source_id":"tool_mcp_claims_http",'
        '"tool_contract_id":"claim_status_lookup",'
        '"mcp_tool_name":"claim.status.lookup",'
        '"result_schema_validation":"passed",'
        '"result_classification":"authorized_tool_result",'
        '"summary":{"claim_id":"CLM-001","status":"open"}}}\n'
        '{"run_id":"run_scope","event_type":"final_output","sequence":5,"status":"ok",'
        '"payload":{"outcome":"ANSWERED_WITH_CITATIONS"}}\n',
        encoding="utf-8",
    )
    receipt_path.write_text(
        "# Governance Receipt\n\n## Final Outcome\n\nANSWERED_WITH_CITATIONS\n",
        encoding="utf-8",
    )
    response_path.write_text("Claim CLM-001 is open.", encoding="utf-8")
    return EvaluationSubject(
        case_ref=EvaluationCaseRef(case_id="mcp_claim_status"),
        trace=EvaluationArtifactRef(ref=trace_path),
        receipt=EvaluationArtifactRef(ref=receipt_path),
        response_projection=EvaluationResponseProjection(
            audience=EvaluationResponseProjectionAudience.OPERATOR,
            ref=response_path,
        ),
    )


def test_knowledge_hard_gate_failure_skips_compensating_quality_and_performance() -> None:
    aggregate = _knowledge_aggregate(
        hard_facts=KnowledgeHardGateFacts(unauthorized_candidate_exposure=1)
    )

    result = evaluate_knowledge_release(aggregate)

    assert result.status == "blocked"
    assert result.hard_gate_failures == 1
    assert result.quality_evaluated is False
    assert result.performance_evaluated is False
    assert result.quality_gate_failures == 0


@pytest.mark.parametrize(
    ("aggregate", "reason"),
    (
        (_knowledge_aggregate(overall_recall_50=0.949), "overall Recall@50"),
        (
            _knowledge_aggregate(conditional_complete_top_10=0.899),
            "conditional_guidance complete-evidence Top-10",
        ),
        (_knowledge_aggregate(retrieval_p95_seconds=5.001), "retrieval P95"),
    ),
)
def test_knowledge_quality_and_performance_thresholds_are_independent(
    aggregate: KnowledgeAcceptanceAggregate,
    reason: str,
) -> None:
    result = evaluate_knowledge_release(aggregate)

    assert result.status == "blocked"
    assert result.hard_gate_failures == 0
    assert any(reason in item for item in result.blocking_reasons)


def test_knowledge_release_passes_only_after_all_gate_stages_pass() -> None:
    result = evaluate_knowledge_release(_knowledge_aggregate())

    assert result.status == "passed"
    assert result.hard_gate_failures == 0
    assert result.quality_gate_failures == 0
    assert result.performance_gate_failures == 0
    assert result.quality_evaluated is True
    assert result.performance_evaluated is True


@pytest.mark.parametrize(
    ("metrics_update", "reason"),
    (
        ({"unauthorized_candidate_exposure": 1}, "unauthorized_candidate_exposure"),
        ({"citation_resolvability_rate": 0.99}, "unresolvable_formal_citation"),
    ),
)
def test_knowledge_hard_gate_derives_nonzero_facts_from_retrieval_report(
    metrics_update: dict[str, float | int],
    reason: str,
) -> None:
    aggregate = _knowledge_aggregate()
    report = aggregate.report.model_copy(
        update={"overall": aggregate.report.overall.model_copy(update=metrics_update)}
    )

    result = evaluate_knowledge_release(aggregate.model_copy(update={"report": report}))

    assert result.status == "blocked"
    assert result.quality_evaluated is False
    assert any(reason in item for item in result.blocking_reasons)
