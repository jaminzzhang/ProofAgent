from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_agent_rollback_rehearsal_entry_is_isolated_and_fail_closed() -> None:
    path = PROJECT_ROOT / "scripts" / "verify-production-agent-rollback-rehearsal.sh"

    script = path.read_text(encoding="utf-8")

    assert "--project-name proofagent-rollback-rehearsal-tdd" in script
    assert "--env-file /dev/null" in script
    assert "docker-compose.hybrid-test.yml" in script
    assert "PROOF_AGENT_REQUIRE_POSTGRES_TESTS=1" in script
    assert "KSS_REQUIRE_POSTGRES_TESTS=1" in script
    assert (
        "tests/contract/knowledge_service/"
        "test_production_agent_rollback_real_dependencies.py"
    ) in script
    assert "trap cleanup EXIT INT TERM" in script
    assert "down --volumes --remove-orphans" in script
    assert ".env.production-local" not in script
    assert "docker-compose.production-local.yml" not in script
    assert "production_agent_rollback_enabled" not in script
