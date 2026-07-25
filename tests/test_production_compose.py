from __future__ import annotations

from pathlib import Path

import yaml  # type: ignore[import-untyped]


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SLOT_COMPOSE = PROJECT_ROOT / "deploy/production/slot/compose.yaml"


def _compose() -> dict[str, object]:
    return yaml.safe_load(SLOT_COMPOSE.read_text(encoding="utf-8"))


def test_slot_contains_five_same_image_product_roles() -> None:
    compose = _compose()
    services = compose["services"]

    assert set(services) == {
        "migrate",
        "api",
        "run-executor",
        "knowledge-worker",
        "dashboard",
        "operator-chat",
    }
    assert {service["image"] for service in services.values()} == {
        "${PROOF_AGENT_IMAGE:?set an immutable name@sha256 image reference}"
    }
    assert services["api"]["command"][:2] == ["proof-agent", "server"]
    assert services["run-executor"]["command"][:2] == ["proof-agent", "run-executor"]
    assert services["knowledge-worker"]["command"][:2] == [
        "proof-agent",
        "knowledge-worker",
    ]
    assert services["dashboard"]["command"][:4] == [
        "proof-agent",
        "serve-static",
        "--surface",
        "dashboard",
    ]
    assert services["operator-chat"]["command"][:4] == [
        "proof-agent",
        "serve-static",
        "--surface",
        "operator-chat",
    ]


def test_every_product_role_has_the_required_container_hardening() -> None:
    services = _compose()["services"]

    for name, service in services.items():
        assert service["user"] == "10001:10001", name
        assert service["read_only"] is True, name
        assert service["cap_drop"] == ["ALL"], name
        assert "no-new-privileges:true" in service["security_opt"], name
        assert service["pids_limit"] <= 256, name
        assert service["cpus"]
        assert service["mem_limit"]
        assert service["restart"] == ("no" if name == "migrate" else "unless-stopped"), name
        assert service["networks"]
        assert "ports" not in service, name
        assert "volumes" not in service, name
        assert any(str(item).startswith("/tmp:") for item in service["tmpfs"]), name


def test_slot_uses_only_external_secret_free_environment_file() -> None:
    compose = _compose()
    example = (
        PROJECT_ROOT / "deploy/production/slot/slot.env.example"
    ).read_text(encoding="utf-8")

    for service in compose["services"].values():
        assert service["env_file"] == ["${SLOT_ENV_FILE:?set the candidate slot env file}"]
        assert "environment" not in service
    assert "PROOF_AGENT_VAULT_AGENT_TOKEN_FILE=/run/secrets/vault-agent-token" in example
    assert "PASSWORD=" not in example
    assert "ACCESS_KEY=" not in example
    assert "SECRET_KEY=" not in example
    assert "PROOF_AGENT_IMAGE=" not in example


def test_slot_network_is_internal_and_named_per_blue_green_slot() -> None:
    network = _compose()["networks"]["slot"]

    assert network["external"] is True
    assert network["name"] == "proofagent-${SLOT:?set blue or green}"


def test_worker_roles_have_loopback_readiness_healthchecks_and_exact_slot() -> None:
    services = _compose()["services"]

    executor = services["run-executor"]
    knowledge = services["knowledge-worker"]
    assert executor["command"][-6:] == [
        "--health-host",
        "127.0.0.1",
        "--health-port",
        "8001",
        "--slot",
        "${SLOT_NUMBER:?set 1 for blue or 2 for green}",
    ]
    assert knowledge["command"][-6:] == [
        "--health-host",
        "127.0.0.1",
        "--health-port",
        "8002",
        "--slot",
        "${SLOT_NUMBER:?set 1 for blue or 2 for green}",
    ]
    assert "127.0.0.1:8001/readyz" in executor["healthcheck"]["test"][-1]
    assert "127.0.0.1:8002/readyz" in knowledge["healthcheck"]["test"][-1]
