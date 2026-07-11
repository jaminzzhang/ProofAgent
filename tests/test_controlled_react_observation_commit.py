from __future__ import annotations

import json
from pathlib import Path

import pytest

from proof_agent.contracts import (
    ControlledReActRunPhase,
    ControlledReActRunState,
    EvidenceChunk,
    EvidenceStatus,
    ObservationRecord,
    ReActActionProposal,
    ReActActionType,
    ReasoningSummary,
    RetrievalObservationTruth,
    ToolObservationTruth,
)
from proof_agent.control.workflow.controlled_react import (
    InMemoryObservationTruthStore,
    ObservationCommitter,
    ObservationEffect,
    ObservationIdentity,
    ObservationSummaryBuilder,
)
from proof_agent.control.workflow.controlled_react.local_stores import (
    FileObservationTruthStore,
)
from proof_agent.errors import ProofAgentError


def test_observation_commit_persists_truth_and_appends_record() -> None:
    action = _proposal("act_retrieve", ReActActionType.PLAN_RETRIEVAL)
    state = ControlledReActRunState(
        run_id="run_001",
        template_name="react_enterprise_qa_v3",
        template_descriptor_version="react_enterprise_qa.v3",
        question="What documents are required?",
        phase=ControlledReActRunPhase.OBSERVING,
        plan_round=1,
        action_history=(action,),
    )
    evidence = EvidenceChunk(
        source="Claims Guide",
        content="Submit a claim form.",
        status=EvidenceStatus.ACCEPTED,
        citation="claims-guide.md#documents",
    )
    truth = RetrievalObservationTruth(
        truth_ref="observation://run_001/obs_001/truth",
        observation_id="obs_001",
        action_id=action.action_id,
        accepted_evidence=(evidence,),
        citation_refs=("claims-guide.md#documents",),
    )
    record = ObservationRecord(
        observation_id="obs_001",
        action_id=action.action_id,
        action_type=action.action_type,
        round=1,
        truth_ref=truth.truth_ref,
        summary={"accepted_evidence_count": 1},
        accepted_evidence_count=1,
        new_evidence_count=1,
        source_refs=("Claims Guide",),
        citation_refs=("claims-guide.md#documents",),
    )
    store = InMemoryObservationTruthStore()

    result = ObservationCommitter(truth_store=store).commit(
        state,
        action,
        ObservationEffect(
            observation_record=record,
            truth_artifact=truth,
            trace_projection={"observation_id": "obs_001", "truth_kind": "retrieval"},
        ),
    )

    assert result.state.phase is ControlledReActRunPhase.PLANNING
    assert (
        result.state.observation_records[0].model_copy(update={"summary": record.summary}) == record
    )
    assert result.state.observation_records[0].summary == {
        "truth_kind": "retrieval",
        "accepted_evidence_count": 1,
        "rejected_evidence_count": 0,
        "citation_count": 1,
    }
    assert store.load(truth.truth_ref) == truth


def test_observation_commit_rebuilds_summary_from_truth() -> None:
    action = _proposal("act_retrieve", ReActActionType.PLAN_RETRIEVAL)
    state = ControlledReActRunState(
        run_id="run_001",
        template_name="react_enterprise_qa_v3",
        template_descriptor_version="react_enterprise_qa.v3",
        question="What documents are required?",
        phase=ControlledReActRunPhase.OBSERVING,
        plan_round=1,
        action_history=(action,),
    )
    evidence = EvidenceChunk(
        source="Claims Guide",
        content="Submit a claim form.",
        status=EvidenceStatus.ACCEPTED,
        citation="claims-guide.md#documents",
    )
    truth = RetrievalObservationTruth(
        truth_ref="observation://run_001/obs_001/truth",
        observation_id="obs_001",
        action_id=action.action_id,
        accepted_evidence=(evidence,),
        citation_refs=("claims-guide.md#documents",),
    )
    record = ObservationRecord(
        observation_id="obs_001",
        action_id=action.action_id,
        action_type=action.action_type,
        round=1,
        truth_ref=truth.truth_ref,
        summary={
            "accepted_evidence_count": 99,
            "evidence": [{"content": "must-not-enter-summary"}],
        },
        accepted_evidence_count=1,
        new_evidence_count=1,
        source_refs=("Claims Guide",),
        citation_refs=("claims-guide.md#documents",),
    )

    result = ObservationCommitter(truth_store=InMemoryObservationTruthStore()).commit(
        state,
        action,
        ObservationEffect(
            observation_record=record,
            truth_artifact=truth,
            trace_projection={},
        ),
    )

    assert result.state.observation_records[0].summary == {
        "truth_kind": "retrieval",
        "accepted_evidence_count": 1,
        "rejected_evidence_count": 0,
        "citation_count": 1,
    }


