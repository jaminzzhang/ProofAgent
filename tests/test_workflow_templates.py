import pytest

from proof_agent.control.workflow.templates import (
    list_workflow_templates,
    resolve_workflow_template,
)
from proof_agent.errors import ProofAgentError


def test_react_template_descriptor_exposes_public_stages() -> None:
    descriptor = resolve_workflow_template("react_enterprise_qa_v3")

    assert descriptor.descriptor_version == "react_enterprise_qa.v3"
    assert [stage.id for stage in descriptor.stages] == [
        "intent_resolution",
        "plan",
        "clarification",
        "retrieval_review",
        "retrieval",
        "model_answer",
        "tool_review",
        "tool",
        "memory",
        "response",
    ]
    plan = descriptor.stage("plan")
    assert "business_context" in plan.editable_prompt_fields
    assert "include_bound_tools" in plan.context_options
    assert "retrieval_review" in plan.successors


def test_non_model_react_stages_do_not_expose_prompt_editing() -> None:
    descriptor = resolve_workflow_template("react_enterprise_qa_v3")

    non_model_stages = [stage for stage in descriptor.stages if not stage.model_bearing]

    assert non_model_stages
    assert all(not stage.editable_prompt_fields for stage in non_model_stages)


def test_list_workflow_templates_is_json_safe() -> None:
    descriptors = list_workflow_templates()

    assert [descriptor.name for descriptor in descriptors] == ["react_enterprise_qa_v3"]
    assert all(
        isinstance(stage.context_options, tuple)
        for descriptor in descriptors
        for stage in descriptor.stages
    )


@pytest.mark.parametrize(
    "removed_template",
    ("enterprise_qa", "react_enterprise_qa", "react_enterprise_qa_v2"),
)
def test_removed_workflow_templates_fail_closed(removed_template: str) -> None:
    with pytest.raises(ProofAgentError) as exc:
        resolve_workflow_template(removed_template)

    assert exc.value.code == "PA_CONFIG_002"
    assert "react_enterprise_qa_v3" in exc.value.fix
