"""Synthetic regressions for the analysis/selection mismatch in run_1fbcbc32."""

import json
import re
from types import SimpleNamespace

import pytest

from proof_agent.contracts import (
    AnswerEvidenceContext,
    ControlledReActRunState,
    EvidenceChunk,
    EvidenceStatus,
    IntentResolution,
    ModelResponse,
    ReActActionProposal,
    ReActActionType,
    ReasoningSummary,
    ReceiptOutcome,
    RetrievalQueryItem,
    ValidationStatus,
)
from proof_agent.control.policy.engine import PolicyEngine
from proof_agent.control.knowledge.answer_requirements import answer_requirements
from proof_agent.control.validators.answer_facts import answer_fact_repair_options
from proof_agent.control.workflow.clarification import apply_clarification_policy
from proof_agent.control.workflow.controlled_react.final_answer_attempt import (
    FinalAnswerAttemptRunner,
)
from proof_agent.control.workflow.harness_helpers import validate_model_output


QUESTION = "甲公司业绩有哪些亮点，哪些业务比较好，哪些业务比较差？"
TEXT = "2026 年第一季度，甲公司寿险业务营运利润 100.00 亿元，同比增长 6.4%。"
TABLE = """### 寿险及健康险业务关键指标

截至 3 月 31 日止三个月期间

| （人民币百万元） | 2026 年 | 2025 年 | 变动（%） |
| --- | --- | --- | --- |
| 新业务价值 | 120 | 100 | 20.0 |
| 新业务价值率（按首年保费，%） | 23.5 | 28.3 | 下降 4.8 个百分点 |
"""


def chunk(content, source="knowledge://performance"):
    return EvidenceChunk(
        source=source,
        citation=source + "#bound",
        content=content,
        status=EvidenceStatus.ACCEPTED,
        admission_score=1.0,
    )


def checks(message, evidence, question=QUESTION):
    return validate_model_output(
        response=ModelResponse(
            content=json.dumps(
                {"message": message, "citations": list(dict.fromkeys(e.citation for e in evidence))}
            ),
            provider_name="offline",
            model_name="test",
            finish_reason="stop",
        ),
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        evidence=evidence,
        question=question,
    )


def test_cjk_presentation_spaces_do_not_change_numeric_facts():
    result = checks(TEXT.replace(" ", ""), (chunk(TEXT),), question="营运利润是多少？")
    assert all(r.status is ValidationStatus.PASSED for r in result)


@pytest.mark.parametrize("replacement", ["-100.00", "100.01", "100 万", "1 00.00"])
def test_numeric_sign_unit_and_digit_boundaries_remain_protected(replacement):
    result = checks(TEXT.replace("100.00", replacement), (chunk(TEXT),))
    assert (
        next(r for r in result if r.validator_name == "answer_facts").status
        is ValidationStatus.FAILED
    )


def test_table_selection_retains_entity_period_units_and_negative_comparison():
    evidence = (chunk(TEXT + "\n" + TABLE),)
    options = answer_fact_repair_options(evidence)
    row = next(o for o in options if "23.5" in o["statement"])
    assert all(
        s in row["statement"] for s in ("寿险", "2026", "2025", "28.3", "4.8", "个百分点", "%")
    )
    assert row["citation"] == evidence[0].citation
    from proof_agent.control.knowledge.business_assessment import render_business_answer
    ids = tuple(f"s{i}" for i, o in enumerate(options) if o["statement"] in (TEXT, row["statement"]))
    result = checks(render_business_answer(evidence, ids), evidence)
    assert all(r.status is ValidationStatus.PASSED for r in result)
    result = checks(TEXT + "\n" + row["statement"].replace("23.5", "35.2"), evidence)
    assert (
        next(r for r in result if r.validator_name == "answer_facts").status
        is ValidationStatus.FAILED
    )


def test_strengths_only_do_not_satisfy_a_two_sided_question():
    result = checks(TEXT, (chunk(TEXT + "\n" + TABLE),))
    adequacy = next(r for r in result if r.validator_name == "final_answer_adequacy")
    assert adequacy.status is ValidationStatus.FAILED
    assert "missing_analysis_pressures" in adequacy.metadata["violation_codes"]


