"""Purchase advice can retrieve public terms before optional policy history."""

import pytest

from proof_agent.contracts import (
    ContextAdmission, IntentResolutionResult, ReActActionProposal, ReActActionType,
    ReasoningSummary, ReceiptOutcome,
)
from proof_agent.contracts.workflow_policy import InteractionPolicy
from proof_agent.control.workflow.clarification import apply_clarification_policy
from proof_agent.control.workflow.controlled_react import (
    ControlledReActOrchestrator, ControlledReActPorts, ControlledReActStartRequest,
)
from tests.test_partial_answer_clarification import resolution
from tests.test_partial_answer_orchestrator import PartialAnswer
from tests.test_retrieval_task_completion import _Knowledge, QUERY_A
from tests.test_workflow_goal_execution import task


QUESTION = "平安御享一生终身寿险保障怎么样？我现在30岁，是否适合买？"
POLICY_FIELD = "用户是否已投保该产品及具体保单信息（如有追问需要）"


def _resolve(question, field, *, kind="required_context", action=None, required_query=True):
    raw = resolution(kind or "required_context").model_copy(update={"missing_fields": (field,)})
    if kind is None:
        raw = raw.model_copy(update={"clarification_assessments": ()})
    else:
        raw = raw.model_copy(update={"clarification_assessments": (
            raw.clarification_assessments[0].model_copy(update={"field": field}),
        )})
    if action is not None:
        raw = raw.model_copy(update={"recommended_next_action": action})
    if not required_query:
        raw = raw.model_copy(update={"retrieval_query_set": ()})
    return apply_clarification_policy(raw, response=None, question=question)


@pytest.mark.parametrize("kind", ["required_context", None])
def test_pre_purchase_policy_history_does_not_block_public_retrieval(kind):
    result = _resolve(QUESTION, POLICY_FIELD, kind=kind)
    assert result.recommended_next_action is ReActActionType.PLAN_RETRIEVAL
    assert POLICY_FIELD not in result.missing_fields
    assert POLICY_FIELD not in result.deferred_answer_fields
    assert any(query.required for query in result.retrieval_query_set)


def test_budget_remains_deferred_answer_context():
    result = _resolve(QUESTION, "预算", kind="answer_context")
    assert result.recommended_next_action is ReActActionType.PLAN_RETRIEVAL
    assert result.deferred_answer_fields == ("预算",)


def test_policy_history_removed_while_budget_stays_deferred():
    raw = resolution("answer_context")
    raw = raw.model_copy(update={
        "missing_fields": (POLICY_FIELD, "预算"),
        "clarification_assessments": (
            raw.clarification_assessments[0].model_copy(update={
                "field": POLICY_FIELD, "kind": "required_context",
            }),
            raw.clarification_assessments[0],
        ),
    })
    result = apply_clarification_policy(raw, response=None, question=QUESTION)
    assert result.recommended_next_action is ReActActionType.PLAN_RETRIEVAL
    assert result.missing_fields == ()
    assert result.deferred_answer_fields == ("预算",)


def test_stale_deferred_policy_history_is_cleared_without_missing_fields():
    raw = resolution("answer_context").model_copy(update={
        "missing_fields": (), "clarification_assessments": (),
        "deferred_answer_fields": (POLICY_FIELD,),
    })
    result = apply_clarification_policy(raw, response=None, question=QUESTION)
    assert result.deferred_answer_fields == ()


@pytest.mark.parametrize("question,field", [
    ("我已投保平安御享一生，是否应该退保？", POLICY_FIELD),
    ("平安御享一生已投保，现在申请理赔怎么办？", POLICY_FIELD),
    ("我的两份保单怎么合并办理？", POLICY_FIELD),
    (QUESTION + "另外查我的保单退保现金价值。", POLICY_FIELD),
    (QUESTION, "客户身份和查询保单的授权"),
    (QUESTION, "用户是否已投保该产品及具体保单信息及查询授权"),
    (QUESTION, "退保所需的具体保单号"),
    (QUESTION, "未知的必需上下文"),
])
def test_hard_or_unknown_context_still_blocks(question, field):
    result = _resolve(question, field)
    assert result.recommended_next_action is ReActActionType.ASK_CLARIFICATION
    assert result.missing_fields == (field,)


@pytest.mark.parametrize("action,required_query", [
    (ReActActionType.PROPOSE_TOOL_CALL, True),
    (ReActActionType.REFUSE, True),
    (None, False),
])
def test_purchase_exception_requires_independent_public_retrieval(action, required_query):
    result = _resolve(QUESTION, POLICY_FIELD, action=action, required_query=required_query)
    assert result.recommended_next_action is (action if action is ReActActionType.REFUSE
                                               else ReActActionType.ASK_CLARIFICATION)
    assert result.missing_fields == (POLICY_FIELD,)