def test_observation_commit_failure_does_not_leave_orphan_truth() -> None:
    action = _proposal("act_retrieve", ReActActionType.PLAN_RETRIEVAL)
    state = ControlledReActRunState(
        run_id="run_001",
        template_name="react_enterprise_qa_v3",
        template_descriptor_version="react_enterprise_qa.v3",
        question="What documents are required?",
        phase=ControlledReActRunPhase.PLANNING,
        plan_round=1,
        action_history=(action,),
    )
    truth = RetrievalObservationTruth(
        truth_ref="observation://run_001/obs_001/truth",
        observation_id="obs_001",
        action_id=action.action_id,
    )
    record = ObservationRecord(
        observation_id="obs_001",
        action_id=action.action_id,
        action_type=action.action_type,
        round=1,
        truth_ref=truth.truth_ref,
    )
    store = InMemoryObservationTruthStore()

    try:
        ObservationCommitter(truth_store=store).commit(
            state,
            action,
            ObservationEffect(
                observation_record=record,
                truth_artifact=truth,
                trace_projection={"observation_id": "obs_001"},
            ),
        )
    except ValueError:
        pass
    else:
        raise AssertionError("commit should fail outside observing phase")

    try:
        store.load(truth.truth_ref)
    except KeyError:
        pass
    else:
        raise AssertionError("failed commit must not persist orphan truth")


def test_observation_commit_propagates_truth_store_failure() -> None:
    action = _proposal("act_retrieve", ReActActionType.PLAN_RETRIEVAL)
    state = ControlledReActRunState(
        run_id="run_001",
        template_name="react_enterprise_qa_v3",
        template_descriptor_version="react_enterprise_qa.v3",
        question="What documents are required?",
        phase=ControlledReActRunPhase.OBSERVING,
        plan_round=1,
        action_history=(action,),
    )
    truth = RetrievalObservationTruth(
        truth_ref="observation://run_001/obs_001/truth",
        observation_id="obs_001",
        action_id=action.action_id,
    )
    record = ObservationRecord(
        observation_id="obs_001",
        action_id=action.action_id,
        action_type=action.action_type,
        round=1,
        truth_ref=truth.truth_ref,
    )

    with pytest.raises(RuntimeError, match="truth store unavailable"):
        ObservationCommitter(truth_store=_FailingTruthStore()).commit(
            state,
            action,
            ObservationEffect(
                observation_record=record,
                truth_artifact=truth,
                trace_projection={"observation_id": "obs_001"},
            ),
        )


def test_observation_commit_does_not_overwrite_truth_for_duplicate_record() -> None:
    action = _proposal("act_retrieve", ReActActionType.PLAN_RETRIEVAL)
    existing_record = ObservationRecord(
        observation_id="obs_001",
        action_id=action.action_id,
        action_type=action.action_type,
        round=1,
        truth_ref="observation://run_001/obs_001/truth",
        summary={"accepted_evidence_count": 1},
        accepted_evidence_count=1,
        new_evidence_count=1,
        citation_refs=("claims-guide.md#original",),
    )
    state = ControlledReActRunState(
        run_id="run_001",
        template_name="react_enterprise_qa_v3",
        template_descriptor_version="react_enterprise_qa.v3",
        question="What documents are required?",
        phase=ControlledReActRunPhase.OBSERVING,
        plan_round=1,
        action_history=(action,),
        observation_records=(existing_record,),
    )
    original_truth = RetrievalObservationTruth(
        truth_ref=existing_record.truth_ref,
        observation_id=existing_record.observation_id,
        action_id=action.action_id,
        citation_refs=("claims-guide.md#original",),
    )
    replacement_truth = RetrievalObservationTruth(
        truth_ref=existing_record.truth_ref,
        observation_id=existing_record.observation_id,
        action_id=action.action_id,
        citation_refs=("claims-guide.md#replacement",),
    )
    store = InMemoryObservationTruthStore()
    store.save(original_truth)

    result = ObservationCommitter(truth_store=store).commit(
        state,
        action,
        ObservationEffect(
            observation_record=existing_record,
            truth_artifact=replacement_truth,
        ),
    )

    assert result.state == state
    assert store.load(existing_record.truth_ref) == original_truth


