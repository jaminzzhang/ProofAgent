"""The answer retry paths retain the task the user actually authorized."""

import json
from types import SimpleNamespace

from proof_agent.contracts import (
    AnswerEvidenceContext, ContextAdmission, ControlledReActRunState, EvidenceChunk,
    EvidenceStatus, ModelResponse, ReActActionProposal, ReActActionType, ReasoningSummary,
    ReceiptOutcome,
)
from proof_agent.control.policy.engine import PolicyEngine
from proof_agent.control.context_budget import InMemoryContextBudgetCalibrationStore
from proof_agent.control.workflow.controlled_react.answer_source_selection import selection_request
from proof_agent.control.workflow.controlled_react.final_answer_attempt import (
    FinalAnswerAttemptRunner,
    FinalAnswerAttemptStatus,
    GeneratedFinalAnswerAttempt,
    NormalizedFinalAnswerAttempt,
    PreparedFinalAnswerAttempt,
    _final_answer_repair_request,
)
from proof_agent.control.workflow.harness_helpers import build_model_request
from tests.test_workflow_goal_execution import task
from tests.test_performance_answer_contract import QUESTION as PERFORMANCE_QUESTION, TEXT, TABLE


QUESTION = "解释等待期，并说明免赔额。"
STAGE = {"business_context_addendum": {"text": "只讨论已发布的产品条款。"},
         "structured_control_context": {"include_citation_requirements": "逐项说明依据"}}


def _case(tmp_path):
    context = ContextAdmission(
        admitted=True,
        summary="用户限定为 2025 年合同。",
        workflow_task=task(tmp_path, constraints=("仅讨论甲产品",)),
    )
    state = SimpleNamespace(question=QUESTION, conversation_context=context,
                            memory_recall_payloads=(), intent_resolution={})
    request = build_model_request(question=QUESTION, evidence=(), provider="offline",
                                  model="synthetic", conversation_context=context,
                                  workflow_stage_context=STAGE)
    prepared = PreparedFinalAnswerAttempt(request=request, estimated_tokens=100, evidence=())
    return state, prepared


def test_context_overflow_retry_preserves_task_and_stage_scope(tmp_path):
    state, prepared = _case(tmp_path)
    runner = object.__new__(FinalAnswerAttemptRunner)
    runner._invocation = SimpleNamespace(model_provider=SimpleNamespace(estimate_tokens=lambda request: 50))
    runner._workflow_stage_context = STAGE

    retry = runner._prepare_context_overflow_retry(state, prepared).request
    prompt = retry.messages[-1].content
    assert "仅讨论甲产品" in prompt
    assert "用户限定为 2025 年合同" in prompt
    assert "只讨论已发布的产品条款" in prompt
    assert "逐项说明依据" in prompt
    assert retry.metadata["context_overflow_recovery"] is True


def test_repair_preserves_stage_scope_and_clause_requirements(tmp_path):
    state, prepared = _case(tmp_path)
    normalized = NormalizedFinalAnswerAttempt(
        generated=GeneratedFinalAnswerAttempt(
            prepared=prepared,
            response=ModelResponse(content='{"message":"","citations":[]}',
                                   provider_name="offline", model_name="synthetic"),
            interaction=None,
        ),
        validation_results=(),
        status=FinalAnswerAttemptStatus.SCHEMA_FAILED,
    )

    payload = json.loads(_final_answer_repair_request(
        state, normalized, workflow_stage_context=STAGE,
    ).messages[-1].content)
    assert payload["workflow_stage_context"]["business_context_addendum"]["text"] == "只讨论已发布的产品条款。"
    assert payload["workflow_stage_context"]["structured_control_context"]["include_citation_requirements"] == "逐项说明依据"
    assert [row["source_text"] for row in payload["answer_requirements"]] == ["解释等待期", "并说明免赔额"]
    assert "仅讨论甲产品" in payload["task_context"]["constraints"]


def test_run_recovers_context_overflow_with_task_and_stage_scope(tmp_path):
    state = ControlledReActRunState(
        run_id="answer-context-retry", template_name="react_enterprise_qa_v3",
        template_descriptor_version="react_enterprise_qa.v3",
        question="What is the reimbursement limit?",
        conversation_context=ContextAdmission(
            admitted=True, summary="Use the 2025 policy edition.",
            workflow_task=task(tmp_path, constraints=("Only product A",)),
        ),
    )
    action_type = ReActActionType.GENERATE_FINAL_ANSWER
    action = ReActActionProposal(
        action_id="answer", action_type=action_type, parameters={}, risk_level="low",
        reasoning_summary=ReasoningSummary(
            goal=state.question, observations=(), candidate_actions=(action_type,),
            selected_action=action_type, rationale_summary="Use evidence.",
            risk_flags=(), required_evidence=(),
        ),
    )
    evidence = EvidenceChunk(
        source="knowledge://policy", citation="knowledge://policy#fact",
        content="The reimbursement limit is 100 yuan.",
        status=EvidenceStatus.ACCEPTED, admission_score=1.0,
    )

    class OverflowThenAnswer:
        provider_name = "offline"
        model_name = "synthetic"

        def __init__(self):
            self.requests = []

        def estimate_tokens(self, request):
            return 100

        def generate(self, request):
            self.requests.append(request)
            if len(self.requests) == 1:
                raise ValueError("context length exceeded")
            return ModelResponse(
                content=json.dumps({"message": evidence.content, "citations": [evidence.citation]}),
                provider_name=self.provider_name, model_name=self.model_name,
                finish_reason="stop",
            )

    provider = OverflowThenAnswer()
    events = []
    trace = SimpleNamespace(emit=lambda *args, **kwargs: events.append((args, kwargs)))
    invocation = SimpleNamespace(
        model_provider=provider, policy=PolicyEngine(()),
        manifest=SimpleNamespace(context=None),
        context_budget_calibration_store=InMemoryContextBudgetCalibrationStore(),
    )
    result = FinalAnswerAttemptRunner(
        invocation, trace=trace, workflow_stage_context=STAGE,
    ).run(state, action, AnswerEvidenceContext(run_id=state.run_id), evidence=(evidence,))

    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert len(provider.requests) == 2
    retry = provider.requests[1]
    assert retry.metadata["context_overflow_recovery"] is True
    assert retry.metadata["context_compression"] == "optional_memory_recall_omitted"
    assert "Only product A" in retry.messages[-1].content
    assert "Use the 2025 policy edition" in retry.messages[-1].content
    assert STAGE["business_context_addendum"]["text"] in retry.messages[-1].content
    assert "逐项说明依据" in retry.messages[-1].content


