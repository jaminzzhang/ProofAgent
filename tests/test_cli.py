import json
import os
import shutil
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.capabilities.knowledge.ingestion.contracts import KnowledgeWorkerDiagnostic
from proof_agent.capabilities.knowledge.ingestion.worker import (
    KnowledgeWorkerResult,
    KnowledgeWorkerTaskOutcome,
)
from proof_agent.configuration.importer import import_agent_package
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.delivery.cli import app
from proof_agent.delivery.cli import _create_server_app_from_env
from proof_agent.delivery.cli import _seed_default_dev_agent
from proof_agent.delivery.cli import _verify_remote_process_is_safe_to_stop
from proof_agent.errors import ProofAgentError
from proof_agent.evaluation.compare.result import RagResult


runner = CliRunner()
REPO_ROOT = Path(__file__).resolve().parents[1]


def test_demo_command_exists() -> None:
    result = runner.invoke(app, ["demo"])
    assert result.exit_code == 0
    assert "Proof Agent demo" in result.output
    assert "clarify: WAITING_FOR_USER_CLARIFICATION" in result.output


def test_react_demo_command_runs_no_key_scenarios() -> None:
    result = runner.invoke(app, ["react-demo"])
    assert result.exit_code == 0
    assert "Proof Agent ReAct demo" in result.output
    assert "supported: ANSWERED_WITH_CITATIONS" in result.output
    assert "unsupported: REFUSED_NO_EVIDENCE" in result.output
    assert "clarify: WAITING_FOR_USER_CLARIFICATION" in result.output
    assert "tool_required: WAITING_FOR_APPROVAL" in result.output


def test_doctor_command_exists() -> None:
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "Python" in result.output


def test_cli_commands_load_local_dotenv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    (tmp_path / ".env").write_text("DEEPSEEK_API_KEY=test-key-from-dotenv\n", encoding="utf-8")

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "deepseek env: DEEPSEEK_API_KEY" in result.output