def test_unrequested_year_is_removed_before_queries_are_frozen():
    intent = IntentResolution(
        resolution_id="i",
        user_goal=QUESTION,
        domain_intent="knowledge",
        known_facts=(),
        missing_fields=(),
        ambiguities=(),
        risk_flags=(),
        confidence=0.8,
        recommended_next_action=ReActActionType.PLAN_RETRIEVAL,
        scope_assumptions=("按用户提问年份默认2025年最新披露期。",),
        retrieval_query_set=(
            RetrievalQueryItem(
                query="甲公司 2025 年报 业绩亮点",
                required=True,
                intent_angle="period",
                reason="default",
            ),
        ),
    )
    result = apply_clarification_policy(intent, response=None, question=QUESTION)
    assert "2025" not in str(result.scope_assumptions)
    assert "2025" not in result.retrieval_query_set[0].query
    explicit = apply_clarification_policy(
        intent, response=None, question="甲公司2025年业绩怎么样？"
    )
    assert "2025" in explicit.retrieval_query_set[0].query


class SelectingProvider:
    provider_name = "offline"
    model_name = "synthetic"

    def __init__(self, *, omit_weakness=False, review_pass=True):
        self.requests = []
        self.omit_weakness = omit_weakness
        self.review_pass = review_pass

    def estimate_tokens(self, request):
        return sum(len(m.content) for m in request.messages) // 4

    def generate(self, request):
        self.requests.append(request)
        if request.metadata.get("answer_grounding_review"):
            obj = {"claims_supported": True, "conditions_preserved": True,
                   "requirements_addressed": self.review_pass}
        else:
            match = re.search(r'"citation":\s*"([^"]+)"', request.messages[-1].content)
            citation = match.group(1) if match else "knowledge://performance#bound"
            message = "2026 年第一季度，甲公司寿险业务营运利润同比增长 6.4%，构成亮点。"
            quotes = [{"claim": "营运利润同比增长 6.4%",
                       "text": "营运利润 100.00 亿元，同比增长 6.4%",
                       "citation": citation}]
            if not self.omit_weakness:
                message += "新业务价值率同比下降 4.8 个百分点，形成压力。"
                quotes.append({"claim": "新业务价值率同比下降 4.8 个百分点",
                               "text": "| 新业务价值率（按首年保费，%） | 23.5 | 28.3 | 下降 4.8 个百分点 |",
                               "citation": citation})
            obj = {"message": message, "citations": [citation],
                   "quotes": quotes,
                   "coverage": [{"requirement_id": r.requirement_id,
                                 "status": "answered" if not self.omit_weakness or r.kind != "pressures" else "needs_evidence"}
                                for r in answer_requirements(QUESTION)]}
        return ModelResponse(
            content=json.dumps(obj),
            provider_name=self.provider_name,
            model_name=self.model_name,
            finish_reason="stop",
        )


def run_analysis(provider, *, second_metadata=None):
    state = ControlledReActRunState(
        run_id="analysis",
        template_name="react_enterprise_qa_v3",
        template_descriptor_version="react_enterprise_qa.v3",
        question=QUESTION,
    )
    action = ReActActionProposal(
        action_id="answer",
        action_type=ReActActionType.GENERATE_FINAL_ANSWER,
        parameters={},
        risk_level="low",
        reasoning_summary=ReasoningSummary(
            goal=QUESTION,
            observations=(),
            candidate_actions=(ReActActionType.GENERATE_FINAL_ANSWER,),
            selected_action=ReActActionType.GENERATE_FINAL_ANSWER,
            rationale_summary="Use evidence.",
            risk_flags=(),
            required_evidence=(),
        ),
    )
    trace = SimpleNamespace(emit=lambda *args, **kwargs: None)
    runner = FinalAnswerAttemptRunner(
        SimpleNamespace(model_provider=provider, policy=PolicyEngine(())), trace=trace
    )
    e = chunk(TEXT + "\n" + TABLE)
    second = e if second_metadata is None else e.model_copy(update={"metadata": second_metadata})
    return runner.run(state, action, AnswerEvidenceContext(run_id=state.run_id), evidence=(e, second))


def test_analysis_selects_first_and_answers_both_sides_without_duplicate_context():
    provider = SelectingProvider()
    result = run_analysis(provider)
    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert [r.function_schema.name for r in provider.requests] == ["submit_final_answer", "review_grounded_answer"]
    assert len(result.evidence) == 1
    assert "23.5" in result.message and "100.00" in result.message
    assert "引用原文" in result.message


