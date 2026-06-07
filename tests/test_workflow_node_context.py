import pytest

from proof_agent.control.workflow.node_context import (
    build_workflow_node_context_preview,
    workflow_node_context_summary,
)
from proof_agent.control.workflow.templates import resolve_workflow_template
from proof_agent.errors import ProofAgentError


def test_preview_redacts_secret_like_prompt_text() -> None:
    descriptor = resolve_workflow_template("react_enterprise_qa")

    preview = build_workflow_node_context_preview(
        descriptor=descriptor,
        node_id="plan",
        prompt={
            "business_context": "Use account secret token SECRET-123.",
            "task_instructions": ["Prefer retrieval."],
            "output_preferences": [],
        },
        context_options={"include_agent_purpose": True},
        sample_context={"agent_purpose": "Answer claims questions."},
    )

    assert preview["node_id"] == "plan"
    assert "SECRET-123" not in preview["business_context_addendum"]["text"]
    assert "[REDACTED]" in preview["business_context_addendum"]["text"]
    assert preview["summary"]["redaction_applied"] is True


def test_preview_rejects_unknown_context_option() -> None:
    descriptor = resolve_workflow_template("react_enterprise_qa")

    with pytest.raises(ProofAgentError) as exc:
        build_workflow_node_context_preview(
            descriptor=descriptor,
            node_id="plan",
            prompt={},
            context_options={"include_raw_trace": True},
            sample_context={},
        )

    assert exc.value.code == "PA_CONFIG_002"
    assert "unsupported context option for workflow node plan" in exc.value.message


def test_summary_is_trace_safe_and_excludes_prompt_text() -> None:
    descriptor = resolve_workflow_template("react_enterprise_qa")
    preview = build_workflow_node_context_preview(
        descriptor=descriptor,
        node_id="plan",
        prompt={
            "business_context": "Insurance claim context.",
            "task_instructions": ["Prefer retrieval."],
            "output_preferences": ["Be concise."],
        },
        context_options={"include_agent_purpose": True, "include_bound_tools": False},
        sample_context={"agent_purpose": "Answer claims questions."},
    )

    summary = workflow_node_context_summary(preview)

    assert summary == {
        "node_id": "plan",
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
    }
    assert "Insurance claim context." not in str(summary)