def test_run_command_executes_v3_manifest_through_controlled_react(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    agent_yaml = (
        REPO_ROOT / "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"
    )

    result = runner.invoke(
        app,
        [
            "run",
            str(agent_yaml),
            "--question",
            "What is the reimbursement rule for travel meals?",
        ],
    )

    assert result.exit_code == 0
    assert "Outcome: ANSWERED_WITH_CITATIONS" in result.output
    events = [
        json.loads(line)
        for line in (tmp_path / "runs/latest/trace.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(
        event["event_type"] == "run_started"
        and event["payload"]["runtime"] == "controlled_react_orchestrator"
        for event in events
    )


def test_dev_command_supervises_api_and_knowledge_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured_specs = []

    def fake_run_dev_processes(specs):
        captured_specs.extend(specs)

    monkeypatch.setattr("proof_agent.delivery.cli._run_dev_processes", fake_run_dev_processes)

    result = runner.invoke(
        app,
        [
            "dev",
            "--host",
            "0.0.0.0",
            "--port",
            "9000",
            "--history-dir",
            str(tmp_path / "history"),
            "--config-dir",
            str(tmp_path / "config"),
            "--worker-poll-interval",
            "0.25",
        ],
    )

    assert result.exit_code == 0
    assert "Starting Proof Agent local backend dev services" in result.output
    assert [name for name, _command in captured_specs] == ["api", "knowledge-worker"]
    assert captured_specs[0][1][-8:] == [
        "--host",
        "0.0.0.0",
        "--port",
        "9000",
        "--history-dir",
        str(tmp_path / "history"),
        "--config-dir",
        str(tmp_path / "config"),
    ]
    assert captured_specs[1][1][-4:] == [
        "--config-dir",
        str(tmp_path / "config"),
        "--poll-interval",
        "0.25",
    ]


def test_dev_command_can_disable_knowledge_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_specs = []

    def fake_run_dev_processes(specs):
        captured_specs.extend(specs)

    monkeypatch.setattr("proof_agent.delivery.cli._run_dev_processes", fake_run_dev_processes)

    result = runner.invoke(app, ["dev", "--no-worker"])

    assert result.exit_code == 0
    assert [name for name, _command in captured_specs] == ["api"]


def test_dev_command_can_enable_api_reload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_specs = []

    def fake_run_dev_processes(specs):
        captured_specs.extend(specs)

    monkeypatch.setattr("proof_agent.delivery.cli._run_dev_processes", fake_run_dev_processes)

    result = runner.invoke(app, ["dev", "--reload", "--no-worker"])

    assert result.exit_code == 0
    assert [name for name, _command in captured_specs] == ["api"]
    assert captured_specs[0][1][-1] == "--reload"


def test_verify_remote_starts_backend_frontends_gateway_and_tunnel(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured_specs = []
    cleanup_calls = []
    captured_env = {}
    build_env = {}

    def fake_which(name: str) -> str | None:
        return {
            "npm": "/usr/bin/npm",
            "cloudflared": "/usr/local/bin/cloudflared",
        }.get(name)

    def fake_stop_verify_remote_processes(*, ports, gateway_port):
        cleanup_calls.append((tuple(ports), gateway_port))
        return ["stopped port 5173 pid 123: node vite"]

    def fake_run_dev_processes(specs):
        captured_env["VITE_CHAT_URL"] = os.environ.get("VITE_CHAT_URL")
        captured_env["VITE_DASHBOARD_URL"] = os.environ.get("VITE_DASHBOARD_URL")
        captured_specs.extend(specs)

    def fake_build_verify_remote_frontends(*, npm_path):
        build_env["npm_path"] = npm_path
        build_env["VITE_CHAT_URL"] = os.environ.get("VITE_CHAT_URL")
        build_env["VITE_DASHBOARD_URL"] = os.environ.get("VITE_DASHBOARD_URL")

    monkeypatch.setattr("proof_agent.delivery.cli.which", fake_which)
    monkeypatch.setattr(
        "proof_agent.delivery.cli._stop_verify_remote_processes",
        fake_stop_verify_remote_processes,
    )
    monkeypatch.setattr("proof_agent.delivery.cli._run_dev_processes", fake_run_dev_processes)
    monkeypatch.setattr(
        "proof_agent.delivery.cli._build_verify_remote_frontends",
        fake_build_verify_remote_frontends,
    )
    monkeypatch.setenv("VITE_CHAT_URL", "http://localhost:5174")
    monkeypatch.setenv("VITE_DASHBOARD_URL", "http://localhost:5173")

    result = runner.invoke(
        app,
        [
            "verify-remote",
            "--backend-port",
            "9000",
            "--dashboard-port",
            "9173",
            "--chat-port",
            "9174",
            "--gateway-port",
            "19080",
            "--history-dir",
            str(tmp_path / "history"),
            "--config-dir",
            str(tmp_path / "config"),
        ],
    )

    assert result.exit_code == 0
    assert "Starting Proof Agent remote verification session" in result.output
    assert "Local gateway: http://127.0.0.1:19080" in result.output
    assert "stopped port 5173 pid 123: node vite" in result.output
    assert cleanup_calls == [((9000, 9173, 9174, 19080), 19080)]
    assert build_env == {
        "npm_path": "/usr/bin/npm",
        "VITE_CHAT_URL": "",
        "VITE_DASHBOARD_URL": "",
    }
    assert captured_env == {"VITE_CHAT_URL": "", "VITE_DASHBOARD_URL": ""}
    assert os.environ["VITE_CHAT_URL"] == "http://localhost:5174"
    assert os.environ["VITE_DASHBOARD_URL"] == "http://localhost:5173"
    assert [name for name, _command in captured_specs] == [
        "api",
        "knowledge-worker",
        "dashboard",
        "chat",
        "verify-gateway",
        "cloudflared",
    ]
    assert captured_specs[0][1][-8:] == [
        "--host",
        "127.0.0.1",
        "--port",
        "9000",
        "--history-dir",
        str(tmp_path / "history"),
        "--config-dir",
        str(tmp_path / "config"),
    ]
    assert captured_specs[2][1] == [
        "/usr/bin/npm",
        "run",
        "preview",
        "-w",
        "proof-agent-dashboard",
        "--",
        "--host",
        "127.0.0.1",
        "--port",
        "9173",
    ]
    assert captured_specs[3][1] == [
        "/usr/bin/npm",
        "run",
        "preview",
        "-w",
        "proof-agent-chat",
        "--",
        "--host",
        "127.0.0.1",
        "--port",
        "9174",
        "--base",
        "/__proofagent_chat__/",
    ]
    gateway_command = captured_specs[4][1]
    assert gateway_command[gateway_command.index("--backend-origin") + 1] == (
        "http://127.0.0.1:9000"
    )
    assert gateway_command[gateway_command.index("--dashboard-origin") + 1] == (
        "http://127.0.0.1:9173"
    )
    assert gateway_command[gateway_command.index("--chat-origin") + 1] == ("http://127.0.0.1:9174")
    assert captured_specs[5][1] == [
        "/usr/local/bin/cloudflared",
        "tunnel",
        "--url",
        "http://127.0.0.1:19080",
    ]


def test_verify_remote_local_only_skips_cloudflared_requirement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_specs = []

    def fake_which(name: str) -> str | None:
        return "/usr/bin/npm" if name == "npm" else None

    def fake_run_dev_processes(specs):
        captured_specs.extend(specs)

    monkeypatch.setattr("proof_agent.delivery.cli.which", fake_which)
    monkeypatch.setattr("proof_agent.delivery.cli._stop_verify_remote_processes", lambda **_: [])
    monkeypatch.setattr("proof_agent.delivery.cli._run_dev_processes", fake_run_dev_processes)
    monkeypatch.setattr(
        "proof_agent.delivery.cli._build_verify_remote_frontends",
        lambda **_: None,
    )

    result = runner.invoke(app, ["verify-remote", "--local-only", "--no-worker"])

    assert result.exit_code == 0
    assert [name for name, _command in captured_specs] == [
        "api",
        "dashboard",
        "chat",
        "verify-gateway",
    ]


def test_verify_remote_requires_cloudflared_by_default_before_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleanup_called = False

    def fake_which(name: str) -> str | None:
        return "/usr/bin/npm" if name == "npm" else None

    def fake_stop_verify_remote_processes(**_):
        nonlocal cleanup_called
        cleanup_called = True
        return []

    monkeypatch.setattr("proof_agent.delivery.cli.which", fake_which)
    monkeypatch.setattr(
        "proof_agent.delivery.cli._stop_verify_remote_processes",
        fake_stop_verify_remote_processes,
    )

    result = runner.invoke(app, ["verify-remote"])

    assert result.exit_code == 1
    assert "cloudflared not found" in result.output
    assert cleanup_called is False


def test_verify_remote_stop_filter_is_limited_to_development_processes() -> None:
    assert _verify_remote_process_is_safe_to_stop(
        "python -m proof_agent.delivery.cli server --port 8000"
    )
    assert _verify_remote_process_is_safe_to_stop("node ./node_modules/vite/bin/vite.js")
    assert _verify_remote_process_is_safe_to_stop("cloudflared tunnel --url http://127.0.0.1:18080")
    assert not _verify_remote_process_is_safe_to_stop("postgres -D /usr/local/var/postgres")


def test_seed_default_dev_agent_publishes_v3_specialist_from_any_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    store = LocalAgentConfigurationStore(tmp_path / "config")

    seeded = _seed_default_dev_agent(store)

    assert seeded is True
    active = store.get_active_version("agent_management_insurance_specialist")
    assert active is not None
    version = store.get_version(
        "agent_management_insurance_specialist",
        active.version_id,
    )
    assert version is not None
    assert version.validation_run_id == "local_dev_seed"
    manifest = load_agent_manifest(
        store.root_dir
        / "agents"
        / "agent_management_insurance_specialist"
        / "versions"
        / active.version_id
        / "agent.yaml"
    )
    assert manifest.workflow.template == "react_enterprise_qa_v3"
    assert manifest.capabilities.tools.enabled is False


def test_seed_default_dev_agent_is_idempotent(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path / "config")
    assert _seed_default_dev_agent(store) is True

    seeded_again = _seed_default_dev_agent(store)

    assert seeded_again is False
    assert len(store.list_versions("agent_management_insurance_specialist")) == 1


def test_seed_default_dev_agent_rejects_stale_active_v2_package(tmp_path: Path) -> None:
    stale_dir = tmp_path / "stale_agent"
    shutil.copytree(
        REPO_ROOT / "examples/agent_management_insurance_specialist",
        stale_dir,
    )
    stale_manifest_path = stale_dir / "agent.yaml"
    raw = yaml.safe_load(stale_manifest_path.read_text(encoding="utf-8"))
    raw["workflow"]["runtime"] = "langgraph"
    raw["workflow"]["template"] = "react_enterprise_qa_v2"
    raw["workflow"]["template_descriptor_version"] = "react_enterprise_qa.v2"
    stale_manifest_path.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    store = LocalAgentConfigurationStore(tmp_path / "config")
    draft = import_agent_package(stale_manifest_path, store=store, actor="test-user")
    stale_version = store.publish_version(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        validation_run_id="stale_v2",
        actor="test-user",
    )

    with pytest.raises(ProofAgentError) as exc:
        _seed_default_dev_agent(store)

    assert exc.value.code == "PA_CONFIG_002"
    assert "config-reset --scope local-store --yes" in exc.value.fix
    active = store.get_active_version("agent_management_insurance_specialist")
    assert active is not None
    assert active.version_id == stale_version.version_id
    assert len(store.list_versions("agent_management_insurance_specialist")) == 1


def test_seed_default_dev_agent_rejects_stale_v3_package_content(tmp_path: Path) -> None:
    stale_dir = tmp_path / "stale_v3_agent"
    shutil.copytree(
        REPO_ROOT / "examples/agent_management_insurance_specialist",
        stale_dir,
    )
    skill_path = stale_dir / "skills/claims_consultation.yaml"
    skill_path.write_text(
        skill_path.read_text(encoding="utf-8") + "\n# stale local seed\n",
        encoding="utf-8",
    )
    store = LocalAgentConfigurationStore(tmp_path / "config")
    draft = import_agent_package(stale_dir / "agent.yaml", store=store, actor="test-user")
    stale_version = store.publish_version(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        validation_run_id="stale_v3",
        actor="test-user",
    )

    with pytest.raises(ProofAgentError) as exc:
        _seed_default_dev_agent(store)

    assert exc.value.code == "PA_CONFIG_002"
    active = store.get_active_version("agent_management_insurance_specialist")
    assert active is not None
    assert active.version_id == stale_version.version_id


def test_seed_default_dev_agent_fails_when_packaged_asset_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_path = tmp_path / "missing" / "agent.yaml"
    monkeypatch.setattr(
        "proof_agent.delivery.cli.PUBLIC_EXAMPLE_PATH",
        missing_path,
    )
    store = LocalAgentConfigurationStore(tmp_path / "config")

    with pytest.raises(ProofAgentError) as exc:
        _seed_default_dev_agent(store)

    assert exc.value.code == "PA_CONFIG_001"
    assert exc.value.artifact_path == missing_path


def test_server_factory_seeds_only_v3_specialist_from_non_repo_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PROOF_AGENT_SERVER_HISTORY_DIR", str(tmp_path / "history"))
    monkeypatch.setenv("PROOF_AGENT_SERVER_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("PROOF_AGENT_SERVER_SEED_EXAMPLE_AGENT", "1")

    application = _create_server_app_from_env()
    response = TestClient(application).get("/api/chat/agents")

    assert response.status_code == 200
    assert [item["agent_id"] for item in response.json()["data"]] == [
        "agent_management_insurance_specialist"
    ]
    store = application.state.agent_configuration_store
    active = store.get_active_version("agent_management_insurance_specialist")
    assert active is not None
    version = store.get_version("agent_management_insurance_specialist", active.version_id)
    assert version is not None
    assert version.workflow_stage_availability is not None
    assert version.workflow_stage_availability.is_available("tool_review") is False


def test_compare_command_runs_supplied_manifest(monkeypatch) -> None:
    calls = []

    def fake_run_harness_rag(question: str, *, agent_yaml: Path) -> RagResult:
        calls.append((question, agent_yaml))
        return RagResult(outcome="REFUSED_NO_EVIDENCE", message="Governed refusal")

    monkeypatch.setattr("proof_agent.delivery.cli.run_harness_rag", fake_run_harness_rag)

    result = runner.invoke(
        app,
        [
            "compare",
            "custom/agent.yaml",
            "--question",
            "What discount should we give this customer next year?",
        ],
    )

    assert result.exit_code == 0
    assert calls == [
        ("What discount should we give this customer next year?", Path("custom/agent.yaml"))
    ]


def test_inspect_trace_jsonl(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        '{"run_id":"run_test","event_type":"run_started","sequence":1,"redaction":{"applied":false}}\n'
        '{"run_id":"run_test","event_type":"final_output","sequence":2,"redaction":{"applied":true}}\n',
        encoding="utf-8",
    )
    result = runner.invoke(app, ["inspect", str(trace_path)])
    assert result.exit_code == 0
    assert "Trace events: 2" in result.output
    assert "Redaction applied: yes" in result.output


def test_inspect_governance_receipt(tmp_path: Path) -> None:
    receipt_path = tmp_path / "governance_receipt.md"
    receipt_path.write_text(
        "# Governance Receipt\n\n## Final Outcome\n\nANSWERED_WITH_CITATIONS\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["inspect", str(receipt_path)])
    assert result.exit_code == 0
    assert "Final Outcome: ANSWERED_WITH_CITATIONS" in result.output


def test_config_reset_local_store_deletes_only_config_dir(tmp_path: Path) -> None:
    config_dir = tmp_path / "runs" / "config"
    history_dir = tmp_path / "runs" / "history"
    latest_dir = tmp_path / "runs" / "latest"
    config_dir.mkdir(parents=True)
    history_dir.mkdir(parents=True)
    latest_dir.mkdir(parents=True)
    (config_dir / "source.json").write_text("{}", encoding="utf-8")
    (history_dir / "trace.jsonl").write_text("{}", encoding="utf-8")
    (latest_dir / "governance_receipt.md").write_text("# receipt", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "config-reset",
            "--scope",
            "local-store",
            "--config-dir",
            str(config_dir),
            "--yes",
        ],
    )

    assert result.exit_code == 0
    assert not config_dir.exists()
    assert history_dir.exists()
    assert latest_dir.exists()
    assert "cleared local configuration store" in result.output


def test_config_reset_requires_explicit_scope(tmp_path: Path) -> None:
    result = runner.invoke(app, ["config-reset", "--config-dir", str(tmp_path / "config")])

    assert result.exit_code != 0
    assert "local-store" in result.output


def test_knowledge_worker_prints_diagnostics_before_task_outcome(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result = _invoke_knowledge_worker(
        monkeypatch,
        tmp_path,
        worker_result=KnowledgeWorkerResult(
            outcome=KnowledgeWorkerTaskOutcome(
                kind="quarantine_validation",
                task_id="upload_123",
                source_id="source_ready",
                state="accepted",
            ),
            diagnostics=(
                KnowledgeWorkerDiagnostic(
                    source_id="source_invalid",
                    code="PA_CONFIG_001",
                    message="Malformed Source configuration.",
                ),
            ),
        ),
    )

    assert result.exit_code == 0
    warning = "knowledge worker warning: source_invalid (PA_CONFIG_001)"
    outcome = "knowledge upload accepted: upload_123"
    assert warning in result.output
    assert outcome in result.output
    assert result.output.index(warning) < result.output.index(outcome)


def test_knowledge_worker_diagnostics_only_does_not_print_no_task(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result = _invoke_knowledge_worker(
        monkeypatch,
        tmp_path,
        worker_result=KnowledgeWorkerResult(
            outcome=None,
            diagnostics=(
                KnowledgeWorkerDiagnostic(
                    source_id="source_invalid",
                    code="PA_CONFIG_001",
                    message="Malformed Source configuration.",
                ),
            ),
        ),
    )

    assert result.exit_code == 0
    assert "knowledge worker warning: source_invalid (PA_CONFIG_001)" in result.output
    assert "no queued knowledge tasks" not in result.output


def test_knowledge_worker_once_prints_no_task_text_when_empty(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result = _invoke_knowledge_worker(monkeypatch, tmp_path, worker_result=None)

    assert result.exit_code == 0
    assert "no queued knowledge tasks" in result.output


@pytest.mark.parametrize(
    ("outcome", "expected_output"),
    [
        (
            KnowledgeWorkerTaskOutcome(
                kind="quarantine_validation",
                task_id="upload_accepted",
                source_id="source_local",
                state="accepted",
            ),
            "knowledge upload accepted: upload_accepted",
        ),
        (
            KnowledgeWorkerTaskOutcome(
                kind="quarantine_validation",
                task_id="upload_rejected",
                source_id="source_local",
                state="rejected",
                error_code="PA_INGESTION_002",
            ),
            "knowledge upload rejected: upload_rejected (PA_INGESTION_002)",
        ),
        (
            KnowledgeWorkerTaskOutcome(
                kind="artifact_build",
                task_id="job_ready",
                source_id="source_local",
                state="ready",
            ),
            "knowledge ingestion job ready: job_ready",
        ),
        (
            KnowledgeWorkerTaskOutcome(
                kind="artifact_build",
                task_id="job_retry",
                source_id="source_local",
                state="retry_scheduled",
                error_code="PA_INGESTION_003",
            ),
            "knowledge ingestion job retry scheduled: job_retry (PA_INGESTION_003)",
        ),
        (
            KnowledgeWorkerTaskOutcome(
                kind="artifact_build",
                task_id="job_deferred",
                source_id="source_local",
                state="deferred",
            ),
            "knowledge ingestion job deferred: job_deferred",
        ),
        (
            KnowledgeWorkerTaskOutcome(
                kind="artifact_build",
                task_id="job_failed",
                source_id="source_local",
                state="failed",
                error_code="PA_INGESTION_003",
            ),
            "knowledge ingestion job failed: job_failed (PA_INGESTION_003)",
        ),
    ],
)
def test_knowledge_worker_prints_task_outcome(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    outcome: KnowledgeWorkerTaskOutcome,
    expected_output: str,
) -> None:
    result = _invoke_knowledge_worker(
        monkeypatch,
        tmp_path,
        worker_result=KnowledgeWorkerResult(outcome=outcome),
    )

    assert result.exit_code == 0
    assert expected_output in result.output


def test_knowledge_worker_store_lock_timeout_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result = _invoke_knowledge_worker(
        monkeypatch,
        tmp_path,
        error=ProofAgentError(
            "PA_INGESTION_004",
            "Timed out waiting for the knowledge store lock.",
            "Retry later.",
        ),
    )

    assert result.exit_code != 0
    assert "PA_INGESTION_004" in result.output


def test_knowledge_worker_runs_continuous_polling_by_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[float] = []

    class FakeKnowledgeIngestionWorker:
        def __init__(self, **_: object) -> None:
            pass

        def run_continuously(self, *, poll_interval_seconds: float, report_result) -> None:
            calls.append(poll_interval_seconds)
            report_result(
                KnowledgeWorkerResult(
                    outcome=KnowledgeWorkerTaskOutcome(
                        kind="quarantine_validation",
                        task_id="upload_continuous",
                        source_id="source_local",
                        state="accepted",
                    )
                )
            )

    monkeypatch.setattr(
        "proof_agent.capabilities.knowledge.ingestion.worker.KnowledgeIngestionWorker",
        FakeKnowledgeIngestionWorker,
    )

    result = runner.invoke(
        app,
        [
            "knowledge-worker",
            "--config-dir",
            str(tmp_path),
            "--poll-interval",
            "0.25",
        ],
    )

    assert result.exit_code == 0
    assert calls == [0.25]
    assert "knowledge worker started" in result.output
    assert "knowledge upload accepted: upload_continuous" in result.output
    assert "knowledge worker stopped" in result.output


def _invoke_knowledge_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    worker_result: KnowledgeWorkerResult | None = None,
    error: ProofAgentError | None = None,
):
    class FakeKnowledgeIngestionWorker:
        def __init__(self, **_: object) -> None:
            pass

        def run_once(self) -> KnowledgeWorkerResult | None:
            if error is not None:
                raise error
            return worker_result

    monkeypatch.setattr(
        "proof_agent.capabilities.knowledge.ingestion.worker.KnowledgeIngestionWorker",
        FakeKnowledgeIngestionWorker,
    )
    return runner.invoke(
        app,
        ["knowledge-worker", "--config-dir", str(tmp_path), "--once"],
    )
