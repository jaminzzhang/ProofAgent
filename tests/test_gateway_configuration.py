from __future__ import annotations

from pathlib import Path

import yaml  # type: ignore[import-untyped]

from proof_agent.deployment.gateway import render_gateway_include
from proof_agent.deployment.state import DeploymentSlot


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GATEWAY_ROOT = PROJECT_ROOT / "deploy/production/gateway"


def test_gateway_is_stable_hardened_and_separate_from_slots() -> None:
    compose = yaml.safe_load((GATEWAY_ROOT / "compose.yaml").read_text(encoding="utf-8"))
    gateway = compose["services"]["gateway"]

    assert set(compose["services"]) == {"gateway"}
    assert "@sha256:" in gateway["image"]
    assert gateway["read_only"] is True
    assert gateway["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in gateway["security_opt"]
    assert gateway["pids_limit"] <= 128
    assert gateway["ports"] == ["443:8443"]
    assert set(gateway["networks"]) == {"edge", "blue", "green"}
    assert not any("docker.sock" in volume for volume in gateway["volumes"])
    assert "./:/etc/nginx/proofagent:ro" in gateway["volumes"]
    assert not any(
        volume.startswith("./active-upstreams.conf:")
        for volume in gateway["volumes"]
    )


def test_nginx_switches_api_callback_sse_and_both_browser_surfaces_together() -> None:
    nginx = (GATEWAY_ROOT / "nginx.conf").read_text(encoding="utf-8")
    active = (GATEWAY_ROOT / "active-upstreams.conf").read_text(encoding="utf-8")
    admission = (GATEWAY_ROOT / "admission-control.conf").read_text(
        encoding="utf-8"
    )

    assert "include /etc/nginx/proofagent/active-upstreams.conf;" in nginx
    assert "include /etc/nginx/proofagent/admission-control.conf;" in nginx
    assert "if ($proofagent_run_admission_blocked)" in nginx
    assert "location = /api/auth/callback" in nginx
    assert "location ~ ^/api/runs/.+/(progress|events)$" in nginx
    assert "proxy_buffering off" in nginx
    assert "location /api/" in nginx
    assert "location /operator" in nginx
    assert "location /" in nginx
    assert "proxy_pass http://proofagent_api" in nginx
    assert "proxy_pass http://proofagent_dashboard" in nginx
    assert "proxy_pass http://proofagent_operator_chat" in nginx
    assert "blue-api:8000" in active
    assert "blue-dashboard:8080" in active
    assert "blue-operator-chat:8080" in active
    assert "# routing-generation: 1" in active
    assert "$proofagent_routing_generation" in active
    assert "$proofagent_routing_slot" in active
    assert "X-ProofAgent-Routing-Generation" in nginx
    assert "X-ProofAgent-Routing-Slot" in nginx
    assert active.encode("utf-8") == render_gateway_include(
        slot=DeploymentSlot.BLUE,
        generation=1,
        deployment_binding_sha256="0" * 64,
    )
    assert 'default "0";' in admission
    assert "$request_method:$uri" in admission


def test_gateway_enforces_tls_limits_and_security_headers() -> None:
    nginx = (GATEWAY_ROOT / "nginx.conf").read_text(encoding="utf-8")

    for required in (
        "listen 8443 ssl",
        "ssl_protocols TLSv1.2 TLSv1.3",
        "client_max_body_size 16m",
        "proxy_read_timeout 130s",
        "X-Content-Type-Options nosniff",
        "Strict-Transport-Security",
        "server_name proof-agent.invalid",
    ):
        assert required in nginx
    assert "server_name _" not in nginx
    assert "proxy_pass http://$" not in nginx
