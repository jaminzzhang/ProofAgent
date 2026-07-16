from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from proof_agent.contracts.run_execution import (
    RoleActivation,
    RoleActivationState,
    RunAttempt,
    RunExecutionSnapshot,
    RunFailure,
    RunFailureCode,
    RunLifecycleState,
    RunProgress,
    RunRequest,
    RunResultAvailability,
    assert_run_transition,
)


NOW = datetime(2026, 7, 15, tzinfo=UTC)
RUN_ID = "019ba001-1111-7000-8000-000000000010"
ATTEMPT_ID = "019ba001-1111-7000-8000-000000000020"
VERSION_ID = "019ba001-1111-7000-8000-000000000001"
DIGEST = "a" * 64


def _snapshot() -> RunExecutionSnapshot:
    return RunExecutionSnapshot(
        run_id=RUN_ID,
        attempt_id=ATTEMPT_ID,
        attempt_number=1,
        release_id="proofagent-2026.07.15",
        image_digest=DIGEST,
        agent_id="agent_management_insurance_specialist",
        agent_version_id=VERSION_ID,
        agent_configuration_sha256=DIGEST,
        knowledge_configuration_sha256=DIGEST,
        model_configuration_sha256=DIGEST,
        egress_policy_version_id=VERSION_ID,
        egress_policy_sha256=DIGEST,
        permission_mapping_version_id=VERSION_ID,
        permission_mapping_sha256=DIGEST,
        permission_epoch=7,
        institution_authorization_sha256=DIGEST,
        tool_configuration_sha256=DIGEST,
        secret_handle_ids=("model/primary",),
        frozen_at=NOW,
    )


def test_run_lifecycle_allows_only_the_governed_transition_graph() -> None:
    allowed = {
        (RunLifecycleState.QUEUED, RunLifecycleState.RUNNING),
        (RunLifecycleState.QUEUED, RunLifecycleState.CANCELLED),
        (RunLifecycleState.RUNNING, RunLifecycleState.FINALIZING),
        (RunLifecycleState.RUNNING, RunLifecycleState.CANCEL_REQUESTED),
        (RunLifecycleState.RUNNING, RunLifecycleState.FAILED),
        (RunLifecycleState.RUNNING, RunLifecycleState.TIMED_OUT),
        (RunLifecycleState.FINALIZING, RunLifecycleState.SUCCEEDED),
        (RunLifecycleState.FINALIZING, RunLifecycleState.CANCEL_REQUESTED),
        (RunLifecycleState.FINALIZING, RunLifecycleState.FAILED),
        (RunLifecycleState.FINALIZING, RunLifecycleState.TIMED_OUT),
        (RunLifecycleState.CANCEL_REQUESTED, RunLifecycleState.CANCELLED),
        (RunLifecycleState.CANCEL_REQUESTED, RunLifecycleState.FAILED),
        (RunLifecycleState.CANCEL_REQUESTED, RunLifecycleState.TIMED_OUT),
    }
    for source in RunLifecycleState:
        for target in RunLifecycleState:
            if (source, target) in allowed:
                assert_run_transition(source, target)
            else:
                with pytest.raises(ValueError, match="Run transition is not allowed"):
                    assert_run_transition(source, target)


def test_run_execution_contracts_freeze_every_authority_digest() -> None:
    snapshot = _snapshot()

    assert snapshot.contract_version == "proofagent.run-execution.v1"
    assert snapshot.secret_handle_ids == ("model/primary",)
    with pytest.raises(ValidationError):
        RunExecutionSnapshot.model_validate(
            {**snapshot.model_dump(mode="json"), "unexpected": True}
        )
    with pytest.raises(ValidationError):
        RunExecutionSnapshot.model_validate(
            {**snapshot.model_dump(mode="json"), "image_digest": "mutable-tag"}
        )


def test_attempt_requires_claim_lease_deadline_and_snapshot_consistency() -> None:
    snapshot = _snapshot()
    attempt = RunAttempt(
        attempt_id=ATTEMPT_ID,
        run_id=RUN_ID,
        attempt_number=1,
        state=RunLifecycleState.RUNNING,
        state_version=2,
        claim_token="claim_" + "b" * 43,
        fencing_epoch=11,
        activation_epoch=5,
        executor_id="executor-green",
        heartbeat_at=NOW,
        lease_expires_at=NOW + timedelta(seconds=15),
        deadline_at=NOW + timedelta(seconds=120),
        snapshot=snapshot,
        snapshot_sha256=snapshot.canonical_sha256(),
        result=RunResultAvailability(),
        created_at=NOW,
        updated_at=NOW,
    )

    assert attempt.result.result_available is False
    with pytest.raises(ValidationError):
        attempt.model_copy(update={"run_id": VERSION_ID}, deep=True).__class__.model_validate(
            {
                **attempt.model_dump(mode="json"),
                "run_id": VERSION_ID,
            }
        )


def test_result_visibility_requires_a_manifest_and_success_has_no_failure() -> None:
    visible = RunResultAvailability(
        result_available=True,
        artifact_manifest_id=VERSION_ID,
        receipt_outcome="ANSWERED_WITH_CITATIONS",
    )
    assert visible.artifact_manifest_id == VERSION_ID
    assert visible.receipt_outcome is not None
    with pytest.raises(ValidationError):
        RunResultAvailability(result_available=True)
    with pytest.raises(ValidationError):
        RunResultAvailability(
            result_available=False,
            artifact_manifest_id=VERSION_ID,
        )
    with pytest.raises(ValidationError):
        RunResultAvailability(receipt_outcome="ANSWERED_WITH_CITATIONS")


def test_request_progress_activation_and_failure_are_bounded_and_strict() -> None:
    request = RunRequest(
        run_id=RUN_ID,
        operator_subject="operator-1",
        idempotency_key="submit-123",
        agent_id="agent_management_insurance_specialist",
        agent_version_id=VERSION_ID,
        question="本产品的等待期是多少？",
        permission_mapping_version_id=VERSION_ID,
        permission_epoch=7,
        submitted_at=NOW,
    )
    progress = RunProgress(
        run_id=RUN_ID,
        state=RunLifecycleState.QUEUED,
        state_version=1,
        event_kind="state_snapshot",
        occurred_at=NOW,
    )
    activation = RoleActivation(
        slot=1,
        state=RoleActivationState.ACTIVE,
        activation_epoch=3,
        executor_id="executor-green",
        updated_at=NOW,
    )
    failure = RunFailure(code=RunFailureCode.EXECUTOR_LOST)

    assert request.contract_version == "proofagent.run-execution.v1"
    assert progress.event_kind == "state_snapshot"
    assert activation.executor_id == "executor-green"
    assert failure.code.value == "PA_EXECUTOR_LOST"
    with pytest.raises(ValidationError):
        RoleActivation(
            slot=1,
            state=RoleActivationState.STANDBY,
            activation_epoch=3,
            executor_id="executor-green",
            updated_at=NOW,
        )
