"""Mixed questions may progress without inventing personal information."""
import pytest
from proof_agent.contracts.react_workflow import IntentResolution, ReActActionType
from proof_agent.contracts.workflow_policy import InteractionPolicy
from proof_agent.control.workflow.clarification import apply_clarification_policy, scope_assumption_context

def resolution(kind):
    return IntentResolution.model_validate(dict(
        resolution_id="mixed", user_goal="产品保障与个人适合性", domain_intent="consultation",
        known_facts=("30岁",), missing_fields=("预算",), ambiguities=(), risk_flags=(),
        confidence=.9, recommended_next_action="ask_clarification",
        clarification_assessments=[dict(field="预算", kind=kind)],
        retrieval_query_set=[dict(query="甲产品保障条款", required=True,
                                  intent_angle="terms", reason="Independent public product facts")],
    ))

def test_partial_answer_preserves_question_without_blocking_retrieval():
    result = apply_clarification_policy(resolution("answer_context"), response=None,
        question="甲产品保障怎么样？适合我吗？", interaction=InteractionPolicy(mode="autonomous"))
    assert result.recommended_next_action is ReActActionType.PLAN_RETRIEVAL
    assert not result.missing_fields
    assert result.deferred_answer_fields == ("预算",)
    context = scope_assumption_context(result.model_dump(mode="json"))
    assert context["structured_control_context"]["deferred_answer_fields"] == ["预算"]

@pytest.mark.parametrize("kind", ["required_context", None])
def test_hard_or_unclassified_context_still_blocks(kind):
    raw = resolution("required_context")
    if kind is None:
        raw = raw.model_copy(update={"clarification_assessments": ()})
    result = apply_clarification_policy(raw, response=None, question="查询客户保单")
    assert result.recommended_next_action is ReActActionType.ASK_CLARIFICATION
    assert result.missing_fields == ("预算",)

def test_no_independent_query_cannot_defer():
    raw = resolution("answer_context").model_copy(update={"retrieval_query_set": ()})
    result = apply_clarification_policy(raw, response=None, question="适合我吗？")
    assert result.recommended_next_action is ReActActionType.ASK_CLARIFICATION
