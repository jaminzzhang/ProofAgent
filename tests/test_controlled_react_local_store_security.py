from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import proof_agent.control.workflow.controlled_react.local_stores as local_stores
from proof_agent.contracts import (
    ApprovedToolProposalSnapshot,
    ControlledReActRunPhase,
    ControlledReActRunState,
    ControlledReActRunStateSnapshot,
    EvidenceChunk,
    EvidenceStatus,
    ObservationRecord,
    ReActActionProposal,
    ReActActionType,
    ReasoningSummary,
    RetrievalObservationTruth,
    ToolObservationTruth,
)
from proof_agent.control.workflow.controlled_react.local_stores import (
    FileControlledReActSnapshotStore,
    FileObservationTruthStore,
)
from proof_agent.control.workflow.controlled_react.artifact_binding import (
    OBSERVATION_TRUTH_BINDING_SCHEMA_VERSION,
    SNAPSHOT_BINDING_SCHEMA_VERSION,
    bind_observation_truth,
)
from proof_agent.control.workflow.controlled_react.observation_commit import (
    InMemoryObservationTruthStore,
    ObservationCommitter,
    ObservationEffect,
)
from proof_agent.errors import ProofAgentError


SNAPSHOT_GOLDEN_DIGEST = "625fa772e34e2e51080d4702b8b5cf50d6190705dc9ca0ad9415bf367287063a"
OBSERVATION_GOLDEN_DIGEST = "5ae2f9c9e131b252bdd9d1460f487dc7573f565a10dd5c33629a2b8c37dc46e3"


@pytest.mark.parametrize(
    "store_type",
    (FileControlledReActSnapshotStore, FileObservationTruthStore),
)
def test_local_artifact_stores_fail_closed_without_anchored_posix_capabilities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    store_type: (type[FileControlledReActSnapshotStore] | type[FileObservationTruthStore]),
) -> None:
    monkeypatch.setattr(local_stores, "_supports_posix_dir_fd", lambda: False)
    unavailable_root = tmp_path / "must-not-be-created"

    with pytest.raises(ProofAgentError) as exc:
        store_type(unavailable_root)

    assert exc.value.code == "PA_RUNTIME_001"
    assert "POSIX" in str(exc.value)
    assert not unavailable_root.exists()


def test_snapshot_ref_uses_versioned_full_payload_digest(tmp_path: Path) -> None:
    snapshot = _snapshot()

    snapshot_ref = FileControlledReActSnapshotStore(tmp_path).save(snapshot)

    assert SNAPSHOT_BINDING_SCHEMA_VERSION == ("proofagent.controlled-react.snapshot-binding.v1")
    assert snapshot_ref == ("controlled-react://run_001/snap_001/sha256/" + SNAPSHOT_GOLDEN_DIGEST)


def test_observation_ref_uses_versioned_normalized_payload_digest(
    tmp_path: Path,
) -> None:
    truth = RetrievalObservationTruth(
        truth_ref="observation://run_001/obs_1/truth",
        observation_id="obs_1",
        action_id="act_original",
    )

    binding = bind_observation_truth(truth)
    truth_ref = FileObservationTruthStore(tmp_path).save(binding.truth)

    assert OBSERVATION_TRUTH_BINDING_SCHEMA_VERSION == (
        "proofagent.controlled-react.observation-truth-binding.v1"
    )
    assert truth_ref == ("observation://run_001/obs_1/truth/sha256/" + OBSERVATION_GOLDEN_DIGEST)
    assert FileObservationTruthStore(tmp_path).load(truth_ref).truth_ref == truth_ref


def test_snapshot_legacy_unbound_ref_fails_closed(tmp_path: Path) -> None:
    store = FileControlledReActSnapshotStore(tmp_path)
    bound_ref = store.save(_snapshot())
    assert "/sha256/" in bound_ref

    with pytest.raises(ProofAgentError) as exc:
        store.load("controlled-react://run_001/snap_001")

    assert exc.value.code == "PA_RUNTIME_001"


def test_snapshot_ref_rejects_modified_digest_segment(tmp_path: Path) -> None:
    store = FileControlledReActSnapshotStore(tmp_path)
    snapshot_ref = store.save(_snapshot())
    assert "/sha256/" in snapshot_ref
    replacement = "0" if snapshot_ref[-1] != "0" else "1"

    with pytest.raises(ProofAgentError) as exc:
        store.load(snapshot_ref[:-1] + replacement)

    assert exc.value.code == "PA_RUNTIME_001"