def test_observation_commit_rejects_record_action_type_mismatch() -> None:
    action = _proposal("act_retrieve", ReActActionType.PLAN_RETRIEVAL)
    state = ControlledReActRunState(
        run_id="run_001",
        template_name="react_enterprise_qa_v3",
        template_descriptor_version="react_enterprise_qa.v3",
        question="What documents are required?",
        phase=ControlledReActRunPhase.OBSERVING,
        plan_round=1,
        action_history=(action,),
    )
    truth = RetrievalObservationTruth(
        truth_ref="observation://run_001/obs_001/truth",
        observation_id="obs_001",
        action_id=action.action_id,
    )
    record = ObservationRecord(
        observation_id="obs_001",
        action_id=action.action_id,
        action_type=ReActActionType.PROPOSE_TOOL_CALL,
        round=1,
        truth_ref=truth.truth_ref,
    )

    with pytest.raises(ValueError, match="action_type"):
        ObservationCommitter(truth_store=InMemoryObservationTruthStore()).commit(
            state,
            action,
            ObservationEffect(observation_record=record, truth_artifact=truth),
        )


def test_observation_commit_rejects_record_round_mismatch() -> None:
    action = _proposal("act_retrieve", ReActActionType.PLAN_RETRIEVAL)
    state = ControlledReActRunState(
        run_id="run_001",
        template_name="react_enterprise_qa_v3",
        template_descriptor_version="react_enterprise_qa.v3",
        question="What documents are required?",
        phase=ControlledReActRunPhase.OBSERVING,
        plan_round=2,
        action_history=(action,),
    )
    truth = RetrievalObservationTruth(
        truth_ref="observation://run_001/obs_001/truth",
        observation_id="obs_001",
        action_id=action.action_id,
    )
    record = ObservationRecord(
        observation_id="obs_001",
        action_id=action.action_id,
        action_type=action.action_type,
        round=1,
        truth_ref=truth.truth_ref,
    )

    with pytest.raises(ValueError, match="round"):
        ObservationCommitter(truth_store=InMemoryObservationTruthStore()).commit(
            state,
            action,
            ObservationEffect(observation_record=record, truth_artifact=truth),
        )


def test_observation_commit_rejects_truth_store_ref_mismatch() -> None:
    action = _proposal("act_retrieve", ReActActionType.PLAN_RETRIEVAL)
    state = ControlledReActRunState(
        run_id="run_001",
        template_name="react_enterprise_qa_v3",
        template_descriptor_version="react_enterprise_qa.v3",
        question="What documents are required?",
        phase=ControlledReActRunPhase.OBSERVING,
        plan_round=1,
        action_history=(action,),
    )
    truth = RetrievalObservationTruth(
        truth_ref="observation://run_001/obs_001/truth",
        observation_id="obs_001",
        action_id=action.action_id,
    )
    record = ObservationRecord(
        observation_id="obs_001",
        action_id=action.action_id,
        action_type=action.action_type,
        round=1,
        truth_ref=truth.truth_ref,
    )

    with pytest.raises(ValueError, match="truth store returned"):
        ObservationCommitter(truth_store=_MismatchingTruthStore()).commit(
            state,
            action,
            ObservationEffect(observation_record=record, truth_artifact=truth),
        )


