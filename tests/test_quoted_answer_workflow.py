"""Synthetic quoted-answer regressions through the real answer attempt runner."""

import json
from types import SimpleNamespace

import pytest

from proof_agent.contracts import (
    AnswerEvidenceContext, ControlledReActRunState, EnforcementPoint, EvidenceChunk, EvidenceStatus,
    ModelResponse, ReActActionProposal, ReActActionType, ReasoningSummary,
    ReceiptOutcome, PolicyDecision, PolicyDecisionType,
)
from proof_agent.contracts.workflow_policy import AssurancePolicy, WorkflowBudget
from proof_agent.control.knowledge.answer_requirements import answer_requirements
from proof_agent.control.policy.engine import PolicyEngine
from proof_agent.control.workflow.assurance import evaluate_assurance
from proof_agent.control.workflow.controlled_react.final_answer_attempt import FinalAnswerAttemptRunner
from proof_agent.control.workflow.execution_budget import BudgetedModelProvider, BudgetExceeded, WorkflowBudgetLedger


QUESTION = "甲产品等待期和身故免责条件是什么？"
SOURCE = "甲产品等待期为30天。因下列情形之一导致被保险人身故的，我们不承担给付身故保险金的责任：故意伤害。"
CITATION = "knowledge://synthetic-policy#L1"
EVIDENCE = (EvidenceChunk(source="knowledge://synthetic-policy", citation=CITATION,
                          content=SOURCE, status=EvidenceStatus.ACCEPTED),)
REVIEW_OK = {"claims_supported": True, "conditions_preserved": True, "requirements_addressed": True}


def answer(*, quote_text=None, quotes=True):
    rows = [
        {"claim": "等待期为30天", "text": "甲产品等待期为30天", "citation": CITATION},
        {"claim": "故意伤害导致身故属于免责条件", "text": quote_text or
         "因下列情形之一导致被保险人身故的，我们不承担给付身故保险金的责任：故意伤害", "citation": CITATION},
    ]
    value = {"message": "甲产品等待期为30天；故意伤害导致身故属于免责条件。",
             "citations": [CITATION],
             "coverage": [{"requirement_id": r.requirement_id, "status": "answered"}
                          for r in answer_requirements(QUESTION)]}
    if quotes:
        value["quotes"] = rows
    return value


class ScriptedProvider:
    provider_name = "offline"
    model_name = "synthetic"

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def estimate_tokens(self, request):
        return 40

    def generate(self, request):
        self.requests.append(request)
        content = self.responses.pop(0)
        return ModelResponse(content=content if isinstance(content, str) else json.dumps(content),
                             provider_name="offline", model_name="synthetic")


def run_case(responses, *, provider=None, policy=None, question=QUESTION, evidence=EVIDENCE):
    provider = provider or ScriptedProvider(responses)
    events = []
    state = ControlledReActRunState(run_id="quoted-synthetic", template_name="react_enterprise_qa_v3",
                                  template_descriptor_version="react_enterprise_qa.v3", question=question)
    kind = ReActActionType.GENERATE_FINAL_ANSWER
    action = ReActActionProposal(action_id="answer", action_type=kind, parameters={}, risk_level="low",
        reasoning_summary=ReasoningSummary(goal=question, observations=(), candidate_actions=(kind,),
            selected_action=kind, rationale_summary="Use admitted evidence.", risk_flags=(), required_evidence=()))
    invocation = SimpleNamespace(model_provider=provider, policy=policy or PolicyEngine(()),
                                 manifest=SimpleNamespace(context=None))
    result = FinalAnswerAttemptRunner(invocation,
        trace=SimpleNamespace(emit=lambda *a, **kw: events.append((a, kw)))).run(
            state, action, AnswerEvidenceContext(run_id=state.run_id), evidence=evidence)
    return result, provider, events


