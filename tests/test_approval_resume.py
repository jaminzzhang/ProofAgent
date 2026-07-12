from __future__ import annotations

import json
import hashlib
import shutil
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
    ReActActionProposal,
    ReActActionType,
    ReasoningSummary,
    RetrievalObservationTruth,
    ToolObservationTruth,
    WorkflowStageAvailability,
    WorkflowStageAvailabilityReason,
    WorkflowStageAvailabilitySet,
    WorkflowStageConfigurationRuntimeSource,
    WorkflowStageConfigurationRuntimeSourceType,
    WorkflowTemplateExecutionInput,
)
from proof_agent.errors import ProofAgentError
from proof_agent.runtime.approval_resume import (
    ApprovalResumeIntegritySigner,
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
    assert "failed HMAC integrity validation" in exc.value.message


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
    assert loaded_snapshot.model_copy(update={"integrity_hmac_sha256": None}) == snapshot
    assert loaded_snapshot.integrity_hmac_sha256 is not None
    assert len(loaded_snapshot.integrity_hmac_sha256) == 64
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
        payload["integrity_hmac_sha256"] = "0" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ProofAgentError) as exc:
        store.load(snapshot_ref)

    assert exc.value.code == "PA_RUNTIME_001"
    assert "failed HMAC integrity validation" in exc.value.message


def test_controlled_react_legacy_unsigned_snapshot_allows_only_public_authorization(
    tmp_path: Path,
) -> None:
    registry = LangGraphApprovalResumeRegistry(
        tmp_path,
        allow_legacy_unsigned_snapshots=True,
    )
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
        payload.pop("integrity_hmac_sha256")
        if snapshot.run_id == "run_public":
            payload["state"].pop("institution_authorization")
        path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = store.load("controlled-react://run_public/snap_public")
    assert loaded.state.institution_authorization == InstitutionAuthorizationContext()

    with pytest.raises(ProofAgentError, match="HMAC integrity validation"):
        store.load("controlled-react://run_scoped/snap_scoped")

    default_store = LangGraphApprovalResumeRegistry(tmp_path).controlled_react_snapshot_store()
    with pytest.raises(ProofAgentError, match="HMAC integrity validation"):
        default_store.load("controlled-react://run_public/snap_public")


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

    assert "failed HMAC integrity validation" in exc.value.message


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
    metadata.pop("integrity_hmac_sha256")
    metadata.pop("institution_authorization")
    metadata.pop("institution_authorization_sha256")
    path.write_text(json.dumps(metadata), encoding="utf-8")

    loaded = LangGraphApprovalResumeRegistry(
        tmp_path,
        allow_legacy_unsigned_metadata=True,
    ).get(execution_input.run_id)

    assert loaded is not None
    assert loaded.institution_authorization == InstitutionAuthorizationContext()