def test_observation_legacy_unbound_ref_fails_closed(tmp_path: Path) -> None:
    store = FileObservationTruthStore(tmp_path)
    truth = RetrievalObservationTruth(
        truth_ref="observation://run_001/obs_1/truth",
        observation_id="obs_1",
        action_id="act_original",
    )
    bound_ref = store.save(bind_observation_truth(truth).truth)
    assert "/sha256/" in bound_ref

    with pytest.raises(ProofAgentError) as exc:
        store.load(truth.truth_ref)

    assert exc.value.code == "PA_RUNTIME_001"


def test_snapshot_digest_rejects_question_tamper(tmp_path: Path) -> None:
    store = FileControlledReActSnapshotStore(tmp_path)
    snapshot_ref = store.save(_snapshot())
    artifact = _only_json_artifact(tmp_path)
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    payload["state"]["question"] = "Tampered question"
    artifact.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ProofAgentError) as exc:
        store.load(snapshot_ref)

    assert exc.value.code == "PA_RUNTIME_001"


def test_snapshot_canonical_json_preserves_utf8_and_rejects_nan(tmp_path: Path) -> None:
    store = FileControlledReActSnapshotStore(tmp_path)
    store.save(_snapshot())
    content = _only_json_artifact(tmp_path).read_text(encoding="utf-8")

    assert "原始问题" in content
    assert "\\u539f" not in content

    invalid = _snapshot().model_copy(
        update={
            "snapshot_id": "snap_nan",
            "state": _snapshot().state.model_copy(
                update={"intent_resolution": {"confidence": float("nan")}}
            ),
        }
    )
    with pytest.raises(ProofAgentError) as exc:
        store.save(invalid)

    assert exc.value.code == "PA_RUNTIME_001"


def test_snapshot_load_rejects_nested_duplicate_json_key(tmp_path: Path) -> None:
    store = FileControlledReActSnapshotStore(tmp_path)
    snapshot_ref = store.save(_snapshot())
    artifact = _only_json_artifact(tmp_path)
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    raw = raw.replace(
        '"question":"原始问题"',
        '"question":"原始问题","question":"重复字段"',
        1,
    )
    artifact.write_text(raw, encoding="utf-8")

    with pytest.raises(ProofAgentError) as exc:
        store.load(snapshot_ref)

    assert exc.value.code == "PA_RUNTIME_001"


def test_snapshot_digest_rejects_approved_proposal_tamper(tmp_path: Path) -> None:
    store = FileControlledReActSnapshotStore(tmp_path)
    snapshot_ref = store.save(_snapshot(with_approved_proposal=True))
    artifact = _only_json_artifact(tmp_path)
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    payload["state"]["approved_tool_proposal_snapshot"]["parameters"]["customer_id"] = (
        "CUST-TAMPERED"
    )
    artifact.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ProofAgentError) as exc:
        store.load(snapshot_ref)

    assert exc.value.code == "PA_RUNTIME_001"


def test_observation_digest_rejects_retrieval_content_tamper(
    tmp_path: Path,
) -> None:
    store = FileObservationTruthStore(tmp_path)
    truth = RetrievalObservationTruth(
        truth_ref="observation://run_001/obs_1/truth",
        observation_id="obs_1",
        action_id="act_retrieve",
        accepted_evidence=(
            EvidenceChunk(
                source="Claims Guide",
                content="Original governed evidence.",
                status=EvidenceStatus.ACCEPTED,
                citation="claims.md#L1",
            ),
        ),
    )
    truth_ref = store.save(bind_observation_truth(truth).truth)
    artifact = _only_json_artifact(tmp_path)
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    payload["accepted_evidence"][0]["content"] = "Tampered evidence."
    artifact.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ProofAgentError) as exc:
        store.load(truth_ref)

    assert exc.value.code == "PA_RUNTIME_001"


def test_observation_digest_rejects_tool_authorized_result_tamper(
    tmp_path: Path,
) -> None:
    store = FileObservationTruthStore(tmp_path)
    truth = ToolObservationTruth(
        truth_ref="observation://run_001/obs_tool/truth",
        observation_id="obs_tool",
        action_id="act_tool",
        tool_name="customer_lookup",
        authorized_result={"status": "active", "customer_id": "CUST-001"},
        result_schema_id="customer_lookup.v1",
    )
    truth_ref = store.save(bind_observation_truth(truth).truth)
    artifact = _only_json_artifact(tmp_path)
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    payload["authorized_result"]["status"] = "cancelled"
    artifact.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ProofAgentError) as exc:
        store.load(truth_ref)

    assert exc.value.code == "PA_RUNTIME_001"


def test_snapshot_store_rejects_parent_directory_symlink(tmp_path: Path) -> None:
    root = tmp_path / "store"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "run_001").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ProofAgentError) as exc:
        FileControlledReActSnapshotStore(root).save(_snapshot())

    assert exc.value.code == "PA_RUNTIME_001"
    assert not tuple(outside.rglob("*.json"))


