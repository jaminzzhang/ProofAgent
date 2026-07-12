from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.contracts import (
    ControlledReActRunState,
    ControlledReActRunStateSnapshot,
    EffectiveWorkflowStageConfiguration,
    EffectiveWorkflowStageConfigurationStage,
    WorkflowStageAvailability,
    WorkflowStageAvailabilityReason,
    WorkflowStageAvailabilitySet,
    WorkflowStageConfigurationRuntimeSource,
    WorkflowStageConfigurationRuntimeSourceType,
    WorkflowTemplateExecutionInput,
)
from proof_agent.control.workflow.controlled_react.local_stores import (
    FileControlledReActSnapshotStore,
)
from proof_agent.control.workflow.controlled_react.artifact_binding import (
    bind_controlled_react_snapshot,
)
from proof_agent.errors import ProofAgentError
from proof_agent.runtime.approval_resume import (
    CONTROLLED_REACT_SNAPSHOT_REF_PREFIX,
    ControlledReActApprovalResumeContext,
    LangGraphApprovalResumeContext,
    LangGraphApprovalResumeRegistry,
)


REACT_V3_AGENT = Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml")
REACT_AGENT = REACT_V3_AGENT


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
    assert metadata["workflow_template_execution_input"]["template_name"] == ("react_enterprise_qa")

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


def test_controlled_react_resume_registry_persists_context_and_snapshot(
    tmp_path: Path,
) -> None:
    registry = LangGraphApprovalResumeRegistry(tmp_path)
    snapshot = ControlledReActRunStateSnapshot(
        snapshot_id="snap_run_controlled",
        run_id="run_controlled",
        state=ControlledReActRunState(
            run_id="run_controlled",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="Please look up customer policy status for CUST-001.",
        ),
    )

    snapshot_ref = registry.controlled_react_snapshot_store().save(snapshot)
    registry.put_controlled_react(
        ControlledReActApprovalResumeContext(
            agent_yaml=REACT_V3_AGENT,
            run_id="run_controlled",
            question=snapshot.state.question,
            manifest=load_agent_manifest(REACT_V3_AGENT),
        )
    )

    assert snapshot_ref.startswith(CONTROLLED_REACT_SNAPSHOT_REF_PREFIX)
    loaded_snapshot = (
        LangGraphApprovalResumeRegistry(tmp_path)
        .controlled_react_snapshot_store()
        .load(snapshot_ref)
    )
    loaded_context = LangGraphApprovalResumeRegistry(tmp_path).get_controlled_react(
        "run_controlled"
    )
    assert loaded_snapshot == snapshot
    assert loaded_context is not None
    assert loaded_context.manifest.workflow.template == "react_enterprise_qa_v3"


@pytest.mark.parametrize(
    ("run_id", "snapshot_id"),
    (
        ("", "snap_001"),
        (".", "snap_001"),
        ("..", "snap_001"),
        ("/absolute", "snap_001"),
        ("run/escape", "snap_001"),
        (r"run\\escape", "snap_001"),
        ("run_001", ""),
        ("run_001", "."),
        ("run_001", ".."),
        ("run_001", "/absolute"),
        ("run_001", "snap/escape"),
        ("run_001", r"snap\\escape"),
    ),
)
def test_file_controlled_react_snapshot_store_rejects_unsafe_path_segments(
    tmp_path: Path,
    run_id: str,
    snapshot_id: str,
) -> None:
    snapshot = ControlledReActRunStateSnapshot(
        snapshot_id=snapshot_id,
        run_id=run_id,
        state=ControlledReActRunState(
            run_id=run_id,
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="Test unsafe local snapshot references.",
        ),
    )

    with pytest.raises(ProofAgentError) as exc:
        FileControlledReActSnapshotStore(tmp_path).save(snapshot)

    assert exc.value.code == "PA_RUNTIME_001"


def test_file_controlled_react_snapshot_store_rejects_conflicting_existing_ref(
    tmp_path: Path,
) -> None:
    store = FileControlledReActSnapshotStore(tmp_path)
    original = ControlledReActRunStateSnapshot(
        snapshot_id="snap_001",
        run_id="run_001",
        state=ControlledReActRunState(
            run_id="run_001",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="Original question",
        ),
    )
    conflicting = original.model_copy(
        update={"state": original.state.model_copy(update={"question": "Conflicting question"})}
    )
    snapshot_ref = store.save(original)

    with pytest.raises(ProofAgentError) as exc:
        store.save(conflicting)

    assert exc.value.code == "PA_RUNTIME_001"
    assert store.load(snapshot_ref) == original