def test_performance_selection_keeps_stage_scope_in_initial_and_repair(tmp_path):
    from proof_agent.control.workflow.harness_helpers import build_model_request
    from tests.test_performance_answer_contract import chunk

    context = ContextAdmission(
        admitted=True, summary="用户追问的是甲公司 2026 年第一季度。",
        workflow_task=task(tmp_path, constraints=("只分析甲公司",)),
    )
    evidence = (chunk(TEXT + "\n" + TABLE),)
    request = build_model_request(
        question=PERFORMANCE_QUESTION, evidence=evidence,
        provider="offline", model="synthetic", conversation_context=context,
        workflow_stage_context=STAGE,
    )
    initial = selection_request(
        request, evidence, question=PERFORMANCE_QUESTION, workflow_stage_context=STAGE,
    )
    first = json.loads(initial.messages[-1].content)
    assert first["workflow_stage_context"] == STAGE

    repair_payload = {
        "question": PERFORMANCE_QUESTION, "validation_error": {"error_code": "answer_facts_failed"},
        "task_context": {"constraints": ["只分析甲公司"]}, "workflow_stage_context": STAGE,
    }
    repair = request.model_copy(update={"messages": (
        request.messages[0], request.messages[1].model_copy(update={"content": json.dumps(repair_payload)}),
    )})
    second = json.loads(selection_request(repair, evidence).messages[-1].content)
    assert second["workflow_stage_context"] == STAGE
    assert second["task_context"]["constraints"] == ["只分析甲公司"]


def test_performance_runner_sends_task_and_stage_scope_on_both_attempts(tmp_path):
    from tests.test_performance_answer_contract import chunk
    from tests.test_task_answer_workflow import GroundedProvider

    context = ContextAdmission(
        admitted=True, summary="用户追问的是甲公司 2026 年第一季度。",
        workflow_task=task(tmp_path, constraints=("只分析甲公司",)),
    )
    state = ControlledReActRunState(
        run_id="performance-context", template_name="react_enterprise_qa_v3",
        template_descriptor_version="react_enterprise_qa.v3",
        question=PERFORMANCE_QUESTION, conversation_context=context,
    )
    action_type = ReActActionType.GENERATE_FINAL_ANSWER
    action = ReActActionProposal(
        action_id="answer", action_type=action_type, parameters={}, risk_level="low",
        reasoning_summary=ReasoningSummary(
            goal=state.question, observations=(), candidate_actions=(action_type,),
            selected_action=action_type, rationale_summary="Use evidence.",
            risk_flags=(), required_evidence=(),
        ),
    )
    provider = GroundedProvider(invalid_first=True)
    trace = SimpleNamespace(emit=lambda *args, **kwargs: None)
    runner = FinalAnswerAttemptRunner(
        SimpleNamespace(model_provider=provider, policy=PolicyEngine(())),
        trace=trace, workflow_stage_context=STAGE,
    )

    result = runner.run(
        state, action, AnswerEvidenceContext(run_id=state.run_id),
        evidence=(chunk(TEXT + "\n" + TABLE),),
    )
    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    answer_requests = [r for r in provider.requests if r.function_schema.name == "submit_final_answer"]
    assert len(answer_requests) == 2
    assert len(provider.requests) == 3  # bounded repair plus independent grounding review
    first_text = answer_requests[0].messages[-1].content
    assert "只分析甲公司" in first_text
    assert "用户追问的是甲公司 2026 年第一季度。" in first_text
    assert STAGE["business_context_addendum"]["text"] in first_text
    repair_payload = json.loads(answer_requests[1].messages[-1].content)
    assert repair_payload["workflow_stage_context"] == STAGE
    assert repair_payload["task_context"]["constraints"] == ["只分析甲公司"]
    assert repair_payload["conversation_context"] == {
        "summary": "用户追问的是甲公司 2026 年第一季度。",
        "usage": "follow_up_resolution_only_not_evidence",
    }
    assert len(repair_payload["answer_requirements"]) == 3
