from __future__ import annotations

import json
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.contracts import (
    EffectiveWorkflowStageConfiguration,
    EffectiveWorkflowStageConfigurationStage,
    WorkflowStageAvailability,
    WorkflowStageAvailabilityReason,
    WorkflowStageAvailabilitySet,
    WorkflowStageConfigurationRuntimeSource,
    WorkflowStageConfigurationRuntimeSourceType,
    WorkflowTemplateExecutionInput,
)
from proof_agent.errors import ProofAgentError
from proof_agent.runtime.approval_resume import (
    LangGraphApprovalResumeContext,
    LangGraphApprovalResumeRegistry,
)


REACT_AGENT = Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa/agent.yaml")


def _execution_input() -> WorkflowTemplateExecutionInput:
    return WorkflowTemplateExecutionInput(
        run_id="run_resume_metadata",
        template_name="react_enterprise_qa",
        template_descriptor_version="react_enterprise_qa.v1",
        question="Look up customer policy status before answering.",
        effective_stage_configuration_ref="package_local:react_enterprise_qa",
        workflow_stage_availability=WorkflowStageAvailabilitySet(
            template_name="react_enterprise_qa",
            template_descriptor_version="react_enterprise_qa.v1",
            stages=(
                WorkflowStageAvailability(
                    stage_id="tool",
                    available=True,
                    reason=WorkflowStageAvailabilityReason.CAPABILITY_ENABLED,
                    capability="tools",
                ),
            ),
        ),
        effective_stage_configuration=EffectiveWorkflowStageConfiguration(
            template_name="react_enterprise_qa",
            template_descriptor_version="react_enterprise_qa.v1",
            stages=(
                EffectiveWorkflowStageConfigurationStage(
                    id="tool",
                    label="Tool",
                    description="Execute approved tool requests.",
                    required=True,
                    model_bearing=False,
                    prompt={"business_context": "Claims context."},
                ),
            ),
        ),
        stage_configuration_source=WorkflowStageConfigurationRuntimeSource(
            source_type=WorkflowStageConfigurationRuntimeSourceType.PACKAGE_LOCAL_LATEST,
            reference="package_local:react_enterprise_qa",
        ),
    )


def test_approval_resume_registry_persists_execution_input_with_integrity(
    tmp_path: Path,
) -> None:
    execution_input = _execution_input()
    registry = LangGraphApprovalResumeRegistry(tmp_path)
    registry.put(
        LangGraphApprovalResumeContext(
            agent_yaml=REACT_AGENT,
            runs_dir=tmp_path / "runs",
            run_id=execution_input.run_id,
            question=execution_input.question,
            checkpointer=MemorySaver(),
            manifest=load_agent_manifest(REACT_AGENT),
            workflow_template_execution_input=execution_input,
        )
    )

    metadata_path = tmp_path / execution_input.run_id / "resume_context.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["workflow_template_execution_input_sha256"]
    assert metadata["workflow_template_execution_input"]["template_name"] == (
        "react_enterprise_qa"
    )

    loaded = LangGraphApprovalResumeRegistry(tmp_path).get(execution_input.run_id)

    assert loaded is not None
    assert loaded.workflow_template_execution_input == execution_input


def test_approval_resume_registry_rejects_tampered_execution_input(
    tmp_path: Path,
) -> None:
    execution_input = _execution_input()
    registry = LangGraphApprovalResumeRegistry(tmp_path)
    registry.put(
        LangGraphApprovalResumeContext(
            agent_yaml=REACT_AGENT,
            runs_dir=tmp_path / "runs",
            run_id=execution_input.run_id,
            question=execution_input.question,
            checkpointer=MemorySaver(),
            manifest=load_agent_manifest(REACT_AGENT),
            workflow_template_execution_input=execution_input,
        )
    )
    metadata_path = tmp_path / execution_input.run_id / "resume_context.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["workflow_template_execution_input"]["template_descriptor_version"] = (
        "react_enterprise_qa.v999"
    )
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(ProofAgentError) as exc:
        LangGraphApprovalResumeRegistry(tmp_path).get(execution_input.run_id)

    assert exc.value.code == "PA_RUNTIME_001"
    assert "failed integrity validation" in exc.value.message