def test_approval_resume_integrity_key_requires_32_bytes(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least 32 bytes"):
        ApprovalResumeIntegritySigner(b"short")
    with pytest.raises(ValueError, match="at least 32 bytes"):
        LangGraphApprovalResumeRegistry(tmp_path, integrity_key=b"short")


@pytest.mark.parametrize(
    ("context_update", "input_update"),
    [
        ({"run_id": "run_other"}, {}),
        ({"question": "Different question"}, {}),
        ({"agent_id": "agent_other"}, {"agent_id": "agent_expected"}),
        ({"agent_id": "agent_expected"}, {}),
        ({}, {"agent_id": "agent_expected"}),
        (
            {"agent_version_id": "version_other"},
            {"agent_version_id": "version_expected"},
        ),
        ({"agent_version_id": "version_expected"}, {}),
        ({}, {"agent_version_id": "version_expected"}),
        ({"draft_id": "draft_other"}, {"draft_id": "draft_expected"}),
        ({"draft_id": "draft_expected"}, {}),
        ({}, {"draft_id": "draft_expected"}),
    ],
)
def test_langgraph_resume_put_rejects_inconsistent_pinned_input(
    tmp_path: Path,
    context_update: dict[str, str],
    input_update: dict[str, str],
) -> None:
    execution_input = _execution_input().model_copy(update=input_update)
    context_kwargs = {
        "agent_yaml": REACT_AGENT,
        "runs_dir": tmp_path / "runs",
        "run_id": execution_input.run_id,
        "question": execution_input.question,
        "checkpointer": MemorySaver(),
        "manifest": load_agent_manifest(REACT_AGENT),
        "workflow_template_execution_input": execution_input,
        **context_update,
    }

    with pytest.raises(ProofAgentError, match="context binding mismatch"):
        LangGraphApprovalResumeRegistry(tmp_path).put(
            LangGraphApprovalResumeContext(**context_kwargs)
        )


def test_langgraph_resume_load_rejects_validly_signed_binding_mismatch(
    tmp_path: Path,
) -> None:
    key = b"l" * 32
    signer = ApprovalResumeIntegritySigner(key)
    execution_input = _execution_input()
    registry = LangGraphApprovalResumeRegistry(tmp_path, integrity_key=key)
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
    metadata["question"] = "Different signed question"
    metadata["integrity_hmac_sha256"] = signer.sign(
        metadata,
        purpose="langgraph-resume-metadata",
    )
    path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(ProofAgentError, match="context binding mismatch"):
        LangGraphApprovalResumeRegistry(tmp_path, integrity_key=key).get(
            execution_input.run_id
        )


@pytest.mark.parametrize(
    ("field", "tamper_context_side"),
    [
        ("agent_id", True),
        ("agent_id", False),
        ("agent_version_id", True),
        ("agent_version_id", False),
        ("draft_id", True),
        ("draft_id", False),
    ],
)
def test_langgraph_resume_load_rejects_one_sided_none_binding_mismatch(
    tmp_path: Path,
    field: str,
    tamper_context_side: bool,
) -> None:
    key = b"n" * 32
    signer = ApprovalResumeIntegritySigner(key)
    execution_input = _execution_input()
    registry = LangGraphApprovalResumeRegistry(tmp_path, integrity_key=key)
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
    value = f"signed_{field}"
    if tamper_context_side:
        metadata[field] = value
    else:
        pinned_input = metadata["workflow_template_execution_input"]
        pinned_input[field] = value
        canonical = json.dumps(
            pinned_input,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        metadata["workflow_template_execution_input_sha256"] = hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest()
    metadata["integrity_hmac_sha256"] = signer.sign(
        metadata,
        purpose="langgraph-resume-metadata",
    )
    path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(ProofAgentError, match="context binding mismatch"):
        LangGraphApprovalResumeRegistry(tmp_path, integrity_key=key).get(
            execution_input.run_id
        )


@pytest.mark.parametrize("tamper", ["question", "action", "tool_args"])
def test_controlled_react_snapshot_rejects_wrong_key_and_plain_sha_recompute(
    tmp_path: Path,
    tamper: str,
) -> None:
    key = b"a" * 32
    action = ReActActionProposal(
        action_id="act_keyed",
        action_type=ReActActionType.PROPOSE_TOOL_CALL,
        reasoning_summary=ReasoningSummary(
            goal="look up status",
            observations=(),
            candidate_actions=(ReActActionType.PROPOSE_TOOL_CALL,),
            selected_action=ReActActionType.PROPOSE_TOOL_CALL,
            rationale_summary="A governed lookup is required.",
            risk_flags=(),
            required_evidence=(),
        ),
        target_tool_name="customer_lookup",
        parameters={"customer_id": "CUST-001"},
        risk_level="low",
    )
    snapshot = ControlledReActRunStateSnapshot(
        snapshot_id="snap_keyed",
        run_id="run_keyed",
        state=ControlledReActRunState(
            run_id="run_keyed",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="Original question",
            action_history=(action,),
        ),
    )
    store = LangGraphApprovalResumeRegistry(
        tmp_path,
        integrity_key=key,
    ).controlled_react_snapshot_store()
    snapshot_ref = store.save(snapshot)

    with pytest.raises(ProofAgentError, match="HMAC integrity validation"):
        LangGraphApprovalResumeRegistry(
            tmp_path,
            integrity_key=b"b" * 32,
        ).controlled_react_snapshot_store().load(snapshot_ref)

    path = tmp_path / "run_keyed" / "controlled_react" / "snap_keyed.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.pop("integrity_hmac_sha256")
    if tamper == "question":
        payload["state"]["question"] = "Tampered question"
    elif tamper == "action":
        payload["state"]["action_history"][0]["action_id"] = "act_other"
    else:
        payload["state"]["action_history"][0]["parameters"] = {
            "customer_id": "CUST-999"
        }
    canonical = json.dumps(payload["state"], sort_keys=True, separators=(",", ":"))
    payload["integrity_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ProofAgentError, match="HMAC integrity validation"):
        store.load(snapshot_ref)


def test_langgraph_resume_metadata_rejects_wrong_key(tmp_path: Path) -> None:
    execution_input = _execution_input()
    registry = LangGraphApprovalResumeRegistry(tmp_path, integrity_key=b"a" * 32)
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

    with pytest.raises(ProofAgentError, match="HMAC integrity validation"):
        LangGraphApprovalResumeRegistry(
            tmp_path,
            integrity_key=b"b" * 32,
        ).get(execution_input.run_id)


def test_legacy_flag_rejects_unsigned_scoped_resume_metadata(tmp_path: Path) -> None:
    registry = LangGraphApprovalResumeRegistry(tmp_path, integrity_key=b"a" * 32)
    registry.put_controlled_react(
        ControlledReActApprovalResumeContext(
            agent_yaml=REACT_V3_AGENT,
            run_id="run_scoped_metadata",
            question="Question",
            manifest=load_agent_manifest(REACT_V3_AGENT),
            institution_authorization=InstitutionAuthorizationContext(roles=("reviewer",)),
        )
    )
    path = tmp_path / "run_scoped_metadata" / "controlled_react_resume_context.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.pop("integrity_hmac_sha256")
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ProofAgentError, match="HMAC integrity validation"):
        LangGraphApprovalResumeRegistry(
            tmp_path,
            integrity_key=b"a" * 32,
            allow_legacy_unsigned_metadata=True,
        ).get_controlled_react("run_scoped_metadata")


@pytest.mark.parametrize(
    "snapshot_ref",
    [
        "controlled-react://../snap",
        "controlled-react://run/..",
        "controlled-react://run/snap/extra",
        "controlled-react://run%2Fother/snap",
        "controlled-react://run.name/snap",
        "controlled-react://run//snap",
    ],
)
def test_controlled_react_snapshot_ref_rejects_path_controls(
    tmp_path: Path,
    snapshot_ref: str,
) -> None:
    store = LangGraphApprovalResumeRegistry(tmp_path).controlled_react_snapshot_store()

    with pytest.raises(ProofAgentError) as exc:
        store.load(snapshot_ref)

    assert exc.value.code == "PA_RUNTIME_001"


def test_controlled_react_snapshot_rejects_cross_run_file_transplant(
    tmp_path: Path,
) -> None:
    registry = LangGraphApprovalResumeRegistry(tmp_path, integrity_key=b"a" * 32)
    store = registry.controlled_react_snapshot_store()
    source_ref = store.save(
        ControlledReActRunStateSnapshot(
            snapshot_id="snap_source",
            run_id="run_source",
            state=ControlledReActRunState(
                run_id="run_source",
                template_name="react_enterprise_qa_v3",
                template_descriptor_version="react_enterprise_qa.v3",
                question="Source question",
            ),
        )
    )
    assert store.load(source_ref).run_id == "run_source"
    source = tmp_path / "run_source" / "controlled_react" / "snap_source.json"
    target = tmp_path / "run_target" / "controlled_react" / "snap_target.json"
    target.parent.mkdir(parents=True)
    shutil.copyfile(source, target)

    with pytest.raises(ProofAgentError, match="reference identity mismatch"):
        store.load("controlled-react://run_target/snap_target")

    with pytest.raises(ProofAgentError, match="run identity mismatch"):
        store.save(
            ControlledReActRunStateSnapshot(
                snapshot_id="snap_mismatch",
                run_id="run_source",
                state=ControlledReActRunState(
                    run_id="run_other",
                    template_name="react_enterprise_qa_v3",
                    template_descriptor_version="react_enterprise_qa.v3",
                    question="Mismatched question",
                ),
            )
        )


def test_controlled_resume_metadata_rejects_cross_run_transplant(tmp_path: Path) -> None:
    registry = LangGraphApprovalResumeRegistry(tmp_path, integrity_key=b"a" * 32)
    registry.put_controlled_react(
        ControlledReActApprovalResumeContext(
            agent_yaml=REACT_V3_AGENT,
            run_id="run_source",
            question="Question",
            manifest=load_agent_manifest(REACT_V3_AGENT),
        )
    )
    source = tmp_path / "run_source" / "controlled_react_resume_context.json"
    target = tmp_path / "run_target" / "controlled_react_resume_context.json"
    target.parent.mkdir(parents=True)
    shutil.copyfile(source, target)

    with pytest.raises(ProofAgentError, match="run identity mismatch"):
        registry.get_controlled_react("run_target")


@pytest.mark.parametrize("kind", ["retrieval", "tool"])
def test_observation_truth_hmac_round_trip_and_rejects_tampering(
    tmp_path: Path,
    kind: str,
) -> None:
    key = b"o" * 32
    registry = LangGraphApprovalResumeRegistry(tmp_path, integrity_key=key)
    store = registry.controlled_react_observation_truth_store()
    truth_ref = "observation://run_truth/obs_001/truth"
    truth = (
        RetrievalObservationTruth(
            truth_ref=truth_ref,
            observation_id="obs_001",
            action_id="act_retrieve",
            citation_refs=("claims.md#rule",),
            admission_metadata={"status": "accepted"},
        )
        if kind == "retrieval"
        else ToolObservationTruth(
            truth_ref=truth_ref,
            observation_id="obs_001",
            action_id="act_tool",
            tool_name="customer_lookup",
            authorized_result={"status": "active"},
            approval_ref="appr_act_tool",
        )
    )

    assert store.save(truth) == truth_ref
    assert store.load(truth_ref) == truth
    path = tmp_path / "run_truth" / "controlled_react" / "observation_truth" / "obs_001.json"
    assert path.stat().st_mode & 0o777 == 0o600
    envelope = json.loads(path.read_text(encoding="utf-8"))
    if kind == "retrieval":
        envelope["payload"]["citation_refs"] = ["tampered.md#rule"]
    else:
        envelope["payload"]["authorized_result"] = {"status": "admin"}
    path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(ProofAgentError, match="HMAC integrity validation"):
        store.load(truth_ref)


def test_observation_truth_rejects_wrong_key_stripped_hmac_and_plain_hash(
    tmp_path: Path,
) -> None:
    key = b"o" * 32
    registry = LangGraphApprovalResumeRegistry(tmp_path, integrity_key=key)
    store = registry.controlled_react_observation_truth_store()
    truth_ref = "observation://run_truth/obs_002/truth"
    truth = ToolObservationTruth(
        truth_ref=truth_ref,
        observation_id="obs_002",
        action_id="act_tool",
        tool_name="customer_lookup",
        authorized_result={"status": "active"},
    )
    store.save(truth)

    with pytest.raises(ProofAgentError, match="HMAC integrity validation"):
        LangGraphApprovalResumeRegistry(
            tmp_path,
            integrity_key=b"x" * 32,
        ).controlled_react_observation_truth_store().load(truth_ref)

    path = tmp_path / "run_truth" / "controlled_react" / "observation_truth" / "obs_002.json"
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope.pop("integrity_hmac_sha256")
    envelope["payload"]["authorized_result"] = {"status": "tampered"}
    canonical = json.dumps(envelope["payload"], sort_keys=True, separators=(",", ":"))
    envelope["integrity_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(ProofAgentError, match="HMAC integrity validation"):
        store.load(truth_ref)


def test_observation_truth_rejects_transplant_internal_mismatch_and_path_controls(
    tmp_path: Path,
) -> None:
    registry = LangGraphApprovalResumeRegistry(tmp_path, integrity_key=b"o" * 32)
    store = registry.controlled_react_observation_truth_store()
    source_ref = "observation://run_source/obs_source/truth"
    truth = RetrievalObservationTruth(
        truth_ref=source_ref,
        observation_id="obs_source",
        action_id="act_retrieve",
    )
    store.save(truth)
    source = (
        tmp_path
        / "run_source"
        / "controlled_react"
        / "observation_truth"
        / "obs_source.json"
    )
    target = (
        tmp_path
        / "run_target"
        / "controlled_react"
        / "observation_truth"
        / "obs_target.json"
    )
    target.parent.mkdir(parents=True)
    shutil.copyfile(source, target)

    with pytest.raises(ProofAgentError, match="identity mismatch"):
        store.load("observation://run_target/obs_target/truth")
    with pytest.raises(ProofAgentError, match="identity mismatch"):
        store.save(
            RetrievalObservationTruth(
                truth_ref="observation://run_source/obs_source/truth",
                observation_id="obs_other",
                action_id="act_retrieve",
            )
        )
    for invalid_ref in (
        "observation://../obs/truth",
        "observation://run/../truth",
        "observation://run%2Fother/obs/truth",
        "observation://run/obs/extra/truth",
    ):
        with pytest.raises(ProofAgentError):
            store.load(invalid_ref)
