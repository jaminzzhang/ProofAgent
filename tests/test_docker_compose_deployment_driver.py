from __future__ import annotations

from collections.abc import Mapping, Sequence
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import shutil

import pytest
from pydantic import TypeAdapter

from proof_agent.deployment.compatibility import (
    deployment_compatibility_sha256,
    load_deployment_compatibility_manifest,
)
from proof_agent.deployment.choreography import DeploymentActionError
from proof_agent.deployment.gateway import render_gateway_include
from proof_agent.deployment.state import (
    BlueGreenDeploymentRequest,
    CandidateBinding,
    DeploymentSlot,
)
from proof_agent.release.digests import sha256_hex
from scripts.deployment.blue_green import CommandResult, DeploymentToolError
from scripts.deployment import blue_green
from scripts.deployment.compose_driver import (
    DockerComposeBlueGreenOperations,
    DockerComposeDriverConfig,
    StableOriginResponse,
)


NOW = datetime(2026, 7, 25, 12, tzinfo=UTC)
OLD_IMAGE = f"registry.example.test/proof-agent@sha256:{'9' * 64}"
CANDIDATE_IMAGE = f"registry.example.test/proof-agent@sha256:{'a' * 64}"


@dataclass(frozen=True)
class RecordedCommand:
    argv: tuple[str, ...]
    timeout_seconds: int
    stdin: bytes | None
    env: Mapping[str, str] | None


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[RecordedCommand] = []

    def run(
        self,
        argv: Sequence[str],
        *,
        timeout_seconds: int,
        stdin: bytes | None = None,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult:
        self.calls.append(
            RecordedCommand(tuple(argv), timeout_seconds, stdin, env)
        )
        if tuple(argv[-3:]) == ("ps", "-q", "gateway"):
            return CommandResult(stdout="gateway-container-id\n")
        if "PostgresWorkerRoleRepository" in " ".join(argv):
            return CommandResult(
                stdout=(
                    '{"ready":true,"run_executor":7,'
                    '"knowledge_worker":7}\n'
                )
            )
        if "proof_agent.contracts.run_execution" in " ".join(argv):
            return CommandResult(stdout='{"compatible":true,"count":1}\n')
        return CommandResult(stdout="")


def _write_env(
    path: Path,
    *,
    slot: DeploymentSlot,
    activation: str,
    release_id: str,
    image_digest: str,
    executor_id: str,
    knowledge_worker_id: str,
) -> None:
    path.write_text(
        "\n".join(
            (
                "PROOF_AGENT_MODE=production",
                f"PROOF_AGENT_RELEASE_ID={release_id}",
                "PROOF_AGENT_RELEASE_SCHEMA=0011_worker_role_leases",
                f"PROOF_AGENT_IMAGE_DIGEST={image_digest}",
                f"PROOF_AGENT_DEPLOYMENT_SLOT={slot.value}",
                f"PROOF_AGENT_ACTIVATION_STATE={activation}",
                "PROOF_AGENT_DEPLOYMENT_COMPATIBILITY_MANIFEST=/run/configs/deployment-compatibility-manifest.json",
                f"PROOF_AGENT_EXECUTOR_ID={executor_id}",
                f"PROOF_AGENT_KNOWLEDGE_WORKER_ID={knowledge_worker_id}",
            )
        )
        + "\n",
        encoding="utf-8",
    )


def _arrange(tmp_path: Path) -> tuple[dict[str, object], BlueGreenDeploymentRequest]:
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("services: {}\n", encoding="utf-8")
    dcm = tmp_path / "deployment-compatibility-manifest.json"
    shutil.copyfile(
        "deploy/production/deployment-compatibility-manifest.example.json",
        dcm,
    )
    migration_set = tmp_path / "migration-set.json"
    migration_set.write_bytes(b'{"head":"0011_worker_role_leases"}\n')
    vault_compatibility = tmp_path / "vault-compatibility.json"
    vault_compatibility.write_text("{}\n", encoding="utf-8")
    active_include = tmp_path / "active-upstreams.conf"
    gateway_compose = tmp_path / "gateway-compose.yaml"
    gateway_compose.write_text("services:\n  gateway: {}\n", encoding="utf-8")
    gateway_nginx = tmp_path / "nginx.conf"
    gateway_nginx.write_text(
        "http {\n"
        "  include /etc/nginx/proofagent/admission-control.conf;\n"
        "  include /etc/nginx/proofagent/active-upstreams.conf;\n"
        "}\n",
        encoding="utf-8",
    )
    gateway_admission = tmp_path / "admission-control.conf"
    gateway_admission.write_text(
        "# Deployment-controller-owned file; do not edit in place.\n"
        'map "$request_method:$uri" $proofagent_run_admission_blocked {\n'
        '    default "0";\n'
        '    "POST:/api/runs" "0";\n'
        '}\n',
        encoding="utf-8",
    )
    tls_ca = tmp_path / "tls-ca.pem"
    tls_ca.write_text("test-ca\n", encoding="utf-8")
    smoke_session = tmp_path / "stable-smoke-session.json"
    smoke_session.write_text(
        json.dumps({"session_cookie": "s" * 48}) + "\n",
        encoding="utf-8",
    )
    smoke_session.chmod(0o600)
    smoke_request = tmp_path / "stable-smoke-request.json"
    smoke_request.write_text(
        json.dumps(
            {
                "agent_id": "agent_management_insurance_specialist",
                "question": "Return a deployment smoke response.",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    old_active = tmp_path / "blue-active.env"
    old_standby = tmp_path / "blue-standby.env"
    candidate_active = tmp_path / "green-active.env"
    candidate_standby = tmp_path / "green-standby.env"
    _write_env(
        old_active,
        slot=DeploymentSlot.BLUE,
        activation="active",
        release_id="release-old",
        image_digest="9" * 64,
        executor_id="executor-blue",
        knowledge_worker_id="knowledge-blue",
    )
    _write_env(
        old_standby,
        slot=DeploymentSlot.BLUE,
        activation="standby",
        release_id="release-old",
        image_digest="9" * 64,
        executor_id="executor-blue",
        knowledge_worker_id="knowledge-blue",
    )
    _write_env(
        candidate_active,
        slot=DeploymentSlot.GREEN,
        activation="active",
        release_id="release-candidate",
        image_digest="a" * 64,
        executor_id="executor-green",
        knowledge_worker_id="knowledge-green",
    )
    _write_env(
        candidate_standby,
        slot=DeploymentSlot.GREEN,
        activation="standby",
        release_id="release-candidate",
        image_digest="a" * 64,
        executor_id="executor-green",
        knowledge_worker_id="knowledge-green",
    )

    queue_fixtures = Path("tests/fixtures/run_execution_contract/v1")
    config: dict[str, object] = {
        "schema_version": "proofagent.docker-compose-blue-green-driver.v1",
        "slot_compose_file": str(compose_file),
        "deployment_compatibility_manifest": str(dcm),
        "migration_set_file": str(migration_set),
        "vault_compatibility_file": str(vault_compatibility),
        "vault_agent_token_secret": "proofagent-vault-agent-token",
        "active_gateway_include": str(active_include),
        "gateway_compose_file": str(gateway_compose),
        "gateway_nginx_config": str(gateway_nginx),
        "gateway_admission_include": str(gateway_admission),
        "stable_origin": "https://proof-agent.invalid",
        "tls_ca_file": str(tls_ca),
        "stable_smoke_session_file": str(smoke_session),
        "stable_smoke_request_file": str(smoke_request),
        "old": {
            "slot": "blue",
            "slot_number": 1,
            "project_name": "proofagent-blue",
            "release_id": "release-old",
            "image_reference": OLD_IMAGE,
            "schema_revision": "0011_worker_role_leases",
            "active_environment_file": str(old_active),
            "standby_environment_file": str(old_standby),
            "run_executor_owner_id": "executor-blue",
            "knowledge_worker_owner_id": "knowledge-blue",
        },
        "candidate": {
            "slot": "green",
            "slot_number": 2,
            "project_name": "proofagent-green",
            "release_id": "release-candidate",
            "image_reference": CANDIDATE_IMAGE,
            "schema_revision": "0011_worker_role_leases",
            "active_environment_file": str(candidate_active),
            "standby_environment_file": str(candidate_standby),
            "run_executor_owner_id": "executor-green",
            "knowledge_worker_owner_id": "knowledge-green",
        },
        "old_api_queue_fixtures": str(queue_fixtures / "old_api_requests.json"),
        "candidate_api_queue_fixtures": str(
            queue_fixtures / "candidate_api_requests.json"
        ),
    }
    dcm_digest = deployment_compatibility_sha256(
        load_deployment_compatibility_manifest(dcm, checked_at=NOW)
    )
    request = BlueGreenDeploymentRequest(
        binding=CandidateBinding(
            release_id="release-candidate",
            image_reference=CANDIDATE_IMAGE,
            deployment_compatibility_manifest_sha256=dcm_digest,
            migration_set_sha256=sha256_hex(migration_set.read_bytes()),
            schema_revision="0011_worker_role_leases",
        ),
        old_slot=DeploymentSlot.BLUE,
        candidate_slot=DeploymentSlot.GREEN,
        old_activation_epoch=7,
        active_gateway_generation=12,
    )
    active_include.write_bytes(
        render_gateway_include(
            slot=DeploymentSlot.BLUE,
            generation=12,
            deployment_binding_sha256="0" * 64,
        )
    )
    return config, request


def test_prechecks_bind_both_exact_images_compose_slots_and_candidate_files(
    tmp_path: Path,
) -> None:
    config, request = _arrange(tmp_path)
    runner = RecordingRunner()
    operations = DockerComposeBlueGreenOperations.from_mapping(
        config,
        runner=runner,
        clock=lambda: NOW,
    )

    operations.validate_prechecks(request)

    commands = [call.argv for call in runner.calls]
    assert ("docker", "image", "inspect", OLD_IMAGE) in commands
    assert ("docker", "image", "inspect", CANDIDATE_IMAGE) in commands
    compose_configs = [command for command in commands if command[-2:] == ("config", "--quiet")]
    assert len(compose_configs) == 2
    assert all(call.env is not None for call in runner.calls if call.argv in compose_configs)


def test_prechecked_deployment_inputs_cannot_change_before_mutation(
    tmp_path: Path,
) -> None:
    config, request = _arrange(tmp_path)
    operations = DockerComposeBlueGreenOperations.from_mapping(
        config,
        runner=RecordingRunner(),
        clock=lambda: NOW,
    )
    operations.validate_prechecks(request)
    Path(config["candidate"]["standby_environment_file"]).write_text(  # type: ignore[index]
        "PROOF_AGENT_MODE=production\n",
        encoding="utf-8",
    )

    with pytest.raises(DeploymentActionError) as caught:
        operations.run_locked_expand_migration(request)

    assert caught.value.error_code == "compose_driver_input_changed"


def test_migration_is_one_shot_candidate_job_with_standby_environment(
    tmp_path: Path,
) -> None:
    config, request = _arrange(tmp_path)
    runner = RecordingRunner()
    operations = DockerComposeBlueGreenOperations.from_mapping(
        config,
        runner=runner,
        clock=lambda: NOW,
    )

    operations.run_locked_expand_migration(request)

    call = runner.calls[-1]
    assert call.argv[-5:] == ("--profile", "migration", "run", "--rm", "migrate")
    assert call.timeout_seconds == 1800
    assert call.env is not None
    assert call.env["SLOT"] == "green"
    assert call.env["SLOT_ENV_FILE"].endswith("green-standby.env")
    assert call.env["PROOF_AGENT_IMAGE"] == CANDIDATE_IMAGE


def test_candidate_slot_starts_all_product_roles_as_standby(tmp_path: Path) -> None:
    config, request = _arrange(tmp_path)
    runner = RecordingRunner()
    operations = DockerComposeBlueGreenOperations.from_mapping(
        config,
        runner=runner,
        clock=lambda: NOW,
    )

    operations.start_candidate_standby(request)

    call = runner.calls[-1]
    assert call.argv[-7:] == (
        "up",
        "-d",
        "api",
        "run-executor",
        "knowledge-worker",
        "dashboard",
        "operator-chat",
    )
    assert call.env is not None
    assert call.env["SLOT_ENV_FILE"].endswith("green-standby.env")


def test_candidate_readiness_checks_exact_identity_for_every_product_role(
    tmp_path: Path,
) -> None:
    config, request = _arrange(tmp_path)
    runner = RecordingRunner()
    operations = DockerComposeBlueGreenOperations.from_mapping(
        config,
        runner=runner,
        clock=lambda: NOW,
    )

    operations.assert_candidate_ready(request)

    calls = runner.calls
    assert [call.argv[-4] for call in calls] == list(
        ("api", "run-executor", "knowledge-worker", "dashboard", "operator-chat")
    )
    assert all(call.argv[-3:-1] == ("python", "-c") for call in calls)
    assert all(call.env is not None for call in calls)
    assert all(call.env["SLOT_ENV_FILE"].endswith("green-standby.env") for call in calls if call.env)
    assert all(call.timeout_seconds == 30 for call in calls)


def test_isolated_smoke_stays_inside_candidate_slot(tmp_path: Path) -> None:
    config, request = _arrange(tmp_path)
    runner = RecordingRunner()
    operations = DockerComposeBlueGreenOperations.from_mapping(
        config,
        runner=runner,
        clock=lambda: NOW,
    )

    operations.run_isolated_smoke(request)

    assert [call.argv[-4] for call in runner.calls] == [
        "api",
        "dashboard",
        "operator-chat",
    ]
    assert all(call.env is not None for call in runner.calls)
    assert all(
        call.env["SLOT"] == "green" for call in runner.calls if call.env
    )


def test_queue_contracts_are_validated_in_both_exact_images_without_network(
    tmp_path: Path,
) -> None:
    config, request = _arrange(tmp_path)
    runner = RecordingRunner()
    operations = DockerComposeBlueGreenOperations.from_mapping(
        config,
        runner=runner,
        clock=lambda: NOW,
    )

    assert operations.queue_contracts_are_bidirectionally_compatible(request)

    assert len(runner.calls) == 2
    candidate_validation, old_validation = runner.calls
    for call in runner.calls:
        assert call.argv[:11] == (
            "docker",
            "run",
            "--rm",
            "-i",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
        )
        assert call.argv[-3:-1] == ("python", "-c")
        assert call.env is None
        assert call.timeout_seconds == 60
    assert candidate_validation.argv[13] == CANDIDATE_IMAGE
    assert candidate_validation.stdin == Path(
        config["old_api_queue_fixtures"]
    ).read_bytes()
    assert old_validation.argv[13] == OLD_IMAGE
    assert old_validation.stdin == Path(
        config["candidate_api_queue_fixtures"]
    ).read_bytes()


class IncompatibleQueueRunner(RecordingRunner):
    def run(
        self,
        argv: Sequence[str],
        *,
        timeout_seconds: int,
        stdin: bytes | None = None,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult:
        super().run(
            argv,
            timeout_seconds=timeout_seconds,
            stdin=stdin,
            env=env,
        )
        return CommandResult(
            stdout=json.dumps({"compatible": False, "count": 0}) + "\n"
        )


def test_queue_contract_incompatibility_is_a_clean_false_result(tmp_path: Path) -> None:
    config, request = _arrange(tmp_path)
    operations = DockerComposeBlueGreenOperations.from_mapping(
        config,
        runner=IncompatibleQueueRunner(),
        clock=lambda: NOW,
    )

    assert not operations.queue_contracts_are_bidirectionally_compatible(request)


class RuntimeStateRunner(RecordingRunner):
    def __init__(
        self,
        *,
        claim_counts: Sequence[tuple[int, int]] = (),
        epoch: int = 8,
    ) -> None:
        super().__init__()
        self.claim_counts = deque(claim_counts)
        self.epoch = epoch

    def run(
        self,
        argv: Sequence[str],
        *,
        timeout_seconds: int,
        stdin: bytes | None = None,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult:
        super().run(
            argv,
            timeout_seconds=timeout_seconds,
            stdin=stdin,
            env=env,
        )
        command = " ".join(argv)
        if "hybrid_ingestion_jobs" in command:
            run_attempts, knowledge_jobs = self.claim_counts.popleft()
            return CommandResult(
                stdout=json.dumps(
                    {
                        "run_attempts": run_attempts,
                        "knowledge_jobs": knowledge_jobs,
                    }
                )
                + "\n"
            )
        if "PostgresWorkerRoleRepository" in command:
            return CommandResult(
                stdout=json.dumps(
                    {
                        "ready": True,
                        "run_executor": self.epoch,
                        "knowledge_worker": self.epoch,
                    }
                )
                + "\n"
            )
        if "PostgresRunQueueRepository" in command:
            return CommandResult(stdout='{"failed_attempts":1}\n')
        return CommandResult(stdout="")


def test_old_workers_drain_and_resume_in_place_with_same_epoch(tmp_path: Path) -> None:
    config, request = _arrange(tmp_path)
    runner = RuntimeStateRunner(epoch=7)
    operations = DockerComposeBlueGreenOperations.from_mapping(
        config,
        runner=runner,
        clock=lambda: NOW,
    )

    operations.begin_old_workers_draining(request)
    operations.restore_old_workers_active(request, expected_epoch=7)

    drain, draining_authority, resume, active_authority = runner.calls
    assert drain.argv[-4:] == (
        "--signal",
        "SIGUSR1",
        "run-executor",
        "knowledge-worker",
    )
    assert resume.argv[-4:] == (
        "--signal",
        "SIGUSR2",
        "run-executor",
        "knowledge-worker",
    )
    assert drain.env is not None and drain.env["SLOT"] == "blue"
    assert resume.env is not None and resume.env["SLOT"] == "blue"
    assert "RoleActivationState.DRAINING" in " ".join(draining_authority.argv)
    assert "RoleActivationState.ACTIVE" in " ".join(active_authority.argv)


def test_claim_drain_polls_both_authoritative_queues_until_zero(tmp_path: Path) -> None:
    config, request = _arrange(tmp_path)
    runner = RuntimeStateRunner(claim_counts=((2, 1), (0, 0)))
    sleeps: list[float] = []
    operations = DockerComposeBlueGreenOperations.from_mapping(
        config,
        runner=runner,
        clock=lambda: NOW,
        sleeper=sleeps.append,
    )

    assert operations.wait_old_claims_zero(request, timeout_seconds=150)

    assert sleeps == [2.0]
    assert len(runner.calls) == 2
    assert all(call.argv[-4] == "api" for call in runner.calls)
    assert all("hybrid_ingestion_jobs" in " ".join(call.argv) for call in runner.calls)


def test_candidate_promotion_stops_old_workers_and_recreates_candidate_active(
    tmp_path: Path,
) -> None:
    config, request = _arrange(tmp_path)
    runner = RuntimeStateRunner(epoch=8)
    operations = DockerComposeBlueGreenOperations.from_mapping(
        config,
        runner=runner,
        clock=lambda: NOW,
    )

    assert operations.activate_candidate_workers(request, previous_epoch=7) == 8

    stop_old, start_candidate, authority = runner.calls
    assert stop_old.argv[-5:] == (
        "stop",
        "--timeout",
        "30",
        "run-executor",
        "knowledge-worker",
    )
    assert stop_old.env is not None
    assert stop_old.env["SLOT_ENV_FILE"].endswith("blue-active.env")
    assert start_candidate.argv[-5:] == (
        "up",
        "-d",
        "--force-recreate",
        "run-executor",
        "knowledge-worker",
    )
    assert start_candidate.env is not None
    assert start_candidate.env["SLOT_ENV_FILE"].endswith("green-active.env")
    assert "PostgresWorkerRoleRepository" in " ".join(authority.argv)


def test_authorized_admission_pause_and_resume_are_atomic_and_probed(
    tmp_path: Path,
) -> None:
    config, request = _arrange(tmp_path)
    runner = RecordingRunner()
    observed: list[bool] = []
    operations = DockerComposeBlueGreenOperations.from_mapping(
        config,
        runner=runner,
        clock=lambda: NOW,
        admission_probe=observed.append,
    )
    authorized = request.model_copy(update={"admission_pause_authorized": True})

    operations.pause_admission(authorized)
    admission_path = Path(config["gateway_admission_include"])
    assert '"POST:/api/runs" "1";' in admission_path.read_text(encoding="utf-8")
    operations.resume_admission(authorized)

    assert '"POST:/api/runs" "0";' in admission_path.read_text(encoding="utf-8")
    assert observed == [True, False]
    assert sum(call.argv[-2:] == ("-q", "gateway") for call in runner.calls) == 4
    assert sum("nginx -t -c" in " ".join(call.argv) for call in runner.calls) == 2
    assert sum(call.argv[-3:] == ("nginx", "-s", "reload") for call in runner.calls) == 2


def test_rollback_drains_candidate_then_fences_for_one_full_lease_window(
    tmp_path: Path,
) -> None:
    config, request = _arrange(tmp_path)
    runner = RuntimeStateRunner(claim_counts=((1, 0), (0, 0)))
    sleeps: list[float] = []
    operations = DockerComposeBlueGreenOperations.from_mapping(
        config,
        runner=runner,
        clock=lambda: NOW,
        sleeper=sleeps.append,
    )

    operations.begin_candidate_workers_draining(request)
    assert operations.wait_candidate_claims_zero(request, timeout_seconds=150)
    operations.fence_candidate_and_wait_for_lease_expiry(request)

    drain = runner.calls[0]
    fence = runner.calls[-1]
    assert drain.argv[-4:] == (
        "--signal",
        "SIGUSR1",
        "run-executor",
        "knowledge-worker",
    )
    assert drain.env is not None and drain.env["SLOT"] == "green"
    assert fence.argv[-5:] == (
        "stop",
        "--timeout",
        "0",
        "run-executor",
        "knowledge-worker",
    )
    assert sleeps == [2.0, 20.0]


def test_rollback_reactivates_old_at_higher_epoch_and_fails_lost_attempts(
    tmp_path: Path,
) -> None:
    config, request = _arrange(tmp_path)
    runner = RuntimeStateRunner(epoch=9)
    operations = DockerComposeBlueGreenOperations.from_mapping(
        config,
        runner=runner,
        clock=lambda: NOW,
    )

    assert operations.activate_old_workers(request, previous_epoch=8) == 9
    operations.fail_lost_candidate_attempts(request)

    stop_candidate, start_old, authority, fail_lost = runner.calls
    assert stop_candidate.argv[-5:] == (
        "stop",
        "--timeout",
        "30",
        "run-executor",
        "knowledge-worker",
    )
    assert start_old.argv[-5:] == (
        "up",
        "-d",
        "--force-recreate",
        "run-executor",
        "knowledge-worker",
    )
    assert start_old.env is not None
    assert start_old.env["SLOT_ENV_FILE"].endswith("blue-active.env")
    assert "PostgresWorkerRoleRepository" in " ".join(authority.argv)
    assert "PostgresRunQueueRepository" in " ".join(fail_lost.argv)


def test_soak_is_exact_and_old_api_assets_are_stopped_afterward(tmp_path: Path) -> None:
    config, request = _arrange(tmp_path)
    runner = RecordingRunner()
    sleeps: list[float] = []
    operations = DockerComposeBlueGreenOperations.from_mapping(
        config,
        runner=runner,
        clock=lambda: NOW,
        sleeper=sleeps.append,
    )

    operations.soak(request, seconds=1800)
    operations.stop_old_compute(request)

    assert sleeps == [60.0] * 30
    stop = runner.calls[-1]
    assert stop.argv[-6:] == (
        "stop",
        "--timeout",
        "30",
        "api",
        "dashboard",
        "operator-chat",
    )


class StableSmokeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.polls = 0

    @staticmethod
    def _headers(**extra: str) -> dict[str, str]:
        return {
            "x-proofagent-routing-generation": "13",
            "x-proofagent-routing-slot": "green",
            **extra,
        }

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        max_bytes: int = 1_048_576,
    ) -> StableOriginResponse:
        del headers, body, max_bytes
        self.calls.append((method, path))
        if path == "/api/auth/login":
            return StableOriginResponse(
                307,
                self._headers(location="https://oidc.example.test/authorize"),
                b"",
            )
        if path == "/api/auth/session":
            return StableOriginResponse(
                200,
                self._headers(),
                json.dumps(
                    {
                        "csrf_token": "c" * 64,
                        "effective_permissions": ["run.submit", "run.view"],
                    }
                ).encode("utf-8"),
            )
        if method == "POST" and path == "/api/runs":
            return StableOriginResponse(
                202,
                self._headers(),
                b'{"run_id":"019ba001-1111-7000-8000-000000000099"}',
            )
        if path.endswith("/receipt"):
            return StableOriginResponse(
                200,
                self._headers(),
                b'{"run_id":"019ba001-1111-7000-8000-000000000099",'
                b'"receipt_markdown":"verified receipt"}',
            )
        if method == "GET" and path.startswith("/api/runs/"):
            self.polls += 1
            payload = (
                {"state": "queued", "result_available": False}
                if self.polls == 1
                else {
                    "state": "succeeded",
                    "result_available": True,
                    "artifact_manifest_id": "019ba001-1111-7000-8000-000000000088",
                }
            )
            return StableOriginResponse(
                200,
                self._headers(),
                json.dumps(payload).encode("utf-8"),
            )
        raise AssertionError((method, path))

    def first_sse_event(
        self,
        path: str,
        *,
        headers: Mapping[str, str],
    ) -> StableOriginResponse:
        del headers
        self.calls.append(("SSE", path))
        return StableOriginResponse(
            200,
            self._headers(**{"content-type": "text/event-stream; charset=utf-8"}),
            b"event: state_snapshot\ndata: {\"state\":\"queued\"}\n\n",
        )


def test_stable_origin_smoke_covers_oidc_submission_sse_terminal_and_s3(
    tmp_path: Path,
) -> None:
    config, request = _arrange(tmp_path)
    client = StableSmokeClient()
    sleeps: list[float] = []
    operations = DockerComposeBlueGreenOperations.from_mapping(
        config,
        runner=RecordingRunner(),
        clock=lambda: NOW,
        sleeper=sleeps.append,
        stable_client=client,  # type: ignore[arg-type]
    )

    operations.run_stable_origin_smoke(request)

    assert client.calls == [
        ("GET", "/api/auth/login"),
        ("GET", "/api/auth/session"),
        ("POST", "/api/runs"),
        ("SSE", "/api/runs/019ba001-1111-7000-8000-000000000099/progress"),
        ("GET", "/api/runs/019ba001-1111-7000-8000-000000000099"),
        ("GET", "/api/runs/019ba001-1111-7000-8000-000000000099"),
        ("GET", "/api/runs/019ba001-1111-7000-8000-000000000099/receipt"),
    ]
    assert sleeps == [2.0]


def test_builtin_compose_driver_loads_without_external_entry_point(
    tmp_path: Path,
) -> None:
    config, _request = _arrange(tmp_path)
    config_path = tmp_path / "driver.json"
    config_path.write_text(json.dumps(config) + "\n", encoding="utf-8")

    operations = blue_green._load_operations(
        driver_name="docker-compose-v1",
        runner=RecordingRunner(),
        config_path=config_path,
    )

    assert isinstance(operations, DockerComposeBlueGreenOperations)


def test_checked_in_compose_driver_example_is_strict_and_secret_free() -> None:
    path = Path("deploy/production/docker-compose-driver.example.json")
    raw = path.read_text(encoding="utf-8")

    config = TypeAdapter(DockerComposeDriverConfig).validate_python(json.loads(raw))

    assert config.schema_version == "proofagent.docker-compose-blue-green-driver.v1"
    assert config.stable_smoke_session_file == Path(
        "/run/secrets/proofagent-deployment-smoke-session.json"
    )
    assert "session_cookie" not in raw


def test_controller_and_driver_must_bind_the_same_gateway_and_origin(
    tmp_path: Path,
) -> None:
    config, _request = _arrange(tmp_path)
    operations = DockerComposeBlueGreenOperations.from_mapping(
        config,
        runner=RecordingRunner(),
    )
    binding = {
        "gateway_compose_file": Path(config["gateway_compose_file"]),
        "gateway_nginx_config": Path(config["gateway_nginx_config"]),
        "gateway_active_include": Path(config["active_gateway_include"]),
        "stable_origin": config["stable_origin"],
        "tls_ca_file": Path(config["tls_ca_file"]),
    }

    operations.validate_controller_binding(**binding)  # type: ignore[arg-type]
    binding["stable_origin"] = "https://other.example.test"
    with pytest.raises(DeploymentToolError) as caught:
        operations.validate_controller_binding(**binding)  # type: ignore[arg-type]

    assert caught.value.error_code == "deployment_controller_binding_mismatch"
