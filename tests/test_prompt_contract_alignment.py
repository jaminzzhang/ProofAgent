"""Model-facing prompt contracts match the governed output branches."""

import json
from types import SimpleNamespace

from proof_agent.capabilities.react.planner import LLMReActPlanner
from proof_agent.contracts import ControlledReActRunState, ReActActionType, ReActPlannerConfig, ModelResponse
from proof_agent.control.knowledge.answer_requirements import answer_requirements
from proof_agent.control.workflow.controlled_react.answer_source_selection import selection_request
from proof_agent.control.workflow.controlled_react.composition import _InvocationPlannerAdapter
from proof_agent.control.workflow.harness_helpers import build_model_request
from tests.test_performance_answer_contract import (
    QUESTION as PERFORMANCE_QUESTION, TEXT, TABLE, chunk, run_analysis,
)


def test_comparative_selection_contract_offers_exactly_one_output_branch():
    evidence = (chunk(TEXT + "\n" + TABLE),)
    request = build_model_request(
        question=PERFORMANCE_QUESTION, evidence=evidence, provider="offline", model="synthetic",
    )
    selection = selection_request(request, evidence, question=PERFORMANCE_QUESTION)
    contract = json.loads(selection.messages[-1].content)["required_output_contract"]
    branches = selection.function_schema.parameters_schema["oneOf"]
    expected = {"statement_ids", "evidence_gap_requirement_ids"}
    assert {tuple(branch["required"]) for branch in branches} == {(name,) for name in expected}
    assert {tuple(branch["required"]) for branch in contract["oneOf"]} == {(name,) for name in expected}
    system = selection.messages[0].content.lower()
    assert "evidence_gap_requirement_ids" in system
    assert "statement_ids" in system
    assert "exactly one" in system or "either" in system
    assert "not both" in system or "never both" in system or "never return both" in system


def test_noncomparative_selection_exposes_only_statement_ids():
    evidence = (chunk("The limit is 100 yuan."),)
    request = build_model_request(
        question="What is the limit?", evidence=evidence, provider="offline", model="synthetic",
    )
    selection = selection_request(request, evidence, question="What is the limit?")
    contract = json.loads(selection.messages[-1].content)["required_output_contract"]
    assert contract["required_fields"] == ["statement_ids"]
    assert "oneOf" not in selection.function_schema.parameters_schema
    assert "evidence_gap_requirement_ids" not in selection.function_schema.parameters_schema["properties"]


def test_real_runner_returns_typed_gap_without_prose_repair():
    from tests.test_task_answer_workflow import GroundedProvider

    provider = GroundedProvider(pressure_status="needs_evidence")
    result = run_analysis(provider)
    expected = {item.requirement_id for item in answer_requirements(PERFORMANCE_QUESTION)}
    assert len(provider.requests) == 2  # answer and separate grounding review
    assert provider.requests[0].function_schema.name == "submit_final_answer"
    assert provider.requests[1].function_schema.name == "review_grounded_answer"
    assert set(result.recovery_requirement_ids) <= expected
    assert result.recovery_requirement_ids
    assert "业务压力仍需补充证据" in result.message


def test_planner_stage_text_once_and_frozen_query_stays_separate():
    stage_text = "Unique plan-stage scope " + "x" * 1000
    stage = {"business_context_addendum": {"text": stage_text}}
    state = ControlledReActRunState(
        run_id="planner-context", template_name="react_enterprise_qa_v3",
        template_descriptor_version="react_enterprise_qa.v3",
        effective_react_action_set=(ReActActionType.PLAN_RETRIEVAL,),
        observation_records=(), question="Original question?",
        intent_resolution={"retrieval_query_set": ({"query": "frozen exact query", "required": True},)},
    )

    class PlannerProvider:
        provider_name = "offline"
        model_name = "synthetic"

        def __init__(self):
            self.requests = []

        def estimate_tokens(self, request):
            return 1

        def generate(self, request):
            self.requests.append(request)
            return ModelResponse(content=json.dumps({"action_type": "plan_retrieval",
                                                     "parameters": {"query": "frozen exact query"}}),
                                 provider_name=self.provider_name, model_name=self.model_name)

    provider = PlannerProvider()
    planner = LLMReActPlanner(config=ReActPlannerConfig(provider="deterministic", name="synthetic"),
                             model_provider=provider)
    invocation = SimpleNamespace(
        cancellation_check=lambda: None, react_planner=planner,
        manifest=SimpleNamespace(response=None, interaction=None),
    )
    action = _InvocationPlannerAdapter(invocation, stage_contexts={"plan": stage}).plan(state)
    payload = json.loads(provider.requests[0].messages[-1].content)
    assert payload["required_query_pending"] == ["frozen exact query"]
    assert provider.requests[0].messages[-1].content.count(stage_text) == 1
    assert action.parameters["query"] == "frozen exact query"