def test_partial_answer_exposes_missing_side_for_orchestrator_retrieval():
    provider = SelectingProvider(omit_weakness=True)
    result = run_analysis(provider)
    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert len(result.recovery_requirement_ids) == 1
    assert any(row["disposition"] == "needs_evidence" for row in result.answer_requirement_report)
    assert all(row["status"] == "unassessed" for row in result.answer_requirement_report)
    assert len(provider.requests) == 2
    assert [r.function_schema.name for r in provider.requests] == [
        "submit_final_answer", "review_grounded_answer"]


@pytest.mark.parametrize(
    "old,new",
    [
        ("2026 年", "2027 年"),
        ("下降 4.8", "上升 4.8"),
        ("寿险及健康险", "银行"),
        ("个百分点", "基点"),
        ("28.3", "23.5"),
    ],
)
def test_table_bindings_protect_period_entity_direction_unit_and_comparator(old, new):
    evidence = (chunk(TABLE),)
    row = next(
        o["statement"] for o in answer_fact_repair_options(evidence) if "23.5" in o["statement"]
    )
    result = checks(row.replace(old, new), evidence, question="价值率是多少？")
    assert (
        next(r for r in result if r.validator_name == "answer_facts").status
        is ValidationStatus.FAILED
    )


def test_table_footnotes_are_required_and_preserved():
    table = TABLE.replace("按首年保费，%", "按标准保费 <sup>(1)</sup>，%")
    assert not any("23.5" in o["statement"] for o in answer_fact_repair_options((chunk(table),)))
    table += "\n注：(1) 标准保费为期交保费 100%及趸交保费 10%之和。"
    row = next(
        o["statement"]
        for o in answer_fact_repair_options((chunk(table),))
        if "23.5" in o["statement"]
    )
    assert "趸交保费 10%" in row
    result = checks(row, (chunk(table),), question="价值率是多少？")
    assert all(r.status is ValidationStatus.PASSED for r in result)


def test_disclosure_is_exact_and_cannot_hide_an_assertion():
    from proof_agent.control.knowledge.performance_analysis import SCOPE_DISCLOSURE

    for message in (
        SCOPE_DISCLOSURE + "净利润为999亿元。",
        SCOPE_DISCLOSURE.replace("未确认", "已确认"),
    ):
        result = checks(message, (chunk(TEXT),), question="利润是多少？")
        assert (
            next(r for r in result if r.validator_name == "answer_facts").status
            is ValidationStatus.FAILED
        )


def test_lower_cost_is_not_a_business_pressure():
    evidence = (
        chunk(
            "2026 年第一季度，甲公司营业收入 100 亿元，同比增长 6%。\n综合成本率 95%，同比下降 1 个百分点。"
        ),
    )
    result = checks(evidence[0].content, evidence)
    adequacy = next(r for r in result if r.validator_name == "final_answer_adequacy")
    assert "missing_analysis_pressures" in adequacy.metadata["violation_codes"]


def test_both_failed_attempts_remain_visible_in_diagnostics():
    result = run_analysis(SelectingProvider(omit_weakness=True, review_pass=False))
    assert result.outcome is ReceiptOutcome.FAILED_WITH_TRACE
    assert len(result.stage_failure_diagnostics) == 2
    assert all("grounding_requirements_addressed_failed" in d.violation_codes
               for d in result.stage_failure_diagnostics)


def test_duplicate_content_does_not_hide_distinct_applicability_metadata():
    result = run_analysis(SelectingProvider(), second_metadata={"applicability": "unknown"})
    assert len(result.evidence) == 2
    from proof_agent.control.workflow.assurance import evaluate_assurance
    from proof_agent.contracts.workflow_policy import AssurancePolicy
    assert not evaluate_assurance(AssurancePolicy(), evidence=result.evidence, message=result.message).passed


def test_over_limit_quotes_fail_without_rendering_or_truncation():
    class OverLimit(SelectingProvider):
        def generate(self, request):
            self.requests.append(request)
            obj = {"message": "甲公司营运利润增长。", "citations": ["knowledge://performance#bound"],
                   "quotes": [{"claim": "甲公司营运利润增长", "text": TEXT,
                               "citation": "knowledge://performance#bound"} for _ in range(30)],
                   "coverage": [{"requirement_id": r.requirement_id, "status": "answered"}
                                for r in answer_requirements(QUESTION)]}
            return ModelResponse(content=json.dumps(obj),
                provider_name="offline", model_name="test", finish_reason="stop")

    provider = OverLimit()
    result = run_analysis(provider)
    assert result.outcome is ReceiptOutcome.FAILED_WITH_TRACE
    assert len(provider.requests) == 2
    assert any("invalid_quote_count" in d.violation_codes for d in result.stage_failure_diagnostics)
    assert "100.00" not in result.message
    assert len(result.stage_failure_diagnostics) == 2


