from proof_agent.control.workflow.templates import (
    list_workflow_templates,
    resolve_workflow_template,
)


def test_react_template_descriptor_exposes_public_stages() -> None:
    descriptor = resolve_workflow_template("react_enterprise_qa")

    assert descriptor.descriptor_version == "react_enterprise_qa.v1"
    assert [stage.id for stage in descriptor.stages] == [
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


def test_enterprise_qa_descriptor_is_read_only_for_prompt_nodes() -> None:
    descriptor = resolve_workflow_template("enterprise_qa")

    assert descriptor.descriptor_version == "enterprise_qa.v1"
    assert all(not stage.editable_prompt_fields for stage in descriptor.stages)


def test_non_model_react_stages_do_not_expose_prompt_editing() -> None:
    descriptor = resolve_workflow_template("react_enterprise_qa")

    non_model_stages = [stage for stage in descriptor.stages if not stage.model_bearing]

    assert non_model_stages
    assert all(not stage.editable_prompt_fields for stage in non_model_stages)


def test_list_workflow_templates_is_json_safe() -> None:
    descriptors = list_workflow_templates()

    assert {descriptor.name for descriptor in descriptors} == {
        "enterprise_qa",
        "react_enterprise_qa",
        "react_enterprise_qa_v2",
        "react_enterprise_qa_v3",
    }
    assert all(
        isinstance(stage.context_options, tuple)
        for descriptor in descriptors
        for stage in descriptor.stages
    )


def test_react_enterprise_qa_v2_starts_with_intent_resolution() -> None:
    template = resolve_workflow_template("react_enterprise_qa_v2")

    assert template.descriptor_version == "react_enterprise_qa.v2"
    assert template.stages[0].id == "intent_resolution"
    assert template.stages[0].successors == ("plan",)
    assert template.stage("plan").predecessors == ("intent_resolution",)
