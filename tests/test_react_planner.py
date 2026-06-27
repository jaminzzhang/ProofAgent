import json

import pytest

from proof_agent.capabilities.models.normalization import ModelOutputNormalizationError
from proof_agent.capabilities.react import (
    DeterministicReActPlanner,
    LLMReActPlanner,
    resolve_react_planner,
)
from proof_agent.contracts import (
    EffectiveToolProposalScope,
    ModelRequest,
    ModelResponse,
    ReActActionProposal,
    ReActActionType,
    ReActPlannerConfig,
    ToolProposalInterface,
    ToolProposalParameter,
    ToolProposalParameterSource,
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


def _proposal_json(proposal: ReActActionProposal) -> str:
    return json.dumps(
        proposal.model_dump(mode="json", warnings=False, fallback=str),
        sort_keys=True,
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


def test_deterministic_planner_generates_final_answer_after_accepted_evidence() -> None:
    planner = DeterministicReActPlanner()

    proposal = planner.plan(
        question="What is the reimbursement rule for travel meals?",
        system_prompt="Use governed ReAct planning.",
        context_summary=(
            "Intent Resolution: domain_intent=enterprise_policy_question; "
            "recommended_next_action=plan_retrieval.\n"
            "Loop Control: plan_round=1; "
            "eligible_actions=ask_clarification,generate_final_answer,"
            "plan_retrieval,propose_tool_call,refuse; "
            "last_convergence_signal=none; "
            "accepted_evidence_count=1; "
            "evidence_growth_since_last_round=1; "
            "last_action_type=plan_retrieval."
        ),
    )

    assert proposal.action_type == ReActActionType.GENERATE_FINAL_ANSWER
    assert proposal.reasoning_summary.selected_action == ReActActionType.GENERATE_FINAL_ANSWER


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


def test_llm_react_planner_accepts_compact_deepseek_style_parameters() -> None:
    provider = FakePlannerProvider(
        json.dumps(
            {
                "action_type": "plan_retrieval",
                "params": {"query": "reimbursement rule for travel meals"},
            }
        )
    )
    planner = LLMReActPlanner(
        config=ReActPlannerConfig(provider="deepseek", name="deepseek-v4-flash"),
        model_provider=provider,
    )

    proposal = planner.plan(
        question="What is the reimbursement rule for travel meals?",
        system_prompt="Use governed ReAct planning.",
        context_summary="No prior context.",
    )

    assert proposal.action_type == ReActActionType.PLAN_RETRIEVAL
    assert dict(proposal.parameters) == {"query": "reimbursement rule for travel meals"}
    assert proposal.reasoning_summary.selected_action == ReActActionType.PLAN_RETRIEVAL
    assert proposal.risk_level == "low"


def test_llm_react_planner_maps_compact_search_tool_call_to_retrieval() -> None:
    provider = FakePlannerProvider(
        json.dumps(
            {
                "action_type": "propose_tool_call",
                "parameters": {
                    "tool": "search_policy",
                    "query": "travel meals reimbursement",
                },
            }
        )
    )
    planner = LLMReActPlanner(
        config=ReActPlannerConfig(provider="deepseek", name="deepseek-v4-flash"),
        model_provider=provider,
    )

    proposal = planner.plan(
        question="What is the reimbursement rule for travel meals?",
        system_prompt="Use governed ReAct planning.",
        context_summary="No prior context.",
    )

    assert proposal.action_type == ReActActionType.PLAN_RETRIEVAL
    assert dict(proposal.parameters) == {"query": "travel meals reimbursement"}
    assert proposal.target_tool_name is None


def test_llm_react_planner_maps_nested_search_tool_arguments_to_retrieval() -> None:
    provider = FakePlannerProvider(
        json.dumps(
            {
                "action_type": "propose_tool_call",
                "parameters": {
                    "tool": "search_policy_documents",
                    "arguments": {"query": "reimbursement rule for travel meals"},
                },
            }
        )
    )
    planner = LLMReActPlanner(
        config=ReActPlannerConfig(provider="deepseek", name="deepseek-v4-flash"),
        model_provider=provider,
    )

    proposal = planner.plan(
        question="What is the reimbursement rule for travel meals?",
        system_prompt="Use governed ReAct planning.",
        context_summary="No prior context.",
    )

    assert proposal.action_type == ReActActionType.PLAN_RETRIEVAL
    assert dict(proposal.parameters) == {"query": "reimbursement rule for travel meals"}


def test_llm_react_planner_maps_compact_plan_field_to_retrieval_query() -> None:
    provider = FakePlannerProvider(
        json.dumps(
            {
                "action_type": "plan_retrieval",
                "parameters": {
                    "plan": "Retrieve the reimbursement rule for travel meals.",
                },
            }
        )
    )
    planner = LLMReActPlanner(
        config=ReActPlannerConfig(provider="deepseek", name="deepseek-v4-flash"),
        model_provider=provider,
    )

    proposal = planner.plan(
        question="What is the reimbursement rule for travel meals?",
        system_prompt="Use governed ReAct planning.",
        context_summary="No prior context.",
    )

    assert proposal.action_type == ReActActionType.PLAN_RETRIEVAL
    assert dict(proposal.parameters) == {
        "query": "Retrieve the reimbursement rule for travel meals."
    }


def test_llm_react_planner_canonicalizes_retrieval_output_before_returning() -> None:
    sentinel = "RAW_MODEL_OUTPUT_SHOULD_NOT_TRACE"
    provider = FakePlannerProvider(
        json.dumps(
            {
                "action_id": "act_llm_1",
                "action_type": "plan_retrieval",
                "reasoning_summary": {
                    "goal": sentinel,
                    "observations": [sentinel],
                    "candidate_actions": ["ask_clarification", "plan_retrieval"],
                    "selected_action": "plan_retrieval",
                    "rationale_summary": sentinel,
                    "risk_flags": [sentinel],
                    "required_evidence": [sentinel],
                },
                "parameters": {
                    "query": "  travel meal reimbursement rule  ",
                    "raw_output": sentinel,
                },
                "target_tool_name": None,
                "risk_level": "low",
            }
        )
    )
    planner = LLMReActPlanner(
        config=ReActPlannerConfig(provider="openai_compatible", name="planner-test"),
        model_provider=provider,
    )

    proposal = planner.plan(
        question="What is the reimbursement rule for travel meals?",
        system_prompt="Use governed ReAct planning.",
        context_summary="No prior context.",
    )

    assert proposal.action_type == ReActActionType.PLAN_RETRIEVAL
    assert dict(proposal.parameters) == {"query": "travel meal reimbursement rule"}
    assert proposal.reasoning_summary.candidate_actions == (ReActActionType.PLAN_RETRIEVAL,)
    assert proposal.reasoning_summary.selected_action == ReActActionType.PLAN_RETRIEVAL
    assert proposal.risk_level == "low"
    assert sentinel not in _proposal_json(proposal)


def test_llm_react_planner_canonicalizes_clarification_output_before_returning() -> None:
    sentinel = "RAW_MODEL_OUTPUT_SHOULD_NOT_TRACE"
    provider = FakePlannerProvider(
        json.dumps(
            {
                "action_id": "act_llm_1",
                "action_type": "ask_clarification",
                "reasoning_summary": {
                    "goal": sentinel,
                    "observations": [sentinel],
                    "candidate_actions": ["ask_clarification"],
                    "selected_action": "ask_clarification",
                    "rationale_summary": sentinel,
                    "risk_flags": [sentinel],
                    "required_evidence": [sentinel],
                },
                "parameters": {
                    "missing_fields": [" customer_id ", " policy_id "],
                    "notes": sentinel,
                },
                "target_tool_name": None,
                "risk_level": "low",
            }
        )
    )
    planner = LLMReActPlanner(
        config=ReActPlannerConfig(provider="openai_compatible", name="planner-test"),
        model_provider=provider,
    )

    proposal = planner.plan(
        question="Can this customer claim it?",
        system_prompt="Use governed ReAct planning.",
        context_summary="No prior context.",
    )

    assert proposal.action_type == ReActActionType.ASK_CLARIFICATION
    assert dict(proposal.parameters) == {"missing_fields": ("customer_id", "policy_id")}
    assert proposal.reasoning_summary.candidate_actions == (ReActActionType.ASK_CLARIFICATION,)
    assert proposal.reasoning_summary.risk_flags == ()
    assert sentinel not in _proposal_json(proposal)


def test_llm_react_planner_allowlists_tool_parameters_and_strips_tool_name() -> None:
    sentinel = "RAW_MODEL_OUTPUT_SHOULD_NOT_TRACE"
    provider = FakePlannerProvider(
        json.dumps(
            {
                "action_id": "act_llm_1",
                "action_type": "propose_tool_call",
                "reasoning_summary": {
                    "goal": sentinel,
                    "observations": [sentinel],
                    "candidate_actions": ["propose_tool_call"],
                    "selected_action": "propose_tool_call",
                    "rationale_summary": sentinel,
                    "risk_flags": [sentinel],
                    "required_evidence": [sentinel],
                },
                "parameters": {
                    "customer_id": " CUST-001 ",
                    "policy_id": " POL-001 ",
                    "notes": sentinel,
                    "raw_output": {"content": sentinel},
                },
                "target_tool_name": " customer_lookup ",
                "risk_level": "high",
            }
        )
    )
    planner = LLMReActPlanner(
        config=ReActPlannerConfig(provider="openai_compatible", name="planner-test"),
        model_provider=provider,
    )

    proposal = planner.plan(
        question="Please look up customer policy status.",
        system_prompt="Use governed ReAct planning.",
        context_summary="No prior context.",
    )

    assert proposal.action_type == ReActActionType.PROPOSE_TOOL_CALL
    assert proposal.target_tool_name == "customer_lookup"
    assert dict(proposal.parameters) == {
        "customer_id": "CUST-001",
        "policy_id": "POL-001",
    }
    assert proposal.reasoning_summary.risk_flags == ("customer_data_access",)
    assert proposal.risk_level == "medium"
    assert sentinel not in _proposal_json(proposal)


def test_llm_react_planner_advertises_governed_planner_actions() -> None:
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
        "generate_final_answer",
        "plan_retrieval",
        "propose_tool_call",
        "refuse",
    ]


def test_llm_react_planner_advertises_current_eligible_actions_only() -> None:
    provider = FakePlannerProvider(
        _planner_output(
            action_type="generate_final_answer",
            candidate_actions=["generate_final_answer"],
            selected_action="generate_final_answer",
        )
    )
    planner = LLMReActPlanner(
        config=ReActPlannerConfig(provider="openai_compatible", name="planner-test"),
        model_provider=provider,
    )

    planner.plan(
        question="What is the reimbursement rule for travel meals?",
        system_prompt="Use governed ReAct planning.",
        context_summary="accepted_evidence_count=1; eligible_actions=generate_final_answer,refuse",
        eligible_actions=frozenset({ReActActionType.GENERATE_FINAL_ANSWER, ReActActionType.REFUSE}),
    )

    user_payload = json.loads(provider.requests[0].messages[1].content)
    assert user_payload["allowed_actions"] == ["generate_final_answer", "refuse"]


def test_llm_react_planner_sends_fixed_function_schema_for_action_shape() -> None:
    provider = FakePlannerProvider(
        _planner_output(
            action_type="generate_final_answer",
            candidate_actions=["generate_final_answer"],
            selected_action="generate_final_answer",
        )
    )
    planner = LLMReActPlanner(
        config=ReActPlannerConfig(provider="openai_compatible", name="planner-test"),
        model_provider=provider,
    )

    planner.plan(
        question="What is the reimbursement rule for travel meals?",
        system_prompt="Use governed ReAct planning.",
        context_summary="accepted_evidence_count=1; eligible_actions=generate_final_answer,refuse",
        eligible_actions=frozenset({ReActActionType.GENERATE_FINAL_ANSWER, ReActActionType.REFUSE}),
    )

    function_schema = provider.requests[0].function_schema
    assert function_schema is not None
    assert function_schema.name == "submit_react_action_proposal"
    assert function_schema.strict is True
    assert function_schema.parameters_schema["required"] == (
        "action_type",
        "parameters",
        "target_tool_name",
    )
    assert function_schema.parameters_schema["additionalProperties"] is False
    properties = function_schema.parameters_schema["properties"]
    assert properties["action_type"]["enum"] == (
        "generate_final_answer",
        "refuse",
    )
    assert properties["parameters"]["anyOf"][0] == {
        "type": "object",
        "additionalProperties": False,
        "required": (),
        "properties": {},
    }
    assert {"query": {"type": "string"}} in tuple(
        parameter_shape["properties"] for parameter_shape in properties["parameters"]["anyOf"]
    )
    assert properties["target_tool_name"]["type"] == ("string", "null")


def test_llm_react_planner_generates_tool_schema_from_effective_scope() -> None:
    provider = FakePlannerProvider(
        _planner_output(
            action_type="propose_tool_call",
            candidate_actions=["propose_tool_call"],
            selected_action="propose_tool_call",
            parameters={"claim_id": "CLM-001", "customer_id": "CUST-001"},
            target_tool_name="claim_status_lookup",
        )
    )
    planner = LLMReActPlanner(
        config=ReActPlannerConfig(provider="openai_compatible", name="planner-test"),
        model_provider=provider,
    )
    effective_scope = EffectiveToolProposalScope(
        run_id="run_scope",
        plan_round=0,
        schema_digest="sha256:scope",
        tool_interfaces=(
            ToolProposalInterface(
                tool_contract_id="claim_status_lookup",
                purpose="claim status lookup",
                risk_level="medium",
                read_only=True,
                requires_approval=False,
                semantic_result_summary="Returns claim status.",
                parameters=(
                    ToolProposalParameter(
                        name="claim_id",
                        required=True,
                        value_type="string",
                        value_source=ToolProposalParameterSource.USER_SUPPLIED,
                    ),
                    ToolProposalParameter(
                        name="customer_id",
                        required=True,
                        value_type="string",
                        value_source=ToolProposalParameterSource.AUTHORIZED_RESOURCE_HANDLE,
                    ),
                ),
            ),
        ),
    )

    proposal = planner.plan(
        question="Look up claim status.",
        system_prompt="Use governed ReAct planning.",
        context_summary="No prior context.",
        eligible_actions=frozenset({ReActActionType.PROPOSE_TOOL_CALL}),
        effective_tool_proposal_scope=effective_scope,
    )

    function_schema = provider.requests[0].function_schema
    assert function_schema is not None
    schema = function_schema.parameters_schema
    assert schema["properties"]["target_tool_name"]["enum"] == ("claim_status_lookup",)
    tool_parameters_schema = schema["properties"]["parameters"]["oneOf"][0]
    assert tool_parameters_schema["required"] == ("claim_id", "customer_id")
    assert set(tool_parameters_schema["properties"]) == {"claim_id", "customer_id"}
    assert "tool_source_id" not in function_schema.model_dump_json()
    assert proposal.target_tool_name == "claim_status_lookup"


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


def test_llm_react_planner_accepts_generate_final_answer_terminal_action() -> None:
    provider = FakePlannerProvider(_planner_output(action_type="generate_final_answer"))
    planner = LLMReActPlanner(
        config=ReActPlannerConfig(provider="openai_compatible", name="planner-test"),
        model_provider=provider,
    )

    proposal = planner.plan(
        question="What is the reimbursement rule for travel meals?",
        system_prompt="Use governed ReAct planning.",
        context_summary=(
            "Loop Control: eligible_actions=generate_final_answer,refuse; "
            "accepted_evidence_count=1."
        ),
    )

    assert proposal.action_type == ReActActionType.GENERATE_FINAL_ANSWER


@pytest.mark.parametrize("action_type", ["stop"])
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
    assert "unsupported planner action" in str(exc.value)


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