def test_observation_identity_is_allocated_from_run_round_and_action() -> None:
    identity = ObservationIdentity.allocate(
        run_id="run_001",
        plan_round=2,
        action_id="act_retrieve",
    )

    assert identity.observation_id == "obs_2_act_retrieve"
    assert identity.truth_ref == "observation://run_001/obs_2_act_retrieve/truth"
    assert identity.commit_key == (
        "run_001",
        "act_retrieve",
        "obs_2_act_retrieve",
        "observation://run_001/obs_2_act_retrieve/truth",
    )


def test_file_observation_truth_store_persists_truth_across_instances(
    tmp_path: Path,
) -> None:
    store = FileObservationTruthStore(tmp_path)
    truth = RetrievalObservationTruth(
        truth_ref="observation://run_001/obs_1_act_retrieve/truth",
        observation_id="obs_1_act_retrieve",
        action_id="act_retrieve",
        citation_refs=("claims-guide.md#documents",),
    )

    store.save(truth)
    reloaded = FileObservationTruthStore(tmp_path).load(truth.truth_ref)

    assert reloaded == truth


@pytest.mark.parametrize(
    "truth_ref",
    (
        "observation:///obs_1/truth",
        "observation://./obs_1/truth",
        "observation://../obs_1/truth",
        "observation:///absolute/obs_1/truth",
        "observation://run_001/./truth",
        "observation://run_001/../truth",
        "observation://run_001//truth",
        r"observation://run_001/..\\outside/truth",
    ),
)
def test_file_observation_truth_store_rejects_unsafe_path_segments(
    tmp_path: Path,
    truth_ref: str,
) -> None:
    truth = RetrievalObservationTruth(
        truth_ref=truth_ref,
        observation_id="obs_1",
        action_id="act_retrieve",
    )

    with pytest.raises(ProofAgentError) as exc:
        FileObservationTruthStore(tmp_path).save(truth)

    assert exc.value.code == "PA_RUNTIME_001"


def test_file_observation_truth_store_rejects_conflicting_existing_ref(
    tmp_path: Path,
) -> None:
    store = FileObservationTruthStore(tmp_path)
    original = RetrievalObservationTruth(
        truth_ref="observation://run_001/obs_1/truth",
        observation_id="obs_1",
        action_id="act_original",
    )
    conflicting = original.model_copy(update={"action_id": "act_conflicting"})
    store.save(original)

    with pytest.raises(ProofAgentError) as exc:
        store.save(conflicting)

    assert exc.value.code == "PA_RUNTIME_001"
    assert store.load(original.truth_ref) == original


def test_file_observation_truth_store_allows_identical_idempotent_save(
    tmp_path: Path,
) -> None:
    store = FileObservationTruthStore(tmp_path)
    truth = RetrievalObservationTruth(
        truth_ref="observation://run_001/obs_1/truth",
        observation_id="obs_1",
        action_id="act_original",
    )

    first_ref = store.save(truth)
    second_ref = store.save(truth)

    assert second_ref == first_ref
    assert store.load(first_ref) == truth


def test_file_observation_truth_store_rejects_ref_observation_identity_mismatch(
    tmp_path: Path,
) -> None:
    truth = RetrievalObservationTruth(
        truth_ref="observation://run_001/obs_1/truth",
        observation_id="obs_other",
        action_id="act_retrieve",
    )

    with pytest.raises(ProofAgentError) as exc:
        FileObservationTruthStore(tmp_path).save(truth)

    assert exc.value.code == "PA_RUNTIME_001"


@pytest.mark.parametrize(
    ("payload_truth_ref", "payload_observation_id"),
    (
        ("observation://run_other/obs_1/truth", "obs_1"),
        ("observation://run_001/obs_other/truth", "obs_other"),
        ("observation://run_001/obs_1/truth", "obs_other"),
    ),
)
def test_file_observation_truth_store_rejects_payload_identity_mismatch(
    tmp_path: Path,
    payload_truth_ref: str,
    payload_observation_id: str,
) -> None:
    path = (
        tmp_path
        / "run_001"
        / "controlled_react"
        / "observation_truth"
        / "obs_1.json"
    )
    path.parent.mkdir(parents=True)
    source = RetrievalObservationTruth(
        truth_ref="observation://run_seed/obs_seed/truth",
        observation_id="obs_seed",
        action_id="act_retrieve",
    )
    FileObservationTruthStore(tmp_path).save(source)
    source_path = (
        tmp_path
        / "run_seed"
        / "controlled_react"
        / "observation_truth"
        / "obs_seed.json"
    )
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    payload["truth_ref"] = payload_truth_ref
    payload["observation_id"] = payload_observation_id
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ProofAgentError) as exc:
        FileObservationTruthStore(tmp_path).load(
            "observation://run_001/obs_1/truth"
        )

    assert exc.value.code == "PA_RUNTIME_001"


