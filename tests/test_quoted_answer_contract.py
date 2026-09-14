"""Source quotes bind a synthesized answer without claiming semantic proof."""

from copy import deepcopy

import pytest

from proof_agent.contracts import EvidenceChunk, EvidenceStatus, ValidationStatus
from proof_agent.control.knowledge.answer_requirements import answer_requirements
from proof_agent.control.validators.quoted_answer import (
    render_quoted_answer,
    validate_quoted_answer,
)


QUESTION = "请总结保障亮点，并说明等待期；若要判断我能否申请理赔还缺什么信息？"
SOURCE = (
    "甲产品保障说明\n"
    "仅在保单生效后适用。\n"
    "| 保障项目 | 给付上限 |\n"
    "| --- | --- |\n"
    "| 住院医疗 | 100 万元 |\n"
    "若在等待期内就诊，该项保障不承担给付责任。"
)
CITATION = "knowledge://policy#bound"


def _evidence(status=EvidenceStatus.ACCEPTED, citation=CITATION):
    return EvidenceChunk(
        source="knowledge://policy", citation=citation, content=SOURCE,
        status=status, admission_score=1.0,
    )


def _output():
    requirements = answer_requirements(QUESTION)
    return {
        "message": (
            "住院医疗给付上限为 100 万元，保障适用仍受保单生效与等待期条件限制。"
            "能否申请理赔还需要确认就诊日期及保单生效日期。"
        ),
        "citations": [CITATION],
        "quotes": [
            {
                "claim": "住院医疗给付上限为 100 万元",
                "text": "| 保障项目 | 给付上限 |\n| --- | --- |\n| 住院医疗 | 100 万元 |",
                "citation": CITATION,
            },
            {
                "claim": "保障适用仍受保单生效与等待期条件限制",
                "text": "仅在保单生效后适用。\n| 保障项目 | 给付上限 |\n| --- | --- |\n| 住院医疗 | 100 万元 |\n若在等待期内就诊，该项保障不承担给付责任。",
                "citation": CITATION,
            },
        ],
        "coverage": [
            {"requirement_id": requirements[0].requirement_id, "status": "answered"},
            {"requirement_id": requirements[1].requirement_id, "status": "answered"},
            {"requirement_id": requirements[2].requirement_id, "status": "needs_user_input"},
        ],
    }


def _check(output, evidence=None):
    return validate_quoted_answer(
        output, evidence=(_evidence(),) if evidence is None else evidence,
        question=QUESTION,
    )


def test_synthesis_accepts_bound_table_and_parent_conditions_without_verbatim_body():
    output = _output()
    result = _check(output)
    assert result.status is ValidationStatus.PASSED
    assert "quote_binding_only" in str(result.metadata)
    assert "住院医疗给付上限为 100 万元" in output["message"]
    assert output["message"] not in SOURCE


@pytest.mark.parametrize("mutation", [
    lambda out: out["quotes"][0].update(text="| 住院医疗 | 500 万元 |"),
    lambda out: out["quotes"][0].update(citation="knowledge://other#bound"),
])
def test_forged_quote_or_wrong_citation_fails(mutation):
    output = _output()
    mutation(output)
    assert _check(output).status is ValidationStatus.FAILED


def test_unaccepted_source_cannot_authorize_a_quote():
    assert _check(_output(), evidence=(_evidence(EvidenceStatus.CANDIDATE),)).status is ValidationStatus.FAILED


def test_coverage_requires_each_user_clause_once_and_known_id():
    for change in ("missing", "duplicate", "unknown"):
        output = _output()
        if change == "missing":
            output["coverage"].pop()
        elif change == "duplicate":
            output["coverage"].append(deepcopy(output["coverage"][0]))
        else:
            output["coverage"][0]["requirement_id"] = "ar_unknown"
        assert _check(output).status is ValidationStatus.FAILED


def test_quote_count_is_bounded():
    empty = _output()
    empty["quotes"] = []
    assert _check(empty).status is ValidationStatus.FAILED
    excessive = _output()
    excessive["quotes"] = excessive["quotes"] * 9
    assert _check(excessive).status is ValidationStatus.FAILED


def test_render_shows_original_table_and_parent_condition_without_internal_uri():
    rendered = render_quoted_answer(_output())
    assert "住院医疗给付上限为 100 万元" in rendered
    assert "| 住院医疗 | 100 万元 |" in rendered
    assert "仅在保单生效后适用。" in rendered
    assert "若在等待期内就诊，该项保障不承担给付责任。" in rendered
    assert "knowledge://" not in rendered
    assert "1" in rendered and "2" in rendered


def test_legacy_shape_cannot_bypass_quote_review_with_unbound_analysis():
    import json

    from proof_agent.contracts import ModelResponse, ReceiptOutcome
    from proof_agent.control.workflow.harness_helpers import validate_model_output

    evidence = EvidenceChunk(
        source="knowledge://product", citation="knowledge://product#bound",
        content="甲产品支持住院申请。", status=EvidenceStatus.ACCEPTED,
        admission_score=1.0,
    )
    response = ModelResponse(
        content=json.dumps({
            "message": "甲产品保障灵活，适合直接购买。",
            "citations": [evidence.citation],
        }, ensure_ascii=False),
        provider_name="offline", model_name="synthetic", finish_reason="stop",
    )

    checks = validate_model_output(
        response=response, outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        evidence=(evidence,), question="甲产品怎么样？",
    )
    assert any(check.status is ValidationStatus.FAILED for check in checks)