def test_table_only_growth_and_pressure_can_satisfy_comparison():
    table = TABLE.replace("新业务价值 |", "营运利润 |").replace("### 寿险", "### 甲公司寿险")
    evidence = (chunk(table),)
    rows = [
        o["statement"]
        for o in answer_fact_repair_options(evidence)
        if "2026 年：" in o["statement"]
    ]
    from proof_agent.control.knowledge.business_assessment import render_business_answer
    options = answer_fact_repair_options(evidence)
    result = checks(render_business_answer(evidence, tuple(f"s{i}" for i, o in enumerate(options) if o["statement"] in rows)), evidence)
    assert all(r.status is ValidationStatus.PASSED for r in result)


@pytest.mark.parametrize("prefix", ["预计", "假设", "目标是", "不代表"])
def test_forecasts_and_negated_growth_are_not_actual_performance_coverage(prefix):
    text = TEXT.replace("甲公司", prefix + "甲公司")
    result = checks(text, (chunk(text + "\n" + TABLE),))
    adequacy = next(r for r in result if r.validator_name == "final_answer_adequacy")
    assert "missing_analysis_strengths" in adequacy.metadata["violation_codes"]


def test_table_projection_does_not_drop_external_applicability_condition():
    table = TABLE.replace("截至", "仅限续期业务，其他业务不适用。\n\n截至", 1)
    assert not any("23.5" in o["statement"] for o in answer_fact_repair_options((chunk(table),)))


def test_conflicting_footnote_definitions_are_not_arbitrarily_selected():
    table = TABLE.replace("按首年保费，%", "按标准保费 <sup>(1)</sup>，%")
    table += "\n注：(1) 标准保费取趸交保费 10%。\n注：(1) 标准保费取趸交保费 20%。"
    assert not any("23.5" in o["statement"] for o in answer_fact_repair_options((chunk(table),)))


@pytest.mark.parametrize("request_gap", [False, True])
def test_composed_agentset_workflow_answers_both_sides_and_counts_unique_progress(request_gap):
    from dataclasses import replace
    from pathlib import Path
    from proof_agent.bootstrap import compose_harness_invocation
    from proof_agent.control.workflow.controlled_react import ControlledReActStartRequest
    from proof_agent.control.workflow.controlled_react.composition import build_controlled_react_orchestrator_for_invocation
    from tests.test_agentset_knowledge import Http, runtime
    from tests.test_retrieval_task_completion import _Intent, _Trace

    http = Http({"success": True, "data": [{"id": "performance#row", "score": 0.9, "text": TEXT + "\n" + TABLE}]})
    class GapOnce(SelectingProvider):
        def generate(self, request):
            if request_gap and not self.requests:
                self.omit_weakness = True
                response = super().generate(request)
                self.omit_weakness = False
                return response
            return super().generate(request)
    provider, trace = GapOnce(), _Trace()
    invocation = compose_harness_invocation(Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"))
    resolver = SimpleNamespace(resolve=lambda **kwargs: _Intent().resolve(SimpleNamespace(question=kwargs["question"])))
    invocation = replace(invocation, external_knowledge=runtime(http), model_provider=provider, intent_resolver=resolver)
    workflow = build_controlled_react_orchestrator_for_invocation(invocation, trace=trace)
    result = workflow.start(ControlledReActStartRequest(run_id="composed_performance",
        template_name="react_enterprise_qa_v3", template_descriptor_version="react_enterprise_qa.v3",
        question=QUESTION, max_plan_rounds=4))
    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS, result.stage_failure_diagnostics
    assert "23.5" in result.final_output and "100.00" in result.final_output
    assert len(http.requests) == 2 + int(request_gap)
    assert len(provider.requests) == 2 + 2 * int(request_gap)
    retrievals = [stage.summary for stage in result.stage_results if stage.stage_id == "retrieval"]
    assert [stage["new_evidence_count"] for stage in retrievals] == [1, 0] + ([0] if request_gap else [])
    assert "source_statement_options" not in str(trace.events)