def test_snapshot_store_rejects_final_file_symlink(tmp_path: Path) -> None:
    root = tmp_path / "store"
    outside = tmp_path / "outside.json"
    store = FileControlledReActSnapshotStore(root)
    snapshot_ref = store.save(_snapshot())
    artifact = _only_json_artifact(root)
    original = artifact.read_bytes()
    outside.write_bytes(original)
    artifact.unlink()
    artifact.symlink_to(outside)

    with pytest.raises(ProofAgentError) as exc:
        store.load(snapshot_ref)

    assert exc.value.code == "PA_RUNTIME_001"
    assert outside.read_bytes() == original


def test_snapshot_store_detects_directory_replacement_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "store"
    outside = tmp_path / "outside"
    detached = tmp_path / "detached-run"
    root.mkdir()
    outside.mkdir()
    store = FileControlledReActSnapshotStore(root)
    real_open = os.open
    swapped = False

    def race_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        file_descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
        if path == "controlled_react" and dir_fd is not None and not swapped:
            run_dir = root / "run_001"
            run_dir.rename(detached)
            run_dir.symlink_to(outside, target_is_directory=True)
            swapped = True
        return file_descriptor

    monkeypatch.setattr(os, "open", race_open)

    with pytest.raises(ProofAgentError) as exc:
        store.save(_snapshot())

    assert exc.value.code == "PA_RUNTIME_001"
    assert swapped is True
    assert not tuple(outside.rglob("*.json"))
    assert not tuple(detached.rglob("*.json"))


def test_observation_committer_records_file_store_authoritative_ref(
    tmp_path: Path,
) -> None:
    action = _proposal()
    state = ControlledReActRunState(
        run_id="run_001",
        template_name="react_enterprise_qa_v3",
        template_descriptor_version="react_enterprise_qa.v3",
        question="What is the policy status?",
        phase=ControlledReActRunPhase.OBSERVING,
        plan_round=1,
        action_history=(action,),
    )
    base_ref = "observation://run_001/obs_1/truth"
    truth = ToolObservationTruth(
        truth_ref=base_ref,
        observation_id="obs_1",
        action_id=action.action_id,
        tool_name="customer_lookup",
        authorized_result={"status": "active"},
    )
    record = ObservationRecord(
        observation_id="obs_1",
        action_id=action.action_id,
        action_type=action.action_type,
        round=1,
        truth_ref=base_ref,
    )
    store = FileObservationTruthStore(tmp_path)

    result = ObservationCommitter(truth_store=store).commit(
        state,
        action,
        ObservationEffect(observation_record=record, truth_artifact=truth),
    )

    authoritative_ref = result.state.observation_records[0].truth_ref
    assert authoritative_ref.startswith(base_ref + "/sha256/")
    assert result.trace_projection["truth_ref"] == authoritative_ref
    assert store.load(authoritative_ref).truth_ref == authoritative_ref


def test_in_memory_store_uses_the_same_domain_bound_observation_ref() -> None:
    store = InMemoryObservationTruthStore()
    truth = RetrievalObservationTruth(
        truth_ref="observation://run_001/obs_1/truth",
        observation_id="obs_1",
        action_id="act_original",
    )

    bound_truth = bind_observation_truth(truth).truth
    truth_ref = store.save(bound_truth)

    assert truth_ref.startswith(truth.truth_ref + "/sha256/")
    assert store.load(truth_ref).truth_ref == truth_ref


def test_observation_commit_rejects_duplicate_identity_with_different_digest() -> None:
    action = _proposal()
    state = ControlledReActRunState(
        run_id="run_001",
        template_name="react_enterprise_qa_v3",
        template_descriptor_version="react_enterprise_qa.v3",
        question="What is the policy status?",
        phase=ControlledReActRunPhase.OBSERVING,
        plan_round=1,
        action_history=(action,),
    )
    base_ref = "observation://run_001/obs_1/truth"
    original = ToolObservationTruth(
        truth_ref=base_ref,
        observation_id="obs_1",
        action_id=action.action_id,
        tool_name="customer_lookup",
        authorized_result={"status": "active"},
    )
    record = ObservationRecord(
        observation_id="obs_1",
        action_id=action.action_id,
        action_type=action.action_type,
        round=1,
        truth_ref=base_ref,
    )
    store = InMemoryObservationTruthStore()
    committer = ObservationCommitter(truth_store=store)
    committed = committer.commit(
        state,
        action,
        ObservationEffect(observation_record=record, truth_artifact=original),
    )
    replacement = original.model_copy(update={"authorized_result": {"status": "cancelled"}})

    with pytest.raises(ValueError, match="conflicting observation"):
        committer.commit(
            committed.state,
            action,
            ObservationEffect(observation_record=record, truth_artifact=replacement),
        )


