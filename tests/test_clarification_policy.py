"""Configuration and governed execution regressions for excessive clarification."""

from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from proof_agent.bootstrap import compose_harness_invocation
from proof_agent.contracts import IntentResolutionResult, ReceiptOutcome
from proof_agent.contracts.manifest import ResponseConfig
from proof_agent.control.workflow.controlled_react import ControlledReActStartRequest
from proof_agent.control.workflow.controlled_react.composition import (
    build_controlled_react_orchestrator_for_invocation,
)


AGENT = Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml")


def intent_payload(kind="preference", default="按已披露的整体经营表现查询"):
    return dict(
        resolution_id="intent_1",
        user_goal="查询集团年度业绩",
        domain_intent="public_information",
        known_facts=["用户询问集团整体业绩"],
        missing_fields=["业绩口径", "时间范围"],
        ambiguities=[],
        risk_flags=[],
        confidence=0.42,
        recommended_next_action="ask_clarification",
        retrieval_query_set=[],
        clarification_assessments=[
            dict(field=field, kind=kind, default_assumption=default)
            for field in ["业绩口径", "时间范围"]
        ],
    )


class CapturedIntent:
    def __init__(self, payload):
        self.payload = payload
        self.context = None

    def resolve(self, **kwargs):
        self.context = kwargs["workflow_stage_context"]
        return IntentResolutionResult(intent_resolution=self.payload)


def run_case(level="balanced", payload=None):
    resolver = CapturedIntent(intent_payload() if payload is None else payload)
    invocation = compose_harness_invocation(AGENT)
    invocation = replace(
        invocation,
        intent_resolver=resolver,
        manifest=invocation.manifest.model_copy(
            update={"response": ResponseConfig(clarification_level=level)},
        ),
    )
    result = build_controlled_react_orchestrator_for_invocation(invocation).start(
        ControlledReActStartRequest(
            run_id="run_clarification_regression",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="平安集团的2026 年业绩怎么样？",
        )
    )
    return result, resolver


def test_default_and_strict_clarification_configuration():
    assert ResponseConfig().clarification_level == "balanced"
    for level in ["minimal", "balanced", "thorough"]:
        assert (
            ResponseConfig.model_validate_json(
                ResponseConfig(clarification_level=level).model_dump_json()
            ).clarification_level
            == level
        )
    for level in ["off", "", 1, None]:
        with pytest.raises(ValidationError):
            ResponseConfig(clarification_level=level)


@pytest.mark.parametrize("level", ["minimal", "balanced"])
def test_overview_with_disclosed_defaults_reaches_retrieval_not_clarification(level):
    result, resolver = run_case(level)
    assert result.outcome != ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION
    assert result.intent_resolution["recommended_next_action"] == "plan_retrieval"
    assert (
        result.intent_resolution["retrieval_query_set"][0]["query"]
        == "平安集团的2026 年业绩怎么样？"
    )
    assert tuple(result.intent_resolution["scope_assumptions"]) == ("按已披露的整体经营表现查询",)
    assert resolver.context["clarification_policy"]["level"] == level
    assert resolver.context["current_date"]
    # With no evidence source this fixture must not fabricate an answer.
    assert result.outcome != ReceiptOutcome.ANSWERED_WITH_CITATIONS


@pytest.mark.parametrize("level", ["minimal", "balanced", "thorough"])
def test_required_context_always_blocks_and_asks_one_chinese_question(level):
    result, _ = run_case(level, intent_payload("required_context", ""))
    assert result.outcome == ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION
    assert "业绩口径" in result.message
    assert "时间范围" not in result.message
    assert "Please provide" not in result.message
    assert result.clarification_need.missing_fields == ("业绩口径", "时间范围")
    assert "ambiguous_business_flow" not in str(result.reasoning_summary)


def test_thorough_confirms_preferences_even_with_default():
    result, _ = run_case("thorough")
    assert result.outcome == ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION


@pytest.mark.parametrize("level", ["minimal", "balanced", "thorough"])
def test_retrievable_information_never_requires_user_input(level):
    result, _ = run_case(level, intent_payload("retrievable", ""))
    assert result.outcome != ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION


def test_balanced_requires_safe_default_but_minimal_can_search_broadly():
    payload = intent_payload("preference", "")
    assert run_case("balanced", payload)[0].outcome == ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION
    assert run_case("minimal", payload)[0].outcome != ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION


def test_unclassified_legacy_missing_fields_remain_blocking():
    payload = intent_payload()
    del payload["clarification_assessments"]
    assert run_case("minimal", payload)[0].outcome == ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION


@pytest.mark.parametrize("action", ["plan_retrieval", "propose_tool_call"])
def test_required_context_cannot_be_bypassed_by_a_different_model_action(action):
    payload = intent_payload("required_context", "")
    payload["recommended_next_action"] = action
    result, _ = run_case("minimal", payload)
    assert result.outcome == ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION


def test_thorough_still_confirms_classified_preferences_when_model_suggests_retrieval():
    payload = intent_payload()
    payload["recommended_next_action"] = "plan_retrieval"
    assert run_case("thorough", payload)[0].outcome == ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION


def test_assumption_capacity_does_not_silently_drop_disclosures():
    payload = intent_payload()
    payload["scope_assumptions"] = [f"scope {index}" for index in range(8)]
    assert run_case("balanced", payload)[0].outcome == ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION


def test_scope_defaults_reach_answer_request_as_non_evidence():
    from proof_agent.control.workflow.clarification import scope_assumption_context
    from proof_agent.control.workflow.harness_helpers import build_model_request

    result, _ = run_case()
    request = build_model_request(
        question="概况？",
        evidence=(),
        provider="test",
        model="test",
        workflow_stage_context=scope_assumption_context(result.intent_resolution),
    )
    user_message = request.messages[1].content
    assert "按已披露的整体经营表现查询" in user_message
    assert "NOT user-confirmed facts or evidence" in user_message
    assert user_message.index("按已披露的整体经营表现查询") < user_message.index("Evidence:")


@pytest.mark.parametrize("change", ["duplicate", "unknown", "too_long", "invalid_kind"])
def test_classifications_are_bounded_and_reference_real_missing_fields(change):
    payload = intent_payload()
    items = payload["clarification_assessments"]
    if change == "duplicate":
        items.append(items[0])
    elif change == "unknown":
        items[0]["field"] = "unlisted"
    elif change == "too_long":
        items[0]["default_assumption"] = "x" * 401
    else:
        items[0]["kind"] = "optional_authorization"
    with pytest.raises(ValidationError):
        IntentResolutionResult(intent_resolution=payload)


@pytest.mark.parametrize("level", ["minimal", "balanced", "thorough"])
def test_agent_yaml_loads_clarification_level_and_binds_execution(level):
    import yaml
    from proof_agent.bootstrap.manifest import manifest_from_mapping

    raw = yaml.safe_load(AGENT.read_text())
    raw["response"] = {"clarification_level": level}
    manifest = manifest_from_mapping(raw, base_dir=AGENT.parent.resolve())
    assert manifest.response.clarification_level == level


def test_agent_yaml_rejects_invalid_clarification_level():
    import yaml
    from proof_agent.bootstrap.manifest import manifest_from_mapping

    raw = yaml.safe_load(AGENT.read_text())
    raw["response"] = {"clarification_level": "off"}
    with pytest.raises(ValidationError):
        manifest_from_mapping(raw, base_dir=AGENT.parent.resolve())
