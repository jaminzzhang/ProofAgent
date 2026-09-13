"""Quoted answer boundary cases with synthetic evidence and scripted review."""

import pytest

from proof_agent.contracts import EvidenceChunk, EvidenceStatus, ReceiptOutcome
from proof_agent.contracts.workflow_policy import AssurancePolicy
from proof_agent.control.knowledge.answer_requirements import answer_requirements
from proof_agent.control.validators.quoted_answer import render_quoted_answer
from proof_agent.control.workflow.assurance import evaluate_assurance
from tests.test_quoted_answer_workflow import (
    CITATION, EVIDENCE, REVIEW_OK, ScriptedProvider, answer, run_case,
)


def test_event_time_age_misreading_requires_review_repair():
    question = "甲产品身故保障按什么年龄计算？30岁投保能永久按160%赔付吗？"
    source = "被保险人身故当时到达年龄为30岁及以下时，身故保险金为基本保险金额的160%；31岁及以上按其他档计算。"
    evidence = (EvidenceChunk(source="knowledge://age-rule", citation=CITATION,
                              content=source, status=EvidenceStatus.ACCEPTED),)
    wrong = {"message": "30岁投保可永久按160%赔付。", "citations": [CITATION],
             "quotes": [{"claim": "30岁投保可永久按160%赔付", "text": source, "citation": CITATION}],
             "coverage": [{"requirement_id": row.requirement_id, "status": "answered"}
                          for row in answer_requirements(question)]}
    right = {"message": "按身故当时到达年龄计算；30岁投保不能据此推定永久按160%赔付。",
             "citations": [CITATION],
             "quotes": [{"claim": "按身故当时到达年龄计算", "text": source, "citation": CITATION}],
             "coverage": wrong["coverage"]}
    review_no = {**REVIEW_OK, "conditions_preserved": False}
    result, provider, _ = run_case([wrong, review_no, right, REVIEW_OK],
                                   question=question, evidence=evidence)
    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert len(provider.requests) == 4
    assert "30岁投保可永久按160%赔付" not in result.message
    assert [r.function_schema.name for r in provider.requests][1::2] == [
        "review_grounded_answer", "review_grounded_answer"]


def test_render_quotes_with_markdown_html_and_backticks_stays_literal():
    text = "| 年龄 | 比例 |\n| 30 | 160% |\n```html\n<script>alert(1)</script>\n```\n````"
    output = {"message": "表格需按年龄条件理解。", "quotes": [
        {"claim": "年龄条件", "text": text, "citation": CITATION}]}
    rendered = render_quoted_answer(output)
    assert "引用原文" in rendered and "原文 1" in rendered
    assert text in rendered
    assert rendered.count("`````") == 2
    assert rendered.index("`````text") < rendered.index(text) < rendered.rindex("`````")


def test_assurance_rejects_changed_evidence_with_same_answer():
    result, _, _ = run_case([answer(), REVIEW_OK])
    changed = (EVIDENCE[0].model_copy(update={"content": EVIDENCE[0].content + " 新版本"}),)
    assessment = evaluate_assurance(AssurancePolicy(), evidence=changed,
                                    message=result.message, fact_validation=result.fact_validation)
    assert "answer_grounding_binding_invalid" in assessment.violations


@pytest.mark.parametrize("failure", [RuntimeError("review unavailable"), ValueError("context length exceeded")])
def test_review_failure_cannot_become_answer_or_blind_pass(failure):
    class ReviewFails(ScriptedProvider):
        def generate(self, request):
            if request.function_schema.name == "review_grounded_answer":
                self.requests.append(request)
                raise failure
            return super().generate(request)

    provider = ReviewFails([answer()])
    with pytest.raises(type(failure)):
        run_case([], provider=provider)
    assert [request.function_schema.name for request in provider.requests] == [
        "submit_final_answer", "review_grounded_answer"]
