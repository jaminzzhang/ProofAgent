import json

import pytest

from proof_agent.capabilities.models.normalization import ModelOutputNormalizationError
from proof_agent.capabilities.react import (
    DeterministicReActPlanner,
    LLMReActPlanner,
    resolve_react_planner,
)
from proof_agent.contracts import (
    ModelRequest,
    ModelResponse,
    ReActActionType,
    ReActPlannerConfig,
)
from proof_agent.contracts.manifest import ModelConfig
from proof_agent.errors import ProofAgentError


class FakePlannerProvider:
    provider_name = "openai_compatible"
    model_name = "planner-test"

    def __init__(self, content: str) -> None:
        self.content = content
        self.requests: list[ModelRequest] = []

    @classmethod
    def from_config(cls, model_config: ModelConfig) -> "FakePlannerProvider":
        _ = model_config
        return cls(VALID_PLANNER_OUTPUT)

    def estimate_tokens(self, request: ModelRequest) -> int:
        _ = request
        return 42

    def generate(self, request: ModelRequest) -> ModelResponse:
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


def _planner_output(
    *,
    action_type: str,
    candidate_actions: list[str] | None = None,
    selected_action: str | None = None,
    parameters: dict[str, object] | None = None,
    target_tool_name: object | None = None,
) -> str:
    return json.dumps(
        {
            "action_id": "act_llm_1",
            "action_type": action_type,
            "reasoning_summary": {
                "goal": "Find the next governed action.",
                "observations": ["The request needs governed planning."],
                "candidate_actions": candidate_actions or [action_type],
                "selected_action": selected_action or action_type,
                "rationale_summary": "The selected action is the next governed step.",
                "risk_flags": [],
                "required_evidence": [],
            },
            "parameters": parameters or {},
            "target_tool_name": target_tool_name,
            "risk_level": "low",
        }
    )


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


def test_llm_react_planner_advertises_only_routeable_initial_actions() -> None:
    provider = FakePlannerProvider(VALID_PLANNER_OUTPUT)
    planner = LLMReActPlanner(
        config=ReActPlannerConfig(provider="openai_compatible", name="planner-test"),
        model_provider=provider,
    )

    planner.plan(
        question="What is the reimbursement rule for travel meals?",
        system_prompt="Use governed ReAct planning.",
        context_summary="No prior context.",
    )

    user_payload = json.loads(provider.requests[0].messages[1].content)
    assert user_payload["allowed_actions"] == [
        "ask_clarification",
        "plan_retrieval",
        "propose_tool_call",
    ]


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


@pytest.mark.parametrize("action_type", ["stop", "generate_final_answer"])
def test_llm_react_planner_rejects_unrouteable_initial_actions(
    action_type: str,
) -> None:
    provider = FakePlannerProvider(_planner_output(action_type=action_type))
    planner = LLMReActPlanner(
        config=ReActPlannerConfig(provider="openai_compatible", name="planner-test"),
        model_provider=provider,
    )

    with pytest.raises(ModelOutputNormalizationError) as exc:
        planner.plan(
            question="What is the reimbursement rule for travel meals?",
            system_prompt="Use governed ReAct planning.",
            context_summary="No prior context.",
        )

    assert exc.value.error_code == "model_output_contract_validation_failed"
    assert "unsupported initial planner action" in str(exc.value)


def test_llm_react_planner_rejects_mismatched_selected_action() -> None:
    provider = FakePlannerProvider(
        _planner_output(
            action_type="plan_retrieval",
            selected_action="ask_clarification",
            parameters={"query": "travel meal reimbursement rule"},
        )
    )
    planner = LLMReActPlanner(
        config=ReActPlannerConfig(provider="openai_compatible", name="planner-test"),
        model_provider=provider,
    )

    with pytest.raises(ModelOutputNormalizationError) as exc:
        planner.plan(
            question="What is the reimbursement rule for travel meals?",
            system_prompt="Use governed ReAct planning.",
            context_summary="No prior context.",
        )

    assert exc.value.error_code == "model_output_contract_validation_failed"
    assert "selected_action must match action_type" in str(exc.value)


def test_llm_react_planner_rejects_retrieval_action_without_query() -> None:
    provider = FakePlannerProvider(_planner_output(action_type="plan_retrieval"))
    planner = LLMReActPlanner(
        config=ReActPlannerConfig(provider="openai_compatible", name="planner-test"),
        model_provider=provider,
    )

    with pytest.raises(ModelOutputNormalizationError) as exc:
        planner.plan(
            question="What is the reimbursement rule for travel meals?",
            system_prompt="Use governed ReAct planning.",
            context_summary="No prior context.",
        )

    assert exc.value.error_code == "model_output_contract_validation_failed"
    assert "plan_retrieval requires parameters.query" in str(exc.value)


@pytest.mark.parametrize(
    "query",
    [
        "   ",
        ["travel"],
        {"query": "travel meal reimbursement rule"},
    ],
)
def test_llm_react_planner_rejects_malformed_retrieval_query(
    query: object,
) -> None:
    content = _planner_output(
        action_type="plan_retrieval",
        parameters={"query": query},
    )
    provider = FakePlannerProvider(content)
    planner = LLMReActPlanner(
        config=ReActPlannerConfig(provider="openai_compatible", name="planner-test"),
        model_provider=provider,
    )

    with pytest.raises(ModelOutputNormalizationError) as exc:
        planner.plan(
            question="What is the reimbursement rule for travel meals?",
            system_prompt="Use governed ReAct planning.",
            context_summary="No prior context.",
        )

    assert exc.value.error_code == "model_output_contract_validation_failed"
    assert exc.value.raw_content_length == len(content)
    assert "plan_retrieval requires parameters.query" in str(exc.value)


@pytest.mark.parametrize("target_tool_name", ["   ", 123])
def test_llm_react_planner_rejects_malformed_tool_name(
    target_tool_name: object,
) -> None:
    content = _planner_output(
        action_type="propose_tool_call",
        target_tool_name=target_tool_name,
    )
    provider = FakePlannerProvider(content)
    planner = LLMReActPlanner(
        config=ReActPlannerConfig(provider="openai_compatible", name="planner-test"),
        model_provider=provider,
    )

    with pytest.raises(ModelOutputNormalizationError) as exc:
        planner.plan(
            question="Please look up customer policy status.",
            system_prompt="Use governed ReAct planning.",
            context_summary="No prior context.",
        )

    assert exc.value.error_code == "model_output_contract_validation_failed"
    assert exc.value.raw_content_length == len(content)


@pytest.mark.parametrize(
    "missing_fields",
    [
        "customer_id",
        {"field": "customer_id"},
        ["customer_id", ""],
        ["customer_id", 123],
    ],
)
def test_llm_react_planner_rejects_malformed_clarification_missing_fields(
    missing_fields: object,
) -> None:
    provider = FakePlannerProvider(
        _planner_output(
            action_type="ask_clarification",
            parameters={"missing_fields": missing_fields},
        )
    )
    planner = LLMReActPlanner(
        config=ReActPlannerConfig(provider="openai_compatible", name="planner-test"),
        model_provider=provider,
    )

    with pytest.raises(ModelOutputNormalizationError) as exc:
        planner.plan(
            question="Can this customer claim it?",
            system_prompt="Use governed ReAct planning.",
            context_summary="No prior context.",
        )

    assert exc.value.error_code == "model_output_contract_validation_failed"
    assert "ask_clarification requires parameters.missing_fields" in str(exc.value)
