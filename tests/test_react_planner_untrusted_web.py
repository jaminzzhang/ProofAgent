from proof_agent.capabilities.react import LLMReActPlanner
from proof_agent.contracts import ModelRequest, ModelResponse, ReActActionType, ReActPlannerConfig


class FakePlannerProvider:
    provider_name = "openai_compatible"
    model_name = "planner-test"

    def __init__(self, content: str) -> None:
        self.content = content

    def estimate_tokens(self, request: ModelRequest) -> int:
        _ = request
        return 42

    def generate(self, request: ModelRequest) -> ModelResponse:
        _ = request
        return ModelResponse(
            content=self.content,
            provider_name=self.provider_name,
            model_name=self.model_name,
            finish_reason="stop",
        )


def test_llm_react_planner_accepts_untrusted_web_search_tool_proposal() -> None:
    planner = LLMReActPlanner(
        config=ReActPlannerConfig(provider="openai_compatible", name="planner-test"),
        model_provider=FakePlannerProvider(
            '{"action_type":"propose_tool_call",'
            '"target_tool_name":"untrusted_web_search",'
            '"parameters":{"query":"latest public reimbursement guidance","max_results":"3"}}'
        ),
    )

    proposal = planner.plan(
        question="What changed today?",
        system_prompt="Use governed ReAct planning.",
        context_summary="",
    )

    assert proposal.action_type == ReActActionType.PROPOSE_TOOL_CALL
    assert proposal.target_tool_name == "untrusted_web_search"
    assert proposal.parameters == {
        "max_results": "3",
        "query": "latest public reimbursement guidance",
    }
