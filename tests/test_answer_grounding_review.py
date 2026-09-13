"""The advisory grounding review accepts only a bounded three-boolean contract."""

import json

import pytest

from proof_agent.contracts import ModelResponse, ValidationStatus
from proof_agent.control.workflow.controlled_react.answer_grounding_review import (
    CHECKS,
    validate_grounding_review,
)


def _response(content):
    return ModelResponse(
        content=content if isinstance(content, str) else json.dumps(content),
        provider_name="offline", model_name="synthetic",
    )


def test_all_three_true_pass_with_advisory_metadata():
    result = validate_grounding_review(_response({key: True for key in CHECKS}))
    assert result.status is ValidationStatus.PASSED
    assert result.metadata["verification_kind"] == "llm_grounding_review"
    assert "not deterministic semantic proof" in result.reason.lower()


@pytest.mark.parametrize("failed_key", CHECKS)
def test_any_false_fails_with_specific_check(failed_key):
    checks = {key: True for key in CHECKS}
    checks[failed_key] = False
    result = validate_grounding_review(_response(checks))
    assert result.status is ValidationStatus.FAILED
    assert f"grounding_{failed_key}_failed" in result.metadata["violation_codes"]
    assert result.metadata["verification_kind"] == "llm_grounding_review"


@pytest.mark.parametrize("content", [
    {"claims_supported": True, "conditions_preserved": True},
    {"claims_supported": True, "conditions_preserved": True,
     "requirements_addressed": True, "extra": True},
    {"claims_supported": 1, "conditions_preserved": True,
     "requirements_addressed": True},
    "{wrong json",
    "x" * 4_001,
])
def test_missing_extra_wrong_type_invalid_json_and_oversize_fail(content):
    result = validate_grounding_review(_response(content))
    assert result.status is ValidationStatus.FAILED
    assert "grounding_review_invalid" in result.metadata["violation_codes"]
    assert result.metadata["verification_kind"] == "llm_grounding_review"
