#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/docker-compose.hybrid-test.yml"
POSTGRES_PORT="${PROOF_AGENT_ROLLBACK_REHEARSAL_POSTGRES_PORT:-55439}"
POSTGRES_DSN="postgresql+psycopg://proof:proof-test-only@127.0.0.1:${POSTGRES_PORT}/proof"
KSS_POSTGRES_DSN="postgresql://proof:proof-test-only@127.0.0.1:${POSTGRES_PORT}/proof"

compose=(
  docker compose
  --project-name proofagent-rollback-rehearsal-tdd
  --env-file /dev/null
  -f "$COMPOSE_FILE"
)

cleanup() {
  HYBRID_TEST_POSTGRES_PORT="$POSTGRES_PORT" \
    "${compose[@]}" down --volumes --remove-orphans
}
trap cleanup EXIT INT TERM

HYBRID_TEST_POSTGRES_PORT="$POSTGRES_PORT" \
  "${compose[@]}" up -d --wait postgres

cd "$ROOT_DIR"
PROOF_AGENT_TEST_POSTGRES_DSN="$POSTGRES_DSN" \
KSS_TEST_POSTGRES_DSN="$KSS_POSTGRES_DSN" \
PROOF_AGENT_REQUIRE_POSTGRES_TESTS=1 \
KSS_REQUIRE_POSTGRES_TESTS=1 \
  .venv/bin/pytest -q \
    tests/contract/knowledge_service/test_production_agent_rollback_real_dependencies.py
