#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  printf 'Usage: %s <exact-kss-release-id>\n' "$0" >&2
  exit 2
fi

EXACT_RELEASE_ID=$1
case "$EXACT_RELEASE_ID" in
  replace-with-exact-kss-release-id|*[!A-Za-z0-9._-]*|"")
    printf 'Provide one valid existing exact KSS Release ID.\n' >&2
    exit 2
    ;;
esac
if [ "${#EXACT_RELEASE_ID}" -gt 128 ]; then
  printf 'Provide one valid existing exact KSS Release ID.\n' >&2
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
  -e PROOF_AGENT_KSS_RELEASE_ID="$EXACT_RELEASE_ID" \
  api python /opt/proof-agent-local/verify_kss_query_authority.py