@pytest.mark.parametrize(
    "payload",
    (
        "{not-json",
        json.dumps(["not", "an", "object"]),
        json.dumps({"kind": "retrieval", "truth_ref": 42}),
    ),
)
def test_file_observation_truth_store_fails_closed_on_corrupt_json(
    tmp_path: Path,
    payload: str,
) -> None:
    path = (
        tmp_path
        / "run_001"
        / "controlled_react"
        / "observation_truth"
        / "obs_1.json"
    )
    path.parent.mkdir(parents=True)
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(ProofAgentError) as exc:
        FileObservationTruthStore(tmp_path).load(
            "observation://run_001/obs_1/truth"
        )

    assert exc.value.code == "PA_RUNTIME_001"


def test_observation_summary_builder_derives_retrieval_summary_without_payload() -> None:
    evidence = EvidenceChunk(
        source="Claims Guide",
        content="Submit a claim form.",
        status=EvidenceStatus.ACCEPTED,
        citation="claims-guide.md#documents",
    )
    truth = RetrievalObservationTruth(
        truth_ref="observation://run_001/obs_001/truth",
        observation_id="obs_001",
        action_id="act_retrieve",
        accepted_evidence=(evidence,),
        rejected_evidence_summary={"count": 2},
        citation_refs=("claims-guide.md#documents",),
    )

    summary = ObservationSummaryBuilder().build(truth)

    assert summary == {
        "truth_kind": "retrieval",
        "accepted_evidence_count": 1,
        "rejected_evidence_count": 2,
        "citation_count": 1,
    }


def test_observation_summary_builder_extracts_tool_summary_fields() -> None:
    truth = ToolObservationTruth(
        truth_ref="observation://run_001/obs_tool/truth",
        observation_id="obs_tool",
        action_id="act_tool",
        tool_name="customer_lookup",
        authorized_result={
            "status": "pending",
            "policy_id": "POL-001",
            "raw_payload": {"secret": "blocked"},
        },
        result_schema_id="customer_lookup.status.v1",
        redaction_metadata={"redacted_field_count": 1},
    )

    summary = ObservationSummaryBuilder().build(
        truth,
        tool_summary_fields=("status", "policy_id"),
    )

    assert summary == {
        "truth_kind": "tool",
        "tool_name": "customer_lookup",
        "result_schema_id": "customer_lookup.status.v1",
        "fields": {"status": "pending", "policy_id": "POL-001"},
        "result": {"status": "pending", "policy_id": "POL-001"},
        "redacted_field_count": 1,
    }


def _proposal(action_id: str, action_type: ReActActionType) -> ReActActionProposal:
    return ReActActionProposal(
        action_id=action_id,
        action_type=action_type,
        reasoning_summary=ReasoningSummary(
            goal="answer the user with governed evidence",
            observations=(),
            candidate_actions=(action_type,),
            selected_action=action_type,
            rationale_summary="Need one governed observation before answering.",
            risk_flags=(),
            required_evidence=("policy document",),
        ),
        parameters={"query": "required claim documents"},
        risk_level="low",
    )


class _FailingTruthStore:
    def save(self, truth: object) -> str:
        _ = truth
        raise RuntimeError("truth store unavailable")

    def load(self, truth_ref: str) -> object:
        _ = truth_ref
        raise AssertionError("commit failure test should not load truth")


class _MismatchingTruthStore:
    def save(self, truth: object) -> str:
        assert isinstance(truth, RetrievalObservationTruth | ToolObservationTruth)
        return f"{truth.truth_ref}-mismatch"

    def load(self, truth_ref: str) -> object:
        _ = truth_ref
        raise AssertionError("ref mismatch test should not load truth")
