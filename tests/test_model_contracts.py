import pytest

from proof_agent.contracts import (
    ModelCallRole,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelRole,
    TokenUsage,
    TraceEventType,
)


def test_model_request_metadata_is_immutable() -> None:
    request = ModelRequest(
        provider="deterministic",
        model="demo",
        messages=[
            ModelMessage(role=ModelRole.SYSTEM, content="Answer with citations."),
            ModelMessage(
                role=ModelRole.USER,
                content="What is the reimbursement rule?",
                metadata={"source": {"kind": "question"}},
            ),
        ],
        metadata={"trace": {"event": "evt_0001"}},
        evidence_sources=["discount-policy.md"],
    )

    assert request.messages[0].role == ModelRole.SYSTEM
    assert request.evidence_sources == ("discount-policy.md",)

    with pytest.raises(AttributeError):
        request.messages.append(ModelMessage(role=ModelRole.USER, content="x"))

    with pytest.raises(TypeError):
        request.metadata["trace"]["event"] = "evt_0002"

    with pytest.raises(TypeError):
        request.messages[1].metadata["source"]["kind"] = "other"


def test_model_response_carries_provider_neutral_usage() -> None:
    response = ModelResponse(
        content="Travel meals are reimbursable with receipts.",
        provider_name="openai_compatible",
        model_name="gpt-4o-mini",
        token_usage=TokenUsage(input_tokens=12, output_tokens=9, total_tokens=21),
        finish_reason="stop",
        raw_response_id="chatcmpl_test",
    )

    assert response.token_usage is not None
    assert response.token_usage.total_tokens == 21


def test_model_call_roles_are_stable_trace_values() -> None:
    assert ModelCallRole.FINAL_ANSWER.value == "final_answer"
    assert ModelCallRole.REACT_PLANNER.value == "react_planner"
    assert ModelCallRole.HARNESS_REVIEW.value == "harness_review"


def test_trace_event_type_includes_model_output_normalization_failure() -> None:
    assert (
        TraceEventType.MODEL_OUTPUT_NORMALIZATION_FAILED.value
        == "model_output_normalization_failed"
    )
