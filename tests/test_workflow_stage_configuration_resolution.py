from __future__ import annotations

from proof_agent.contracts import (
    WorkflowStageConfigurationRuntimeSource,
    WorkflowStageConfigurationRuntimeSourceType,
)
from proof_agent.control.workflow.stage_configuration import (
    resolve_workflow_stage_runtime_configuration,
)


def test_resolver_excludes_unavailable_tool_stages_from_effective_configuration() -> None:
    resolved = resolve_workflow_stage_runtime_configuration(
        """
name: react_enterprise_qa_v3
purpose: "Answer governed questions."
workflow:
  template: react_enterprise_qa_v3
  stages:
    - id: plan
      prompt:
        business_context: "Claims context."
      context:
        include_agent_purpose: true
capabilities:
  tools:
    enabled: false
  memory:
    enabled: true
    provider: session
""",
        source=WorkflowStageConfigurationRuntimeSource(
            source_type=WorkflowStageConfigurationRuntimeSourceType.PACKAGE_LOCAL_LATEST,
            reference="package:react_enterprise_qa_v3",
        ),
    )

    assert resolved is not None
    assert resolved.workflow_stage_availability.is_available("tool_review") is False
    assert resolved.workflow_stage_availability.is_available("tool") is False
    assert "tool_review" not in resolved.effective_stage_configuration.stage_ids
    assert "tool" not in resolved.effective_stage_configuration.stage_ids
    assert resolved.trace_summary.source.reference == "package:react_enterprise_qa_v3"
    plan_summary = next(
        stage for stage in resolved.trace_summary.stages if stage.stage_id == "plan"
    )
    assert plan_summary.prompt_field_names == ("business_context",)
    assert plan_summary.context_option_names == ("include_agent_purpose",)


def test_resolver_excludes_unavailable_memory_stage_from_effective_configuration() -> None:
    resolved = resolve_workflow_stage_runtime_configuration(
        """
name: react_enterprise_qa_v3
purpose: "Answer governed questions."
workflow:
  template: react_enterprise_qa_v3
capabilities:
  tools:
    enabled: true
    file: ./tools.yaml
  memory:
    enabled: false
""",
        source=WorkflowStageConfigurationRuntimeSource(
            source_type=WorkflowStageConfigurationRuntimeSourceType.PACKAGE_LOCAL_LATEST,
            reference="package:react_enterprise_qa_v3",
        ),
    )

    assert resolved is not None
    assert resolved.workflow_stage_availability.is_available("memory") is False
    assert "memory" not in resolved.effective_stage_configuration.stage_ids
    assert "memory" not in {stage.stage_id for stage in resolved.trace_summary.stages}