def test_misclassified_deferred_policy_history_is_removed():
    raw = resolution("answer_context")
    raw = raw.model_copy(update={
        "missing_fields": (POLICY_FIELD,),
        "clarification_assessments": (
            raw.clarification_assessments[0].model_copy(update={"field": POLICY_FIELD}),
        ),
    })
    result = apply_clarification_policy(raw, response=None, question=QUESTION)
    assert result.recommended_next_action is ReActActionType.PLAN_RETRIEVAL
    assert POLICY_FIELD not in result.missing_fields
    assert POLICY_FIELD not in result.deferred_answer_fields


@pytest.mark.parametrize("stage,interaction", [
    ("plan", InteractionPolicy(mode="autonomous")),
    ("plan", None),
    ("tool_input", InteractionPolicy(mode="autonomous")),
])
def test_planner_reask_respects_purchase_and_tool_input_boundaries(tmp_path, stage, interaction):
    class PurchaseIntent:
        def resolve(self, state):
            raw = resolution("required_context")
            raw = raw.model_copy(update={
                "missing_fields": (POLICY_FIELD,),
                "clarification_assessments": (
                    raw.clarification_assessments[0].model_copy(update={"field": POLICY_FIELD}),
                ),
                "retrieval_query_set": (
                    raw.retrieval_query_set[0].model_copy(update={"query": QUERY_A}),
                ),
            })
            return IntentResolutionResult(intent_resolution=apply_clarification_policy(
                raw, response=None, question=state.question,
                interaction=InteractionPolicy(mode="autonomous")))

    class ReaskingPlanner:
        def __init__(self):
            self.calls = 0

        def plan(self, state):
            self.calls += 1
            kind = ReActActionType.ASK_CLARIFICATION
            return ReActActionProposal(
                action_id=f"reask-policy-{self.calls}", action_type=kind,
                parameters={"missing_fields": [POLICY_FIELD], "interaction_stage": stage},
                risk_level="low", reasoning_summary=ReasoningSummary(
                    goal=state.question, observations=(), candidate_actions=(kind,),
                    selected_action=kind, rationale_summary="Ask for policy history.",
                    risk_flags=(), required_evidence=()))

    knowledge, answer, planner = _Knowledge(), PartialAnswer(), ReaskingPlanner()
    workflow = ControlledReActOrchestrator(ports=ControlledReActPorts(
        planner=planner, knowledge_observation=knowledge, answer_synthesis=answer,
        intent_resolution=PurchaseIntent(), interaction_policy=interaction))
    snapshot = task(tmp_path)
    snapshot = snapshot.model_copy(update={"goal": snapshot.goal.model_copy(update={
        "objective": QUESTION, "required_context": (),
    })})
    result = workflow.start(ControlledReActStartRequest(
        run_id="purchase-policy-reask", template_name="react_enterprise_qa_v3",
        template_descriptor_version="react_enterprise_qa.v3", question=QUESTION,
        conversation_context=ContextAdmission(admitted=True, workflow_task=snapshot)))
    assert planner.calls >= 1
    if stage == "plan":
        assert knowledge.queries == [QUERY_A]
        assert len(answer.contexts) == 1
        assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    else:
        assert knowledge.queries == []
        assert answer.contexts == []
        assert result.workflow_task_update.phase == "paused"


@pytest.mark.parametrize("required_field", ["product_id", POLICY_FIELD])
def test_frozen_task_required_context_still_pauses_before_purchase_retrieval(tmp_path, required_field):
    class PurchaseIntent:
        def resolve(self, state):
            return IntentResolutionResult(intent_resolution=_resolve(QUESTION, POLICY_FIELD))

    knowledge, answer = _Knowledge(), PartialAnswer()
    workflow = ControlledReActOrchestrator(ports=ControlledReActPorts(
        planner=None, knowledge_observation=knowledge, answer_synthesis=answer,
        intent_resolution=PurchaseIntent(), interaction_policy=InteractionPolicy(mode="autonomous")))
    snapshot = task(tmp_path)
    # Model copy represents a pre-existing frozen task value at the runtime gate;
    # GoalContract creation normally rejects non-identifier Chinese field labels.
    snapshot = snapshot.model_copy(update={"goal": snapshot.goal.model_copy(update={
        "required_context": (required_field,),
    })})
    result = workflow.start(ControlledReActStartRequest(
        run_id="purchase-frozen-context", template_name="react_enterprise_qa_v3",
        template_descriptor_version="react_enterprise_qa.v3", question=QUESTION,
        conversation_context=ContextAdmission(admitted=True, workflow_task=snapshot)))
    assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE
    assert result.workflow_task_update.phase == "paused"
    assert knowledge.queries == []
