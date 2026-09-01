#!/bin/sh
set -eu

if [ "$#" -ne 0 ]; then
  printf 'Usage: %s\n' "$0" >&2
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
  api python /opt/proof-agent-local/verify_control_plane_admission.py
