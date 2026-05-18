import pytest

from proof_agent.capabilities.react import (
    DeterministicReActPlanner,
    LLMReActPlanner,
    resolve_react_planner,
)
from proof_agent.contracts import ModelResponse, ReActActionType, ReActPlannerConfig
from proof_agent.errors import ProofAgentError


class FakePlannerProvider:
    provider_name = "openai_compatible"
    model_name = "planner-test"

    def __init__(self, content: str) -> None:
        self.content = content
        self.requests = []

    def estimate_tokens(self, request):
        return 42

    def generate(self, request):
        self.requests.append(request)
        return ModelResponse(
            content=self.content,
            provider_name=self.provider_name,
            model_name=self.model_name,
            finish_reason="stop",
        )


VALID_PLANNER_OUTPUT = """
{
  "action_id": "act_llm_1",
  "action_type": "plan_retrieval",
  "reasoning_summary": {
    "goal": "Find policy evidence before answering.",
    "observations": ["The request needs enterprise policy evidence."],
    "candidate_actions": ["plan_retrieval"],
    "selected_action": "plan_retrieval",
    "rationale_summary": "Retrieval is required before final answer generation.",
    "risk_flags": [],
    "required_evidence": ["policy evidence"]
  },
  "parameters": {"query": "travel meal reimbursement rule"},
  "target_tool_name": null,
  "risk_level": "low"
}
"""


def test_deterministic_planner_plans_retrieval_for_travel_meals() -> None:
    planner = DeterministicReActPlanner()

    proposal = planner.plan(
        question="What is the reimbursement rule for travel meals?",
        system_prompt="Use governed ReAct planning.",
        context_summary="No prior context.",
    )

    assert proposal.action_type == ReActActionType.PLAN_RETRIEVAL
    assert proposal.parameters["query"] == "travel meals reimbursement rule"
    assert proposal.reasoning_summary.selected_action == ReActActionType.PLAN_RETRIEVAL


def test_deterministic_planner_asks_clarification_for_underspecified_claim() -> None:
    planner = DeterministicReActPlanner()

    proposal = planner.plan(
        question="Can this customer claim it?",
        system_prompt="Use governed ReAct planning.",
        context_summary="No prior context.",
    )

    assert proposal.action_type == ReActActionType.ASK_CLARIFICATION
    assert "missing_fields" in proposal.parameters


def test_deterministic_planner_proposes_governed_customer_policy_tool_call() -> None:
    planner = DeterministicReActPlanner()

    proposal = planner.plan(
        question="Please look up customer policy status.",
        system_prompt="Use governed ReAct planning.",
        context_summary="No prior context.",
    )

    assert proposal.action_type == ReActActionType.PROPOSE_TOOL_CALL
    assert proposal.target_tool_name == "customer_lookup"
    assert proposal.risk_level == "medium"
    assert proposal.parameters["customer_id"] == "CUST-001"
    assert proposal.parameters["policy_id"] == "POL-001"


def test_unsupported_react_planner_provider_raises_actionable_error() -> None:
    config = ReActPlannerConfig(provider="unsupported", name="planner")

    with pytest.raises(ProofAgentError) as exc:
        resolve_react_planner(config)

    assert exc.value.code == "PA_MODEL_001"
    assert "unsupported model provider" in str(exc.value)


def test_llm_react_planner_uses_model_provider_and_json_contract() -> None:
    provider = FakePlannerProvider(VALID_PLANNER_OUTPUT)
    planner = LLMReActPlanner(
        config=ReActPlannerConfig(
            provider="openai_compatible",
            name="planner-test",
            params={"temperature": 0},
        ),
        model_provider=provider,
    )

    proposal = planner.plan(
        question="What is the reimbursement rule for travel meals?",
        system_prompt="Use governed ReAct planning.",
        context_summary="No prior context.",
    )

    assert proposal.action_type == ReActActionType.PLAN_RETRIEVAL
    assert proposal.parameters["query"] == "travel meal reimbursement rule"
    assert provider.requests[0].response_format == "json"
    assert provider.requests[0].stream is False


def test_resolve_react_planner_uses_llm_adapter_for_registered_model_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakePlannerProvider(VALID_PLANNER_OUTPUT)
    monkeypatch.setattr(
        "proof_agent.capabilities.react.planner.resolve_provider",
        lambda config: provider,
    )

    planner = resolve_react_planner(
        ReActPlannerConfig(provider="openai_compatible", name="planner-test")
    )

    assert isinstance(planner, LLMReActPlanner)


def test_llm_react_planner_rejects_invalid_model_output() -> None:
    provider = FakePlannerProvider("I will retrieve first.")
    planner = LLMReActPlanner(
        config=ReActPlannerConfig(provider="openai_compatible", name="planner-test"),
        model_provider=provider,
    )

    with pytest.raises(Exception) as exc:
        planner.plan(
            question="What is the reimbursement rule for travel meals?",
            system_prompt="Use governed ReAct planning.",
            context_summary="No prior context.",
        )

    assert "Model output did not contain a valid JSON object" in str(exc.value)
