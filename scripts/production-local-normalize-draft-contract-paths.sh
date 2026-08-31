#!/bin/sh
set -eu

if [ "$#" -ne 3 ]; then
  printf 'Usage: %s <exact-agent-id> <exact-draft-id> <expected-draft-revision>\n' "$0" >&2
  exit 2
fi

EXACT_AGENT_ID=$1
EXACT_DRAFT_ID=$2
EXPECTED_DRAFT_REVISION=$3
case "$EXACT_AGENT_ID" in
  *[!A-Za-z0-9._-]*|"")
    printf 'Provide one valid exact Agent ID.\n' >&2
    exit 2
    ;;
esac
case "$EXACT_DRAFT_ID" in
  *[!A-Za-z0-9._-]*|"")
    printf 'Provide one valid exact Draft ID.\n' >&2
    exit 2
    ;;
esac
case "$EXPECTED_DRAFT_REVISION" in
  *[!0-9]*|""|0)
    printf 'Provide one positive expected Draft revision.\n' >&2
    exit 2
    ;;
esac
if [ "${#EXACT_AGENT_ID}" -gt 128 ] || [ "${#EXACT_DRAFT_ID}" -gt 128 ]; then
  printf 'Exact identifiers must not exceed 128 characters.\n' >&2
  exit 2
fi
if [ "${#EXPECTED_DRAFT_REVISION}" -gt 9 ]; then
  printf 'Provide one positive expected Draft revision.\n' >&2
  exit 2
fi

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
COMPOSE_FILE="$ROOT_DIR/docker-compose.production-local.yml"
ENV_FILE="$ROOT_DIR/.env.production-local"
DOCKER_CONFIG="$ROOT_DIR/docker/production-local/runtime/docker-cli"
export DOCKER_CONFIG

if [ ! -f "$ENV_FILE" ]; then
  printf 'Run scripts/production-local-up.sh first.\n' >&2
  exit 1
fi

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T \
  -e PROOF_AGENT_DRAFT_PATH_AGENT_ID="$EXACT_AGENT_ID" \
  -e PROOF_AGENT_DRAFT_PATH_DRAFT_ID="$EXACT_DRAFT_ID" \
  -e PROOF_AGENT_DRAFT_PATH_EXPECTED_REVISION="$EXPECTED_DRAFT_REVISION" \
  api python /opt/proof-agent-local/normalize_draft_contract_paths.py