def test_file_controlled_react_snapshot_store_allows_identical_idempotent_save(
    tmp_path: Path,
) -> None:
    store = FileControlledReActSnapshotStore(tmp_path)
    snapshot = ControlledReActRunStateSnapshot(
        snapshot_id="snap_001",
        run_id="run_001",
        state=ControlledReActRunState(
            run_id="run_001",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="Original question",
        ),
    )

    first_ref = store.save(snapshot)
    second_ref = store.save(snapshot)

    assert second_ref == first_ref
    assert store.load(first_ref) == snapshot


def test_file_controlled_react_snapshot_store_rejects_state_run_identity_mismatch(
    tmp_path: Path,
) -> None:
    snapshot = ControlledReActRunStateSnapshot(
        snapshot_id="snap_001",
        run_id="run_001",
        state=ControlledReActRunState(
            run_id="run_other",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="Mismatched run identity",
        ),
    )

    with pytest.raises(ProofAgentError) as exc:
        FileControlledReActSnapshotStore(tmp_path).save(snapshot)

    assert exc.value.code == "PA_RUNTIME_001"


@pytest.mark.parametrize(
    ("payload_run_id", "payload_snapshot_id", "state_run_id"),
    (
        ("run_other", "snap_001", "run_other"),
        ("run_001", "snap_other", "run_001"),
        ("run_001", "snap_001", "run_other"),
    ),
)
def test_file_controlled_react_snapshot_store_rejects_payload_identity_mismatch(
    tmp_path: Path,
    payload_run_id: str,
    payload_snapshot_id: str,
    state_run_id: str,
) -> None:
    path = tmp_path / "run_001" / "controlled_react" / "snap_001.json"
    path.parent.mkdir(parents=True)
    source = ControlledReActRunStateSnapshot(
        snapshot_id="snap_seed",
        run_id="run_seed",
        state=ControlledReActRunState(
            run_id="run_seed",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="Mismatched persisted identity",
        ),
    )
    FileControlledReActSnapshotStore(tmp_path).save(source)
    source_path = tmp_path / "run_seed" / "controlled_react" / "snap_seed.json"
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    payload["run_id"] = payload_run_id
    payload["snapshot_id"] = payload_snapshot_id
    payload["state"]["run_id"] = state_run_id
    path.write_text(json.dumps(payload), encoding="utf-8")
    expected_snapshot = ControlledReActRunStateSnapshot(
        snapshot_id="snap_001",
        run_id="run_001",
        state=ControlledReActRunState(
            run_id="run_001",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="Mismatched persisted identity",
        ),
    )

    with pytest.raises(ProofAgentError) as exc:
        FileControlledReActSnapshotStore(tmp_path).load(
            bind_controlled_react_snapshot(expected_snapshot).reference
        )

    assert exc.value.code == "PA_RUNTIME_001"


def test_file_controlled_react_snapshot_store_publish_failure_leaves_no_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = ControlledReActRunStateSnapshot(
        snapshot_id="snap_001",
        run_id="run_001",
        state=ControlledReActRunState(
            run_id="run_001",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="Atomic publication failure",
        ),
    )
    target = tmp_path / "run_001" / "controlled_react" / "snap_001.json"
    store = FileControlledReActSnapshotStore(tmp_path)

    def fail_publish(
        _source: os.PathLike[str],
        _target: os.PathLike[str],
        **_kwargs: object,
    ) -> None:
        raise OSError("injected atomic publication failure")

    monkeypatch.setattr(os, "link", fail_publish)

    with pytest.raises(ProofAgentError) as exc:
        store.save(snapshot)

    assert exc.value.code == "PA_RUNTIME_001"
    assert not target.exists()
    assert not tuple(target.parent.glob(".*.tmp"))


@pytest.mark.parametrize(
    "payload",
    (
        "{not-json",
        json.dumps(["not", "an", "object"]),
        json.dumps({"snapshot_id": 42}),
    ),
)
def test_file_controlled_react_snapshot_store_fails_closed_on_corrupt_json(
    tmp_path: Path,
    payload: str,
) -> None:
    path = tmp_path / "run_001" / "controlled_react" / "snap_001.json"
    path.parent.mkdir(parents=True)
    path.write_text(payload, encoding="utf-8")
    expected_snapshot = ControlledReActRunStateSnapshot(
        snapshot_id="snap_001",
        run_id="run_001",
        state=ControlledReActRunState(
            run_id="run_001",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="Corrupt persisted snapshot",
        ),
    )

    with pytest.raises(ProofAgentError) as exc:
        FileControlledReActSnapshotStore(tmp_path).load(
            bind_controlled_react_snapshot(expected_snapshot).reference
        )

    assert exc.value.code == "PA_RUNTIME_001"
