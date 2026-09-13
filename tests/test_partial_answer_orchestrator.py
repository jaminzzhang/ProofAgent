"""Synthetic end-to-end orchestration for a partial answer and deferred question."""

from proof_agent.contracts import (
    ContextAdmission, IntentResolutionResult, ReActActionProposal, ReActActionType,
    ReasoningSummary, ReceiptOutcome,
)
from proof_agent.contracts.workflow_policy import InteractionPolicy
from proof_agent.control.workflow.clarification import apply_clarification_policy
from proof_agent.control.workflow.controlled_react import (
    AnswerSynthesisResult, ControlledReActOrchestrator, ControlledReActPorts,
    ControlledReActStartRequest,
)
from tests.test_partial_answer_clarification import resolution
from tests.test_retrieval_task_completion import _harness, _Knowledge, QUERY_A, FACT_A
from tests.test_workflow_goal_execution import task


QUESTION = "甲产品的报销上限是多少？适合我的预算吗？"


class DeferredIntent:
    def resolve(self, state):
        raw = resolution("answer_context").model_copy(update={
            "user_goal": state.question,
            "retrieval_query_set": resolution("answer_context").retrieval_query_set[:1],
        })
        query = raw.retrieval_query_set[0].model_copy(update={"query": QUERY_A})
        raw = raw.model_copy(update={"retrieval_query_set": (query,)})
        return IntentResolutionResult(intent_resolution=apply_clarification_policy(
            raw, response=None, question=state.question,
            interaction=InteractionPolicy(mode="autonomous")))


class PartialAnswer:
    def __init__(self):
        self.contexts = []

    def synthesize(self, state, action, answer_context):
        self.contexts.append(answer_context)
        message = FACT_A + " 请提供预算，才能判断是否适合你。"
        return AnswerSynthesisResult(outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
                                     message=message, final_output=message)


def test_autonomous_orchestrator_retrieves_answers_then_asks_without_completing_task(tmp_path):
    answer = PartialAnswer()
    workflow, knowledge, _, trace, planner = _harness(
        intent_resolution=DeferredIntent(), answer_synthesis=answer,
        interaction_policy=InteractionPolicy(mode="autonomous"))
    snapshot = task(tmp_path)
    snapshot = snapshot.model_copy(update={"goal": snapshot.goal.model_copy(update={
        "objective": QUESTION, "required_context": (),
    })})
    result = workflow.start(ControlledReActStartRequest(
        run_id="partial-answer-autonomous", template_name="react_enterprise_qa_v3",
        template_descriptor_version="react_enterprise_qa.v3", question=QUESTION,
        conversation_context=ContextAdmission(admitted=True, workflow_task=snapshot)))
    assert knowledge.queries == [QUERY_A]
    assert len(answer.contexts) == 1
    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert FACT_A in result.message and "请提供预算" in result.message
    assert result.workflow_task_update.phase == "waiting_for_input"
    assert result.workflow_task_update.question.fields[0].label == "预算"
    assert result.workflow_task_update.phase != "complete"


def test_hard_required_context_still_blocks_before_retrieval(tmp_path):
    workflow, knowledge, answer, _, planner = _harness(
        intent_resolution=DeferredIntent(), interaction_policy=InteractionPolicy(mode="autonomous"))
    snapshot = task(tmp_path, required_context=("product_id",))
    result = workflow.start(ControlledReActStartRequest(
        run_id="hard-context-autonomous", template_name="react_enterprise_qa_v3",
        template_descriptor_version="react_enterprise_qa.v3", question=QUESTION,
        conversation_context=ContextAdmission(admitted=True, workflow_task=snapshot)))
    assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE
    assert result.workflow_task_update.phase == "paused"
    assert knowledge.queries == [] and not planner.states


def test_planner_cannot_repromote_deferred_budget_to_pre_answer_clarification(tmp_path):
    class ReaskingPlanner:
        def __init__(self):
            self.calls = 0

        def plan(self, state):
            self.calls += 1
            kind = ReActActionType.ASK_CLARIFICATION
            return ReActActionProposal(action_id=f"reask-{self.calls}", action_type=kind,
                parameters={"missing_fields": ["预算"], "interaction_stage": "plan"}, risk_level="low",
                reasoning_summary=ReasoningSummary(goal=state.question, observations=(),
                    candidate_actions=(kind,), selected_action=kind,
                    rationale_summary="Ask for budget.", risk_flags=(), required_evidence=()))

    knowledge, answer, planner = _Knowledge(), PartialAnswer(), ReaskingPlanner()
    workflow = ControlledReActOrchestrator(ports=ControlledReActPorts(
        planner=planner, knowledge_observation=knowledge, answer_synthesis=answer,
        intent_resolution=DeferredIntent(), interaction_policy=InteractionPolicy(mode="autonomous")))
    snapshot = task(tmp_path)
    snapshot = snapshot.model_copy(update={"goal": snapshot.goal.model_copy(update={"objective": QUESTION})})
    result = workflow.start(ControlledReActStartRequest(
        run_id="deferred-planner-reask", template_name="react_enterprise_qa_v3",
        template_descriptor_version="react_enterprise_qa.v3", question=QUESTION,
        conversation_context=ContextAdmission(admitted=True, workflow_task=snapshot)))
    assert knowledge.queries == [QUERY_A]
    assert planner.calls >= 1 and len(answer.contexts) == 1
    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert result.workflow_task_update.phase == "waiting_for_input"
    assert result.workflow_task_update.question.stage == "answer"
