import json

import pytest

from proof_agent.control.workflow.stage_context import (
    build_workflow_stage_context_preview,
    workflow_stage_context_summary,
)
from proof_agent.control.workflow.templates import resolve_workflow_template
from proof_agent.errors import ProofAgentError


def test_preview_redacts_secret_like_prompt_text() -> None:
    descriptor = resolve_workflow_template("react_enterprise_qa_v3")

    preview = build_workflow_stage_context_preview(
        descriptor=descriptor,
        stage_id="plan",
        prompt={
            "business_context": "Use account secret token SECRET-123.",
            "task_instructions": ["Prefer retrieval."],
            "output_preferences": [],
        },
        context_options={"include_agent_purpose": True},
        sample_context={"agent_purpose": "Answer claims questions."},
    )

    assert preview["stage_id"] == "plan"
    assert "SECRET-123" not in preview["business_context_addendum"]["text"]
    assert "[REDACTED]" in preview["business_context_addendum"]["text"]
    assert preview["summary"]["redaction_applied"] is True


def test_preview_rejects_unknown_context_option() -> None:
    descriptor = resolve_workflow_template("react_enterprise_qa_v3")

    with pytest.raises(ProofAgentError) as exc:
        build_workflow_stage_context_preview(
            descriptor=descriptor,
            stage_id="plan",
            prompt={},
            context_options={"include_raw_trace": True},
            sample_context={},
        )

    assert exc.value.code == "PA_CONFIG_002"
    assert "unsupported context option for workflow stage plan" in exc.value.message


def test_summary_is_trace_safe_and_excludes_prompt_text() -> None:
    descriptor = resolve_workflow_template("react_enterprise_qa_v3")
    preview = build_workflow_stage_context_preview(
        descriptor=descriptor,
        stage_id="plan",
        prompt={
            "business_context": "Insurance claim context.",
            "task_instructions": ["Prefer retrieval."],
            "output_preferences": ["Be concise."],
        },
        context_options={"include_agent_purpose": True, "include_bound_tools": False},
        sample_context={"agent_purpose": "Answer claims questions."},
    )

    summary = workflow_stage_context_summary(preview)

    assert summary == {
        "stage_id": "plan",
        "prompt_fields": [
            "business_context",
            "task_instructions",
            "output_preferences",
        ],
        "context_options": ["include_agent_purpose"],
        "business_context_length": len("Insurance claim context."),
        "task_instruction_count": 1,
        "output_preference_count": 1,
        "redaction_applied": False,
        "truncation_applied": False,
    }
    assert "Insurance claim context." not in str(summary)


def test_preview_truncates_oversized_agent_purpose() -> None:
    descriptor = resolve_workflow_template("react_enterprise_qa_v3")

    preview = build_workflow_stage_context_preview(
        descriptor=descriptor,
        stage_id="plan",
        prompt={},
        context_options={"include_agent_purpose": True},
        sample_context={"agent_purpose": "A" * 50_000},
    )

    projected = preview["structured_control_context"]["include_agent_purpose"]
    assert len(projected) <= 12_000
    assert "[TRUNCATED]" in projected
    assert preview["summary"]["truncation_applied"] is True
    assert len(json.dumps(preview)) < 20_000


@pytest.mark.parametrize(
    ("stage_id", "context_option", "sample_key"),
    (
        (
            "model_answer",
            "include_response_disclosure_policy",
            "response_disclosure_policy",
        ),
        ("memory", "include_memory_scope", "memory_scope"),
    ),
)
def test_preview_bounds_nested_structured_context(
    stage_id: str,
    context_option: str,
    sample_key: str,
) -> None:
    descriptor = resolve_workflow_template("react_enterprise_qa_v3")
    oversized = {
        "items": [
            {"label": f"item-{index}", "value": "V" * 5_000}
            for index in range(200)
        ]
    }

    preview = build_workflow_stage_context_preview(
        descriptor=descriptor,
        stage_id=stage_id,
        prompt={},
        context_options={context_option: True},
        sample_context={sample_key: oversized},
    )

    assert preview["summary"]["truncation_applied"] is True
    assert len(json.dumps(preview)) < 20_000


def test_preview_counts_non_string_scalars_against_context_budget() -> None:
    descriptor = resolve_workflow_template("react_enterprise_qa_v3")
    oversized = {f"scope-{index}": 10**3_999 for index in range(100)}

    preview = build_workflow_stage_context_preview(
        descriptor=descriptor,
        stage_id="memory",
        prompt={},
        context_options={"include_memory_scope": True},
        sample_context={"memory_scope": oversized},
    )

    assert preview["summary"]["truncation_applied"] is True
    assert "[TRUNCATED]" in json.dumps(preview)
    assert len(json.dumps(preview)) < 20_000


@pytest.mark.parametrize("non_finite", (float("nan"), float("inf"), float("-inf")))
def test_preview_replaces_non_finite_scalars_with_truncation_marker(
    non_finite: float,
) -> None:
    descriptor = resolve_workflow_template("react_enterprise_qa_v3")

    preview = build_workflow_stage_context_preview(
        descriptor=descriptor,
        stage_id="memory",
        prompt={},
        context_options={"include_memory_scope": True},
        sample_context={"memory_scope": {"value": non_finite}},
    )

    assert preview["summary"]["truncation_applied"] is True
    assert "[TRUNCATED]" in json.dumps(preview, allow_nan=False)
