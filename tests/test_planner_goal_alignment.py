"""The planner request must respect Control Plane retrieval priorities."""

import json
from types import SimpleNamespace

from proof_agent.capabilities.react.planner import LLMReActPlanner
from proof_agent.contracts import ControlledReActRunState, ModelRequest, ModelResponse, ReActActionType, ReActPlannerConfig
from proof_agent.control.workflow.controlled_react.composition import _InvocationPlannerAdapter
from proof_agent.control.workflow.controlled_react.orchestrator import ControlledReActOrchestrator


class CapturingProvider:
    provider_name = "openai_compatible"
    model_name = "planner-test"

    def __init__(self, *, force_query: str | None = None) -> None:
        self.request: ModelRequest | None = None
        self.force_query = force_query

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.request = request
        payload = json.loads(request.messages[1].content)
        query = self.force_query or payload["required_query_pending"][0]
        return ModelResponse(
            content=json.dumps({"action_type": "plan_retrieval", "parameters": {"query": query}}),
            provider_name=self.provider_name,
            model_name=self.model_name,
            finish_reason="stop",
        )


def _case(provider: CapturingProvider):
    planner = LLMReActPlanner(
        config=ReActPlannerConfig(provider="openai_compatible", name="planner-test"),
        model_provider=provider,
    )
    pending = "2025 年净息差的原始报告期及单位"
    state = ControlledReActRunState(
        run_id="run-goal-alignment", template_name="react_enterprise_qa_v3",
        template_descriptor_version="v3", question="请分析 2025 年经营表现。",
        intent_resolution={"retrieval_query_set": [{"query": pending, "required": True}]},
        effective_react_action_set=(ReActActionType.PLAN_RETRIEVAL, ReActActionType.REFUSE),
    )
    invocation = SimpleNamespace(
        react_planner=planner, cancellation_check=lambda: None,
        manifest=SimpleNamespace(response=None, interaction=None),
    )
    return state, _InvocationPlannerAdapter(invocation), pending


def test_adapter_sends_frozen_pending_query_to_llm_planner() -> None:
    provider = CapturingProvider()
    state, adapter, pending = _case(provider)
    proposal = adapter.plan(state)

    assert proposal.action_type is ReActActionType.PLAN_RETRIEVAL
    assert proposal.parameters["query"] == pending
    assert provider.request is not None
    request = provider.request
    user_payload = json.loads(request.messages[1].content)
    assert user_payload["required_query_pending"] == [pending]
    control_prompt = request.messages[0].content
    assert "required_query_pending" in control_prompt
    assert "If no pending required query is supplied" in control_prompt


def test_control_plane_rewrites_model_query_to_frozen_requirement() -> None:
    provider = CapturingProvider(force_query="请分析 2025 年经营表现。")
    state, adapter, pending = _case(provider)
    proposed = adapter.plan(state)
    assert proposed.parameters["query"] != pending

    orchestrator = object.__new__(ControlledReActOrchestrator)
    actual = orchestrator._constrain_next_action(state, proposed, max_plan_rounds=4)
    assert actual.action_type is ReActActionType.PLAN_RETRIEVAL
    assert actual.parameters["query"] == pending
