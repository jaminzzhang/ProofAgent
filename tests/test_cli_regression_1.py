from __future__ import annotations

from proof_agent.delivery.cli import _verify_remote_process_specs


# Regression for ISSUE-002 in the 2026-07-11 ProofAgent integration QA report.
CHAT_BASE = "/__proofagent_chat__/"


def test_verify_remote_chat_and_gateway_use_exact_same_base() -> None:
    specs = _verify_remote_process_specs(
        npm_path="/usr/bin/npm",
        cloudflared_path=None,
        backend_port=8000,
        dashboard_port=5173,
        chat_port=5174,
        gateway_port=18080,
        history_dir="runs/history",
        config_dir="runs/config",
        worker_poll_interval_seconds=2.0,
        reload=False,
        no_worker=False,
    )
    commands = dict(specs)
    chat_command = commands["chat"]
    gateway_command = commands["verify-gateway"]

    assert chat_command[chat_command.index("--base") + 1] == CHAT_BASE
    assert gateway_command[gateway_command.index("--chat-base") + 1] == CHAT_BASE