def test_observation_commit_retry_with_same_identity_and_payload_is_idempotent() -> None:
    action = _proposal()
    state = ControlledReActRunState(
        run_id="run_001",
        template_name="react_enterprise_qa_v3",
        template_descriptor_version="react_enterprise_qa.v3",
        question="What is the policy status?",
        phase=ControlledReActRunPhase.OBSERVING,
        plan_round=1,
        action_history=(action,),
    )
    base_ref = "observation://run_001/obs_1/truth"
    truth = ToolObservationTruth(
        truth_ref=base_ref,
        observation_id="obs_1",
        action_id=action.action_id,
        tool_name="customer_lookup",
        authorized_result={"status": "active"},
    )
    record = ObservationRecord(
        observation_id="obs_1",
        action_id=action.action_id,
        action_type=action.action_type,
        round=1,
        truth_ref=base_ref,
    )
    effect = ObservationEffect(observation_record=record, truth_artifact=truth)
    committer = ObservationCommitter(truth_store=InMemoryObservationTruthStore())

    committed = committer.commit(state, action, effect)
    retried = committer.commit(committed.state, action, effect)

    authoritative_ref = committed.state.observation_records[0].truth_ref
    assert retried.state == committed.state
    assert retried.state.observation_records[0].truth_ref == authoritative_ref
    assert retried.trace_projection["truth_ref"] == authoritative_ref


def test_concurrent_same_observation_payload_is_idempotent(tmp_path: Path) -> None:
    store = FileObservationTruthStore(tmp_path)
    truth = RetrievalObservationTruth(
        truth_ref="observation://run_001/obs_1/truth",
        observation_id="obs_1",
        action_id="act_original",
    )

    bound_truth = bind_observation_truth(truth).truth
    with ThreadPoolExecutor(max_workers=2) as executor:
        refs = tuple(executor.map(store.save, (bound_truth, bound_truth)))

    assert refs[0] == refs[1]
    assert "/sha256/" in refs[0]


def test_concurrent_different_observation_payload_has_one_winner(
    tmp_path: Path,
) -> None:
    store = FileObservationTruthStore(tmp_path)
    original = RetrievalObservationTruth(
        truth_ref="observation://run_001/obs_1/truth",
        observation_id="obs_1",
        action_id="act_original",
    )
    conflicting = original.model_copy(update={"action_id": "act_conflicting"})

    def save_outcome(truth: RetrievalObservationTruth) -> str:
        try:
            store.save(truth)
        except ProofAgentError:
            return "conflict"
        return "saved"

    bound_original = bind_observation_truth(original).truth
    bound_conflicting = bind_observation_truth(conflicting).truth
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(save_outcome, (bound_original, bound_conflicting)))

    assert sorted(outcomes) == ["conflict", "saved"]


def _snapshot(*, with_approved_proposal: bool = False) -> ControlledReActRunStateSnapshot:
    approved_proposal = (
        ApprovedToolProposalSnapshot(
            snapshot_id="approved_act_tool",
            action_id="act_tool",
            tool_contract_id="customer_lookup",
            parameters={"customer_id": "CUST-001"},
            parameter_digest="a" * 64,
            policy_decision="require_approval",
            risk_level="high",
            approval_reason="Operator approval required.",
        )
        if with_approved_proposal
        else None
    )
    return ControlledReActRunStateSnapshot(
        snapshot_id="snap_001",
        run_id="run_001",
        state=ControlledReActRunState(
            run_id="run_001",
            template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3",
            question="原始问题",
            approved_tool_proposal_snapshot=approved_proposal,
        ),
    )


def _proposal() -> ReActActionProposal:
    return ReActActionProposal(
        action_id="act_tool",
        action_type=ReActActionType.PROPOSE_TOOL_CALL,
        reasoning_summary=ReasoningSummary(
            goal="Use one governed tool observation.",
            observations=(),
            candidate_actions=(ReActActionType.PROPOSE_TOOL_CALL,),
            selected_action=ReActActionType.PROPOSE_TOOL_CALL,
            rationale_summary="The governed tool can provide the required status.",
            risk_flags=(),
            required_evidence=(),
        ),
        target_tool_name="customer_lookup",
        risk_level="high",
    )


def _only_json_artifact(root: Path) -> Path:
    artifacts = tuple(root.rglob("*.json"))
    assert len(artifacts) == 1
    return artifacts[0]