def test_summary_quotes_and_independent_review_reach_answered():
    result, provider, events = run_case([answer(), REVIEW_OK])
    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert "等待期为30天" in result.message and "引用原文" in result.message
    assert "因下列情形之一导致被保险人身故" in result.message
    assert [r.function_schema.name for r in provider.requests] == ["submit_final_answer", "review_grounded_answer"]
    assert any(i.role == "harness_review" for i in result.stage_llm_interactions)
    assert any("harness_review" in str(kw.get("payload", {})) for _, kw in events)


def test_failed_review_repairs_normal_json_and_reviews_again():
    no = {**REVIEW_OK, "conditions_preserved": False}
    result, provider, _ = run_case([answer(), no, answer(), REVIEW_OK])
    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert [r.function_schema.name for r in provider.requests] == [
        "submit_final_answer", "review_grounded_answer", "submit_final_answer", "review_grounded_answer"]
    assert all(r.function_schema.name != "select_answer_statements" for r in provider.requests)


def test_repeated_failed_or_invalid_review_fails_with_trace():
    no = {**REVIEW_OK, "conditions_preserved": False}
    for reviews in ((no, no), ("not json", "not json")):
        result, provider, _ = run_case([answer(), reviews[0], answer(), reviews[1]])
        assert result.outcome is ReceiptOutcome.FAILED_WITH_TRACE
        assert len(provider.requests) == 4
        assert result.stage_failure_diagnostics


def test_missing_or_forged_quote_cannot_be_approved_by_review():
    for invalid in (answer(quotes=False), answer(quote_text="不存在的免责原文")):
        result, provider, _ = run_case([invalid, answer(), REVIEW_OK])
        assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
        assert provider.requests[1].function_schema.name != "review_grounded_answer"


def test_review_uses_shared_model_budget_before_dispatch():
    raw = ScriptedProvider([answer(), REVIEW_OK])
    ledger = WorkflowBudgetLedger(WorkflowBudget(max_model_calls=2, max_total_tokens=10000),
                                  usage={"model_calls": 1, "tokens": 100})
    provider = BudgetedModelProvider(raw, ledger)
    with pytest.raises(BudgetExceeded, match="model_calls_exhausted"):
        run_case([], provider=provider)
    assert len(raw.requests) == 1
    assert ledger.snapshot()["model_calls"] == 2


def test_review_passes_before_model_call_policy_independently():
    class DenyReview:
        def __init__(self):
            self.calls = []

        def evaluate(self, enforcement_point, context, *, trace_event_id):
            self.calls.append((enforcement_point, context))
            return PolicyDecision(decision=PolicyDecisionType.DENY if len(self.calls) == 2 else PolicyDecisionType.ALLOW,
                                  enforcement_point=EnforcementPoint.BEFORE_MODEL_CALL,
                                  reason="Synthetic review denial", policy_rule_id="test.review", trace_event_id=trace_event_id)

    policy = DenyReview()
    result, provider, _ = run_case([answer(), REVIEW_OK], policy=policy)
    assert result.outcome is ReceiptOutcome.POLICY_DENIED
    assert len(policy.calls) == 2
    assert len(provider.requests) == 1


def test_assurance_binds_rendered_answer_and_strict_retains_unassessed():
    result, _, _ = run_case([answer(), REVIEW_OK])
    assert result.fact_validation is not None
    normal = evaluate_assurance(AssurancePolicy(), evidence=EVIDENCE,
                                message=result.message, fact_validation=result.fact_validation)
    assert normal.passed
    tampered = evaluate_assurance(AssurancePolicy(), evidence=EVIDENCE,
                                  message=result.message + " altered", fact_validation=result.fact_validation)
    assert "answer_grounding_binding_invalid" in tampered.violations
    strict = evaluate_assurance(AssurancePolicy(level="strict"), evidence=EVIDENCE,
                                message=result.message, fact_validation=result.fact_validation)
    assert "required_claim_unassessed" in strict.violations
