from __future__ import annotations

import json
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.contracts import (
    ControlledReActRunState,
    ControlledReActRunStateSnapshot,
    EffectiveWorkflowStageConfiguration,
    EffectiveWorkflowStageConfigurationStage,
    InstitutionAuthorizationContext,
    WorkflowStageAvailability,
    WorkflowStageAvailabilityReason,
    WorkflowStageAvailabilitySet,
    WorkflowStageConfigurationRuntimeSource,
    WorkflowStageConfigurationRuntimeSourceType,
    WorkflowTemplateExecutionInput,
)
from proof_agent.errors import ProofAgentError
from proof_agent.runtime.approval_resume import (
    CONTROLLED_REACT_SNAPSHOT_REF_PREFIX,
    ControlledReActApprovalResumeContext,
    LangGraphApprovalResumeContext,
    LangGraphApprovalResumeRegistry,
)


REACT_AGENT = Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa/agent.yaml")
REACT_V3_AGENT = Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml")


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
    authorization = InstitutionAuthorizationContext(
        institutions=("branch-1",), roles=("specialist",)
    )
    execution_input = execution_input.model_copy(
        update={"institution_authorization": authorization}
    )
    registry.put(
        LangGraphApprovalResumeContext(
            agent_yaml=REACT_AGENT,
            runs_dir=tmp_path / "runs",
            run_id=execution_input.run_id,
            question=execution_input.question,
            checkpointer=MemorySaver(),
            manifest=load_agent_manifest(REACT_AGENT),
            workflow_template_execution_input=execution_input,
            institution_authorization=authorization,
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
    assert loaded.institution_authorization == authorization


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


def test_controlled_react_resume_registry_persists_context_and_snapshot(
    tmp_path: Path,
) -> None:
    registry = LangGraphApprovalResumeRegistry(tmp_path)
    authorization = InstitutionAuthorizationContext(regions=("east",), roles=("reviewer",))
    snapshot = ControlledReActRunStateSnapshot(
        snapshot_id="snap_run_controlled",
        run_id="run_controlled",
        state=ControlledReActRunState(
            run_id="run_controlled",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="Please look up customer policy status for CUST-001.",
            institution_authorization=authorization,
        ),
    )

    snapshot_ref = registry.controlled_react_snapshot_store().save(snapshot)
    registry.put_controlled_react(
        ControlledReActApprovalResumeContext(
            agent_yaml=REACT_V3_AGENT,
            run_id="run_controlled",
            question=snapshot.state.question,
            manifest=load_agent_manifest(REACT_V3_AGENT),
            institution_authorization=authorization,
        )
    )

    assert snapshot_ref.startswith(CONTROLLED_REACT_SNAPSHOT_REF_PREFIX)
    loaded_snapshot = LangGraphApprovalResumeRegistry(
        tmp_path
    ).controlled_react_snapshot_store().load(snapshot_ref)
    loaded_context = LangGraphApprovalResumeRegistry(tmp_path).get_controlled_react(
        "run_controlled"
    )
    assert loaded_snapshot.model_copy(update={"integrity_sha256": None}) == snapshot
    assert loaded_snapshot.integrity_sha256 is not None
    assert len(loaded_snapshot.integrity_sha256) == 64
    assert loaded_context is not None
    assert loaded_context.manifest.workflow.template == "react_enterprise_qa_v3"
    assert loaded_context.institution_authorization == authorization
    assert loaded_snapshot.state.institution_authorization == authorization


@pytest.mark.parametrize("tamper", ["authorization", "question", "digest"])
def test_controlled_react_snapshot_rejects_tampering(
    tmp_path: Path,
    tamper: str,
) -> None:
    registry = LangGraphApprovalResumeRegistry(tmp_path)
    authorization = InstitutionAuthorizationContext(roles=("reviewer",))
    snapshot = ControlledReActRunStateSnapshot(
        snapshot_id="snap_tamper",
        run_id="run_tamper",
        state=ControlledReActRunState(
            run_id="run_tamper",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="Original question",
            institution_authorization=authorization,
        ),
    )
    store = registry.controlled_react_snapshot_store()
    snapshot_ref = store.save(snapshot)
    path = tmp_path / "run_tamper" / "controlled_react" / "snap_tamper.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if tamper == "authorization":
        payload["state"]["institution_authorization"]["roles"] = ["administrator"]
    elif tamper == "question":
        payload["state"]["question"] = "Tampered question"
    else:
        payload["integrity_sha256"] = "0" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ProofAgentError) as exc:
        store.load(snapshot_ref)

    assert exc.value.code == "PA_RUNTIME_001"
    assert "failed integrity validation" in exc.value.message


def test_controlled_react_legacy_unsigned_snapshot_allows_only_public_authorization(
    tmp_path: Path,
) -> None:
    registry = LangGraphApprovalResumeRegistry(tmp_path)
    store = registry.controlled_react_snapshot_store()
    public_snapshot = ControlledReActRunStateSnapshot(
        snapshot_id="snap_public",
        run_id="run_public",
        state=ControlledReActRunState(
            run_id="run_public",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="Public question",
        ),
    )
    scoped_snapshot = ControlledReActRunStateSnapshot(
        snapshot_id="snap_scoped",
        run_id="run_scoped",
        state=ControlledReActRunState(
            run_id="run_scoped",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="Scoped question",
            institution_authorization=InstitutionAuthorizationContext(roles=("reviewer",)),
        ),
    )
    for snapshot in (public_snapshot, scoped_snapshot):
        store.save(snapshot)
        path = (
            tmp_path
            / snapshot.run_id
            / "controlled_react"
            / f"{snapshot.snapshot_id}.json"
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.pop("integrity_sha256")
        if snapshot.run_id == "run_public":
            payload["state"].pop("institution_authorization")
        path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = store.load("controlled-react://run_public/snap_public")
    assert loaded.state.institution_authorization == InstitutionAuthorizationContext()

    with pytest.raises(ProofAgentError, match="unsigned controlled ReAct snapshot"):
        store.load("controlled-react://run_scoped/snap_scoped")


def test_controlled_react_resume_registry_rejects_tampered_authorization(
    tmp_path: Path,
) -> None:
    registry = LangGraphApprovalResumeRegistry(tmp_path)
    registry.put_controlled_react(
        ControlledReActApprovalResumeContext(
            agent_yaml=REACT_V3_AGENT,
            run_id="run_tampered_authorization",
            question="Question",
            manifest=load_agent_manifest(REACT_V3_AGENT),
            institution_authorization=InstitutionAuthorizationContext(roles=("reviewer",)),
        )
    )
    path = tmp_path / "run_tampered_authorization" / "controlled_react_resume_context.json"
    metadata = json.loads(path.read_text(encoding="utf-8"))
    metadata["institution_authorization"]["roles"] = ["administrator"]
    path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(ProofAgentError) as exc:
        LangGraphApprovalResumeRegistry(tmp_path).get_controlled_react(
            "run_tampered_authorization"
        )

    assert "failed integrity validation" in exc.value.message


def test_old_resume_metadata_defaults_institution_authorization_to_public_only(
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
    path = tmp_path / execution_input.run_id / "resume_context.json"
    metadata = json.loads(path.read_text(encoding="utf-8"))
    metadata.pop("institution_authorization")
    metadata.pop("institution_authorization_sha256")
    path.write_text(json.dumps(metadata), encoding="utf-8")

    loaded = LangGraphApprovalResumeRegistry(tmp_path).get(execution_input.run_id)

    assert loaded is not None
    assert loaded.institution_authorization == InstitutionAuthorizationContext()
