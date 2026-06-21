from pathlib import Path

import pytest

from proof_agent.contracts import ReceiptOutcome
from proof_agent.evaluation.suites import EvaluationInputError, load_evaluation_suite


def test_suite_loader_reads_expected_cases(tmp_path: Path) -> None:
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text(
        """
suite_id: insurance_qa_smoke
version: "2026-06-07"
name: Insurance QA Smoke
purpose: smoke
gate_profile_id: core_analyzer_gates.v1
cases:
  - case_id: supported_travel_meal
    question: What is the reimbursement rule for travel meals?
    intent_type: service_process_guidance
    expected_resolution: answer_with_citations
    risk_class: low_business_fact
    capability_path: retrieval_only
    expected:
      outcome: ANSWERED_WITH_CITATIONS
      required_citation_refs:
        - customer-support-policy
""".lstrip(),
        encoding="utf-8",
    )

    suite = load_evaluation_suite(suite_path)

    assert suite.suite_id == "insurance_qa_smoke"
    assert suite.gate_profile_id == "core_analyzer_gates.v1"
    assert suite.cases[0].case_id == "supported_travel_meal"
    assert suite.cases[0].expected.outcome == ReceiptOutcome.ANSWERED_WITH_CITATIONS


def test_suite_loader_supports_builtin_smoke_suite() -> None:
    suite = load_evaluation_suite("smoke")
    path_suite = load_evaluation_suite(Path("smoke"))

    assert suite.suite_id == "insurance_qa_smoke"
    assert suite.gate_profile_id == "core_analyzer_gates.v1"
    assert suite.cases
    assert path_suite.suite_id == suite.suite_id


def test_suite_loader_supports_builtin_v3_intent_execution_suite() -> None:
    suite = load_evaluation_suite("v3_intent_execution")

    assert suite.suite_id == "v3_intent_execution"
    assert suite.gate_profile_id == "core_analyzer_gates.v1"
    assert len(suite.cases) >= 4
    by_id = {case.case_id: case for case in suite.cases}
    assert by_id[
        "v3_bfsp_policy_answer"
    ].expected.expected_business_flow_skill_pack_recommendation_type == "single_pack"
    assert by_id[
        "v3_bfsp_policy_answer"
    ].expected.expected_business_flow_skill_pack_decision == "admitted"
    assert by_id[
        "v3_bfsp_policy_answer"
    ].expected.max_action_constraint_rewrites == 0
    assert by_id["v3_bfsp_low_confidence_no_pack"].expected.forbid_clarification is True
    assert by_id[
        "v3_bfsp_composite_task_split"
    ].expected.expected_business_flow_skill_pack_decision == "needs_clarification"


def test_suite_loader_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text(
        """
suite_id: insurance_qa_smoke
version: "2026-06-07"
name: Insurance QA Smoke
cases:
  - case_id: duplicate
    question: Q1
    intent_type: guidance
    expected_resolution: answer_with_citations
    risk_class: low
    capability_path: retrieval_only
    expected:
      outcome: ANSWERED_WITH_CITATIONS
  - case_id: duplicate
    question: Q2
    intent_type: guidance
    expected_resolution: refuse_no_evidence
    risk_class: low
    capability_path: retrieval_only
    expected:
      outcome: REFUSED_NO_EVIDENCE
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(EvaluationInputError, match="duplicate case_id"):
        load_evaluation_suite(suite_path)


def test_suite_loader_rejects_duplicate_scenario_step_ids(tmp_path: Path) -> None:
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text(
        """
suite_id: insurance_qa_smoke
version: "2026-06-07"
name: Insurance QA Smoke
cases:
  - case_id: supported
    question: Q1
    intent_type: guidance
    expected_resolution: answer_with_citations
    risk_class: low
    capability_path: retrieval_only
    expected:
      outcome: ANSWERED_WITH_CITATIONS
scenarios:
  - scenario_id: duplicate_steps
    steps:
      - step_id: same
        case_id: supported
      - step_id: same
        case_id: supported
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(EvaluationInputError, match="duplicate scenario step_id"):
        load_evaluation_suite(suite_path)
