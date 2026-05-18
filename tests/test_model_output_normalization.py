from __future__ import annotations

import pytest

from proof_agent.capabilities.models.normalization import (
    ModelOutputNormalizationError,
    parse_model_contract,
)
from proof_agent.contracts import ReActActionProposal, ReActActionType


VALID_PROPOSAL_JSON = """
{
  "action_id": "act_1",
  "action_type": "plan_retrieval",
  "reasoning_summary": {
    "goal": "Find policy evidence before answering.",
    "observations": ["The question asks for a policy-backed answer."],
    "candidate_actions": ["plan_retrieval"],
    "selected_action": "plan_retrieval",
    "rationale_summary": "Evidence is required before final answer generation.",
    "risk_flags": [],
    "required_evidence": ["policy evidence"]
  },
  "parameters": {"query": "travel meal reimbursement rule"},
  "target_tool_name": null,
  "risk_level": "low"
}
"""


def test_parse_model_contract_accepts_full_json_object() -> None:
    proposal = parse_model_contract(
        content=VALID_PROPOSAL_JSON,
        contract_type=ReActActionProposal,
        role="react_planner",
    )

    assert proposal.action_type == ReActActionType.PLAN_RETRIEVAL
    assert proposal.parameters["query"] == "travel meal reimbursement rule"


def test_parse_model_contract_accepts_positional_arguments() -> None:
    proposal = parse_model_contract(
        VALID_PROPOSAL_JSON,
        ReActActionProposal,
        "react_planner",
    )

    assert proposal.action_id == "act_1"


def test_parse_model_contract_accepts_fenced_json_object() -> None:
    proposal = parse_model_contract(
        content=f"```json\n{VALID_PROPOSAL_JSON}\n```",
        contract_type=ReActActionProposal,
        role="react_planner",
    )

    assert proposal.action_id == "act_1"


def test_parse_model_contract_rejects_full_non_object_json() -> None:
    content = "[1, 2]"

    with pytest.raises(ModelOutputNormalizationError) as exc:
        parse_model_contract(
            content=content,
            contract_type=ReActActionProposal,
            role="react_planner",
        )

    assert exc.value.error_code == "model_output_json_not_object"
    assert exc.value.raw_content_length == len(content)


def test_parse_model_contract_rejects_fenced_non_object_json() -> None:
    content = "```json\n[1, 2]\n```"

    with pytest.raises(ModelOutputNormalizationError) as exc:
        parse_model_contract(
            content=content,
            contract_type=ReActActionProposal,
            role="react_planner",
        )

    assert exc.value.error_code == "model_output_json_not_object"
    assert exc.value.raw_content_length == len(content)


def test_parse_model_contract_rejects_multiple_fenced_json_objects() -> None:
    with pytest.raises(ModelOutputNormalizationError) as exc:
        parse_model_contract(
            content=(
                f"```json\n{VALID_PROPOSAL_JSON}\n```\n"
                f"```json\n{VALID_PROPOSAL_JSON}\n```"
            ),
            contract_type=ReActActionProposal,
            role="react_planner",
        )

    assert exc.value.role == "react_planner"
    assert exc.value.error_code == "model_output_json_parse_failed"


def test_parse_model_contract_rejects_natural_language() -> None:
    with pytest.raises(ModelOutputNormalizationError) as exc:
        parse_model_contract(
            content="I should retrieve policy evidence first.",
            contract_type=ReActActionProposal,
            role="react_planner",
        )

    assert exc.value.role == "react_planner"
    assert exc.value.error_code == "model_output_json_parse_failed"


def test_parse_model_contract_rejects_invalid_contract_shape() -> None:
    with pytest.raises(ModelOutputNormalizationError) as exc:
        parse_model_contract(
            content='{"action_id": "act_1", "action_type": "unknown"}',
            contract_type=ReActActionProposal,
            role="react_planner",
        )

    assert exc.value.error_code == "model_output_contract_validation_failed"
